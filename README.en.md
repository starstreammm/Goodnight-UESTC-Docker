# GoodNight UESTC

A self-hosted bilingual account console for UESTC night check-in, with IDAS login
and the [YYB-Go-Enhanced](https://github.com/525815266/YYB-Go-Enhanced) WeChat backend.

[中文](README.md) · [HTTP API](docs/api.md) · [Login Python API and CAS flow](login/docs/api.md)

Login, SMS verification, CAS exchange and check-in use `httpx`; no Playwright or Chromium is required. Nginx starts after the backend health check passes.

## Layout

- `login/`: independently installable `uestc-login` Python package, its own
  `pyproject.toml`, `uv.lock`, `.venv`, and tests. Handles password login, browser
  identity, SMS reauthentication, encrypted credentials, seven-day leases and
  service adapters (`uestc_login/skill/jzsz.py` returns a `SESSION` string).
- `goodnight/`: independent uv project. Depends on `uestc-login` through the local
  `../login` package. Owns the API, account store, school adapter, private WeChat
  adapter and scheduler.
- `app/`: React UI with its own npm dependencies. Chinese browser language selects
  Chinese; every other browser language selects English. The header switch is
  saved locally.

## Start with the published image

Users only need Docker Compose. `compose.yaml` pulls the published GHCR image;
Node.js and the source build are not required. Run from the directory containing
`compose.yaml`:

```sh
docker compose pull
docker compose up -d
```

Open [http://localhost:8000](http://localhost:8000) and log in with the default
administrator username `admin` and password `yyytttqqq`. Change the default password
after your first login. Existing installations keep their configured password.

The named `goodnight-data`
volume persists account state, encrypted credentials, the encryption keys,
check-in journals and WeChat credentials. Back up the entire volume together.
The published port binds to localhost. Use a trusted authenticated reverse proxy
or private network if remote access is needed; this is a single-operator console.

Repeat these commands to update. Set `GOODNIGHT_IMAGE` in `.env` to pin a published
version or use the Docker Hub mirror, for example
`GOODNIGHT_IMAGE=starstreammm/goodnight-uestc-docker:latest`.
`GOODNIGHT_PORT` changes the local port (default `8000`). Raw school HTTP tracing
is disabled by default for users.

### Local build and testing setup

Developers also need Node.js 24 and npm. Frontend assets **must be built on the
host**; Docker has no Node stage. The explicit `compose.local.yaml` override builds
`goodnight-uestc-docker:local` with raw HTTP tracing disabled by default
(see [diagnostic logging](docs/api.md)). It is not
automatically loaded for users.

```sh
npm --prefix app ci
npm --prefix app run build
GOODNIGHT_PORT=8002 docker compose -p goodnight-local -f compose.yaml -f compose.local.yaml up -d --build
```

Open [http://localhost:8002](http://localhost:8002). The separate `goodnight-local`
project uses its own data volume. Use the same project name and both `-f` options
for subsequent local commands. To update an existing installation from local
source instead, omit `-p goodnight-local` and the port override to retain its
existing Compose project and volume.

### Image publishing

GitHub Actions builds the frontend from `app/`, then publishes `linux/amd64` and
`linux/arm64` images to Docker Hub and GHCR. Pushes to `main` publish `main` and
`latest`; Git tags publish their own tag, and tags without `-` also update
`latest`. Prerelease tags such as `v0.2.0-rc.1` do not update `latest`. SemVer tags
also get a version alias without the leading `v`; all builds get a `sha-` tag.
Configure repository secrets `DOCKER_USERNAME` and `DOCKER_PASSWORD` for Docker
Hub; GHCR uses `GITHUB_TOKEN`. Make the GHCR package public for anonymous pulls.
The workflow publishes images; it does not create a GitHub Release.

The Docker image copies the YYB binary from a pinned multiarchitecture upstream
image (see `YYB_IMAGE` in `Dockerfile`). Nginx publishes only this application's UI
and API. YYB listens on **127.0.0.1:8001 inside the container**, has no published
port or reverse-proxy route, and its own Web UI is inaccessible to users.
The application generates private backend credentials and authenticates to YYB
internally. Operators never need YYB's login, tokens, account IDs or Web UI.
`docker build --build-arg YYB_IMAGE=... .` can explicitly select a newer upstream
image after checking adapter compatibility.

## Accounts

1. Add a school username and password. Alias is optional and defaults to the
   real name returned by the school.
2. Complete SMS reauthentication if requested by the school.
3. Scan the displayed WeChat QR code and confirm on the phone.
4. Review the school profile, schedule and location range, select a location, then
   choose **Confirm and save**. Cancelling does not save a new account.
5. Use **Info**, **Settings**, **Run now**, or **More** on each account.

Info shows school profile data, schedule and location, the local UESTC session deadline and the
WeChat authorization deadline: up to 30 days from the QR scan recorded by YYB.
Automatic credential refresh does not extend this countdown; scan again when it
expires. Older accounts without a recorded scan time show no deadline, and the
server can revoke authorization earlier. Settings supports
Admin-owned account aliases, allowed location selection, and forgetting a saved password.
User-owned account aliases follow the display name, falling back to the console username. More
contains sign-in again and deletion. Deleting an account also removes its WeChat
record unless another school account still references it.

**More** offers separate **Sign in to school again** and **Sign in to WeChat again**
actions. Each updates only that service's credentials. **Sign in with a new browser
fingerprint** starts a school login with a new browser identity and fresh cookies. The replacement fingerprint
and session are saved only after **Confirm and save**.
For accounts that have not yet been confirmed, each new login attempt also uses
a fresh fingerprint, including retries after a failed Add account attempt.

Location selectors default to the first actual school location and save its key.
Account details show remaining-time progress bars for school and WeChat credentials.

Passwords are saved only when explicitly enabled, encrypted locally. Otherwise,
the session has a fixed maximum seven-day lifetime, after which the password must
be entered again. Server expiry can happen earlier. With password storage enabled,
auto-renewal submits the stored password; any required SMS or CAPTCHA asks for
interactive sign-in. SMS codes, wx.login codes and check-in tickets are not saved.
The keys live beside the encrypted data, so protect the full data volume.

## Check-in behavior

Within the existing seven-day local lease, the service checks the last jzsz
session with `/api/isLoginFailure` before requesting a new one. A valid session
is reused without extending that lease; timeouts and malformed responses stop
renewal. If invalid, `uestc-login`
tries the saved CAS session, then an opted-in password login. It periodically
loads the profile, allowed location ranges, effective school schedule and today's
record. Daily random times follow the fetched school schedule; the configured
fallback is used while the schedule is unavailable. The last five minutes are
excluded as a submission safety margin. A restarted service can catch up before
the cutoff. The school schedule and today's record are checked again before POST.

School requests use the manual diagnostic's Safari headers and cookie-name
filters, with a 0.3-second delay before each send and a 30-second total network
deadline. CAS preserves the `https://jzsz.uestc.edu.cn/#/hall/home` service, and
new sessions pass the login-status check before mini-program profile validation.

When submission is needed, the service gets a fresh `wx.login` code for
`wxaa78bf2905f01cee`, exchanges it at `/platform-app/api/auth/checkin-ticket` using
the same jzsz context, and adds `X-Checkin-Ticket` to the check-in request. The
request includes the GCJ-02 location fields. Location uses the selected
school-provided center, as in this repository's existing behavior.

The persisted submission journal prevents repeat POSTs after an ambiguous network
failure. A successful POST alone is not considered success: the school record
must confirm it. Run now uses the same journal and school time checks. A result
that remains unconfirmed requires checking the official school record.

## Local Python development and verification

To manually inspect Goodnight with an existing jzsz `SESSION` cookie, run from
the repository root:

```sh
uv run --project goodnight python goodnight/manual_test.py
```

Paste the cookie value (or `SESSION=value`) at the hidden prompt. Alternatively,
pass `--session VALUE`. The script makes three read-only requests and prints JSON
containing `location` (allowed locations), `status` (today's record and interpreted
state), and `schedule` (effective school schedule and current check-in window in
Asia/Shanghai, including Goodnight's five-minute cutoff). It does not submit a
check-in. Each result includes `ok` and either school data or an error; exit code
is 1 if any request fails, otherwise 0. The school schedule is separate from the
application's locally selected random run time.

Each Python project has its own uv environment and lockfile:

```sh
(cd login && uv sync --frozen && uv run pytest)
(cd goodnight && uv sync --frozen && uv run pytest)
npm --prefix app run typecheck
npm --prefix app run build
```

From the repository root, run the backend with
`uv run --project goodnight uvicorn goodnight.main:app --host 127.0.0.1 --port 8000`.
For a complete local login flow, run the private YYB binary through
`goodnight.yyb_process` with the same `DATA_DIR`; Docker handles this automatically.

The offline tests use synthetic accounts and API fixtures. Real school login,
SMS delivery, QR confirmation and attendance submission require a user's live
account and have not been exercised by these tests. No captured credentials from
the task are bundled in the code.

Existing installations retain the SQLite schema and submission journal. Accounts
created before the new login package lack a login lease and WeChat binding and
must be connected again.

The verified IDAS password algorithm is documented in
[login/docs/password-encryption.md](login/docs/password-encryption.md).
