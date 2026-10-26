"""Night-checkin port of GoodNight-UESTC at 15881c7 (see THIRD_PARTY.md)."""

import asyncio
import math
import hashlib
import json
import time
from uestc_login.http import USER_AGENT
from uestc_login.browser import REQUEST_TIMEOUT_MS
from .policy import succeeded, today_state, checkin_window, now

ORIGIN = "https://jzsz.uestc.edu.cn"


class SchoolError(Exception):
    def __init__(self, reason, *, http_status=None, api_code=None):
        super().__init__(reason)
        self.http_status = http_status
        self.api_code = api_code


async def request(ctx, path, body=None, *, headers=None):
    try:
        response = await ctx.request.fetch(
            ORIGIN + "/daily-checkin/api" + path,
            method="POST" if body is not None else "GET",
            data=body,
            headers={"platform": "h5", **(headers or {})},
            timeout=REQUEST_TIMEOUT_MS,
            max_redirects=0,
        )
    except Exception:
        raise SchoolError("transport_error") from None
    try:
        try:
            r = await response.json()
        except ValueError:
            r = None
        code = (
            r.get("code")
            if isinstance(r, dict) and type(r.get("code")) is int
            else None
        )
        if response.status in (301, 302, 401, 403):
            raise SchoolError("need_login", http_status=response.status, api_code=code)
        if response.status != 200:
            raise SchoolError("http_error", http_status=response.status, api_code=code)
        if (
            not isinstance(r, dict)
            or type(r.get("code")) is not int
            or ("ok" in r and type(r["ok"]) is not bool)
        ):
            raise SchoolError("invalid_api_response", http_status=response.status)
        if r["code"] == 5000:
            raise SchoolError("need_login", http_status=response.status, api_code=code)
        return r
    finally:
        await response.dispose()


async def authenticate(ctx):
    from uestc_login.client import validate, LoginError, ServiceUnavailable

    try:
        return await validate(ctx)
    except ServiceUnavailable:
        raise SchoolError("transport_error") from None
    except LoginError:
        raise SchoolError("need_login") from None


async def checkin_ticket(ctx, code):
    response = await ctx.request.post(
        ORIGIN + "/platform-app/api/auth/checkin-ticket",
        data={"code": code},
        headers={"platform": "mp-weixin"},
        max_redirects=0,
        timeout=REQUEST_TIMEOUT_MS,
    )
    try:
        if response.status in (301, 302, 401, 403):
            raise SchoolError("need_login")
        if response.status != 200:
            raise SchoolError("ticket_unavailable")
        payload = await response.json()
        if payload.get("code") == 5000:
            raise SchoolError("need_login")
        data = payload.get("data") or {}
        if (
            not succeeded(payload)
            or not isinstance(data.get("ticket"), str)
            or not data["ticket"]
        ):
            raise SchoolError("ticket_unavailable")
        try:
            expires = float(data["expiresAt"]) / 1000
        except (KeyError, ValueError, TypeError):
            raise SchoolError("ticket_unavailable") from None
        if not math.isfinite(expires) or expires <= time.time() + 2:
            raise SchoolError("ticket_expired")
        return data["ticket"]
    finally:
        await response.dispose()


def available_locations(response):
    """Validate centers while preserving school order."""
    if not succeeded(response) or not isinstance(response.get("data"), list):
        raise SchoolError("locations_unavailable")
    valid = []
    for row in response["data"]:
        if not isinstance(row, dict):
            continue
        values = [row.get(key) for key in ("latitude", "longitude", "radiusMeter")]
        if any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in values
        ):
            continue
        lat, lon, radius = values
        if abs(lat) <= 90 and abs(lon) <= 180 and radius > 0:
            valid.append(row)
    if not valid:
        raise SchoolError("no_available_locations")
    return valid


def location_option(row):
    name = row.get("locationName") or row.get("name")
    name = name.strip() if isinstance(name, str) else ""
    name = name or f"School location ({row['latitude']}, {row['longitude']})"
    # Prefer a stable school ID; otherwise match the named center, never its list index.
    identity = (
        ["id", str(row["id"])]
        if type(row.get("id")) in (str, int)
        else [name, float(row["latitude"]), float(row["longitude"])]
    )
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
    return {"key": key, "name": name}


def choose_location(rows, key=None):
    if key is None:
        return rows[0]
    for row in rows:
        if location_option(row)["key"] == key:
            return row
    raise SchoolError("selected_location_unavailable")


def submission_failure(diagnostic, state):
    """Only classify a rejection against a fresh, authenticated pending record."""
    diagnostic = diagnostic or {}
    if state == "pending" and diagnostic.get("code") in (46001, 46002, 46003):
        return "checkin_authorization_required"
    if diagnostic.get("error") == "need_login" or diagnostic.get("code") == 5000:
        return "need_login"
    if (
        state == "pending"
        and diagnostic.get("code") == 4001
        and diagnostic.get("ok") is not True
    ):
        return "checkin_rejected"
    return "unconfirmed"


async def run_checkin(
    ctx,
    date,
    journal,
    mark_submitted,
    *,
    location_key=None,
    on_location=None,
    submission_diagnostic=None,
    on_submission=None,
    ticket_provider=None,
):
    await authenticate(ctx)

    async def today():
        return await request(ctx, "/student-checkin-record/today")

    record = await today()
    state = today_state(record, date)
    if state == "done":
        return (
            "success"
            if record["data"]["recordStatusCode"] == "CHECKED_IN"
            else "already_done"
        )
    if state != "pending":
        return "unknown_record"
    if journal:
        return submission_failure(submission_diagnostic, state)  # Never repeat a POST.
    window = checkin_window(
        await request(ctx, "/checkin-schedule/effective"), date, now()
    )
    if window != "open":
        return window
    rows = available_locations(
        await request(ctx, "/checkin-location/available-locations")
    )
    selected = choose_location(rows, location_key)
    if on_location:
        on_location(location_option(selected)["name"])
    geo = {
        "latitude": selected["latitude"],
        "longitude": selected["longitude"],
        "accuracy": 20,
    }
    address = ""
    try:
        r = await request(
            ctx, f"/map/reverse?lat={geo['latitude']}&lng={geo['longitude']}"
        )
        if succeeded(r) and isinstance(r.get("data"), str):
            address = r["data"]
    except SchoolError as e:
        if str(e) == "need_login":
            raise
    record = await today()
    state = today_state(record, date)
    if state != "pending":
        if state == "done":
            return (
                "success"
                if record["data"]["recordStatusCode"] == "CHECKED_IN"
                else "already_done"
            )
        return "unknown_record"
    window = checkin_window(
        await request(ctx, "/checkin-schedule/effective"), date, now()
    )
    if window != "open":
        return window
    body = {
        **geo,
        "reverseGeocode": address,
        "userAgent": USER_AGENT,
        "clientTime": now().strftime("%Y-%m-%d %H:%M:%S"),
        "coordinateSystemCode": "gcj02",
        "locationDurationMs": 0,
        "networkTypeCode": "unknown",
        "locationEnabled": False,
        "locationAuthorized": "",
        "locationAccuracy": "",
        "errorMessage": "",
    }
    ticket = await ticket_provider(ctx) if ticket_provider else None
    # Ticket acquisition can take time. Check the window again before journaling.
    if (
        checkin_window(await request(ctx, "/checkin-schedule/effective"), date, now())
        != "open"
    ):
        return "window_missed"
    if not mark_submitted():
        return "window_missed"
    diagnostic = {}
    try:
        result = await request(
            ctx,
            "/student-checkin-record/checkin",
            body,
            **({"headers": {"X-Checkin-Ticket": ticket}} if ticket else {}),
        )
        diagnostic = {key: result[key] for key in ("code", "ok") if key in result}
    except SchoolError as e:
        diagnostic = {"error": str(e), "http_status": e.http_status, "code": e.api_code}
    except Exception as e:
        diagnostic = {"error": "runtime_error", "exception_type": type(e).__name__}
    # Preserve only protocol metadata, never response bodies, tickets or credentials.
    if on_submission:
        on_submission(diagnostic)
    state = "unknown"
    for attempt in range(1, 4):
        await asyncio.sleep(1.5 * attempt)
        try:
            record = await today()
            state = today_state(record, date)
            if state == "done":
                return (
                    "success"
                    if record["data"]["recordStatusCode"] == "CHECKED_IN"
                    else "already_done"
                )
        except SchoolError as e:
            state = "unknown"
            if str(e) == "need_login":
                raise
    return submission_failure(diagnostic, state)
