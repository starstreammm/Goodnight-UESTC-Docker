#!/usr/bin/env python3
"""Interactive IDAS → jzsz diagnostic. Run: uv run --project login python login/manual_login.py"""

import argparse
import asyncio
import base64
from datetime import datetime
from getpass import getpass
import math
import os
from pathlib import Path
import secrets
import sys
import time
from urllib.parse import parse_qs, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
from uestc_login.crypto import encrypt_password
from uestc_login.form import PasswordForm

IDAS = "https://idas.uestc.edu.cn/authserver"
LOGIN = IDAS + "/login"
SERVICE = "https://jzsz.uestc.edu.cn/"
INITIAL_LOGIN = LOGIN + "?service=https%3A%2F%2Fjzsz.uestc.edu.cn%2F%23%2Fhall%2Fhome"
SERVICE_LOGIN = INITIAL_LOGIN
REDIRECTS = {301, 302, 303, 307, 308}
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/27.0.1 Safari/605.1.15"
)
LOCALE_COOKIE = "org.springframework.web.servlet.i18n.CookieLocaleResolver.LOCALE"
FINGERPRINT_COOKIES = ("JSESSIONID", "route", LOCALE_COOKIE)
IDAS_COOKIES = (
    "CASTGC",
    "JSESSIONID",
    "route",
    "MULTIFACTOR_BROWSER_FINGERPRINT",
    "happyVoyage",
    LOCALE_COOKIE,
)
PORTAL_COOKIES = ("SESSION", "_ga_968CMWQK03", "_ga")
DEFAULT_FINGERPRINT_FILE = (
    Path(__file__).resolve().parent / "data" / "manual-browser-fingerprint"
)


class Stopped(Exception):
    pass


def valid_fingerprint(value):
    return len(value) == 32 and all(c in "0123456789abcdefABCDEF" for c in value)


def load_fingerprint(path, override=None):
    """Keep a stable browser ID across runs, independently of login sessions."""
    if override is not None and not valid_fingerprint(override):
        raise ValueError("Fingerprint must contain exactly 32 hexadecimal characters.")
    path = Path(path).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if override is None:
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            fingerprint = path.read_text(encoding="utf-8").strip()
            if not valid_fingerprint(fingerprint):
                raise ValueError(
                    f"Invalid saved fingerprint in {path}. Use --fingerprint to replace it."
                )
            return fingerprint
        fingerprint = secrets.token_hex(16).upper()
    else:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        fingerprint = override
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(fingerprint + "\n")
    return fingerprint


class Trace:
    def __init__(self, stream=sys.stdout, file=None):
        self.stream, self.file = stream, file

    def __call__(self, text=""):
        print(text, file=self.stream, flush=True)
        if self.file:
            print(text, file=self.file, flush=True)


def safe_target(base, location):
    target = urljoin(base, location)
    parsed = urlparse(target)
    if parsed.scheme != "https" or parsed.netloc not in (
        "idas.uestc.edu.cn",
        "jzsz.uestc.edu.cn",
    ):
        raise Stopped(
            "Redirect leaves the expected HTTPS hosts. Inspect its raw Location above; it was not followed."
        )
    return target


def browser_headers(
    user_agent, *, ajax=False, referer=None, site="same-origin", method="GET"
):
    headers = {
        "User-Agent": user_agent,
        "Accept": (
            "application/json, text/javascript, */*; q=0.01"
            if ajax
            else "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        ),
        "Sec-Fetch-Dest": "empty" if ajax else "document",
        "Sec-Fetch-Site": site,
        "Sec-Fetch-Mode": "cors" if ajax else "navigate",
        "Accept-Language": "en-US,en;q=0.9",
        "Priority": "u=3, i" if ajax else "u=0, i",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Connection": "keep-alive",
    }
    if referer:
        headers["Referer"] = referer
    if ajax:
        headers["X-Requested-With"] = "XMLHttpRequest"
    if method == "POST":
        headers["Origin"] = "https://idas.uestc.edu.cn"
        headers["Content-Type"] = (
            "application/x-www-form-urlencoded;charset=utf-8"
            if ajax
            else "application/x-www-form-urlencoded"
        )
    return headers


def restrict_cookies(request, allowed):
    # Filter HTTPX's already domain/path/expiry-scoped cookies. Never copy captured
    # credentials or send IDAS's broad-domain platformMultilingual cookie to jzsz.
    pairs = [
        part.strip()
        for part in request.headers.get("Cookie", "").split(";")
        if "=" in part
    ]
    selected = [
        part for name in allowed for part in pairs if part.split("=", 1)[0] == name
    ]
    request.headers.pop("Cookie", None)
    if selected:
        request.headers["Cookie"] = "; ".join(selected)


class ManualLogin:
    def __init__(
        self,
        client,
        trace,
        *,
        ask=input,
        secret=getpass,
        request_delay=2.0,
        request_timeout=30.0,
        user_agent=DEFAULT_UA,
    ):
        if not math.isfinite(request_delay) or request_delay < 0:
            raise ValueError(
                "Request delay must be a finite, non-negative number of seconds."
            )
        if not math.isfinite(request_timeout) or request_timeout <= 0:
            raise ValueError(
                "Request timeout must be a finite, positive number of seconds."
            )
        self.client, self.trace, self.ask, self.secret = client, trace, ask, secret
        self.request_delay, self.request_timeout = request_delay, request_timeout
        self.user_agent = user_agent
        self.cas_referer = INITIAL_LOGIN
        self.step = 0

    def pause(self, message):
        answer = self.ask(message + " [Enter = continue, q = quit] ").strip().lower()
        if answer == "q":
            raise Stopped("Stopped by user.")

    async def request(
        self,
        title,
        method,
        url,
        *,
        ajax=False,
        referer=None,
        site="same-origin",
        cookie_names=None,
        **kwargs,
    ):
        self.step += 1
        headers = browser_headers(
            self.user_agent, ajax=ajax, referer=referer, site=site, method=method
        )
        headers.update(kwargs.pop("headers", {}))
        request = self.client.build_request(
            method, url, headers=headers, timeout=self.request_timeout, **kwargs
        )
        if cookie_names is None:
            if request.url.host == "idas.uestc.edu.cn":
                cookie_names = (
                    FINGERPRINT_COOKIES
                    if request.url.path.endswith("/bfp/info")
                    else IDAS_COOKIES
                )
            else:
                cookie_names = () if "ticket" in request.url.params else PORTAL_COOKIES
        restrict_cookies(request, cookie_names)
        self.trace("\n" + "=" * 78)
        self.trace(f"STEP {self.step}: {title}")
        self.trace(datetime.now(ZoneInfo("Asia/Shanghai")).isoformat())
        self.trace(f"URL: {request.url}\n\nREQUEST")
        self.trace(f'{request.method} {request.url.raw_path.decode("ascii")} HTTP/1.1')
        for name, value in request.headers.multi_items():
            self.trace(f"{name}: {value}")
        self.trace("")
        self.trace(
            request.content.decode("utf-8", errors="replace")
            if request.content
            else "(empty body)"
        )
        self.pause("Send this request?")
        if self.request_delay:
            self.trace(f"Waiting {self.request_delay:g}s before sending...")
            await asyncio.sleep(self.request_delay)
        self.trace(
            f'Sending at {datetime.now(ZoneInfo("Asia/Shanghai")).isoformat()} '
            f"(request deadline: {self.request_timeout:g}s)"
        )
        start = time.monotonic()
        try:
            # The deadline covers sending and reading the complete response body,
            # but excludes the interactive prompt and deliberate pacing delay.
            async with asyncio.timeout(self.request_timeout):
                response = await self.client.send(request, follow_redirects=False)
        except (TimeoutError, httpx.TimeoutException) as error:
            self.trace(
                f"\nREQUEST TIMEOUT ({time.monotonic() - start:.3f}s): {type(error).__name__}"
            )
            raise Stopped("Request timed out; no automatic retry was made.") from None
        except httpx.HTTPError as error:
            self.trace(f"\nTRANSPORT ERROR: {type(error).__name__}: {error}")
            raise Stopped("Request failed; no automatic retry was made.") from None
        self.trace(f"\nRESPONSE ({time.monotonic() - start:.3f}s)")
        self.trace(
            f"{response.http_version} {response.status_code} {response.reason_phrase}"
        )
        # Preserve repeated Set-Cookie headers, including different cookie paths.
        for name, value in response.headers.multi_items():
            self.trace(f"{name}: {value}")
        self.trace("")
        if not response.content:
            self.trace("(empty body)")
        elif response.headers.get("content-type", "").startswith("image/"):
            self.trace(
                "[Base64 image body]\n" + base64.b64encode(response.content).decode()
            )
        else:
            self.trace(response.text)
        self.trace("\nCOOKIE JAR AFTER RESPONSE")
        for cookie in self.client.cookies.jar:
            self.trace(
                f"{cookie.name}={cookie.value}; Domain={cookie.domain}; Path={cookie.path}; "
                f"Expires={cookie.expires}; Secure={cookie.secure}"
            )
        return response

    @staticmethod
    def payload(response):
        try:
            result = response.json()
            return result if isinstance(result, dict) else None
        except ValueError:
            return None

    async def sms(self, username, url):
        view = await self.request(
            "Open SMS reauthentication page", "GET", url, referer=INITIAL_LOGIN
        )
        if view.status_code != 200:
            raise Stopped(
                "Reauthentication page did not return 200. Inspect the response above."
            )
        self.cas_referer = url
        sent = await self.request(
            "Request an SMS code",
            "POST",
            IDAS + "/dynamicCode/getDynamicCodeByReauth.do",
            ajax=True,
            referer=url,
            data={"userName": username, "authCodeTypeName": "reAuthDynamicCodeType"},
        )
        if (
            sent.status_code != 200
            or (self.payload(sent) or {}).get("res") != "success"
        ):
            raise Stopped("SMS request was not successful. Inspect the response above.")
        for attempt in range(5):
            code = self.secret("Enter the SMS code (hidden): ")
            result = await self.request(
                "Submit SMS code",
                "POST",
                IDAS + "/reAuthCheck/reAuthSubmit.do",
                ajax=True,
                referer=url,
                data={
                    "service": parse_qs(urlparse(url).query).get("service", [""])[0],
                    "reAuthType": "3",
                    "isMultifactor": "true",
                    "password": "",
                    "dynamicCode": code,
                    "uuid": "",
                    "answer1": "",
                    "answer2": "",
                    "otpCode": "",
                    "skipTmpReAuth": "true",
                },
            )
            code = None
            if (
                result.status_code == 200
                and (self.payload(result) or {}).get("code") == "reAuth_success"
            ):
                return
            if (
                self.ask(
                    "SMS verification failed. Enter r to retry, or Enter to stop: "
                )
                .strip()
                .lower()
                != "r"
            ):
                break
        raise Stopped("SMS verification did not complete.")

    async def finish_password(self, response, username):
        for _ in range(10):
            if response.status_code not in REDIRECTS or not response.headers.get(
                "location"
            ):
                raise Stopped(
                    "Password step did not produce a recognized redirect. Inspect the response above."
                )
            target = safe_target(str(response.url), response.headers["location"])
            path = urlparse(target).path
            if path.startswith("/authserver/reAuthCheck/"):
                await self.sms(username, target)
                return
            if path == "/authserver/index.do":
                self.trace(
                    "\nIDAS returned its success landing. Next: request the jzsz CAS service URL."
                )
                choice = (
                    self.ask(
                        "Enter f to inspect the index.do landing redirects instead, or Enter for CAS: "
                    )
                    .strip()
                    .lower()
                )
                if choice != "f":
                    return
            if urlparse(target).netloc == "jzsz.uestc.edu.cn":
                self.trace(
                    "\nA jzsz handoff is already present. Following its ticket redirect next."
                )
                return response
            response = await self.request(
                "Follow IDAS redirect", "GET", target, referer=str(response.url)
            )
            if response.status_code == 200 and not PasswordForm(response.text).found:
                return
        raise Stopped("Too many password-step redirects.")

    async def exchange(self, username, response=None):
        if response is None:
            response = await self.request(
                "Final CAS service request",
                "GET",
                SERVICE_LOGIN,
                referer=self.cas_referer,
            )
        ticket_seen = False
        for _ in range(10):
            if response.status_code in REDIRECTS and response.headers.get("location"):
                target = safe_target(str(response.url), response.headers["location"])
                parsed = urlparse(target)
                if parsed.netloc == "idas.uestc.edu.cn" and parsed.path.startswith(
                    "/authserver/reAuthCheck/"
                ):
                    await self.sms(username, target)
                    response = await self.request(
                        "Retry CAS after SMS",
                        "GET",
                        SERVICE_LOGIN,
                        referer=self.cas_referer,
                    )
                    continue
                if parsed.netloc == "jzsz.uestc.edu.cn" and parse_qs(parsed.query).get(
                    "ticket"
                ):
                    ticket_seen = True
                referer = (
                    "https://idas.uestc.edu.cn/"
                    if parsed.netloc == "jzsz.uestc.edu.cn"
                    else self.cas_referer
                )
                response = await self.request(
                    "Follow CAS Location / redeem ticket",
                    "GET",
                    target,
                    referer=referer,
                    site=(
                        "same-site"
                        if parsed.netloc == "jzsz.uestc.edu.cn"
                        else "same-origin"
                    ),
                )
                continue
            if response.status_code != 200 or not ticket_seen:
                raise Stopped(
                    "CAS did not complete the jzsz ticket redirect. Inspect the response above."
                )
            break
        else:
            raise Stopped("Too many CAS redirects.")
        self.client.cookies.jar.clear_expired_cookies()
        sessions = [
            cookie
            for cookie in self.client.cookies.jar
            if cookie.name == "SESSION"
            and cookie.domain.lstrip(".") == "jzsz.uestc.edu.cn"
            and cookie.path == "/"
        ]
        if not sessions:
            raise Stopped("No jzsz SESSION cookie was issued.")
        self.trace(
            "\nCAS HANDOFF COMPLETE — SESSION received; API authentication is tested next."
        )
        for cookie in sessions:
            self.trace(
                f"SESSION={cookie.value}; Domain={cookie.domain}; Path={cookie.path}"
            )
        return sessions

    async def profile(self, sessions):
        # Snapshot before the first probe: an unauthenticated API can replace SESSION.
        snapshot = list(self.client.cookies.jar)
        await self.request(
            "Check portal login status",
            "GET",
            SERVICE + "api/isLoginFailure",
            params={"_t": str(int(time.time() * 1000))},
            headers={
                "Accept": "application/json, text/plain, */*",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Accept-Language": "en-US,en;q=0.9",
                "Priority": "u=3, i",
            },
        )
        response = await self.request(
            "Validate mini-program user profile",
            "GET",
            SERVICE + "platform-app/api/h5/user/base-info",
            headers={
                "platform": "mp-weixin",
                "Accept": "application/json, text/plain, */*",
                "Sec-Fetch-Dest": "empty",
                "Sec-Fetch-Mode": "cors",
                "Priority": "u=3, i",
            },
        )
        payload = self.payload(response)
        if (
            response.status_code == 200
            and isinstance(payload, dict)
            and type(payload.get("code")) is int
            and payload["code"] == 0
            and payload.get("ok") is not False
            and payload.get("data")
        ):
            self.trace("\nPROFILE VALIDATION PASSED.")
        else:
            self.trace(
                "\nPROFILE VALIDATION FAILED. This is separate from password submission and CAS ticket issuance."
            )
        while True:
            choice = self.ask(
                "\nOptional probes: 1 = web profile, 2 = check-in auth with sessionId, "
                "3 = today record, Enter = finish: "
            ).strip()
            if not choice:
                return
            cases = {
                "1": ("Web profile", "platform-app/api/h5/user/base-info", None),
                "2": (
                    "Check-in authentication",
                    "daily-checkin/api/auth/user-info",
                    {"sessionId": sessions[0].value},
                ),
                "3": (
                    "Today's check-in record (read only)",
                    "daily-checkin/api/student-checkin-record/today",
                    None,
                ),
            }
            if choice not in cases:
                continue
            title, path, params = cases[choice]
            self.client.cookies.clear()
            for cookie in snapshot:
                self.client.cookies.jar.set_cookie(cookie)
            await self.request(
                title + " — using original CAS cookies",
                "GET",
                SERVICE + path,
                headers={
                    "platform": "h5",
                    "Accept": "application/json, text/plain, */*",
                    "Sec-Fetch-Dest": "empty",
                    "Sec-Fetch-Mode": "cors",
                    "Priority": "u=3, i",
                },
                params=params,
            )

    async def run(self, username, fingerprint, check_captcha=False):
        self.trace(f"Browser fingerprint for this run: {fingerprint}")
        response = await self.request(
            "Load IDAS login form", "GET", INITIAL_LOGIN, site="none", cookie_names=()
        )
        if response.status_code != 200:
            raise Stopped("Login page did not return 200.")
        form = PasswordForm(response.text)
        if not form.found or not form.fields.get("execution") or not form.salt:
            raise Stopped("Password form, execution or pwdEncryptSalt is missing.")
        action = safe_target(INITIAL_LOGIN, form.action or INITIAL_LOGIN)
        if (
            urlparse(action).netloc != "idas.uestc.edu.cn"
            or urlparse(action).path != "/authserver/login"
        ):
            raise Stopped("Unexpected password form destination.")
        self.trace(
            f'Parsed execution: {form.fields["execution"]}\nParsed pwdEncryptSalt: {form.salt}'
        )
        # This non-authentication preference appears in the browser before bfp/info.
        self.client.cookies.set(
            LOCALE_COOKIE, "en", domain="idas.uestc.edu.cn", path="/authserver"
        )
        result = await self.request(
            "Register browser fingerprint",
            "GET",
            IDAS + "/bfp/info",
            params={"bfp": fingerprint, "_": str(int(time.time() * 1000))},
            ajax=True,
            referer=INITIAL_LOGIN,
        )
        if result.status_code != 200:
            raise Stopped("Fingerprint registration failed.")
        if check_captcha:
            result = await self.request(
                "Check CAPTCHA requirement",
                "GET",
                IDAS + "/checkNeedCaptcha.htl",
                params={"username": username, "_": str(int(time.time() * 1000))},
                ajax=True,
                referer=INITIAL_LOGIN,
            )
            payload = self.payload(result)
            if (
                result.status_code != 200
                or not isinstance(payload, dict)
                or payload.get("isNeed") is not False
            ):
                raise Stopped(
                    "CAPTCHA required or requirement unknown. This manual script does not solve CAPTCHA."
                )
        password = self.secret("School password (hidden; plaintext is not printed): ")
        if not password:
            raise Stopped("Password is empty.")
        try:
            encrypted = encrypt_password(password, form.salt)
        finally:
            password = None
        fields = {
            **form.fields,
            "username": username,
            "password": encrypted,
            "captcha": "",
            "_eventId": "submit",
            "cllt": "userNameLogin",
            "dllt": "generalLogin",
            "rememberMe": "true",
        }
        fields.pop("passwordText", None)
        response = await self.request(
            "Submit encrypted password",
            "POST",
            action,
            data=fields,
            referer=INITIAL_LOGIN,
        )
        fields.clear()
        handoff = await self.finish_password(response, username)
        sessions = await self.exchange(username, response=handoff)
        await self.profile(sessions)
        self.trace(
            "\nManual test finished. Inspect the separate CAS and profile results above."
        )


def arguments():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--username",
        help="Prompted if omitted; password always uses a hidden terminal prompt.",
    )
    parser.add_argument(
        "--fingerprint",
        help="Set and save a 32-character hexadecimal browser fingerprint for this and future runs.",
    )
    parser.add_argument(
        "--fingerprint-file",
        type=Path,
        default=DEFAULT_FINGERPRINT_FILE,
        help=f"Persistent browser fingerprint file (default: {DEFAULT_FINGERPRINT_FILE}).",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_UA,
        help=f"HTTP User-Agent (default: {DEFAULT_UA}).",
    )
    parser.add_argument(
        "--request-delay",
        type=float,
        default=2.0,
        help="Seconds to wait after confirmation before every request, including redirects (default: 2).",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=30.0,
        help="Total seconds allowed to send a request and read its response (default: 30).",
    )
    parser.add_argument(
        "--check-captcha",
        action="store_true",
        help="Add the optional CAPTCHA-requirement GET before password submission.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Also write the complete trace to a NEW private file (mode 0600).",
    )
    args = parser.parse_args()
    if not math.isfinite(args.request_delay) or args.request_delay < 0:
        parser.error("--request-delay must be finite and non-negative")
    if not math.isfinite(args.request_timeout) or args.request_timeout <= 0:
        parser.error("--request-timeout must be finite and positive")
    if args.fingerprint is not None and not valid_fingerprint(args.fingerprint):
        parser.error("--fingerprint must contain exactly 32 hexadecimal characters")
    return args


async def main(args, trace):
    trace("Manual IDAS → jzsz login test. Every HTTP request pauses before sending.")
    trace(
        f"Request pacing: {args.request_delay:g}s after confirmation; "
        f"total deadline: {args.request_timeout:g}s per request."
    )
    trace(
        "Raw output includes session cookies, tickets and any SMS code you submit. Keep it private."
    )
    trace(
        "Bodies are shown after HTTPX decompression; headers retain the received encoding/length values."
    )
    fingerprint = load_fingerprint(args.fingerprint_file, args.fingerprint)
    trace(
        f"Persistent browser fingerprint file: {args.fingerprint_file.expanduser().resolve()}"
    )
    username = args.username or input("School username: ").strip()
    if not username:
        raise Stopped("Username is empty.")
    async with httpx.AsyncClient(
        follow_redirects=False,
        trust_env=False,
        timeout=args.request_timeout,
        headers={"User-Agent": args.user_agent, "Accept": "*/*"},
    ) as client:
        await ManualLogin(
            client,
            trace,
            request_delay=args.request_delay,
            request_timeout=args.request_timeout,
            user_agent=args.user_agent,
        ).run(username, fingerprint, args.check_captcha)


if __name__ == "__main__":
    args = arguments()
    output = None
    try:
        if args.output:
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            output = os.fdopen(fd, "w", encoding="utf-8")
        trace = Trace(file=output)
        asyncio.run(main(args, trace))
    except (Stopped, KeyboardInterrupt, EOFError) as error:
        Trace(file=output)(f'\nSTOPPED: {error or "interrupted"}')
        sys.exit(1)
    except (OSError, ValueError) as error:
        Trace(file=output)(f"\nERROR: {error}")
        sys.exit(1)
    finally:
        if output:
            output.close()
