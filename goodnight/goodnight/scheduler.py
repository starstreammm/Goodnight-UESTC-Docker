import asyncio
import logging
import time
import json
import traceback
from pathlib import Path
from datetime import timedelta
from .policy import now, choose_time, bounds
from .school import run_checkin, authenticate, SchoolError, request, available_locations, choose_location, location_option, checkin_ticket
from uestc_login import LoginError
from uestc_login.client import ServiceUnavailable
from .wechat import WeChatError

log = logging.getLogger('goodnight')
RETRY = {'transport_error', 'http_error', 'window_not_open', 'runtime_error', 'checkin_timeout', 'unknown_record', 'unconfirmed', 'wechat_unavailable', 'ticket_unavailable', 'ticket_expired'}


class Scheduler:
    def __init__(self, store, sessions, wechat=None):
        self.store, self.sessions = store, sessions
        self.wechat = wechat
        self.busy = set()
        self.tasks = set()
        self.last_probe = {}

    async def session(self, account):
        if self.wechat is None:
            return self.store.state(account)
        return await self.store.login.session(self.sessions, account['username'], self.store.state(account))

    async def ticket(self, context, account):
        if not account['wechat_ref']:
            raise WeChatError('wechat_expired')
        code = await self.wechat.code(account['wechat_ref'])
        return await checkin_ticket(context, code)

    @staticmethod
    def school_window(account, date):
        try:
            saved = json.loads(account['schedule'] or '{}')
            if saved.get('date') != date or saved['response']['code'] != 0 or saved['response'].get('ok') is False:
                return None
            data = saved['response']['data']
            start, end = data['studentCheckinStartOffsetMinute'], data['studentCheckinEndOffsetMinute']
            if type(start) is not int or type(end) is not int or not 0 <= start < end <= 1440:
                return None
            end = min(end - 5, 1439)
            if start >= end:
                return None
            return f'{start//60:02}:{start%60:02}_{end//60:02}:{end%60:02}'
        except (KeyError, TypeError, ValueError):
            return None

    def automatic_window(self, account, date):
        school = self.school_window(account, date)
        window = school or self.store.config().checkin_time
        if account['checkin_time']:
            start, end = window.split('_')
            preferred_start, preferred_end = account['checkin_time'].split('_')
            start, end = max(start, preferred_start), min(end, preferred_end)
            window = f'{start}_{end}' if start < end else None
        return window, school is not None

    @staticmethod
    def automatic_bounds(account, date, window, has_school):
        low, high = bounds(date, window, padding=not account['checkin_time'])
        if has_school:
            _, high = bounds(date, window, padding=False)
        return low, high

    def reschedule(self, ident, *, force=False):
        current = now()
        date = current.date().isoformat()
        with self.store.connect() as db:
            account = db.execute('SELECT * FROM accounts WHERE id=?', (ident,)).fetchone()
            job = db.execute('SELECT * FROM jobs WHERE account_id=? AND date=?', (ident, date)).fetchone()
            if not account or not job or job['submitted'] or job['status'] not in ('scheduled', 'retry', 'missed'):
                return
            window, has_school = self.automatic_window(account, date)
            if not window:
                db.execute("UPDATE jobs SET status='missed',message='random_window_unavailable' WHERE account_id=? AND date=?", (ident, date))
                return
            low, high = self.automatic_bounds(account, date, window, has_school)
            # Keep a pending random time unless the allowed range has changed.
            if force or not low.isoformat() <= job['scheduled_at'] < high.isoformat() or job['cutoff'] != high.isoformat() or (job['status'] == 'missed' and current < high):
                due = choose_time(date, window, padding=not account['checkin_time'])
                if current < high:
                    due = max(current, due)
                db.execute("UPDATE jobs SET due=?,scheduled_at=?,cutoff=?,status=?,message=NULL WHERE account_id=? AND date=?",
                    (due.isoformat(), due.isoformat(), high.isoformat(), 'scheduled' if current < high else 'missed', ident, date))

    def plan(self, current):
        date = current.date().isoformat()
        with self.store.connect() as db:
            # A running manual check may legitimately outlive the automatic
            # cutoff. Never replace its progress or erase the last failure.
            db.execute("UPDATE jobs SET message='automatic_window_missed' WHERE message='Service was offline past the allowed window'")
            db.execute("UPDATE jobs SET status='missed',message=COALESCE(NULLIF(message,''),'automatic_window_missed') WHERE status IN ('scheduled','retry') AND cutoff<?", (current.isoformat(),))
            for account in db.execute("SELECT * FROM accounts WHERE status='ready'").fetchall():
                window, has_school = self.automatic_window(account, date)
                available = window is not None
                window = window or account['checkin_time']
                _, high = self.automatic_bounds(account, date, window, has_school)
                due = choose_time(date, window, padding=not account['checkin_time'])
                db.execute('INSERT OR IGNORE INTO jobs(account_id,date,due,scheduled_at,cutoff,status,message) VALUES(?,?,?,?,?,?,?)',
                    (account['id'], date, due.isoformat(), due.isoformat(), high.isoformat(),
                     'scheduled' if available and current < high else 'missed', None if available else 'random_window_unavailable'))

    async def execute(self, job, manual=False):
        ident, date = job['account_id'], job['date']
        ctx = None
        stage = 'load_session'
        try:
            with self.store.connect() as db:
                account = db.execute('SELECT * FROM accounts WHERE id=?', (ident,)).fetchone()
                if not account:
                    return
                db.execute("UPDATE jobs SET status='running',attempts=attempts+1 WHERE account_id=? AND date=?", (ident, date))
            async with asyncio.timeout(180):
                stage = 'open_session'
                ctx = await self.sessions.new_context(storage_state=await self.session(account))
                def mark():
                    current = now()
                    if current.date().isoformat() != date or (not manual and current.isoformat() > job['cutoff']):
                        return False
                    with self.store.connect() as db:
                        changed = db.execute('UPDATE jobs SET submitted=1 WHERE account_id=? AND date=? AND submitted=0', (ident, date))
                        return changed.rowcount == 1
                stage = 'check_school_record_and_submit'
                def remember_location(name):
                    with self.store.connect() as db:
                        db.execute('UPDATE accounts SET location_name=? WHERE id=?', (name, ident))
                def remember_submission(diagnostic):
                    detail = json.dumps(diagnostic, sort_keys=True)
                    with self.store.connect() as db:
                        db.execute('UPDATE jobs SET submission_diagnostic=? WHERE account_id=? AND date=?',
                                   (detail, ident, date))
                    level = logging.INFO if diagnostic.get('code') == 0 and diagnostic.get('ok') is not False else logging.WARNING
                    log.log(level, 'Account %s: submission_response %s', ident, detail)
                result = await run_checkin(ctx, date, job['submitted'], mark,
                    location_key=account['location_key'], on_location=remember_location,
                    submission_diagnostic=json.loads(job.get('submission_diagnostic') or 'null'),
                    on_submission=remember_submission,
                    **({"ticket_provider": lambda context: self.ticket(context, account)} if self.wechat else {}))
                stage = 'save_session'
                state = await ctx.storage_state()
                with self.store.connect() as db:
                    db.execute('UPDATE accounts SET session=? WHERE id=?', (self.store.cipher.encrypt(json.dumps(state).encode()), ident))
        except ServiceUnavailable:
            result = 'transport_error'
        except LoginError:
            result = 'need_login'
        except WeChatError as e:
            result = str(e)
        except SchoolError as e:
            result = str(e)
        except TimeoutError:
            result = 'checkin_timeout'
            log.warning('Account %s: checkin_timeout stage=%s', ident, stage)
        except Exception as error:
            result = 'runtime_error'
            # Log stack locations, never exception messages or credential data.
            frames = ' > '.join(f'{Path(f.filename).name}:{f.lineno}:{f.name}'
                                for f in traceback.extract_tb(error.__traceback__))
            log.warning('Account %s: runtime_error stage=%s type=%s frames=%s',
                        ident, stage, type(error).__name__, frames)
        finally:
            try:
                if ctx:
                    await ctx.close()
            except Exception:
                pass
            finally:
                self.busy.discard(ident)
        retry = result in RETRY and job['attempts'] < 11 and now().isoformat() < job['cutoff']
        with self.store.connect() as db:
            db.execute('UPDATE jobs SET status=?,message=?,due=?,checked=MAX(checked,?) WHERE account_id=? AND date=?',
                ('retry' if retry else result, result, (now()+timedelta(minutes=2)).isoformat() if retry else job['due'], result == 'success', ident, date))
            if result == 'need_login':
                db.execute("UPDATE accounts SET status='need_login' WHERE id=?", (ident,))
        log.log(logging.INFO if result in ('success', 'already_done') else logging.WARNING,
                'Account %s: %s', ident, result)

    async def probe(self, ident):
        ctx = None
        try:
            with self.store.connect() as db:
                account = db.execute('SELECT * FROM accounts WHERE id=?', (ident,)).fetchone()
            if not account:
                return
            async with asyncio.timeout(45):
                ctx = await self.sessions.new_context(storage_state=await self.session(account))
                detail = await authenticate(ctx)
                schedule = await request(ctx, '/checkin-schedule/effective')
                today = await request(ctx, '/student-checkin-record/today')
                with self.store.connect() as db:
                    db.execute('UPDATE accounts SET details=?,schedule=? WHERE id=?',
                        (json.dumps(detail), json.dumps({'date': now().date().isoformat(), 'response': schedule}), ident))
                    from .policy import today_state
                    if today_state(today, now().date().isoformat()) == 'done':
                        status = 'success' if today['data']['recordStatusCode'] == 'CHECKED_IN' else 'already_done'
                        db.execute('UPDATE jobs SET status=?,checked=1,message=? WHERE account_id=? AND date=?',
                                   (status, status, ident, now().date().isoformat()))
                self.reschedule(ident)
                state = await ctx.storage_state()
                with self.store.connect() as db:
                    db.execute('UPDATE accounts SET session=? WHERE id=?',
                               (self.store.cipher.encrypt(json.dumps(state).encode()), ident))
                rows = available_locations(await request(ctx, '/checkin-location/available-locations'))
                selected = choose_location(rows, account['location_key'])
                with self.store.connect() as db:
                    db.execute('UPDATE accounts SET location_name=? WHERE id=?', (location_option(selected)['name'], ident))
            log.debug('Account %s: session validated', ident)
        except ServiceUnavailable:
            log.debug('Account %s: school service unavailable', ident)
        except LoginError:
            with self.store.connect() as db:
                db.execute("UPDATE accounts SET status='need_login' WHERE id=?", (ident,))
        except SchoolError as e:
            if str(e) == 'need_login':
                with self.store.connect() as db:
                    db.execute("UPDATE accounts SET status='need_login' WHERE id=?", (ident,))
                log.warning('Account %s: sign-in required', ident)
        except Exception:
            log.debug('Account %s: session probe unavailable', ident)
        finally:
            try:
                if ctx:
                    await ctx.close()
            except Exception:
                pass
            finally:
                self.busy.discard(ident)

    async def loop(self):
        # One worker owns this scheduler; interrupted jobs reconcile the persisted journal.
        with self.store.connect() as db:
            db.execute("UPDATE jobs SET status='retry' WHERE status='running'")
        while True:
            try:
                current = now()
                self.plan(current)
                with self.store.connect() as db:
                    jobs = db.execute("SELECT jobs.* FROM jobs JOIN accounts ON accounts.id=account_id WHERE jobs.status IN ('scheduled','retry') AND accounts.status='ready' AND due<=? AND cutoff>=?", (current.isoformat(), current.isoformat())).fetchall()
                for job in jobs:
                    if job['account_id'] in self.busy or len(self.tasks) >= 3:
                        continue
                    self.busy.add(job['account_id'])
                    task = asyncio.create_task(self.execute(dict(job)))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                with self.store.connect() as db:
                    accounts = db.execute("SELECT * FROM accounts WHERE status='ready'").fetchall()
                for account in accounts:
                    ident = account['id']
                    if ident in self.busy or len(self.tasks) >= 3 or time.monotonic() - self.last_probe.get(ident, -600) < 600:
                        continue
                    self.busy.add(ident)
                    self.last_probe[ident] = time.monotonic()
                    task = asyncio.create_task(self.probe(ident))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
            except Exception:
                log.error('Scheduler cycle failed; retrying')
            await asyncio.sleep(10)
