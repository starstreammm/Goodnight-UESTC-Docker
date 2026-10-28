# Authentication and account ownership

The console login identity (`User`) is separate from the existing school/WeChat
business entity (`Account`). The existing Admin page remains the management page;
regular Users receive a separate, compact single-Account interface.

## First startup and upgrades

On first startup with this version, the database creates the built-in Admin:

- Username: `admin`
- Initial password: `yyytttqqq`

Log in at `/login`. Successful login opens `/admin` for the built-in Admin or
`/user/<username>` for a regular User. `/` redirects through login, and visiting
another User's URL redirects to your own page. Navigation between these pages
loads a new document. `/`, `/login` and `/admin` have prerendered HTML entry points;
dynamic `/user/<username>` paths use the static-file fallback for direct links
and refreshes. React Router keeps `ssr: false`.

Share `/login?signup=1` to open registration directly; `/login` opens login.
The form's login/registration links update the URL and load a new document.
Registration still follows the administrator's registration policy.
The browser remembers the last successfully authenticated console username in
local storage and prefills it on login, including after logout. Registration
starts with an empty username. Passwords are not stored by this feature; if
browser storage is blocked, login still works without remembering the username.

The console displays a password-change prompt while the
initial/reset password is in use. Change it through **Settings → Change password**.
There is exactly one Admin, whose username is permanently `admin`. The built-in
Admin cannot be renamed, deleted or demoted. All public registrations and
Admin-created identities have the `user` role; creating or promoting another
Admin is disallowed by the API and SQLite. Startup does not reset the password.

On upgrade from the earlier multi-Admin version, extra Admins with at most one
Account become Users and their sessions are revoked. If an extra Admin has
multiple Accounts, or another User has claimed the name `admin`, migration stops
without deleting or transferring data. Resolve that conflict in the earlier
version before upgrading. A renamed built-in Admin is restored to `admin`.

The migration adds console identities and ownership to the existing SQLite
store. Existing Accounts are assigned to the built-in Admin; account IDs, school
sessions, saved credentials, schedules, locations and job history are retained.
No ownership transfer or manual assignment API is provided. Back up the persistent
data directory before upgrading; an older application version does not understand
the required ownership column and should not write to the migrated database.

Registration initially defaults to **Disabled**. The Admin can choose Disabled,
Invitation Only, or Open Registration in the Header's **Settings** dialog.
Invitation codes are single-use; consumption and User creation commit in the same
transaction. Failed registration does not consume a code. Public registration
always creates a `user` with no Account, regardless of registration mode.

### Updating a local Docker deployment

Rebuild the frontend before rebuilding the local image. Docker copies
`app/build/client` as-is; rebuilding only the image can pair the new authentication
backend with an old frontend that has no login page. That old frontend displays
“操作未完成，请检查输入或稍后重试。” when protected requests are rejected.

Run from the repository root, keeping your deployment's existing Compose project
name and port settings:

```sh
npm --prefix app run build
docker compose -f compose.yaml -f compose.local.yaml up -d --build
```

Both commands must complete successfully. Then reload `/login`; if the browser
still has the previous page open, use a hard refresh. Restarting an existing
container alone does not replace the bundled frontend.

## Accounts and User management

New Accounts belong to the authenticated creator. Regular Users can have zero or
one Account; Admins can have multiple. School-account usernames remain globally
unique, and reconnecting an existing Account never changes its owner. SQLite
foreign keys and triggers enforce ownership, prevent orphaned Accounts, reject
ownership changes and enforce the single fixed Admin identity.

The Admin Account List shows the school real name (school username if unavailable)
in its account-info column. A separate associated-user column contains the alias,
console username and role, between account info and latest activity. Regular User
aliases are derived from their display name, or their console username when the
display name is blank; they cannot be edited independently. Existing aliases are
synchronized on startup, and profile changes synchronize them atomically. Its single-level More menu includes User info, profile editing,
password reset and User deletion. The Header Settings dialog manages
registration, invitation codes and Users without Accounts, and offers profile,
password and logout controls. Each invitation has a Copy button. Used invitations are hidden in a collapsed
section until expanded; registration
in invitation mode tells new Users to obtain a code from the Admin.
Admin-created Users also start without an Account.

The login form is centered in the viewport. Admin and User pages share the same
full-width Header with a Logout button. The User page fills the viewport and keeps its footer at the bottom. The header
shows one check-in indicator. Account actions sit above the content; the profile
and editable settings appear directly in two columns on desktop, stacked on narrow
screens. Confirmed check-ins show the school's actual `checkinTime`, while pending
jobs show their scheduled time. Long content scrolls internally. Confirmation
dialogs remain scrollable with their scrollbars hidden.

School profile fields use English/Chinese labels for student number, name, phone,
gender, college, major, class and grade. Internal codes and the duplicate college
field are hidden. Normal logging uses `info`; raw school response tracing defaults
to off in both Compose configurations.

Account deletion asks for confirmation with **Also delete associated User**
checked by default. This deletes a regular owner and revokes their sessions;
unchecking retains an empty User. Admin identities are always retained when
an Account is deleted. Explicit Admin-authorized User deletion removes all their
Accounts. The built-in Admin is never deletable.

User, Account, job and session cascades commit atomically in SQLite. Deletion
queues removal of local school credentials and unshared WeChat credentials in
the same transaction. The background reaper performs this cleanup every ten
seconds and retries failures, including after a restart. A school username cannot
be re-added until its cleanup completes. Remote service deletion cannot participate
in the SQLite transaction; it is eventual. Shared WeChat credentials are retained.
Running check-ins or pending sign-ins block conflicting deletions.

## Sessions and deployment

Passwords use salted scrypt hashes (`N=32768`, `r=8`, `p=3`), separate from encrypted
school credentials. Sessions use random opaque tokens; only SHA-256 token hashes
are stored in SQLite. Cookies are HttpOnly, SameSite=Strict and scoped to `/api`.
Sessions last 30 days, survive service restarts and are not extended by polling.
Logout revokes the current session. Changing a personal password revokes all old
sessions and creates a replacement for the caller; an Admin reset revokes all
of the target User's sessions and prompts them to change their password.

Every protected request reads the current role from the database. Account routes
check ownership, state is filtered by owner, and pending school/WeChat sign-ins
are bound to their initiating console User. State-changing requests require the
`X-Requested-With: GoodNight` header and enforce same-origin checks; the frontend
API helper supplies the header. Login and registration have persistent attempt
limits. Unauthenticated visitors are redirected to `/login`.

Serve external deployments over HTTPS. Cookies automatically use Secure when
FastAPI sees an HTTPS request. If a TLS-terminating proxy forwards HTTP internally,
set `AUTH_COOKIE_SECURE=1` in the backend container environment. For Compose, add
that variable under the service's `environment` in your deployment override.
Keep the backend and private WeChat control service inaccessible directly from
the public network, and trust forwarded headers only from your reverse proxy.
The default localhost HTTP deployment continues to work without this variable.

## Validation status and manual commands

No test files were created or modified, and no tests were run. Existing backend
tests that create ownerless Accounts or call endpoints anonymously need deliberate
updates for the authentication contract before the whole suite can pass; they
were left unchanged per instruction. There is currently no frontend test script.
The repository's existing backend test command is:

```sh
(cd goodnight && uv run pytest)
```

The frontend's separate static type-check command is:

```sh
npm --prefix app run typecheck
```

Browser interactions, upgrade behavior against a real persisted database, and
mobile/touch behavior still require manual validation.

## Implementation references

SQLite documents the restriction on adding a non-null foreign-key column to a
populated table, which is why this migration adds the foreign key and enforces
required ownership with triggers: [ALTER TABLE](https://www.sqlite.org/lang_altertable.html).
Cascades use SQLite's [foreign-key support](https://www.sqlite.org/foreignkeys.html).
