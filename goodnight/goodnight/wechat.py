"""Private, authenticated YYB adapter. No upstream routes or tokens reach the UI."""

import asyncio
import json
import os
import secrets
from pathlib import Path
import httpx

APP_ID = "wxaa78bf2905f01cee"


class WeChatError(Exception):
    def __init__(self, code="wechat_unavailable"):
        super().__init__(code)


def credentials(directory):
    path = Path(directory) / "wechat-control.json"
    if path.exists():
        return json.loads(path.read_text())
    data = {
        "username": "goodnight-service",
        "password": secrets.token_urlsafe(40),
        "token": secrets.token_urlsafe(40),
    }
    tmp = path.with_suffix("." + secrets.token_hex(8) + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.link(tmp, path)  # Publish complete credentials exactly once.
        except FileExistsError:
            pass
    finally:
        tmp.unlink(missing_ok=True)
    return json.loads(path.read_text())


class WeChat:
    def __init__(self, directory):
        self.credentials = credentials(directory)
        self.http = httpx.AsyncClient(
            base_url=os.environ.get("YYB_URL", "http://127.0.0.1:8001"),
            timeout=55,
            trust_env=False,
        )
        self.lock = asyncio.Lock()

    async def close(self):
        await self.http.aclose()

    async def request(self, method, path, body=None, *, protocol=False):
        try:
            headers = (
                {"Authorization": "Bearer " + self.credentials["token"]}
                if protocol
                else {}
            )
            response = await self.http.request(method, path, json=body, headers=headers)
            if not protocol and response.status_code in (401, 302, 303):
                async with self.lock:
                    auth = await self.http.post(
                        "/login",
                        json={k: self.credentials[k] for k in ("username", "password")},
                    )
                    if auth.status_code != 200:
                        raise WeChatError()
                response = await self.http.request(method, path, json=body)
            if response.status_code == 409:
                raise WeChatError(
                    "wechat_pending" if path.endswith("/confirm") else "wechat_expired"
                )
            if response.status_code != 200:
                raise WeChatError()
            payload = response.json()
            if payload.get("code") != 0:
                raise WeChatError()
            return payload["data"]
        except (httpx.HTTPError, ValueError, KeyError):
            raise WeChatError() from None

    async def start(self):
        data = await self.request("POST", "/qr?as_base64=true", {})
        if not isinstance(data.get("session_id"), str) or not str(
            data.get("image_base64", "")
        ).startswith("data:image/"):
            raise WeChatError()
        return data

    async def poll(self, ident):
        return await self.request("GET", f"/qr/{ident}/poll")

    async def confirm(self, ident):
        return await self.request("POST", f"/qr/{ident}/confirm", {})

    async def cancel(self, ident):
        await self.request("POST", f"/qr/{ident}/cancel", {})

    async def delete(self, ref):
        await self.request("DELETE", f"/accounts?ref={int(ref)}")

    async def info(self, ref):
        accounts = await self.request("GET", "/accounts")
        for account in accounts:
            if str(account["id"]) == str(ref):
                return {
                    key: account.get(key)
                    for key in (
                        "id",
                        "nickname",
                        "status",
                        "credential_expires_at",
                        "rescan_recommended",
                    )
                }
        raise WeChatError("wechat_expired")

    async def code(self, ref):
        result = await self.request(
            "POST", "/wxapp/getCode", {"ref": str(ref), "app_id": APP_ID}, protocol=True
        )
        value = result.get("result")
        # The protocol returns a JSON payload, sometimes encoded as a string.
        for _ in range(5):
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    break
            if not isinstance(value, dict):
                break
            if any(value.get(k) not in (None, 0) for k in ("errcode", "err_no", "ret")):
                raise WeChatError("wechat_expired")
            if isinstance(value.get("code"), str) and value["code"]:
                return value["code"]
            value = value.get("data")
        raise WeChatError("wechat_code_invalid")
