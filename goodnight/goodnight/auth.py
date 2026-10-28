"""Console identities, persistent sessions, and ownership authorization."""

import hashlib
import hmac
import logging
import os
import secrets
import sqlite3
import time
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from starlette.concurrency import run_in_threadpool

from .wechat import WeChatError

COOKIE = "goodnight_session"
SESSION_TTL = 30 * 86400
USER_FIELDS = (
    "id,username,display_name,role,builtin,must_change_password,language,"
    "bark_enabled,bark_prompt_dismissed,(bark_key IS NOT NULL) AS bark_configured"
)
router = APIRouter(prefix="/api")


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=bytes.fromhex(salt),
        n=32768,
        r=8,
        p=3,
        maxmem=64 * 1024 * 1024,
    ).hex()
    return f"scrypt${salt}${digest}"


def verify_password(password, encoded):
    _, salt, _ = encoded.split("$")
    return hmac.compare_digest(hash_password(password, salt), encoded)


def initialize_auth(db):
    for statement in (
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT NOT NULL DEFAULT '', password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','user')),
            builtin INTEGER NOT NULL DEFAULT 0 CHECK(builtin IN (0,1)),
            must_change_password INTEGER NOT NULL DEFAULT 0)""",
        "CREATE UNIQUE INDEX IF NOT EXISTS builtin_admin ON users(builtin) WHERE builtin=1",
        """CREATE TABLE IF NOT EXISTS auth_sessions (
            token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL
            REFERENCES users(id) ON DELETE CASCADE, expires_at REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS auth_settings (
            id INTEGER PRIMARY KEY CHECK(id=1), registration_mode TEXT NOT NULL
            CHECK(registration_mode IN ('disabled','invitation','open')))""",
        """CREATE TABLE IF NOT EXISTS invitations (
            id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL, used_at REAL)""",
        """CREATE TABLE IF NOT EXISTS auth_attempts (
            key TEXT PRIMARY KEY, started_at REAL NOT NULL, attempts INTEGER NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS credential_cleanup (
            username TEXT PRIMARY KEY, wechat_ref TEXT)""",
    ):
        db.execute(statement)
    user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)")}
    for name, definition in (
        ("language", "TEXT NOT NULL DEFAULT 'en' CHECK(language IN ('en','zh'))"),
        ("bark_key", "BLOB"),
        ("bark_enabled", "INTEGER NOT NULL DEFAULT 0 CHECK(bark_enabled IN (0,1))"),
        (
            "bark_prompt_dismissed",
            "INTEGER NOT NULL DEFAULT 0 CHECK(bark_prompt_dismissed IN (0,1))",
        ),
    ):
        if name not in user_columns:
            db.execute(f"ALTER TABLE users ADD COLUMN {name} {definition}")
    admin = db.execute("SELECT id FROM users WHERE builtin=1").fetchone()
    if not admin:
        admin_id = db.execute(
            "INSERT INTO users(username,display_name,password_hash,role,builtin,must_change_password) "
            "VALUES('admin','Admin',?,'admin',1,1)",
            (hash_password("yyytttqqq"),),
        ).lastrowid
    else:
        admin_id = admin["id"]
    # Upgrade the earlier multi-Admin model without deleting or transferring Accounts.
    columns = {row["name"] for row in db.execute("PRAGMA table_info(accounts)")}
    if (
        "owner_id" in columns
        and db.execute(
            "SELECT 1 FROM users WHERE builtin=0 AND role='admin' "
            "AND (SELECT count(*) FROM accounts WHERE owner_id=users.id)>1"
        ).fetchone()
    ):
        raise RuntimeError(
            "An additional Admin owns multiple Accounts. Reduce their Accounts to at most one before upgrading."
        )
    if db.execute(
        "SELECT 1 FROM users WHERE username='admin' AND builtin=0"
    ).fetchone():
        raise RuntimeError(
            "The username admin belongs to another User. Rename that User before upgrading."
        )
    db.execute(
        "DELETE FROM auth_sessions WHERE user_id IN (SELECT id FROM users WHERE builtin=0 AND role='admin')"
    )
    db.execute("UPDATE users SET role='user' WHERE builtin=0 AND role='admin'")
    db.execute("UPDATE users SET username='admin' WHERE builtin=1")
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS single_admin ON users(role) WHERE role='admin'"
    )
    db.execute("INSERT OR IGNORE INTO auth_settings VALUES(1,'disabled')")
    if "owner_id" not in columns:
        db.execute(
            "ALTER TABLE accounts ADD COLUMN owner_id INTEGER REFERENCES users(id) ON DELETE CASCADE"
        )
        db.execute("UPDATE accounts SET owner_id=?", (admin_id,))
    db.execute("CREATE INDEX IF NOT EXISTS account_owner ON accounts(owner_id)")
    db.execute(
        "UPDATE accounts SET alias=(SELECT COALESCE(NULLIF(trim(display_name),''),username) "
        "FROM users WHERE id=accounts.owner_id) "
        "WHERE owner_id IN (SELECT id FROM users WHERE role='user')"
    )
    # ADD COLUMN cannot add a non-null foreign key to a populated SQLite table.
    # Triggers enforce non-null ownership without rebuilding accounts or jobs.
    for statement in (
        """CREATE TRIGGER IF NOT EXISTS user_alias_insert AFTER INSERT ON accounts
            WHEN (SELECT role FROM users WHERE id=NEW.owner_id)='user'
            BEGIN UPDATE accounts SET alias=(SELECT COALESCE(NULLIF(trim(display_name),''),username)
                FROM users WHERE id=NEW.owner_id) WHERE id=NEW.id; END""",
        """CREATE TRIGGER IF NOT EXISTS user_alias_update AFTER UPDATE OF alias ON accounts
            WHEN NEW.alias IS NOT (SELECT COALESCE(NULLIF(trim(display_name),''),username)
                FROM users WHERE id=NEW.owner_id AND role='user')
            AND (SELECT role FROM users WHERE id=NEW.owner_id)='user'
            BEGIN UPDATE accounts SET alias=(SELECT COALESCE(NULLIF(trim(display_name),''),username)
                FROM users WHERE id=NEW.owner_id) WHERE id=NEW.id; END""",
        """CREATE TRIGGER IF NOT EXISTS user_profile_alias AFTER UPDATE OF username,display_name ON users
            WHEN NEW.role='user'
            BEGIN UPDATE accounts SET alias=COALESCE(NULLIF(trim(NEW.display_name),''),NEW.username)
                WHERE owner_id=NEW.id; END""",
        """CREATE TRIGGER IF NOT EXISTS fixed_admin_insert BEFORE INSERT ON users
            WHEN (NEW.role='admin' OR NEW.builtin=1 OR lower(NEW.username)='admin')
            AND NOT (NEW.role='admin' AND NEW.builtin=1 AND NEW.username COLLATE BINARY='admin')
            BEGIN SELECT RAISE(ABORT,'Only the built-in admin can be an Admin'); END""",
        """CREATE TRIGGER IF NOT EXISTS fixed_admin_update BEFORE UPDATE OF role,builtin,username ON users
            WHEN (NEW.role='admin' OR NEW.builtin=1 OR lower(NEW.username)='admin')
            AND NOT (NEW.role='admin' AND NEW.builtin=1 AND NEW.username COLLATE BINARY='admin')
            BEGIN SELECT RAISE(ABORT,'Only the built-in admin can be an Admin'); END""",
        """CREATE TRIGGER IF NOT EXISTS account_owner_required BEFORE INSERT ON accounts
            WHEN NEW.owner_id IS NULL
            BEGIN SELECT RAISE(ABORT,'Account owner is required'); END""",
        """CREATE TRIGGER IF NOT EXISTS account_owner_immutable BEFORE UPDATE OF owner_id ON accounts
            WHEN NEW.owner_id IS NOT OLD.owner_id
            BEGIN SELECT RAISE(ABORT,'Account ownership cannot change'); END""",
        """CREATE TRIGGER IF NOT EXISTS user_account_limit BEFORE INSERT ON accounts
            WHEN (SELECT role FROM users WHERE id=NEW.owner_id)='user'
            AND EXISTS(SELECT 1 FROM accounts WHERE owner_id=NEW.owner_id AND username!=NEW.username)
            BEGIN SELECT RAISE(ABORT,'Users may own only one Account'); END""",
        """CREATE TRIGGER IF NOT EXISTS user_role_limit BEFORE UPDATE OF role ON users
            WHEN NEW.role='user' AND (SELECT count(*) FROM accounts WHERE owner_id=NEW.id)>1
            BEGIN SELECT RAISE(ABORT,'An Admin with multiple Accounts cannot become a User'); END""",
        """CREATE TRIGGER IF NOT EXISTS protect_builtin_delete BEFORE DELETE ON users
            WHEN OLD.builtin=1 BEGIN SELECT RAISE(ABORT,'The built-in Admin cannot be deleted'); END""",
        """CREATE TRIGGER IF NOT EXISTS protect_builtin_role BEFORE UPDATE OF role,builtin ON users
            WHEN OLD.builtin=1 AND (NEW.role!='admin' OR NEW.builtin!=1)
            BEGIN SELECT RAISE(ABORT,'The built-in Admin must remain an Admin'); END""",
    ):
        db.execute(statement)


def public_user(db, ident):
    row = db.execute(f"SELECT {USER_FIELDS} FROM users WHERE id=?", (ident,)).fetchone()
    if not row:
        raise HTTPException(404, "User not found")
    return dict(row)


def current_user(request):
    token = request.cookies.get(COOKIE, "")
    with request.app.state.store.connect() as db:
        session = db.execute(
            "SELECT user_id FROM auth_sessions WHERE token_hash=? AND expires_at>?",
            (hashlib.sha256(token.encode()).hexdigest(), time.time()),
        ).fetchone()
        if not session:
            raise HTTPException(401, "Please log in")
        return public_user(db, session["user_id"])


async def authorize(request: Request):
    path = request.url.path
    if not path.startswith("/api/"):
        return
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if (
            request.headers.get("x-requested-with") != "GoodNight"
            or request.headers.get("sec-fetch-site") == "cross-site"
            or (origin and urlparse(origin).netloc != request.headers.get("host"))
        ):
            raise HTTPException(403, "Cross-origin requests are not allowed")
    if path in (
        "/api/health",
        "/api/auth/login",
        "/api/auth/register",
        "/api/auth/registration",
    ):
        return
    user = current_user(request)
    request.state.user = user
    if (
        path.startswith(("/api/users", "/api/invitations"))
        or path == "/api/config"
        or path == "/api/auth/settings"
    ):
        if user["role"] != "admin":
            raise HTTPException(403, "Admin access required")
    ident = request.path_params.get("ident")
    if path.startswith("/api/accounts/") and ident is not None:
        with request.app.state.store.connect() as db:
            account = db.execute(
                "SELECT owner_id FROM accounts WHERE id=?", (ident,)
            ).fetchone()
        if not account or (
            user["role"] != "admin" and account["owner_id"] != user["id"]
        ):
            raise HTTPException(404, "Account not found")
    if path.startswith("/api/logins/") and ident is not None:
        pending = request.app.state.pending_logins.get(ident)
        if pending and pending.user_id != user["id"]:
            raise HTTPException(404, "Login not found")


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: SecretStr = Field(min_length=1, max_length=128)


class Registration(Credentials):
    password: SecretStr = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=80)
    invitation: str = Field(default="", max_length=128)
    language: str = Field(default="en", max_length=64)

    @field_validator("language")
    @classmethod
    def browser_language(cls, value):
        return "zh" if value.lower().split("-")[0] == "zh" else "en"


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["en", "zh"] = "en"
    bark_enabled: bool = False
    bark_key: SecretStr = Field(default=SecretStr(""), max_length=256)
    bark_prompt_dismissed: Literal[True] = True

    @field_validator("bark_key")
    @classmethod
    def device_key(cls, value):
        key = value.get_secret_value().strip()
        if key and not all(c.isascii() and (c.isalnum() or c in "-_") for c in key):
            raise ValueError("Enter the Bark device key, not a URL")
        return SecretStr(key)


class NewUser(Credentials):
    password: SecretStr = Field(min_length=8, max_length=128)
    display_name: str = Field(default="", max_length=80)
    role: Literal["user"] = "user"


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.-]+$")
    display_name: str = Field(max_length=80)


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=8, max_length=128)
    current_password: SecretStr = Field(min_length=1, max_length=128)


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: SecretStr = Field(min_length=8, max_length=128)


class RegistrationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    registration_mode: Literal["disabled", "invitation", "open"]


def rate_limit(request, username):
    timestamp = time.time()
    ip = request.client.host if request.client else "local"
    # Persistent limits apply before password hashing, including unsuccessful registrations.
    with request.app.state.store.connect() as db:
        db.execute("DELETE FROM auth_attempts WHERE started_at<?", (timestamp - 900,))
        for key, limit in (("ip:" + ip, 50), ("user:" + username.lower(), 10)):
            row = db.execute(
                "SELECT attempts FROM auth_attempts WHERE key=?", (key,)
            ).fetchone()
            if row and row["attempts"] >= limit:
                raise HTTPException(429, "Too many attempts. Try again in 15 minutes.")
        for key in ("ip:" + ip, "user:" + username.lower()):
            db.execute(
                "INSERT INTO auth_attempts VALUES(?,?,1) ON CONFLICT(key) DO UPDATE SET attempts=attempts+1",
                (key, timestamp),
            )


def create_session(db, user_id, request, response):
    token = secrets.token_urlsafe(32)
    db.execute(
        "DELETE FROM auth_sessions WHERE expires_at<=? OR token_hash=?",
        (
            time.time(),
            hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest(),
        ),
    )
    db.execute(
        "INSERT INTO auth_sessions VALUES(?,?,?)",
        (
            hashlib.sha256(token.encode()).hexdigest(),
            user_id,
            time.time() + SESSION_TTL,
        ),
    )
    response.set_cookie(
        COOKIE,
        token,
        max_age=SESSION_TTL,
        httponly=True,
        samesite="strict",
        path="/api",
        secure=request.url.scheme == "https"
        or os.environ.get("AUTH_COOKIE_SECURE") == "1",
    )


@router.get("/auth/registration")
async def registration_mode(request: Request):
    with request.app.state.store.connect() as db:
        return dict(
            db.execute(
                "SELECT registration_mode FROM auth_settings WHERE id=1"
            ).fetchone()
        )


@router.post("/auth/login")
async def login(data: Credentials, request: Request, response: Response):
    rate_limit(request, data.username)
    store = request.app.state.store
    with store.connect() as db:
        user = db.execute(
            "SELECT * FROM users WHERE username=?", (data.username,)
        ).fetchone()
        # Equal hashing work for unknown names.
        dummy = db.execute(
            "SELECT password_hash FROM users WHERE builtin=1"
        ).fetchone()[0]
    valid = await run_in_threadpool(
        verify_password,
        data.password.get_secret_value(),
        user["password_hash"] if user else dummy,
    )
    if not user:
        raise HTTPException(
            401,
            {"code": "invalid_credentials", "message": "Invalid username or password"},
        )
    if not valid:
        raise HTTPException(
            401, {"code": "wrong_password", "message": "Wrong password"}
        )
    with store.connect() as db:
        fresh = db.execute(
            "SELECT password_hash FROM users WHERE id=?", (user["id"],)
        ).fetchone()
        if not fresh or fresh[0] != user["password_hash"]:
            raise HTTPException(401, "Please log in again")
        create_session(db, user["id"], request, response)
        return public_user(db, user["id"])


@router.post("/auth/register", status_code=201)
async def register(data: Registration, request: Request, response: Response):
    rate_limit(request, data.username)
    encoded = await run_in_threadpool(hash_password, data.password.get_secret_value())
    try:
        with request.app.state.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            mode = db.execute(
                "SELECT registration_mode FROM auth_settings WHERE id=1"
            ).fetchone()[0]
            if mode == "disabled":
                raise HTTPException(403, "Registration is disabled")
            if mode == "invitation":
                used = db.execute(
                    "UPDATE invitations SET used_at=? WHERE code=? AND used_at IS NULL",
                    (time.time(), data.invitation.strip()),
                )
                if used.rowcount != 1:
                    raise HTTPException(400, "Invalid or used invitation code")
            ident = db.execute(
                "INSERT INTO users(username,display_name,password_hash,role,language) VALUES(?,?,?,'user',?)",
                (data.username, data.display_name.strip(), encoded, data.language),
            ).lastrowid
            create_session(db, ident, request, response)
            return public_user(db, ident)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username is already in use") from None


@router.get("/auth/me")
async def me(request: Request):
    return request.state.user


@router.patch("/auth/preferences")
async def preferences(
    data: Preferences, request: Request, background_tasks: BackgroundTasks
):
    store, ident = request.app.state.store, request.state.user["id"]
    updates = data.model_dump(exclude_unset=True)
    if "bark_key" in updates:
        key = data.bark_key.get_secret_value()
        updates["bark_key"] = store.cipher.encrypt(key.encode()) if key else None
        if not key:
            updates["bark_enabled"] = False
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        was_enabled = db.execute(
            "SELECT bark_enabled FROM users WHERE id=?", (ident,)
        ).fetchone()[0]
        if updates.get("bark_enabled"):
            key = updates.get("bark_key") or db.execute(
                "SELECT bark_key FROM users WHERE id=?", (ident,)
            ).fetchone()[0]
            if not key:
                raise HTTPException(
                    400, "Configure a Bark key before enabling notifications"
                )
        if updates:
            columns = ",".join(f"{column}=?" for column in updates)
            db.execute(
                f"UPDATE users SET {columns} WHERE id=?", (*updates.values(), ident)
            )
        user = public_user(db, ident)
    if not was_enabled and user["bark_enabled"]:
        background_tasks.add_task(request.app.state.scheduler.bark.send_test, ident)
    return user


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    with request.app.state.store.connect() as db:
        db.execute(
            "DELETE FROM auth_sessions WHERE token_hash=?",
            (hashlib.sha256(request.cookies.get(COOKIE, "").encode()).hexdigest(),),
        )
    response.delete_cookie(COOKIE, path="/api")
    return {"ok": True}


def update_profile(store, ident, data):
    try:
        with store.connect() as db:
            user = public_user(db, ident)
            if user["builtin"] and data.username != "admin":
                raise HTTPException(403, "The Admin username must remain 'admin'")
            db.execute(
                "UPDATE users SET username=?,display_name=? WHERE id=?",
                (data.username, data.display_name.strip(), ident),
            )
            return public_user(db, ident)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username is already in use") from None


@router.patch("/auth/me")
async def profile(data: Profile, request: Request):
    return update_profile(request.app.state.store, request.state.user["id"], data)


@router.put("/auth/password")
async def change_password(data: PasswordChange, request: Request, response: Response):
    store, ident = request.app.state.store, request.state.user["id"]
    with store.connect() as db:
        old = db.execute(
            "SELECT password_hash FROM users WHERE id=?", (ident,)
        ).fetchone()[0]
    if not await run_in_threadpool(
        verify_password, data.current_password.get_secret_value(), old
    ):
        raise HTTPException(400, "Current password is incorrect")
    if data.password.get_secret_value() == data.current_password.get_secret_value():
        raise HTTPException(400, "Choose a different password")
    encoded = await run_in_threadpool(hash_password, data.password.get_secret_value())
    with store.connect() as db:
        updated = db.execute(
            "UPDATE users SET password_hash=?,must_change_password=0 WHERE id=? AND password_hash=?",
            (encoded, ident, old),
        )
        if updated.rowcount != 1:
            raise HTTPException(409, "Password changed. Please log in again")
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (ident,))
        create_session(db, ident, request, response)
        return public_user(db, ident)


@router.put("/auth/settings")
async def settings(data: RegistrationSettings, request: Request):
    with request.app.state.store.connect() as db:
        db.execute(
            "UPDATE auth_settings SET registration_mode=? WHERE id=1",
            (data.registration_mode,),
        )
    return data


@router.get("/invitations")
async def invitations(request: Request):
    with request.app.state.store.connect() as db:
        return [
            dict(row)
            for row in db.execute("SELECT * FROM invitations ORDER BY id DESC")
        ]


@router.post("/invitations", status_code=201)
async def new_invitation(request: Request):
    with request.app.state.store.connect() as db:
        code = secrets.token_urlsafe(24)
        db.execute(
            "INSERT INTO invitations(code,created_at) VALUES(?,?)", (code, time.time())
        )
    return {"code": code}


@router.delete("/invitations/{ident}")
async def delete_invitation(ident: int, request: Request):
    with request.app.state.store.connect() as db:
        db.execute("DELETE FROM invitations WHERE id=?", (ident,))
    return {"ok": True}


@router.get("/users")
async def users(request: Request, empty: bool = False):
    with request.app.state.store.connect() as db:
        return [
            dict(row)
            for row in db.execute(
                f"SELECT {USER_FIELDS},(SELECT count(*) FROM accounts WHERE owner_id=users.id) AS account_count FROM users "
                + (
                    "WHERE NOT EXISTS(SELECT 1 FROM accounts WHERE owner_id=users.id) "
                    if empty
                    else ""
                )
                + "ORDER BY id"
            )
        ]


@router.post("/users", status_code=201)
async def new_user(data: NewUser, request: Request):
    encoded = await run_in_threadpool(hash_password, data.password.get_secret_value())
    if current_user(request)["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    try:
        with request.app.state.store.connect() as db:
            ident = db.execute(
                "INSERT INTO users(username,display_name,password_hash,role) VALUES(?,?,?,?)",
                (data.username, data.display_name.strip(), encoded, data.role),
            ).lastrowid
            return public_user(db, ident)
    except sqlite3.IntegrityError:
        raise HTTPException(409, "Username is already in use") from None


@router.get("/users/{ident}")
async def user_info(ident: int, request: Request):
    with request.app.state.store.connect() as db:
        user = public_user(db, ident)
        user["account_count"] = db.execute(
            "SELECT count(*) FROM accounts WHERE owner_id=?", (ident,)
        ).fetchone()[0]
        return user


@router.patch("/users/{ident}")
async def edit_user(ident: int, data: Profile, request: Request):
    return update_profile(request.app.state.store, ident, data)


@router.put("/users/{ident}/password")
async def reset_password(ident: int, data: PasswordReset, request: Request):
    encoded = await run_in_threadpool(hash_password, data.password.get_secret_value())
    if current_user(request)["role"] != "admin":
        raise HTTPException(403, "Admin access required")
    with request.app.state.store.connect() as db:
        public_user(db, ident)
        if ident == request.state.user["id"]:
            raise HTTPException(403, "Use your personal password settings")
        db.execute(
            "UPDATE users SET password_hash=?,must_change_password=1 WHERE id=?",
            (encoded, ident),
        )
        db.execute("DELETE FROM auth_sessions WHERE user_id=?", (ident,))
    return {"ok": True}


def delete_records(request, *, account_id=None, user_id=None, delete_user=True):
    state, store = request.app.state, request.app.state.store
    with store.connect() as db:
        db.execute("BEGIN IMMEDIATE")
        if account_id is not None:
            account = db.execute(
                "SELECT * FROM accounts WHERE id=?", (account_id,)
            ).fetchone()
            if not account:
                raise HTTPException(404, "Account not found")
            owner = public_user(db, account["owner_id"])
            if (
                request.state.user["role"] != "admin"
                and owner["id"] != request.state.user["id"]
            ):
                raise HTTPException(404, "Account not found")
            user_id = owner["id"] if delete_user and owner["role"] == "user" else None
        if user_id is not None:
            owner = public_user(db, user_id)
            if owner["builtin"]:
                raise HTTPException(403, "The built-in Admin cannot be deleted")
            accounts = db.execute(
                "SELECT * FROM accounts WHERE owner_id=?", (user_id,)
            ).fetchall()
        else:
            accounts = [account]
        ids = {a["id"] for a in accounts}
        if ids & state.scheduler.busy or any(
            p.account_id in ids or (user_id is not None and p.user_id == user_id)
            for p in state.pending_logins.values()
        ):
            raise HTTPException(
                409, "An account operation is running. Try again when it finishes"
            )
        for account in accounts:
            db.execute(
                "INSERT INTO credential_cleanup VALUES(?,?)",
                (account["username"], account["wechat_ref"]),
            )
        if user_id is not None:
            db.execute("DELETE FROM users WHERE id=?", (user_id,))
        else:
            db.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    return {"ok": True, "user_deleted": user_id == request.state.user["id"]}


@router.delete("/users/{ident}")
async def delete_user(ident: int, request: Request):
    return delete_records(request, user_id=ident)


@router.delete("/auth/me")
async def delete_me(request: Request, response: Response):
    result = delete_records(request, user_id=request.state.user["id"])
    response.delete_cookie(COOKIE, path="/api")
    return result


async def cleanup_credentials(app):
    store = app.state.store
    with store.connect() as db:
        records = db.execute("SELECT * FROM credential_cleanup").fetchall()
    for record in records:
        try:
            store.login.delete(record["username"])
            with store.connect() as db:
                shared = db.execute(
                    "SELECT 1 FROM accounts WHERE wechat_ref=?", (record["wechat_ref"],)
                ).fetchone()
            if record["wechat_ref"] and not shared:
                try:
                    await app.state.wechat.info(record["wechat_ref"])
                except WeChatError as error:
                    if str(error) != "wechat_expired":
                        raise
                else:
                    await app.state.wechat.delete(record["wechat_ref"])
            with store.connect() as db:
                db.execute(
                    "DELETE FROM credential_cleanup WHERE username=?",
                    (record["username"],),
                )
        except Exception:
            logging.getLogger("goodnight").warning(
                "Deleted-account credential cleanup will be retried"
            )
