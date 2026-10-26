"""HTTP sessions with persistent cookie scope and a small async response interface."""

import http.cookiejar
import asyncio
import base64
import logging
import os
import secrets
import time
import httpx
from .browser import (
    USER_AGENT,
    REQUEST_TIMEOUT_MS,
    REQUEST_DELAY,
    LOCALE_COOKIE,
    browser_headers,
    restrict_cookies,
)

HTTP_LOG = logging.getLogger("uestc_login.http")


def body_text(content, content_type):
    if not content:
        return "(empty body)"
    if content_type.startswith("image/") or content_type.startswith(
        "application/octet-stream"
    ):
        return "[Base64 body]\n" + base64.b64encode(content).decode("ascii")
    return content.decode("utf-8", errors="replace")


class Response:
    def __init__(self, response):
        self.response = response
        self.status = response.status_code
        self.headers = response.headers

    async def json(self):
        return self.response.json()

    async def text(self):
        return self.response.text

    async def dispose(self):
        await self.response.aclose()


class HttpSession:
    def __init__(self, state=None, *, transport=None):
        self.trace = os.environ.get("UESTC_HTTP_TRACE", "").lower() in (
            "1",
            "true",
            "yes",
        )
        self.trace_id = secrets.token_hex(6)
        self.request_number = 0
        self.request_lock = asyncio.Lock()
        if self.trace:
            HTTP_LOG.setLevel(logging.INFO)
        self.client = httpx.AsyncClient(
            follow_redirects=False,
            trust_env=False,
            timeout=REQUEST_TIMEOUT_MS / 1000,
            headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
            transport=transport,
            event_hooks=(
                {"request": [self.trace_request], "response": [self.trace_response]}
                if self.trace
                else None
            ),
        )
        for item in (state or {}).get("cookies", []):
            domain = item["domain"]
            self.client.cookies.jar.set_cookie(
                http.cookiejar.Cookie(
                    version=0,
                    name=item["name"],
                    value=item["value"],
                    port=None,
                    port_specified=False,
                    domain=domain,
                    domain_specified=item.get(
                        "domainSpecified", domain.startswith(".")
                    ),
                    domain_initial_dot=domain.startswith("."),
                    path=item.get("path", "/"),
                    path_specified=True,
                    secure=item.get("secure", False),
                    expires=(
                        int(item["expires"]) if item.get("expires", -1) > 0 else None
                    ),
                    discard=item.get("expires", -1) <= 0,
                    comment=None,
                    comment_url=None,
                    rest={"HttpOnly": None} if item.get("httpOnly") else {},
                    rfc2109=False,
                )
            )
        self.request = self

    async def trace_request(self, request):
        self.request_number += 1
        ident = f"{self.trace_id}/{self.request_number}"
        request.extensions["uestc_trace_id"] = ident
        request.extensions["uestc_trace_start"] = time.monotonic()
        content = await request.aread()
        headers = "\n".join(
            f"{name}: {value}" for name, value in request.headers.multi_items()
        )
        HTTP_LOG.info(
            "SCHOOL HTTP [%s] REQUEST\nURL: %s\n%s %s HTTP/1.1\n%s\n\n%s\nEND REQUEST [%s]",
            ident,
            request.url,
            request.method,
            request.url.raw_path.decode("ascii"),
            headers,
            body_text(content, request.headers.get("content-type", "")),
            ident,
        )

    async def trace_response(self, response):
        request = response.request
        ident = request.extensions["uestc_trace_id"]
        try:
            await response.aread()
        except httpx.HTTPError:
            headers = "\n".join(
                f"{name}: {value}" for name, value in response.headers.multi_items()
            )
            HTTP_LOG.exception(
                "SCHOOL HTTP [%s] RESPONSE BODY READ FAILED\n%s %s %s\n%s",
                ident,
                response.http_version,
                response.status_code,
                response.reason_phrase,
                headers,
            )
            raise
        elapsed = time.monotonic() - request.extensions["uestc_trace_start"]
        headers = "\n".join(
            f"{name}: {value}" for name, value in response.headers.multi_items()
        )
        cookies = "\n".join(
            f"{cookie.name}={cookie.value}; Domain={cookie.domain}; Path={cookie.path}; "
            f"Expires={cookie.expires}; Secure={cookie.secure}"
            for cookie in self.client.cookies.jar
        )
        HTTP_LOG.info(
            "SCHOOL HTTP [%s] RESPONSE elapsed=%.3fs\nURL: %s\n%s %s %s\n%s\n\n%s\n"
            "COOKIE JAR AFTER RESPONSE:\n%s\nEND RESPONSE [%s]",
            ident,
            elapsed,
            request.url,
            response.http_version,
            response.status_code,
            response.reason_phrase,
            headers,
            body_text(response.content, response.headers.get("content-type", "")),
            cookies or "(empty)",
            ident,
        )

    async def fetch(
        self,
        url,
        *,
        method="GET",
        data=None,
        form=None,
        headers=None,
        timeout=REQUEST_TIMEOUT_MS,
        max_redirects=0,
        params=None,
        referer=None,
        site="same-origin",
        cookie_names=None,
    ):
        if max_redirects != 0:
            raise ValueError("Redirects must be handled explicitly")
        timeout_seconds = min(timeout, REQUEST_TIMEOUT_MS) / 1000
        request_headers = browser_headers(url, method, referer=referer, site=site)
        request_headers.update(headers or {})
        try:
            async with self.request_lock:
                # Pace requests separately from their network deadline.
                await asyncio.sleep(REQUEST_DELAY)
                if httpx.URL(url).host == "idas.uestc.edu.cn" and httpx.URL(
                    url
                ).path.endswith("/bfp/info"):
                    self.client.cookies.set(
                        LOCALE_COOKIE,
                        "en",
                        domain="idas.uestc.edu.cn",
                        path="/authserver",
                    )
                request = self.client.build_request(
                    method,
                    url,
                    json=data,
                    data=form,
                    headers=request_headers,
                    timeout=timeout_seconds,
                    params=params,
                )
                restrict_cookies(request, cookie_names)
                try:
                    async with asyncio.timeout(timeout_seconds):
                        response = await self.client.send(
                            request, follow_redirects=False
                        )
                except TimeoutError:
                    raise httpx.ReadTimeout(
                        "School request exceeded its total deadline.", request=request
                    ) from None
        except httpx.HTTPError as error:
            if self.trace:
                HTTP_LOG.exception(
                    "SCHOOL HTTP [%s/%s] TRANSPORT ERROR method=%s url=%s timeout_ms=%s type=%s reason=%s",
                    self.trace_id,
                    self.request_number,
                    method,
                    url,
                    timeout,
                    type(error).__name__,
                    str(error),
                )
            raise
        return Response(response)

    async def get(self, url, **kwargs):
        return await self.fetch(url, method="GET", **kwargs)

    async def post(self, url, **kwargs):
        return await self.fetch(url, method="POST", **kwargs)

    async def cookies(self, url=None):
        self.client.cookies.jar.clear_expired_cookies()
        result = []
        for cookie in self.client.cookies.jar:
            if url:
                request = httpx.Request("GET", url)
                probe = httpx.Cookies()
                probe.jar.set_cookie(cookie)
                probe.set_cookie_header(request)
                if "cookie" not in request.headers:
                    continue
            result.append(
                {
                    "name": cookie.name,
                    "value": cookie.value,
                    "domain": cookie.domain,
                    "domainSpecified": cookie.domain_specified,
                    "path": cookie.path,
                    "expires": cookie.expires if cookie.expires is not None else -1,
                    "secure": cookie.secure,
                    "httpOnly": cookie.has_nonstandard_attr("HttpOnly"),
                }
            )
        return result

    async def storage_state(self):
        return {"cookies": await self.cookies(), "origins": []}

    async def close(self):
        await self.client.aclose()


class HttpSessions:
    def __init__(self, *, transport=None):
        self.transport = transport

    async def new_context(self, *, storage_state=None):
        return HttpSession(storage_state, transport=self.transport)
