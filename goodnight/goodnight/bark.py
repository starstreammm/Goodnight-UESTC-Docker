"""Optional, durable Bark notifications, isolated from school operations."""

import asyncio
import json
import logging
from datetime import datetime, timedelta

import httpx

from .policy import now

log = logging.getLogger("goodnight")
ICON = "https://free.picui.cn/free/20172/2026/10/28/6ae1f5056cd1e.png"
EVENTS = {
    "session_warning": (
        "active",
        "{account}: Your School session expires within 24 hours. Please sign in again.",
        "{account}：学校会话将在 24 小时内过期，请重新登录。",
    ),
    "session_expired": (
        "timeSensitive",
        "{account}: Your School session has expired. Please sign in again.",
        "{account}：学校会话已过期，请重新登录。",
    ),
    "session_renewing": (
        "passive",
        "{account}: Your School session has expired. Automatic renewal will use your saved password.",
        "{account}：学校会话已过期，将使用已保存的密码自动续期。",
    ),
    "renewal_failed": (
        "active",
        "{account}: Automatic School session renewal failed. Please sign in again.",
        "{account}：学校会话自动续期失败，请重新登录。",
    ),
    "checkin_deadline": (
        "critical",
        "{account}: Check-in is still incomplete with 5 minutes or less until the deadline. Please check your account now.",
        "{account}：距签到截止不足或等于 5 分钟，签到仍未完成，请立即检查账号。",
    ),
    "checkin_success": (
        "passive",
        "{account}: Check-in succeeded for {date}.",
        "{account}：{date} 签到成功。",
    ),
}


class Bark:
    def __init__(self, store, scheduler):
        self.store = store
        self.scheduler = scheduler

    async def send(self, client, recipient, level, body):
        payload = {
            "device_key": self.store.cipher.decrypt(recipient["bark_key"]).decode(),
            "title": "Goodnight UESTC",
            "icon": ICON,
            "body": body,
            "level": level,
        }
        destination = self.store.config().bark_url
        if destination:
            payload["url"] = destination
        async with asyncio.timeout(10):
            response = await client.post("https://api.day.app/push", json=payload)
            response.raise_for_status()
            if response.json().get("code") != 200:
                raise ValueError("Bark rejected the notification")

    async def send_test(self, user_id):
        try:
            with self.store.connect() as db:
                recipient = db.execute(
                    "SELECT language,bark_key FROM users WHERE id=? "
                    "AND bark_enabled=1 AND bark_key IS NOT NULL",
                    (user_id,),
                ).fetchone()
            if not recipient:
                return
            body = (
                "Bark 通知已启用。这是一条来自 Goodnight UESTC 的测试通知。"
                if recipient["language"] == "zh"
                else "Bark notifications are enabled. This is a test notification from Goodnight UESTC."
            )
            async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
                await self.send(client, recipient, "active", body)
        except Exception:
            log.warning("User %s: Bark activation notification failed", user_id)

    def enqueue(self, account, event, occurrence):
        # Persist only events for opted-in owners. The key never enters the journal.
        try:
            with self.store.connect() as db:
                db.execute(
                    "INSERT INTO bark_events(account_id,event,occurrence) "
                    "SELECT id,?,? FROM accounts WHERE id=? AND owner_id IN "
                    "(SELECT id FROM users WHERE bark_enabled=1 AND bark_key IS NOT NULL) "
                    "ON CONFLICT(account_id,event,occurrence) DO UPDATE SET status='pending' "
                    "WHERE bark_events.status='skipped'",
                    (event, str(occurrence), account["id"]),
                )
        except Exception:
            log.warning("Account %s: could not queue Bark event %s", account["id"], event)

    def session_expired(self, account, *, failed=False):
        try:
            metadata = self.store.login.metadata(account["username"])
            saved = metadata["save_password"]
            if failed and not saved:
                return
            event = (
                "renewal_failed"
                if failed
                else "session_renewing"
                if saved
                else "session_expired"
            )
            self.enqueue(account, event, metadata["uestc_expires_at"] or "legacy")
        except Exception:
            log.warning("Account %s: could not inspect Bark session event", account["id"])

    def deadline(self, account, job, current):
        date = current.date().isoformat()
        if self.scheduler.school_window(account, date):
            # The automatic cutoff already reserves five minutes. Read the
            # validated school end offset so that buffer is not applied twice.
            data = json.loads(account["schedule"])["response"]["data"]
            midnight = current.replace(hour=0, minute=0, second=0, microsecond=0)
            return midnight + timedelta(minutes=data["studentCheckinEndOffsetMinute"])
        if job:
            return datetime.fromisoformat(job["cutoff"])
        window, has_school = self.scheduler.automatic_window(account, date)
        if window:
            return self.scheduler.automatic_bounds(account, date, window, has_school)[1]
        return None

    def deadline_pending(self, account, job, current):
        if job and (
            job["checked"]
            or job["checked_at"]
            or job["status"] in ("success", "already_done")
        ):
            return False
        deadline = self.deadline(account, job, current)
        return (
            deadline is not None
            and deadline - timedelta(minutes=5) <= current < deadline
        )

    def scan(self):
        current = now()
        date = current.date().isoformat()
        with self.store.connect() as db:
            accounts = db.execute(
                "SELECT accounts.* FROM accounts JOIN users ON users.id=owner_id "
                "WHERE bark_enabled=1 AND bark_key IS NOT NULL"
            ).fetchall()
            jobs = {
                row["account_id"]: row
                for row in db.execute("SELECT * FROM jobs WHERE date=?", (date,))
            }
        for account in accounts:
            try:
                metadata = self.store.login.metadata(account["username"])
                expiry = metadata["uestc_expires_at"]
                if account["status"] == "need_login" or (
                    expiry is not None and expiry <= current.timestamp()
                ):
                    self.session_expired(account)
                elif (
                    expiry is not None
                    and expiry - current.timestamp() <= 86400
                    and not metadata["save_password"]
                ):
                    self.enqueue(account, "session_warning", expiry)
                job = jobs.get(account["id"])
                if job and (job["status"] == "success" or job["checked_at"]):
                    self.enqueue(account, "checkin_success", date)
                # Accounts needing login may have no job today. Use the same
                # schedule/bounds as automatic check-in in that case.
                if self.deadline_pending(account, job, current):
                    self.enqueue(account, "checkin_deadline", date)
            except Exception:
                log.warning("Account %s: Bark event scan failed", account["id"])

    async def deliver(self, client, event):
        ident, kind, occurrence = event["account_id"], event["event"], event["occurrence"]
        identity = (ident, kind, occurrence)
        try:
            with self.store.connect() as db:
                recipient = db.execute(
                    "SELECT accounts.*,users.language,users.bark_key,users.bark_enabled "
                    "FROM accounts JOIN users ON users.id=owner_id WHERE accounts.id=?",
                    (ident,),
                ).fetchone()
                eligible = bool(
                    recipient and recipient["bark_enabled"] and recipient["bark_key"]
                )
                current = now()
                if eligible and kind == "session_warning":
                    metadata = self.store.login.metadata(recipient["username"])
                    expiry = metadata["uestc_expires_at"]
                    eligible = (
                        not metadata["save_password"]
                        and recipient["status"] == "ready"
                        and str(expiry) == occurrence
                        and 0 < expiry - current.timestamp() <= 86400
                    )
                if eligible and kind == "checkin_deadline":
                    job = db.execute(
                        "SELECT * FROM jobs WHERE account_id=? AND date=?",
                        (ident, occurrence),
                    ).fetchone()
                    eligible = (
                        occurrence == current.date().isoformat()
                        and self.deadline_pending(recipient, job, current)
                    )
                if not eligible:
                    status = "skipped"
                else:
                    status = "sending"
                claimed = db.execute(
                    "UPDATE bark_events SET status=? WHERE account_id=? AND event=? "
                    "AND occurrence=? AND status='pending'",
                    (status, *identity),
                ).rowcount
            if not claimed or status != "sending":
                return
            level, en, zh = EVENTS[kind]
            body = (zh if recipient["language"] == "zh" else en).format(
                account=recipient["alias"], date=occurrence
            )
            await self.send(client, recipient, level, body)
            status = "sent"
        except Exception:
            # Do not log HTTP exception messages, payloads, or credentials.
            log.warning("Account %s: Bark delivery failed for %s", ident, kind)
            status = "failed"
        with self.store.connect() as db:
            db.execute(
                "UPDATE bark_events SET status=? WHERE account_id=? AND event=? AND occurrence=?",
                (status, *identity),
            )

    async def loop(self):
        # A claimed request is never replayed: a timeout/crash can occur after
        # Bark accepted it. Separate event kinds still permit severity escalation.
        async with httpx.AsyncClient(timeout=10, follow_redirects=False) as client:
            while True:
                try:
                    self.scan()
                    with self.store.connect() as db:
                        pending = db.execute(
                            "SELECT queued.* FROM bark_events AS queued WHERE status='pending' "
                            "AND NOT EXISTS (SELECT 1 FROM bark_events AS earlier "
                            "WHERE earlier.account_id=queued.account_id AND earlier.status='pending' "
                            "AND earlier.rowid<queued.rowid) "
                            "ORDER BY (event='checkin_deadline') DESC,queued.rowid LIMIT 3"
                        ).fetchall()
                    results = await asyncio.gather(
                        *(self.deliver(client, event) for event in pending),
                        return_exceptions=True,
                    )
                    if any(isinstance(result, Exception) for result in results):
                        log.warning("Could not persist a Bark delivery result")
                except Exception:
                    log.warning("Bark processing failed; retrying next cycle")
                await asyncio.sleep(10)
