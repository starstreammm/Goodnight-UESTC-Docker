# GoodNight HTTP API

Base URL: `http://localhost:8000/api` with the default Compose configuration.
Send JSON bodies with `Content-Type: application/json`. Successful responses are
JSON objects without an additional envelope. Responses use `Cache-Control: no-store`.

The console uses persistent cookie authentication. Log in through `POST /auth/login`
and send the returned `goodnight_session` cookie on protected requests. Every
state-changing request also requires `X-Requested-With: GoodNight`. Cross-site
requests and an `Origin` host/port differing from `Host` are rejected with HTTP 403.
Only health, login, registration, and the registration-mode query are public.
Users see only their own Account, jobs, and busy status; Admins see all Accounts
and the global `config` field.
`PUT /config` and all User/invitation management endpoints require an Admin.
Pending school/WeChat login IDs are accessible only to the console User who started them.

The private YYB control credentials, school cookies, password hashes, passwords and
check-in tickets are never returned. IDs shown below are synthetic examples.
See [Authentication and deployment](authentication.md) for setup, migration, and
session/ownership behavior.

## Console authentication and User management

All console usernames use 1–64 ASCII letters, digits, underscores, dots or hyphens,
with case-insensitive uniqueness. The sole Admin's username is fixed as `admin`.
Every other identity has the `user` role. Passwords use 8–128 characters. `display_name`
is optional at creation and accepts up to 80 characters. Unknown body fields are
rejected, including ownership fields and public registration roles.

| Method | Path | Request / result |
| --- | --- | --- |
| GET | `/auth/registration` | Public `{registration_mode: "disabled" / "invitation" / "open"}` |
| POST | `/auth/login` | `{username,password}`; returns User and sets session cookie; an incorrect password for an existing User returns `401` with `code: "wrong_password"` and `message: "Wrong password"` |
| POST | `/auth/register` | `{username,password,display_name?,invitation?}`; creates a regular User with no Account and sets session cookie |
| GET | `/auth/me` | Current User, including `must_change_password` |
| PATCH | `/auth/me` | `{username,display_name}`; updates personal profile; the Admin username must remain `admin` |
| DELETE | `/auth/me` | Deletes the current User, sessions, all owned Accounts and jobs, and clears the login cookie; built-in Admin is protected |
| PUT | `/auth/password` | `{current_password,password}`; changes password, revokes sessions, creates replacement session |
| POST | `/auth/logout` | Revokes current session and clears its cookie |
| PUT | `/auth/settings` | Admin: `{registration_mode}`; takes effect immediately |
| GET | `/invitations` | Admin: codes, creation timestamps and `used_at` |
| POST | `/invitations` | Admin: generates a single-use code |
| DELETE | `/invitations/{id}` | Admin: deletes a code; registered Users remain |
| GET | `/users` | Admin: Users and Account counts; `?empty=true` returns Users without Accounts |
| GET | `/users/{id}` | Admin: User info and Account count |
| POST | `/users` | Admin: `{username,password,display_name?,role?}`; the only accepted role is `user`, no Account created |
| PATCH | `/users/{id}` | Admin: `{username,display_name}` |
| PUT | `/users/{id}/password` | Admin: `{password}`; revokes target sessions and prompts a password change; use `/auth/password` for yourself |
| DELETE | `/users/{id}` | Admin: atomically deletes User, sessions, all owned Accounts and jobs; built-in Admin is protected |

Authentication failures return 401, permission failures 403, unavailable Accounts
404, ownership/operation conflicts 409, invalid input 422, and excessive login or
registration attempts 429. Invitation errors return 400 and closed registration
returns 403. Login and registration share persistent 15-minute attempt limits:
10 per username and 50 per client IP.

## Endpoints

| Method | Path | Request body | Successful result |
| --- | --- | --- | --- |
| GET | `/health` | — | `200 {"status":"ok"}` |
| GET | `/state` | — | `200`, dashboard state described below |
| POST | `/accounts` | `Login` | `201`, pending CAPTCHA, SMS or WeChat step; account is not saved yet |
| POST | `/logins/{login_id}/captcha` | `CaptchaGesture` | `200`, next login step or updated CAPTCHA |
| POST | `/logins/{login_id}/captcha/refresh` | — | `200`, updated CAPTCHA step |
| POST | `/logins/{login_id}/code` | `{"code":"123456"}` | `200`, next login step |
| GET | `/logins/{login_id}/wechat` | — | `200`, scan status or account review; does not save the account |
| POST | `/logins/{login_id}/confirm` | `{"key":null}` or `{"key":"<location-key>"}` | `200 {"state":"done","ok":true}`; confirm and save the reviewed account |
| DELETE | `/logins/{login_id}` | — | `200 {"ok":true}`; cancels and releases pending resources |
| GET | `/accounts/{id}/info` | — | `200`, profile, school lease and WeChat metadata |
| PATCH | `/accounts/{id}` | `{"checkin_time":"21:00_23:00"}` and/or `{"alias":"My account"}` | `200 {"ok":true}`; alias editing is allowed only for Admin-owned Accounts |
| DELETE | `/accounts/{id}/password` | — | `200 {"ok":true}`; forget saved school password |
| DELETE | `/accounts/{id}` | — | `200 {"ok":true,"user_deleted":false}`; defaults to also deleting a regular owner; use `?delete_user=false` to retain them. Admin owners are always retained. `user_deleted` reports whether the caller was deleted. |
| GET | `/accounts/{id}/locations` | — | `200`, currently available location choices |
| PUT | `/accounts/{id}/location` | `{"key":"<location-key>"}` or `{"key":null}` | `200`, location choices and updated selection |
| POST | `/accounts/{id}/check-in` | — | `202 {"status":"running","date":"2026-10-25"}` |
| PUT | `/config` | `Config` | `200`, saved configuration |

The state response includes `accounts[].real_name` from the school profile,
separate from the Account alias. Regular User aliases always follow their console
display name, falling back to their console username. Profile edits update those
aliases atomically; independent alias changes are rejected.

`jobs[].checked_at` is the school's `checkinTime` for a confirmed `CHECKED_IN`
record with the matching `businessDate`, normalized to an ISO timestamp in
Asia/Shanghai. Both check-in execution and background record refreshes preserve
it. Confirmed records show this time instead of `scheduled_at`; when the school
provides no timestamp, the UI says so rather than displaying the scheduled time.
Current-day confirmed jobs acquire the timestamp on their next school record
refresh. Older jobs without a stored school timestamp remain unknown.

## Connect or reconnect an account

POST `/accounts`:

```json
{
  "username": "example-student",
  "password": "<school-password>",
  "alias": "",
  "save_password": false,
  "new_browser_fingerprint": false,
  "login_target": "both"
}
```

`username` is required, 1–100 characters without whitespace. `alias` is optional,
up to 80 characters. For Admin-owned Accounts it defaults to the school's real
name (school username if unavailable). User-owned Accounts always use the owner's
display name or console username, regardless of the supplied alias.
`password` is 1–512 characters; omit it or use `null` only when a
password was previously saved. The school's own form may impose tighter limits.
`save_password` defaults to `false`; this value applies when login completes.
Unrecognized fields are rejected. Reusing a username reconnects the existing
account and preserves its ID, owner and submission journal. Reconnection requires
Account access. A newly created Account belongs to the current console User;
regular Users may own at most one. Manual assignment and ownership transfer are
not supported.

`login_target` is `both` by default for account creation. Existing accounts can use
`school` to force a school password login and proceed directly to account review,
preserving the WeChat binding. `wechat` starts a QR flow without a school password
or any school requests. Once authorized, polling returns `state: "wechat_confirm"`;
POST `/logins/{login_id}/confirm` with `{}` to replace only the WeChat binding.
Both single-service modes require an existing account and preserve the other
service's credentials. Cancellation does not commit the replacement credentials.

`new_browser_fingerprint` defaults to `false`. Set it to `true` to generate a new
browser fingerprint and start password authentication with an empty cookie jar,
bypassing saved portal and CAS sessions. Continue through SMS when required and
account review (also WeChat when `login_target` is `both`). The UI uses `school`
for this action. The fingerprint is staged with the pending login and
saved with the new session only on final confirmation. Cancelling or failing the
flow leaves the previously saved fingerprint and credentials unchanged.

For a username with no confirmed account, every POST `/accounts` automatically
stages a fresh fingerprint, even when `new_browser_fingerprint` is false. This
also applies after a failed initial login; a leftover fingerprint-only record is
not reused. The new fingerprint is persisted only on final confirmation. Normal
sign-in for a confirmed account retains its fingerprint unless a reset is requested.

A pending login lasts at most five minutes across all steps. At most two logins
may run concurrently; a username cannot have two active login attempts. Existing
accounts are reserved against concurrent check-in, editing and deletion.

### CAPTCHA step

The default login follows the manual HTTP sequence and omits the optional
CAPTCHA-requirement request. These challenge endpoints remain available for
integrations that explicitly enable `check_captcha=True` in the login package.

```json
{
  "state": "captcha",
  "login_id": "<opaque-login-id>",
  "expires_in": 285,
  "challenge": {
    "ticket": "<challenge-id>",
    "image": "data:image/png;base64,...",
    "width": 320,
    "height": 280,
    "handle": {"x": 0.05, "y": 0.7, "width": 0.12, "height": 0.14},
    "piece": null
  },
  "message": "Drag the slider to complete the school CAPTCHA."
}
```

`piece`, when present, contains `image`, `x`, `y`, `width`, and `height`. Coordinates
and dimensions in `handle`/`piece` are normalized to the challenge panel.
`image_height` and `image_width` specify the background dimensions as fractions of that panel; the
remaining area holds the slider track. Images come directly from IDAS over HTTP.
Relay the user's gesture to POST `/logins/{login_id}/captcha`:

```json
{
  "ticket": "<challenge-id>",
  "points": [
    {"x": 0.1, "y": 0.75, "t": 0},
    {"x": 0.3, "y": 0.75, "t": 150},
    {"x": 0.5, "y": 0.75, "t": 400}
  ]
}
```

There must be 2–300 points. Coordinates are finite numbers in `[0,1]`; `t` is an
integer number of milliseconds, starts at 0, increases monotonically and ends
between 50 and 15000. The first point must be inside the handle. The HTTP adapter translates actual
user positions and elapsed times to the school widget track format, then encrypts
the verification payload with the per-challenge key. The school decides
whether the gesture succeeds. A rejection returns an updated CAPTCHA; always use
its new ticket. Refresh also invalidates the previous challenge ticket.

### SMS reauthentication step

```json
{
  "state": "sms",
  "login_id": "<opaque-login-id>",
  "expires_in": 270,
  "challenge": null,
  "message": "SMS code sent. Enter the code from the school."
}
```

The password login has already reached the school's reauthentication page and
requested a code. Submit 4–10 numeric characters to POST
`/logins/{login_id}/code`. Up to five invalid verification attempts are allowed.
Incorrect codes return `detail.code = "invalid_code"`; the pending context stays
available until the attempt limit or deadline. There is no SMS-only login endpoint.

### WeChat step

```json
{
  "state": "wechat",
  "login_id": "<opaque-login-id>",
  "expires_in": 240,
  "image": "data:image/jpeg;base64,..."
}
```

Show the QR image and poll GET `/logins/{login_id}/wechat`, about every two seconds.
While waiting, it returns `{"state":"wechat","status":"pending"}` or another
upstream scan status such as `scanned`. Once authorized, it fetches the school
profile, effective schedule and valid locations, then returns the review below.
Stop polling when `state` is `review`. Expired/cancelled scans return HTTP 410.
Do not issue overlapping polls; operations on a busy login return HTTP 409.

### Final account review

```json
{
  "state": "review",
  "login_id": "<opaque-login-id>",
  "expires_in": 180,
  "review": {
    "username": "example-student",
    "alias": "Example",
    "save_password": false,
    "detail": {"realName":"Example"},
    "schedule": {
      "date": "2026-10-25",
      "response": {"code":0,"data":{"studentCheckinStartOffsetMinute":1260,"studentCheckinEndOffsetMinute":1410}}
    },
    "locations": [{"key":"<location-key>","name":"Campus","latitude":30.7,"longitude":104.0,"radiusMeter":100}],
    "location_key": "<location-key>",
    "location_changed": false
  }
}
```

`detail` comes from `/platform-app/api/h5/user/base-info`. Schedule offsets are
minutes after midnight in Asia/Shanghai. A successful school response with null
schedule data is displayed as no effective schedule. `location_key` preserves an
existing account's selection if still available; otherwise it contains the first valid
school location's key. `location_changed` warns that the prior selection
is no longer available. The user can select a key from `locations`.

POST `/logins/{login_id}/confirm` with `{"key":"<location-key>"}` for a listed location.
For compatibility, a null key resolves to the first location and saves its concrete
key; it does not create an automatic-selection setting. This action confirms the
private WeChat binding and saves the account, optional password, profile,
schedule, selected location and seven-day school lease. It returns
`{"state":"done","ok":true}`. Refresh `/state` for the account ID.
Before this action, no new account is scheduled and an existing account remains
unchanged and reserved. The five-minute deadline includes review; it does not reset.
`wechat_pending` (409) means credentials are not ready; retry confirmation shortly.
`review_unavailable` (502) means schedule/location loading failed; retry the poll.

Cancel a pending login with DELETE `/logins/{login_id}`. Cancellation is idempotent
for an ID that is already gone; a currently running step may return HTTP 409.
Cancelling or expiring a review discards it without saving the account.

## Dashboard and account information

GET `/state` returns:

```json
{
  "accounts": [{
    "id": 1,
    "username": "example-student",
    "alias": "Example",
    "status": "ready",
    "location_key": "<location-key>",
    "location_name": "School location",
    "wechat_ref": "1",
    "uestc_expires_at": 1793500000,
    "save_password": false
  }],
  "jobs": [],
  "busy_accounts": [],
  "config": {"checkin_time":"21:00_23:30","log":"info"},
  "timezone": "Asia/Shanghai",
  "date": "2026-10-25"
}
```

`wechat_ref` is an internal reference for display/state only; clients cannot use
it to select arbitrary YYB accounts. `uestc_expires_at` is Unix **seconds**, or
`null` for an account without a login lease. Validation never extends that lease.
`save_password` is a boolean, never the password. `busy_accounts` lists reserved IDs.

Each daily job includes `account_id`, `date`, `due`, `cutoff`, `scheduled_at`,
`checked`, `status`, `submitted`, `attempts`, `message`, and `submission_diagnostic`.
Date-time strings include the Shanghai UTC offset. `checked`/`submitted` are 0/1.
`submission_diagnostic` is a JSON-encoded string or `null` with protocol metadata
only. Typical statuses include `scheduled`, `running`, `retry`, `success`,
`already_done`, `need_login`, `wechat_expired`, `missed` and `unconfirmed`.
Other failure statuses reflect the school/transport error and should be displayed
as requiring attention. An accepted run is not proof that check-in succeeded.

GET `/accounts/{id}/info` returns:

```json
{
  "uestc_expires_at": 1793500000,
  "save_password": false,
  "detail": {"realName":"Example"},
  "schedule": {},
  "location_name": "Campus",
  "wechat": {
    "id": 1,
    "nickname": "Example",
    "status": "alive",
    "credential_expires_at": 1793000000,
    "credential_observed_at": 1792900000,
    "rescan_recommended": false
  },
  "wechat_error": null
}
```

`detail` contains the cached school profile; its fields are school-defined.
`schedule` is either `{}` or `{"date":"YYYY-MM-DD","response":<school-envelope>}`.
`location_name` is the selected location's last known name, or null.
WeChat metadata is fetched when this endpoint is called. Its deadline uses Unix
seconds and may move after automatic renewal. `wechat` can be `null`; failures are
reported through `wechat_error`, such as `wechat_expired` or `wechat_unavailable`.
`credential_observed_at` is the first local observation of the current expiry,
in Unix seconds. It provides a stable baseline for the remaining-time bar and
resets when the upstream expiry changes; it is not the credential's issue time.

PATCH alias requires a nonblank value of at most 80 characters; whitespace is
trimmed. Forgetting a password does not extend or immediately invalidate the
existing lease. Deletion also removes the corresponding YYB account unless another
local account shares it. If upstream deletion fails, the local account is retained.

## Location selection

Both location endpoints return:

```json
{
  "locations": [{"key":"<stable-key>","name":"School location"}],
  "selected_key": "<stable-key>",
  "automatic": false,
  "unavailable": false
}
```

Use a key from a fresh response; clients cannot supply coordinates. For legacy
clients, `null` resolves to the first valid school-provided location and persists
its concrete key. The UI defaults to that first location and has no automatic
selection option. The location list is
validated for finite coordinates and a positive radius. A removed saved key is
reported as unavailable and is never silently replaced. A write is validated
against the school's current list, and may return HTTP 409 if the key disappeared.

## Run and configuration

POST `/accounts/{id}/check-in` starts asynchronous work and returns HTTP 202.
Poll `/state` for the result. It uses the school's allowed hours, checks today's
record, obtains a fresh WeChat check-in ticket, and uses the persisted submission
journal. It cannot force a duplicate POST or bypass the school time window.
Busy accounts, full worker capacity, or expired school login return HTTP 409.

PUT `/config` accepts both fields (omitted fields use the defaults):

```json
{"checkin_time":"21:00_23:30","log":"info"}
```

`checkin_time` must be `HH:mm_HH:mm`, with start before end on the same Shanghai
day. This is a fallback until the school's schedule is available. New fallback
jobs choose a random time between 13% and 87% of the window; editing config does
not rewrite existing daily schedules. The fetched school schedule can adjust a
job separately. `log` is one of `info`, `error`, `warning`, `debug`.

## Errors

Errors use either a string or a structured detail:

```json
{"detail":{"code":"invalid_code","message":"The school rejected the SMS code. Try again."}}
```

```json
{"detail":"Account not found"}
```

| HTTP status | Meaning |
| --- | --- |
| 400 | Login, CAPTCHA or SMS step rejected; inspect `detail.code` when present |
| 403 | Cross-origin request rejected |
| 404 | Account or API route does not exist |
| 409 | Account/login busy, check-in capacity exhausted, or login/location action required |
| 410 | Pending login or QR session expired/cancelled |
| 422 | Invalid request shape, length, format, or unexpected field |
| 502 | Upstream login, school or WeChat request failed |
| 503 | Frontend build missing when requesting the SPA |

Relevant structured codes include `password_missing` (no password received),
`password_required` (expired saved authentication), `login_rejected` (school returned
to its password form), `school_session_failed` (password submitted but CAS session
exchange failed), `sms_required`,
`invalid_code`, `captcha_error`, `expired`, `login_failed`, `login_unavailable`,
`need_login`, `selected_location_unavailable`, `wechat_expired`, and
`wechat_unavailable`. Validation errors do not echo submitted secret values.

## Server-to-server APIs

These are implementation details, **not public proxy endpoints**. All calls use
server-owned cookie jars or credentials. The normal successful school response is
`{"code":0,"data":...,"ok":true}`; `ok` may be absent. Nonzero `code` or
`ok:false` is not success.

| Method | School path on `https://jzsz.uestc.edu.cn` | Purpose |
| --- | --- | --- |
| GET | `/platform-app/api/h5/user/base-info` | Validate `SESSION` and read profile; `platform: mp-weixin` |
| GET | `/daily-checkin/api/checkin-location/available-locations` | Read school-defined coordinates/radii |
| GET | `/daily-checkin/api/checkin-schedule/effective` | Read start/end offsets in minutes |
| GET | `/daily-checkin/api/student-checkin-record/today` | Read business date and record status |
| GET | `/daily-checkin/api/map/reverse?lat=...&lng=...` | Read location address |
| POST | `/platform-app/api/auth/checkin-ticket` | JSON `{"code":"<fresh-wx.login-code>"}`, `platform: mp-weixin` |
| POST | `/daily-checkin/api/student-checkin-record/checkin` | Submit check-in with `platform: h5` and `X-Checkin-Ticket` |

The ticket response contains `data.ticket` and `data.expiresAt` (Unix **milliseconds**).
Ticket exchange and check-in share the same jzsz `SESSION`. The check-in JSON has
`latitude`, `longitude`, `reverseGeocode`, `clientTime` (`YYYY-MM-DD HH:mm:ss`,
Shanghai), `userAgent`, `coordinateSystemCode: "gcj02"`, `accuracy`,
`locationDurationMs`, `networkTypeCode`, `locationEnabled`, `locationAuthorized`,
`locationAccuracy`, and `errorMessage`. The service uses the selected school's
location center, not device GPS.

The private YYB server defaults to `http://127.0.0.1:8001` inside the container.
The adapter authenticates with POST `/login`, creates QR sessions through
POST `/qr?as_base64=true`, polls `/qr/{id}/poll`, confirms `/qr/{id}/confirm`, and
cancels `/qr/{id}/cancel`. GET `/accounts` supplies credential deadlines;
DELETE `/accounts?ref=...` deletes the binding. POST `/wxapp/getCode` uses a private
Bearer token and JSON `{"ref":"...","app_id":"wxaa78bf2905f01cee"}`.
The returned `data.result.code` is exchanged with the school immediately and is
never returned to the browser or persisted.

For the final CAS ticket handoff and Python API, see
[uestc-login API](../login/docs/api.md).

## HTTP login diagnostics

The warning `School login failed` includes the exception type, error code and
specific reason. `login_unavailable` covers network/timeouts and unexpected school
responses; the code alone does not identify the failing request.

For `login_unavailable`, `detail` can also include `stage`, `http_status`,
`reason` and (for timeouts) `timeout_seconds`. The UI displays these fields so a
password POST returning HTTP 500 is distinguishable from a network timeout or a
failed session-status check. These fields never include raw school response bodies,
cookies or credentials. School requests wait 0.3 seconds before sending and allow
30 seconds for the complete network response.

Both `compose.yaml` and `compose.local.yaml` default to `UESTC_HTTP_TRACE=0`.
Normal application logging uses `info` and does not dump school response bodies.
Raw tracing is an explicit diagnostic opt-in only. When enabled, school requests and responses are
logged in full, with matching request IDs, elapsed time, repeated headers, bodies,
cookie state and transport exception stacks. Read them with
`docker compose logs -f --tail=200 goodnight`. Keep raw logs private: they contain
cookies, tickets, encrypted passwords, submitted SMS codes and user information.
Disable raw tracing with `UESTC_HTTP_TRACE=0 docker compose up -d` after diagnosis.
For a local override deployment, include its original project name and both
`-f compose.yaml -f compose.local.yaml` options when applying this change.
WeChat's private control API is not part of this school HTTP trace.
