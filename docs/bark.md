# Bark notifications

Bark is optional and disabled by default. Notifications belong to the console
User who owns a School Account; an Admin receives notifications for their own
Accounts, not for every User they manage.

## User setup and language

After the first successful console sign-in (including registration), a dismissible
dialog introduces Bark. Enter the device key and save to enable notifications, or
choose **Skip setup**, press Escape, or dismiss the dialog. The decision is saved
on the User, so subsequent logins and other browsers do not repeat the prompt.
Existing Users receive this prompt once after upgrading. No Bark promotion appears
on the sign-in or registration page.

Users can change these options under **My profile → Bark notifications**. Admins
also have the same personal controls in **Settings**, below the profile/logout
buttons. The dialog remains scrollable with its scrollbars hidden. Save a replacement key to
update it, switch notifications off to retain the key without sending, or choose
**Remove Bark key** to erase it and disable notifications. Only the device key is
accepted, not a full push URL. The saved key is never returned to the browser.

Saving a change from disabled to enabled sends one localized `active` test
notification in the background, even if the User has no School Account yet.
It uses the same title, icon, and Admin destination URL as other notifications.
Saving unchanged settings or opening the settings dialog does not send it again;
disabling and then re-enabling Bark sends a new test notification. Delivery
failures are logged without reverting settings or blocking the save response.
This activation message is attempted once after the response and is not persisted
for replay after a server restart.

The UI explains that Bark supports only iOS and iPadOS and links to the
[Bark setup tutorial](https://bark.day.app/?utm_source=chatgpt.com#/tutorial?id=发送推送).

Registration initializes the User's language from the browser: `zh` and `zh-*`
become `zh`; English and unsupported languages become `en`. The existing language
toggle persists changes for authenticated Users. Subsequent logins restore that
User's saved preference, including on another browser. Existing and Admin-created
Users start with `en`. Guest language selection remains local to the browser.
Notification bodies use the owner's saved language at delivery time.

## Admin configuration

In **Settings → Notification destination URL · Admin**, optionally set an absolute
HTTP(S) URL, typically the console's public URL. It is sent in Bark's `url` field
and opens when the recipient taps a notification. Clearing it omits the field.
Changes save automatically after a 500 ms typing pause, or immediately when the
field loses focus or the dialog closes. There is no separate save button.
This option is protected by the existing Admin authorization for `/api/config`.
It does not change the Bark server endpoint.

## Events and timing

| Event | Level | Deduplication scope |
| --- | --- | --- |
| School session expires within 24 hours, without a saved password | `active` | Account and session lease |
| School session expired, without a saved password | `timeSensitive` | Account and session lease |
| School session expired, with a saved password | `passive` | Account and session lease |
| Automatic saved-password renewal fails | `active` | Account and session lease |
| Check-in remains incomplete in the last **5 minutes** | `critical` | Account and Shanghai calendar date |
| School confirms successful check-in | `passive` | Account and Shanghai calendar date |

The five-minute reminder uses today's School schedule end offset. The scheduler
already stops automatic submissions five minutes before that deadline; the
reminder uses the same boundary, without subtracting another five minutes. For
example, a School deadline of 23:00 produces a reminder from 22:55 until 23:00.
If today's School schedule is unavailable, it uses the persisted job cutoff,
or the existing scheduler's calculated bounds when no job exists. Accounts that
need login are included even if they have no job today. Already checked-in,
reported, and exempt records do not trigger an incomplete-check-in reminder.
Only confirmed check-ins trigger success messages, not exemptions or reports.

Session expiry uses the existing LoginManager lease metadata and authentication
checks. A saved password suppresses the 24-hour warning. Expiry queues a passive
message, then the existing noninteractive saved-password mechanism attempts
renewal. A failed attempt queues a separate active escalation; repeated failures
for that lease do not repeat the escalation. Renewal remains subject to the
existing scheduler, account status, concurrency limits, and login requirements;
Bark does not add another authentication or retry mechanism.

## Persistence and delivery

Startup upgrades the existing SQLite database in place. The `users` table gains
`language`, `bark_enabled`, `bark_key`, and `bark_prompt_dismissed`. The key is
encrypted with the existing Store Fernet key (`session.key`). Keep that key with
the database when backing up or moving the installation. The existing JSON
configuration gains `bark_url`, defaulting to an empty string.

`bark_events` stores Account/event/occurrence identities and delivery status, with
an Account foreign key and cascading deletion. Session events use the saved
lease expiration timestamp; check-in events use the Shanghai date. Event types
are separate so a warning or passive expiry message cannot suppress a later
expiration or renewal-failure escalation. Disabling and re-enabling Bark does not
erase the journal or replay an already attempted event.

`goodnight.bark.Bark` queues events without doing network I/O in authentication
or check-in workflows. An independent background task scans approximately every
10 seconds, sends up to three requests concurrently, prioritizes deadline
reminders, and limits each request to 10 seconds. A slow batch can extend the scan
interval. Recipients must still be enabled and have a key when delivery starts.
Queued deadline reminders are rechecked for completion and timing; queued
24-hour warnings are rechecked for renewal and saved-password changes.

Delivery uses JSON `POST https://api.day.app/push`, following the official
[Bark API V2 documentation](https://github.com/Finb/bark-server/blob/master/docs/API_V2.md).
Every payload includes `device_key`, `title: Goodnight UESTC`, a localized `body`,
the event's `level`, and this `icon`:
`https://free.picui.cn/free/20172/2026/10/28/6ae1f5056cd1e.png`.
The optional Admin destination is included as `url`. HTTP errors and Bark API
rejections are logged without credentials, notification content, or response
bodies and do not interrupt authentication, session renewal, or check-in.

Delivery is **at most once per event**, including across restarts. An event is
claimed before the HTTP request, and an ambiguous timeout or interrupted request
is not replayed because Bark may already have accepted it. This prevents duplicate
alerts but means a delivery failure can lose that notification. The journal keeps
`pending`, `sending`, `sent`, `failed`, or `skipped` status; a crash may leave an
attempt as `sending`. A new session lease or check-in date creates new events.
Changing a key does not replay earlier attempted events. Notifications are based
on the latest locally confirmed School state; no extra School requests are made
just for Bark. Phone delivery also depends on Bark and the device's notification
permissions; an accepted API response is not confirmation of display on the phone.

## Preference API

`PATCH /api/auth/preferences` uses the existing console cookie and same-origin
request protections. It changes only the authenticated User. All fields are
optional; omitted fields remain unchanged:

| Field | Accepted value |
| --- | --- |
| `language` | `en` or `zh` |
| `bark_enabled` | Boolean; enabling requires a configured key |
| `bark_key` | Device key, up to 256 ASCII letters/digits/`-`/`_`; empty string removes it and disables Bark |
| `bark_prompt_dismissed` | `true`; dismissal cannot be reset through this endpoint |

The response is the public User, including language and the
`bark_enabled`, `bark_configured`, and `bark_prompt_dismissed` flags, never the key.
`POST /api/auth/register` accepts an optional browser `language` string.
The existing Admin-only `PUT /api/config` accepts `bark_url` alongside
`checkin_time` and `log`; clients should preserve the other configuration fields.

## Manual validation commands

No tests were added or run for this integration. The repository's existing checks
can be run manually from the repository root:

```sh
(cd login && uv run pytest)
(cd goodnight && uv run pytest)
(cd app && npm run typecheck)
```
