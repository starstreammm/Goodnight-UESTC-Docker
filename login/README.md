# uestc-login

Independent Python package and uv environment for UESTC IDAS login.

```sh
cd login
uv sync --frozen
uv run pytest
```

Complete reference: [Python API and final CAS service exchange](docs/api.md).

Public API:

```python
from uestc_login import HttpSessions, LoginManager, Reauth, submit_sms
from uestc_login.skill.jzsz import session

sessions = HttpSessions()
manager = LoginManager('/path/to/private/login-data')
result = await manager.login(sessions, username, password)
if isinstance(result, Reauth):
    try:
        # Get the SMS code from the user, never store it.
        result_state = await submit_sms(result, sms_code)
    finally:
        await result.context.close()
else:
    result_state = result
manager.save(username, result_state, password, save_password=False)
# Validate the saved session, exchange CAS again if necessary, or renew using
# an explicitly saved password. Raises PasswordRequired/AdditionalVerification
# when a person must sign in again. Does not send background SMS.
session_string = await session(manager, sessions, username)
```

The default flow matches the manual script: Safari User-Agent, fresh login cookies,
a persistent per-account fingerprint, `rememberMe=true`, and no CAPTCHA preflight.
Integrations can opt into the CAPTCHA check with `check_captcha=True` and handle
the challenge through the optional `challenge` callback.
A `Reauth` owns an open HTTP session: close it after success, failure, timeout,
or cancellation. The caller enforces a short expiry and an SMS attempt limit;
Goodnight uses five minutes and five attempts.

Cookie state and opt-in passwords are encrypted at rest. The key and data files
are mode 0600 in a mode 0700 directory. Keep the key and data together when backing
up; possession of both permits decryption. The seven-day lease starts when a login
is saved and does not slide during validation or CAS service renewal. Upstream
revocation can shorten it. A saved password permits a new login after expiry;
MFA and CAPTCHA still require user interaction.

`uestc_login/skill/` contains service adapters. The jzsz adapter returns only the
raw `SESSION` string. New adapters should request a service-specific CAS ticket,
validate the service session, and avoid logging credentials or tickets.

See [password-encryption.md](docs/password-encryption.md) for the verified
password transform and `uestc_login.crypto.encrypt_password` compatibility helper.

## Manual HTTP login test

From the repository root:

```sh
uv run --project login python login/manual_login.py
```

Enter the username, then press Enter before each outgoing request. The password
and SMS code use hidden terminal prompts. Enter `q` at a request prompt to stop.
The script prints complete request/response headers and bodies, preserves repeated
`Set-Cookie` headers, and lists the cookie jar with domains and paths after every
response. HTTPX decompresses response bodies; this is an HTTP trace, not a packet capture.

The sequence is: login form → fingerprint → encrypted password → optional SMS →
explicit jzsz CAS service request → ticket redemption → `SESSION` → profile check.
An `index.do` redirect defaults to starting the service exchange; enter `f` if you
want to inspect the landing-page redirects instead. The final menu offers separate
read-only web-profile, check-in-authentication and today's-record probes. Each
probe starts with the original CAS cookies so one probe cannot contaminate another.
It never submits a check-in or starts WeChat login.

Optional arguments:

```sh
uv run --project login python login/manual_login.py --output /tmp/uestc-login-trace.log
uv run --project login python login/manual_login.py --username YOUR_ID --fingerprint YOUR_32_HEX_FINGERPRINT
```

The first run generates a browser fingerprint and saves it to
`login/data/manual-browser-fingerprint` (mode 0600, ignored by Git). Every later run
reuses that exact ID, regardless of your working directory. `--fingerprint` replaces
the saved ID for this and future runs; `--fingerprint-file PATH` selects a separate
browser identity file. Only the fingerprint ID is persisted by this script; each
run still starts with a fresh session cookie jar.

`--check-captcha` adds the CAPTCHA-requirement check; it is omitted by default to
match the supplied request sequence. If a CAPTCHA is required, this script stops
instead of solving it. `--user-agent` lets you compare clients; the default matches
the supplied Safari capture. The trace contains live cookies/tickets and submitted
SMS codes. Keep it private. Output files are created with mode 0600 and never
overwritten. No password or session is saved to the application's account store.
