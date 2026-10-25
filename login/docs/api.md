# uestc-login API

`uestc-login` is an independent Python package managed by `login/pyproject.toml`
and `login/uv.lock`. It does not start an HTTP server. The application HTTP API is
documented in [docs/api.md](../../docs/api.md).

## Final IDAS → jzsz exchange

After the password POST, the client first follows the returned redirect chain
(including intermediate login pages and SMS reauthentication when required).
A redirect to `/authserver/index.do` marks password success: the client starts the
jzsz service exchange immediately instead of following the landing page into the
unrelated campus portal.
Password success and successful SMS reauthentication both end with this request:

```http
GET /authserver/login?service=https%3A%2F%2Fjzsz.uestc.edu.cn%2F HTTP/1.1
Host: idas.uestc.edu.cn
Cache-Control: no-cache
Cookie: <the current IDAS cookie jar>
```

The expected response from the supplied capture is **302 Found**, with a fresh,
service-specific ticket in `Location`:

```http
HTTP/1.1 302 Found
Location: https://jzsz.uestc.edu.cn/?ticket=ST-example-only
```

The client follows that exact URL with the same HTTP session:

```http
GET /?ticket=ST-example-only HTTP/1.1
Host: jzsz.uestc.edu.cn
```

The service consumes the ticket and typically responds:

```http
HTTP/1.1 302 Found
Set-Cookie: SESSION=<new-session>; Path=/; HttpOnly
Location: https://jzsz.uestc.edu.cn/
```

After following the final redirect, the package requires a nonempty jzsz `SESSION`
and verifies it through GET `/platform-app/api/h5/user/base-info`, using
`platform: mp-weixin`. An IDAS success page alone is insufficient.

`304 Not Modified` concerns cache validation and is not accepted as an
authentication redirect. Redirects are bounded to ten
responses and restricted to the expected HTTPS hosts. A return to IDAS login or
reauthentication requests user action. Tickets are freshly issued, never copied
from captures or reused. Cookies retain their server-provided domains and paths,
including the distinct `/authserver` and `/authserver/` CASTGC cookies.

## Login endpoints used internally

All paths below are relative to `https://idas.uestc.edu.cn/authserver`.

| Method | Path | Request / result |
| --- | --- | --- |
| GET | `/login` | Load current form, `execution`, encryption key and cookies |
| GET | `/bfp/info?bfp=...&_=...` | Register persistent 32-character browser ID; `_` is Unix milliseconds |
| GET | `/checkNeedCaptcha.htl?username=...&_=...` | Optional, only when `check_captcha=True`; omitted by default |
| POST | `/login` | Submit Python-encrypted `password`, username and current hidden fields as form data |
| POST | `/dynamicCode/getDynamicCodeByReauth.do` | Form `userName=<username>&authCodeTypeName=reAuthDynamicCodeType`; require `res: "success"` |
| POST | `/reAuthCheck/reAuthSubmit.do` | Form described below; require `code: "reAuth_success"` |
| GET | `/login?service=https%3A%2F%2Fjzsz.uestc.edu.cn%2F` | Final service-specific CAS exchange described above |

SMS verification form fields are `service=<service query from the reauthentication URL, or "">`, `reAuthType="3"`,
`isMultifactor="true"`, `password=""`, `dynamicCode=<user-code>`, `uuid=""`,
`answer1=""`, `answer2=""`, `otpCode=""`, and `skipTmpReAuth="true"`.
The dynamic-code requests use `X-Requested-With: XMLHttpRequest` and the
reauthentication page as `Referer`. The existing cookie jar remains active.

Password submission parses the current `pwdFromId` form, preserves its hidden
fields, and encrypts the password in Python using the fresh `pwdEncryptSalt`.
The persistent fingerprint is registered through `/bfp/info`. No browser process
or page JavaScript runs. See
[password encryption](password-encryption.md) for the verified transform.

The app and manual script share the Safari User-Agent from the supplied capture.
Both submit `rememberMe=true`, use fresh cookies for a password login, register
the saved browser ID, and omit the optional CAPTCHA preflight by default. A
regression test compares their outgoing requests for SMS and non-SMS flows.
`rememberMe` does not override the package's fixed seven-day local lease.

## Public Python interface

```python
from uestc_login import (
    HttpSessions, LoginManager, Reauth, submit_sms,
    LoginError, PasswordRequired, AdditionalVerification, InvalidCode,
)
from uestc_login.skill.jzsz import session
from uestc_login.crypto import encrypt_password
```

`sessions` is an `HttpSessions()` factory backed by `httpx.AsyncClient`. Returned
`state` contains serialized cookies and an empty `origins` list. Existing saved
cookie records remain readable; treat this state as a secret.

| Call | Result / behavior |
| --- | --- |
| `LoginManager(directory)` | Open/create an encrypted local credential store |
| `await manager.login(sessions, username, password, *, challenge=None, interactive=True, check_captcha=False)` | Submit credentials; return verified jzsz state or an open `Reauth` |
| `await submit_sms(reauth, code)` | Verify SMS, perform the final CAS service exchange, return verified state |
| `manager.save(username, state, password=None, save_password=False)` | Encrypt and persist state; start a fixed seven-day lease; save password only when opted in |
| `await manager.session(sessions, username, cached=None)` | Validate cached state, exchange CAS if needed, or renew using an opted-in password |
| `manager.metadata(username)` | `{"uestc_expires_at": <Unix-seconds-or-null>, "save_password": <bool>}` |
| `manager.forget_password(username)` | Remove stored password without extending the lease |
| `manager.delete(username)` | Delete the account's local login record |
| `await session(manager, sessions, username)` | Return only the raw jzsz `SESSION` string |
| `encrypt_password(password, salt)` | Return raw Base64 ciphertext; caller must form-encode it |

The package also exports the lower-level
`await sign_in(sessions, username, password, *, fingerprint, state=None, challenge=None, interactive=True, check_captcha=False)`.
`LoginManager.login` supplies the saved fingerprint with a fresh cookie jar, as
the manual script does. Old browser-trust cookies are not restored for password
submission. `manager.session` still reuses saved service sessions before renewing.
The fingerprint is persisted before the first request so failed/cancelled attempts
reuse it too; authenticated session persistence is explicit via `manager.save`.

With `check_captcha=True`, `challenge` is an optional async callback receiving the HTTP session. It must wait
for a person to finish a school-requested CAPTCHA; without it, a required CAPTCHA raises
`AdditionalVerification`. `interactive=False` never sends a background SMS code
and raises `AdditionalVerification` when reauthentication is required.

### Example lifecycle

```python
sessions = HttpSessions()
manager = LoginManager("./private-login-data")
result = await manager.login(sessions, username, password, challenge=relay_captcha)
if isinstance(result, Reauth):
    try:
        # Obtain the code interactively; do not persist it.
        result_state = await submit_sms(result, sms_code)
    finally:
        await result.context.close()
else:
    result_state = result

manager.save(username, result_state, password, save_password=False)
jzsz_session = await session(manager, sessions, username)
```

`Reauth` has `context`, `username` and the actual reauthentication page `url`.
The URL supplies the SMS Referer and optional service parameter.
The caller owns and must close its HTTP
session on success, cancellation, expiry and unrecoverable failure. On `InvalidCode`
it may retain that context for a bounded retry. The Goodnight HTTP API imposes a
five-minute total login deadline and five invalid SMS attempts.

`manager.session` checks the fixed local lease before using a saved jzsz cookie.
Within that lease, it validates the last session first; if expired upstream, it
requests the final CAS service URL again. This does not extend the local deadline.
After expiry, a saved password permits a new login; otherwise `PasswordRequired`
is raised. Server expiry may be earlier. MFA/CAPTCHA still require a person even
when the password is saved.

## Exceptions

| Exception | `code` | Meaning |
| --- | --- | --- |
| `LoginError` | `login_failed` | Malformed handoff or missing service cookie |
| `uestc_login.client.LoginRejected` | `login_rejected` | School returned a password form after submission |
| `uestc_login.client.SessionEstablishmentError` | `school_session_failed` | Fresh password was submitted, but CAS session exchange remained unauthenticated |
| `PasswordRequired` | `password_required` | Lease expired or redirected to credential login |
| `AdditionalVerification` | `sms_required` | SMS, CAPTCHA or another interactive step required |
| `InvalidCode` | `invalid_code` | SMS rejected; caller may retry within its limits |
| `uestc_login.client.ServiceUnavailable` | `login_unavailable` | Upstream response invalid/unavailable or redirect limit exceeded |

Transport errors and overall timeouts may also propagate from httpx/asyncio;
applications should report a retryable failure. The standalone package does not impose per-user
concurrency locks; the Goodnight application does.

Stored account records are encrypted using a private local key. Local possession of
both key and encrypted files permits decryption. Neither a stored state nor a raw
`SESSION` should be included in an API response or repository. Raw diagnostic
logs described below contain these secrets and must be kept private.

The application logs login stages and the failure's exception type, code and reason.
Set `UESTC_HTTP_TRACE=1` to additionally log every school HTTP request and response:
full URLs, repeated headers, form/JSON bodies, response bodies, scoped cookie state,
elapsed time, and transport exceptions with stack traces. Each pair has an ID
such as `SCHOOL HTTP [abc123/1]`. Response bodies are decompressed by HTTPX;
binary image bodies are Base64. Bodies are not truncated. Plaintext school
passwords are not transmitted, but encrypted passwords, SMS codes, cookies,
tickets and school profile data appear in the trace.

Compose enables this tracing by default for login diagnosis. Disable it with
`UESTC_HTTP_TRACE=0 docker compose up -d`. Standalone package use leaves it off
unless explicitly enabled. The HTTP trace emits at INFO independently of the
application's configured log level. View container output with
`docker compose logs -f --tail=200 goodnight`.
