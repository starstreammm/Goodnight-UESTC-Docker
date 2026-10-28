import asyncio
import logging
import math
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Depends, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from uestc_login.http import HttpSessions
from .db import Store
from .auth import (
    authorize,
    router as auth_router,
    delete_records,
    cleanup_credentials,
    current_user,
)
from .models import Config, Login, AccountAlias, LocationChoice, SMSCode, CaptchaGesture
from .policy import now, succeeded
from .scheduler import Scheduler
from .bark import Bark
from uestc_login import submit_sms, LoginError, InvalidCode, Reauth
from uestc_login.client import validate, ServiceUnavailable
from uestc_login.browser import REQUEST_TIMEOUT_MS
from .wechat import WeChat, WeChatError
from .captcha import CaptchaRelay, CaptchaInteractionError
from .school import (
    authenticate,
    request as school_request,
    SchoolError,
    available_locations,
    choose_location,
    location_option,
)


@asynccontextmanager
async def lifespan(app):
    os.umask(0o077)
    store = Store(os.environ.get("DATA_DIR", "data"))
    # Linux/macOS advisory lock also prevents accidental multi-worker duplicate scheduling.
    import fcntl

    lock = (store.directory / "service.lock").open("a")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with store.connect() as db:
        db.execute("DELETE FROM invitations WHERE used_at IS NOT NULL")
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("goodnight").setLevel(store.config().log.upper())
    logging.getLogger("uestc_login").setLevel(store.config().log.upper())
    app.state.store, app.state.sessions = store, HttpSessions()
    app.state.logins = set()
    app.state.pending_logins = {}
    app.state.login_lock = asyncio.Lock()
    app.state.wechat = WeChat(store.directory)
    app.state.scheduler = Scheduler(store, app.state.sessions, app.state.wechat)
    app.state.scheduler.bark = Bark(store, app.state.scheduler)
    scheduler = asyncio.create_task(app.state.scheduler.loop())
    notifications = asyncio.create_task(app.state.scheduler.bark.loop())
    reaper = asyncio.create_task(expire_logins_loop())
    try:
        yield
    finally:
        for task in [scheduler, notifications, reaper, *app.state.scheduler.tasks]:
            task.cancel()
        await asyncio.gather(
            scheduler,
            notifications,
            reaper,
            *app.state.scheduler.tasks,
            return_exceptions=True,
        )
        for ident, pending in list(app.state.pending_logins.items()):
            await close_login(ident, pending)
        try:
            await app.state.wechat.close()
        finally:
            lock.close()


app = FastAPI(
    title="GoodNight UESTC",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    dependencies=[Depends(authorize)],
)
app.include_router(auth_router)


async def same_origin(request: Request):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Cross-origin requests are not allowed")


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Pydantic's normal error input can contain plaintext passwords; never echo it.
    return JSONResponse(
        status_code=422,
        content={
            "detail": "; ".join(
                str(e["loc"][-1]) + ": " + e["msg"] for e in exc.errors()
            )
        },
    )


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/state", dependencies=[Depends(same_origin)])
async def state(request: Request):
    store = app.state.store
    with store.connect() as db:
        accounts = [
            dict(r)
            for r in db.execute(
                "SELECT a.id,a.username,a.alias,a.status,a.location_key,a.location_name,a.wechat_ref,a.checkin_time,a.schedule,a.details, "
                "u.id AS owner_id,u.username AS owner_username,u.display_name AS owner_display_name,u.role AS owner_role,u.builtin AS owner_builtin "
                "FROM accounts a JOIN users u ON u.id=a.owner_id WHERE (?='admin' OR a.owner_id=?) ORDER BY a.id",
                (request.state.user["role"], request.state.user["id"]),
            )
        ]
        for account in accounts:
            account["real_name"] = real_name(json.loads(account.pop("details") or "{}"))
            account["school_window"] = Scheduler.school_window(
                account, now().date().isoformat()
            )
            account.pop("schedule")
            account.update(store.login.metadata(account["username"]))
        jobs = [
            dict(r)
            for r in db.execute(
                "SELECT jobs.* FROM jobs JOIN accounts ON accounts.id=jobs.account_id "
                "WHERE date=? AND (?='admin' OR accounts.owner_id=?)",
                (
                    now().date().isoformat(),
                    request.state.user["role"],
                    request.state.user["id"],
                ),
            )
        ]
    return {
        "accounts": accounts,
        "jobs": jobs,
        "busy_accounts": sorted(app.state.scheduler.busy & {a["id"] for a in accounts}),
        "user": request.state.user,
        **({"config": store.config()} if request.state.user["role"] == "admin" else {}),
        "timezone": "Asia/Shanghai",
        "date": now().date().isoformat(),
    }


@app.post(
    "/api/accounts/{ident}/check-in",
    dependencies=[Depends(same_origin)],
    status_code=202,
)
async def manual_checkin(ident: int):
    scheduler, store = app.state.scheduler, app.state.store
    if ident in scheduler.busy:
        raise HTTPException(
            409, "This account is busy; wait for the current operation to finish"
        )
    if len(scheduler.tasks) >= 3:
        raise HTTPException(409, "All check-in workers are busy; try again shortly")
    with store.connect() as db:
        account = db.execute(
            "SELECT status FROM accounts WHERE id=?", (ident,)
        ).fetchone()
    if not account:
        raise HTTPException(404, "Account not found")
    if account["status"] == "need_login":
        raise HTTPException(409, "Sign in again before checking this account")
    current = now()
    scheduler.plan(current)
    date = current.date().isoformat()
    with store.connect() as db:
        job = dict(
            db.execute(
                "SELECT * FROM jobs WHERE account_id=? AND date=?", (ident, date)
            ).fetchone()
        )
        db.execute(
            "UPDATE jobs SET status='running',message='Checking the school record; submitting only if needed' WHERE account_id=? AND date=?",
            (ident, date),
        )
    # Reserve before yielding; manual and scheduled runs share one journal.
    scheduler.busy.add(ident)
    task = asyncio.create_task(scheduler.execute(job, manual=True))
    scheduler.tasks.add(task)
    task.add_done_callback(scheduler.tasks.discard)
    return {"status": "running", "date": date}


@app.put("/api/config", dependencies=[Depends(same_origin)])
async def config(config: Config):
    store = app.state.store
    with store.connect() as db:
        db.execute("UPDATE config SET value=? WHERE id=1", (config.model_dump_json(),))
    logging.getLogger("goodnight").setLevel(config.log.upper())
    # Existing daily schedules stay fixed; edits take effect for new daily jobs.
    return config


async def account_locations(ident, choice=None):
    runner, store = app.state.scheduler, app.state.store
    if ident in runner.busy:
        raise HTTPException(409, "This account is busy; try again when it finishes")
    with store.connect() as db:
        account = db.execute("SELECT * FROM accounts WHERE id=?", (ident,)).fetchone()
    if not account:
        raise HTTPException(404, "Account not found")
    if account["status"] == "need_login":
        raise HTTPException(409, "Sign in again to load school locations")
    runner.busy.add(ident)
    ctx = None
    try:
        async with asyncio.timeout(45):
            saved = await runner.session(account)
            ctx = await app.state.sessions.new_context(storage_state=saved)
            await authenticate(ctx)
            rows = available_locations(
                await school_request(ctx, "/checkin-location/available-locations")
            )
            options = [location_option(row) for row in rows]
            key = choice.key if choice is not None else account["location_key"]
            # Let users replace a saved location that the school has removed.
            selected = None
            try:
                selected = location_option(choose_location(rows, key))
            except SchoolError:
                if choice is not None:
                    raise
            session = store.cipher.encrypt(
                json.dumps(await ctx.storage_state()).encode()
            )
            with store.connect() as db:
                db.execute("UPDATE accounts SET session=? WHERE id=?", (session, ident))
                if selected:
                    db.execute(
                        "UPDATE accounts SET location_name=? WHERE id=?",
                        (selected["name"], ident),
                    )
                if choice is not None:
                    db.execute(
                        "UPDATE accounts SET location_key=? WHERE id=?",
                        (selected["key"], ident),
                    )
                elif selected and key is None:
                    db.execute(
                        "UPDATE accounts SET location_key=? WHERE id=?",
                        (selected["key"], ident),
                    )
            return {
                "locations": options,
                "selected_key": selected["key"] if selected else None,
                "automatic": False,
                "unavailable": selected is None,
            }
    except LoginError:
        with store.connect() as db:
            db.execute("UPDATE accounts SET status='need_login' WHERE id=?", (ident,))
        raise HTTPException(
            409,
            {
                "code": "need_login",
                "message": "Sign in again to load school locations.",
            },
        ) from None
    except SchoolError as error:
        code = str(error)
        if code == "need_login":
            with store.connect() as db:
                db.execute(
                    "UPDATE accounts SET status='need_login' WHERE id=?", (ident,)
                )
        message = {
            "need_login": "Sign in again to load school locations.",
            "selected_location_unavailable": "This location is no longer allowed. Refresh and choose another.",
            "no_available_locations": "The school returned no valid locations. Try refreshing later.",
        }.get(code, "School locations could not be loaded. Try refreshing shortly.")
        raise HTTPException(
            409 if code in ("need_login", "selected_location_unavailable") else 502,
            {"code": code, "message": message},
        ) from None
    except Exception:
        raise HTTPException(
            502, "School locations are unavailable. Try again shortly."
        ) from None
    finally:
        try:
            if ctx:
                await ctx.close()
        except Exception:
            pass
        finally:
            runner.busy.discard(ident)


@app.get("/api/accounts/{ident}/locations", dependencies=[Depends(same_origin)])
async def get_account_locations(ident: int):
    return await account_locations(ident)


@app.put("/api/accounts/{ident}/location", dependencies=[Depends(same_origin)])
async def set_account_location(ident: int, choice: LocationChoice):
    return await account_locations(ident, choice)


@app.patch("/api/accounts/{ident}", dependencies=[Depends(same_origin)])
async def rename_account(ident: int, data: AccountAlias):
    if ident in app.state.scheduler.busy:
        raise HTTPException(409, "This account is busy; try again when it finishes")
    with app.state.store.connect() as db:
        account = db.execute("SELECT * FROM accounts WHERE id=?", (ident,)).fetchone()
        if not account:
            raise HTTPException(404, "Account not found")
        if "checkin_time" in data.model_fields_set and data.checkin_time is not None:
            window = Scheduler.school_window(account, now().date().isoformat())
            if not window:
                raise HTTPException(
                    409,
                    {
                        "code": "schedule_unavailable",
                        "message": "Today’s school check-in window is unavailable. Try again after it refreshes.",
                    },
                )
            start, end = window.split("_")
            preferred_start, preferred_end = data.checkin_time.split("_")
            if preferred_start < start or preferred_end > end:
                raise HTTPException(
                    422,
                    {
                        "code": "invalid_checkin_range",
                        "message": "Choose a range inside the available school check-in window.",
                    },
                )
        owner = db.execute(
            "SELECT role,username,display_name FROM users WHERE id=?",
            (account["owner_id"],),
        ).fetchone()
        alias = data.alias if data.alias is not None else account["alias"]
        if owner["role"] == "user":
            alias = owner["display_name"].strip() or owner["username"]
            if data.alias is not None and data.alias != alias:
                raise HTTPException(
                    403,
                    "Account aliases follow the User display name and cannot be edited separately",
                )
        db.execute("UPDATE accounts SET alias=? WHERE id=?", (alias, ident))
        changed = (
            "checkin_time" in data.model_fields_set
            and data.checkin_time != account["checkin_time"]
        )
        if changed:
            db.execute(
                "UPDATE accounts SET checkin_time=? WHERE id=?",
                (data.checkin_time, ident),
            )
    if changed:
        app.state.scheduler.reschedule(ident, force=True)
    return {"ok": True}


@app.delete("/api/accounts/{ident}", dependencies=[Depends(same_origin)])
async def delete_account(ident: int, request: Request, delete_user: bool = True):
    return delete_records(request, account_id=ident, delete_user=delete_user)


@dataclass
class PendingLogin:
    context: object | None
    username: str
    alias: str
    account_id: int | None
    user_id: int
    login_target: str = "both"
    wechat_authorized: bool = False
    expires: float = field(default_factory=lambda: time.monotonic() + 300)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    attempts: int = 0
    relay: CaptchaRelay = field(default_factory=CaptchaRelay)
    task: asyncio.Task | None = None
    password: str | None = field(default=None, repr=False)
    save_password: bool = False
    new_fingerprint: str | None = field(default=None, repr=False)
    school_state: dict | None = field(default=None, repr=False)
    qr: str | None = None
    review: dict | None = field(default=None, repr=False)
    locations: list = field(default_factory=list, repr=False)
    wechat_account: dict | None = field(default=None, repr=False)


async def reserve_login(username, user):
    async with app.state.login_lock:
        if len(app.state.logins) >= 2 or username in app.state.logins:
            raise HTTPException(409, "A sign-in is already running; try again shortly")
        with app.state.store.connect() as db:
            account = db.execute(
                "SELECT id,owner_id FROM accounts WHERE username=?", (username,)
            ).fetchone()
            if db.execute(
                "SELECT 1 FROM credential_cleanup WHERE username=?", (username,)
            ).fetchone():
                raise HTTPException(
                    409,
                    "Previous account credentials are being removed. Try again shortly",
                )
            if (
                account
                and user["role"] != "admin"
                and account["owner_id"] != user["id"]
            ):
                raise HTTPException(403, "This school account is not available")
            if (
                not account
                and user["role"] == "user"
                and (
                    db.execute(
                        "SELECT 1 FROM accounts WHERE owner_id=?", (user["id"],)
                    ).fetchone()
                    or any(
                        p.user_id == user["id"]
                        for p in app.state.pending_logins.values()
                    )
                )
            ):
                raise HTTPException(409, "Users may own only one Account")
        if account and account["id"] in app.state.scheduler.busy:
            raise HTTPException(409, "This account is checking in; try again shortly")
        app.state.logins.add(username)
        account_id = account["id"] if account else None
        if account_id is not None:
            app.state.scheduler.busy.add(account_id)
        return account_id


def release_login(username, account_id):
    app.state.logins.discard(username)
    if account_id is not None:
        app.state.scheduler.busy.discard(account_id)


def login_error(error):
    if isinstance(error, CaptchaInteractionError):
        return HTTPException(400, {"code": "captcha_error", "message": str(error)})
    if isinstance(error, WeChatError):
        if str(error) == "wechat_pending":
            return HTTPException(
                409,
                {
                    "code": "wechat_pending",
                    "message": "WeChat credentials are not ready yet. Confirm again shortly.",
                },
            )
        return HTTPException(
            502,
            {"code": str(error), "message": "WeChat is unavailable. Please try again."},
        )
    if isinstance(error, LoginError):
        logging.getLogger("goodnight").warning(
            "School login failed: code=%s type=%s reason=%s",
            error.code,
            type(error).__name__,
            str(error),
        )
        detail = {"code": error.code, "message": str(error)}
        if isinstance(error, ServiceUnavailable):
            # Only structured protocol metadata reaches the UI, never raw HTML,
            # request URLs, cookies, form fields or transport exception text.
            detail.update(
                stage=error.stage, http_status=error.http_status, reason=error.reason
            )
            if error.reason == "timeout":
                detail["timeout_seconds"] = REQUEST_TIMEOUT_MS / 1000
        return HTTPException(400, detail)
    if isinstance(error, SchoolError):
        return HTTPException(
            502,
            {
                "code": "review_unavailable",
                "message": "Could not load the school schedule or locations. Retry to review the account.",
            },
        )
    logging.getLogger("goodnight").error(
        "School sign-in failed unexpectedly: type=%s reason=%s",
        type(error).__name__,
        str(error),
        exc_info=(type(error), error, error.__traceback__),
    )
    return HTTPException(
        502, "School sign-in is unavailable; check network access and try again"
    )


async def close_login(ident, pending):
    if app.state.pending_logins.pop(ident, None) is None:
        return
    try:
        if pending.task:
            pending.task.cancel()
            results = await asyncio.gather(pending.task, return_exceptions=True)
            # An SMS task can finish between cancellation and cleanup. Its context
            # has not yet been transferred to pending.context in that case.
            if results and isinstance(results[0], Reauth):
                await results[0].context.close()
        if pending.context:
            await pending.context.context.close()
        if pending.qr:
            await app.state.wechat.cancel(pending.qr)
    except Exception:
        logging.getLogger("goodnight").warning("Could not close a login HTTP session")
    finally:
        pending.password = None
        pending.new_fingerprint = None
        release_login(pending.username, pending.account_id)


async def expire_logins():
    for ident, pending in list(app.state.pending_logins.items()):
        if pending.expires <= time.monotonic() and not pending.lock.locked():
            async with pending.lock:
                await close_login(ident, pending)


async def expire_logins_loop():
    while True:
        await asyncio.sleep(10)
        await expire_logins()
        await cleanup_credentials(app)


def expired_error():
    return HTTPException(
        410, {"code": "expired", "message": "Login expired. Please start again."}
    )


def get_pending(ident):
    pending = app.state.pending_logins.get(ident)
    if pending is None:
        raise expired_error()
    if pending.lock.locked():
        raise HTTPException(409, "This login is busy; try again shortly")
    return pending


async def check_expiry(ident, pending):
    if pending.expires <= time.monotonic():
        await close_login(ident, pending)
        raise expired_error()


def pending_response(ident, pending, message=None):
    captcha = pending.relay.ready.is_set()
    return {
        "login_id": ident,
        "expires_in": max(0, int(pending.expires - time.monotonic())),
        "state": "captcha" if captcha else "sms",
        "challenge": pending.relay.snapshot if captcha else None,
        "message": message
        or (
            "Drag the slider to complete the school CAPTCHA."
            if captcha
            else "SMS code sent. Enter the code from the school."
        ),
    }


async def prepare_review(pending):
    context = await app.state.sessions.new_context(storage_state=pending.school_state)
    try:
        detail = await validate(context)
        schedule = await school_request(context, "/checkin-schedule/effective")
        if not succeeded(schedule) or not isinstance(
            schedule.get("data"), (dict, type(None))
        ):
            raise SchoolError("schedule_unavailable")
        locations = available_locations(
            await school_request(context, "/checkin-location/available-locations")
        )
        pending.school_state = await context.storage_state()
    finally:
        await context.close()
    key = None
    if pending.account_id is not None:
        with app.state.store.connect() as db:
            key = db.execute(
                "SELECT location_key FROM accounts WHERE id=?", (pending.account_id,)
            ).fetchone()["location_key"]
    options = [
        {
            **location_option(row),
            **{field: row[field] for field in ("latitude", "longitude", "radiusMeter")},
        }
        for row in locations
    ]
    unavailable = key is not None and not any(
        option["key"] == key for option in options
    )
    pending.locations = locations
    with app.state.store.connect() as db:
        owner = db.execute(
            "SELECT role,username,display_name FROM users WHERE id=COALESCE("
            "(SELECT owner_id FROM accounts WHERE id=?),?)",
            (pending.account_id, pending.user_id),
        ).fetchone()
    alias = (
        owner["display_name"].strip() or owner["username"]
        if owner["role"] == "user"
        else pending.alias.strip() or real_name(detail) or pending.username
    )
    pending.review = {
        "username": pending.username,
        "alias": alias,
        "detail": detail,
        "schedule": {"date": now().date().isoformat(), "response": schedule},
        "locations": options,
        "location_key": options[0]["key"] if unavailable or key is None else key,
        "location_changed": unavailable,
        "save_password": pending.save_password,
    }


async def step_response(ident, pending):
    """Wait for the school result or a challenge that needs the user's gesture."""
    waiter = asyncio.create_task(pending.relay.ready.wait())
    try:
        await asyncio.wait([pending.task, waiter], return_when=asyncio.FIRST_COMPLETED)
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
    if not pending.task.done():
        return pending_response(ident, pending)
    task, pending.task = pending.task, None
    try:
        result = task.result()
        if isinstance(result, Reauth):
            pending.context = result
            return pending_response(ident, pending)
        pending.school_state = result
        if pending.login_target == "school":
            await prepare_review(pending)
            return review_response(ident, pending)
        qr = await app.state.wechat.start()
        pending.qr = qr["session_id"]
        return {
            "state": "wechat",
            "login_id": ident,
            "image": qr["image_base64"],
            "expires_in": max(0, int(pending.expires - time.monotonic())),
        }
    except InvalidCode as error:
        if pending.attempts < 5:
            raise login_error(error) from None
        await close_login(ident, pending)
        raise HTTPException(
            400,
            {
                "code": "expired",
                "message": "Too many failed attempts. Please start again.",
            },
        ) from None
    except BaseException as error:
        await close_login(ident, pending)
        if isinstance(error, asyncio.CancelledError):
            raise expired_error() from None
        if not isinstance(error, Exception):
            raise
        raise login_error(error) from None


async def begin_login(data, request):
    await expire_logins()
    user = current_user(request)
    account_id = await reserve_login(data.username, user)
    if data.login_target != "both" and account_id is None:
        release_login(data.username, account_id)
        raise HTTPException(
            404, "Add the account before signing in to one service separately"
        )
    ident = secrets.token_urlsafe(24)
    pending = PendingLogin(
        None,
        data.username,
        data.alias,
        account_id,
        user["id"],
        login_target=data.login_target,
    )
    app.state.pending_logins[ident] = pending
    async with pending.lock:
        if pending.login_target == "wechat":
            try:
                qr = await app.state.wechat.start()
                pending.qr = qr["session_id"]
                return {
                    "state": "wechat",
                    "login_id": ident,
                    "image": qr["image_base64"],
                    "expires_in": max(0, int(pending.expires - time.monotonic())),
                }
            except BaseException as error:
                await close_login(ident, pending)
                if not isinstance(error, Exception):
                    raise
                raise login_error(error) from None
        password = (
            data.password.get_secret_value()
            if data.password
            else (
                app.state.store.login.load(data.username).get("password")
                if account_id is not None
                else None
            )
        )
        if not password:
            await close_login(ident, pending)
            raise HTTPException(
                400,
                {
                    "code": "password_missing",
                    "message": "No school password was received. Enter it or use a previously saved password.",
                },
            )
        pending.password = password if data.save_password else None
        pending.save_password = data.save_password
        # Failed Add-account attempts may leave a legacy fingerprint-only record.
        # Until an account is confirmed, every attempt starts with a new identity.
        if account_id is None or data.new_browser_fingerprint:
            pending.new_fingerprint = app.state.store.login.new_fingerprint(
                data.username
            )
        logging.getLogger("goodnight").info(
            "School login browser_identity=%s",
            (
                "new_account"
                if account_id is None
                else (
                    "new_fingerprint"
                    if pending.new_fingerprint is not None
                    else "existing_account"
                )
            ),
        )
        pending.task = asyncio.create_task(
            app.state.store.login.login(
                app.state.sessions,
                data.username,
                password,
                challenge=pending.relay,
                new_fingerprint=pending.new_fingerprint,
                force=pending.login_target == "school",
            )
        )
        try:
            return await step_response(ident, pending)
        except asyncio.CancelledError:
            await close_login(ident, pending)
            raise


@app.post("/api/accounts", dependencies=[Depends(same_origin)], status_code=201)
async def add_account(data: Login, request: Request):
    return await begin_login(data, request)


@app.post("/api/logins/{ident}/code", dependencies=[Depends(same_origin)])
async def verify_sms(ident: str, data: SMSCode):
    pending = get_pending(ident)
    async with pending.lock:
        await check_expiry(ident, pending)
        if pending.task or pending.context is None or pending.school_state is not None:
            raise HTTPException(409, "Complete the CAPTCHA before entering an SMS code")
        pending.attempts += 1
        pending.task = asyncio.create_task(
            submit_sms(pending.context, data.code.get_secret_value())
        )
        return await step_response(ident, pending)


@app.post("/api/logins/{ident}/captcha", dependencies=[Depends(same_origin)])
async def drag_captcha(ident: str, data: CaptchaGesture):
    pending = get_pending(ident)
    async with pending.lock:
        await check_expiry(ident, pending)
        if not pending.task:
            raise HTTPException(409, "No CAPTCHA is awaiting input")
        if pending.task.done():
            return await step_response(ident, pending)
        try:
            accepted = await pending.relay.drag(data)
        except CaptchaInteractionError as error:
            return pending_response(ident, pending, str(error))
        except Exception:
            await close_login(ident, pending)
            raise HTTPException(
                400,
                {
                    "code": "expired",
                    "message": "The CAPTCHA expired or could not be verified. Please start again.",
                },
            ) from None
        if not accepted:
            return pending_response(
                ident, pending, "The school rejected that drag. Try the new CAPTCHA."
            )
        return await step_response(ident, pending)


@app.post("/api/logins/{ident}/captcha/refresh", dependencies=[Depends(same_origin)])
async def refresh_captcha(ident: str):
    pending = get_pending(ident)
    async with pending.lock:
        await check_expiry(ident, pending)
        if not pending.task:
            raise HTTPException(409, "No CAPTCHA is awaiting input")
        if pending.task.done():
            return await step_response(ident, pending)
        try:
            await pending.relay.refresh()
            return pending_response(ident, pending)
        except Exception:
            await close_login(ident, pending)
            raise HTTPException(
                400,
                {
                    "code": "expired",
                    "message": "Could not refresh the CAPTCHA. Please start again.",
                },
            ) from None


@app.delete("/api/logins/{ident}", dependencies=[Depends(same_origin)])
async def cancel_login(ident: str):
    pending = app.state.pending_logins.get(ident)
    if pending is not None:
        if pending.lock.locked():
            raise HTTPException(409, "This login is busy; try again shortly")
        async with pending.lock:
            await close_login(ident, pending)
    return {"ok": True}


@app.get("/api/logins/{ident}/wechat", dependencies=[Depends(same_origin)])
async def poll_wechat(ident: str):
    pending = get_pending(ident)
    async with pending.lock:
        await check_expiry(ident, pending)
        if not pending.qr or (
            pending.login_target != "wechat" and not pending.school_state
        ):
            raise HTTPException(409, "Complete school sign-in first")
        if pending.review is not None:
            return review_response(ident, pending)
        try:
            result = await app.state.wechat.poll(pending.qr)
            if result["status"] in ("expired", "cancelled"):
                await close_login(ident, pending)
                raise expired_error()
            if result["status"] != "authorized":
                return {"state": "wechat", "status": result["status"]}
            if pending.login_target == "wechat":
                pending.wechat_authorized = True
                return {
                    "state": "wechat_confirm",
                    "login_id": ident,
                    "expires_in": max(0, int(pending.expires - time.monotonic())),
                }
            await prepare_review(pending)
        except WeChatError as error:
            raise login_error(error) from None
        except LoginError as error:
            await close_login(ident, pending)
            raise login_error(error) from None
        except SchoolError as error:
            raise login_error(error) from None
        except HTTPException:
            raise
        except Exception as error:
            raise login_error(error) from None
        return review_response(ident, pending)


def review_response(ident, pending):
    return {
        "state": "review",
        "login_id": ident,
        "expires_in": max(0, int(pending.expires - time.monotonic())),
        "review": pending.review,
    }


@app.post("/api/logins/{ident}/confirm", dependencies=[Depends(same_origin)])
async def confirm_login(ident: str, choice: LocationChoice, request: Request):
    pending = get_pending(ident)
    async with pending.lock:
        await check_expiry(ident, pending)
        if pending.login_target == "wechat":
            if not pending.wechat_authorized:
                raise HTTPException(409, "Scan and authorize WeChat first")
            try:
                if pending.wechat_account is None:
                    pending.wechat_account = await app.state.wechat.confirm(pending.qr)
                    pending.qr = None
            except WeChatError as error:
                raise login_error(error) from None
            current_user(request)
            with app.state.store.connect() as db:
                db.execute(
                    "UPDATE accounts SET wechat_ref=?,wechat_lease_started_at=NULL, "
                    "wechat_lease_expires_at=NULL WHERE id=?",
                    (str(pending.wechat_account["id"]), pending.account_id),
                )
                # Resume work blocked on WeChat, preserving any submission journal.
                db.execute(
                    "UPDATE jobs SET status='scheduled',attempts=0 WHERE account_id=? "
                    "AND status IN ('wechat_expired','wechat_code_invalid')",
                    (pending.account_id,),
                )
            await close_login(ident, pending)
            return {"state": "done", "ok": True}
        if pending.review is None:
            raise HTTPException(409, "Complete sign-in and review the account first")
        try:
            selected = location_option(choose_location(pending.locations, choice.key))
        except SchoolError:
            raise HTTPException(
                409,
                {
                    "code": "selected_location_unavailable",
                    "message": "Choose a location from the account review.",
                },
            ) from None
        try:
            if pending.login_target != "school" and pending.wechat_account is None:
                pending.wechat_account = await app.state.wechat.confirm(pending.qr)
                pending.qr = None
        except WeChatError as error:
            raise login_error(error) from None
        user = current_user(request)
        with app.state.store.connect() as db:
            account = db.execute(
                "SELECT owner_id FROM accounts WHERE username=?", (pending.username,)
            ).fetchone()
            if (
                account
                and user["role"] != "admin"
                and account["owner_id"] != user["id"]
            ):
                raise HTTPException(403, "Account access changed. Start sign-in again")
        # No account, saved password or scheduler entry is created before this action.
        store, review = app.state.store, pending.review
        store.login.save(
            pending.username,
            pending.school_state,
            pending.password,
            pending.save_password,
            fingerprint=pending.new_fingerprint,
        )
        store.save_session(
            pending.username, review["alias"], pending.school_state, pending.user_id
        )
        with store.connect() as db:
            db.execute(
                "UPDATE accounts SET details=?,schedule=?,location_key=?,location_name=? WHERE username=?",
                (
                    json.dumps(review["detail"]),
                    json.dumps(review["schedule"]),
                    selected["key"],
                    selected["name"],
                    pending.username,
                ),
            )
            if pending.login_target != "school":
                db.execute(
                    "UPDATE accounts SET wechat_ref=?,wechat_lease_started_at=NULL, "
                    "wechat_lease_expires_at=NULL WHERE username=?",
                    (str(pending.wechat_account["id"]), pending.username),
                )
        await close_login(ident, pending)
        return {"state": "done", "ok": True}


def real_name(detail):
    if not isinstance(detail, dict):
        return None
    for key in ("realName", "userName", "name", "studentName"):
        if isinstance(detail.get(key), str) and detail[key].strip():
            return detail[key].strip()
    for key in ("user", "student", "baseInfo"):
        if name := real_name(detail.get(key)):
            return name
    return None


@app.get("/api/accounts/{ident}/info", dependencies=[Depends(same_origin)])
async def account_info(ident: int):
    store = app.state.store
    with store.connect() as db:
        account = db.execute("SELECT * FROM accounts WHERE id=?", (ident,)).fetchone()
    if not account:
        raise HTTPException(404, "Account not found")
    metadata = store.login.metadata(account["username"])
    wx = None
    wx_error = None
    if account["wechat_ref"]:
        try:
            wx = await app.state.wechat.info(account["wechat_ref"])
            expiry = wx.get("credential_expires_at")
            if type(expiry) in (int, float) and math.isfinite(expiry):
                # Keep a stable baseline for the expiry bar. Reset it only when
                # the upstream reports a different credential expiry (renewal).
                started = account["wechat_lease_started_at"]
                if started is None or account["wechat_lease_expires_at"] != expiry:
                    started = time.time()
                    with store.connect() as db:
                        db.execute(
                            "UPDATE accounts SET wechat_lease_started_at=?,wechat_lease_expires_at=? "
                            "WHERE id=? AND wechat_ref=?",
                            (started, expiry, ident, account["wechat_ref"]),
                        )
                wx["credential_observed_at"] = started
        except WeChatError as error:
            wx_error = str(error)
    return {
        **metadata,
        "schedule": json.loads(account["schedule"] or "{}"),
        "detail": json.loads(account["details"] or "{}"),
        "location_name": account["location_name"],
        "wechat": wx,
        "wechat_error": wx_error,
    }


@app.delete("/api/accounts/{ident}/password", dependencies=[Depends(same_origin)])
async def forget_password(ident: int):
    if ident in app.state.scheduler.busy:
        raise HTTPException(409, "Account is busy")
    with app.state.store.connect() as db:
        account = db.execute(
            "SELECT username FROM accounts WHERE id=?", (ident,)
        ).fetchone()
    if not account:
        raise HTTPException(404, "Account not found")
    app.state.store.login.forget_password(account["username"])
    return {"ok": True}


static = Path(os.environ.get("STATIC_DIR", "app/build/client")).resolve()
if (static / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")


@app.get("/{path:path}")
async def page(path: str):
    if path.startswith("api/"):
        raise HTTPException(404, "API route not found")
    route = path.rstrip("/")
    html = (
        static / route / "index.html"
        if route in ("", "login", "admin")
        else static / "__spa-fallback.html"
    )
    if not html.is_file():
        raise HTTPException(
            503, "Build the frontend or use the Vite development server"
        )
    return FileResponse(html)
