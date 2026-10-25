import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from goodnight import main, scheduler, school
from goodnight.db import Store
from goodnight.policy import ZONE


def setup(tmp_path, monkeypatch):
    store = Store(tmp_path)
    store.save_session('student', 'Test', {'cookies': [], 'origins': []})
    ctx = SimpleNamespace(storage_state=AsyncMock(return_value={'cookies': [], 'origins': []}), close=AsyncMock())
    runner = scheduler.Scheduler(store, SimpleNamespace(new_context=AsyncMock(return_value=ctx)))
    monkeypatch.setattr(main.app.state, 'store', store, raising=False)
    monkeypatch.setattr(main.app.state, 'scheduler', runner, raising=False)
    current = datetime(2026, 10, 23, 23, 15, tzinfo=ZONE)  # After automatic cutoff.
    monkeypatch.setattr(main, 'now', lambda: current)
    monkeypatch.setattr(scheduler, 'now', lambda: current)
    return store, runner


def test_manual_run_excludes_concurrent_actions_and_preserves_journal(tmp_path, monkeypatch):
    store, runner = setup(tmp_path, monkeypatch)

    async def scenario():
        release = asyncio.Event()
        async def check(ctx, date, journal, mark, **kwargs):
            await release.wait()
            if journal:
                return 'unconfirmed'
            assert mark(), 'Manual action may run after automatic cutoff'
            assert not mark(), 'Only one submission may claim the journal'
            return 'unconfirmed'
        monkeypatch.setattr(scheduler, 'run_checkin', check)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            assert (await client.post('/api/accounts/1/check-in')).status_code == 202
            assert (await client.post('/api/accounts/1/check-in')).status_code == 409
            assert (await client.delete('/api/accounts/1')).status_code == 409
            state = (await client.get('/api/state')).json()
            assert state['busy_accounts'] == [1]
            release.set()
            await asyncio.gather(*list(runner.tasks))
            assert not runner.busy
            assert (await client.post('/api/accounts/1/check-in')).status_code == 202
            await asyncio.gather(*list(runner.tasks))
            state = (await client.get('/api/state')).json()
            assert state['jobs'][0]['status'] == 'unconfirmed'
            assert state['jobs'][0]['submitted'] == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('record,expected', [('CHECKED_IN', 'success'), ('EXEMPT', 'already_done')])
def test_manual_reads_existing_record_without_submission(tmp_path, monkeypatch, record, expected):
    _, runner = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(school, 'authenticate', AsyncMock())
    request = AsyncMock(return_value={'code': 0, 'data': {'businessDate': '2026-10-23', 'recordStatusCode': record}})
    monkeypatch.setattr(school, 'request', request)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            assert (await client.post('/api/accounts/1/check-in')).status_code == 202
            await asyncio.gather(*list(runner.tasks))
            job = (await client.get('/api/state')).json()['jobs'][0]
            assert job['status'] == expected and job['submitted'] == 0
            assert job['checked'] == (record == 'CHECKED_IN')
    asyncio.run(scenario())
    assert request.await_count == 1
    assert request.await_args.args[1] == '/student-checkin-record/today'


def test_runtime_diagnostic_does_not_log_secret(tmp_path, monkeypatch, caplog):
    _, runner = setup(tmp_path, monkeypatch)
    monkeypatch.setattr(scheduler, 'run_checkin', AsyncMock(side_effect=ValueError('secret-cookie-value')))
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            await client.post('/api/accounts/1/check-in')
            await asyncio.gather(*list(runner.tasks))
            assert (await client.get('/api/state')).json()['jobs'][0]['message'] == 'runtime_error'
    asyncio.run(scenario())
    assert 'type=ValueError' in caplog.text and 'stage=check_school_record_and_submit' in caplog.text
    assert 'frames=' in caplog.text and 'secret-cookie-value' not in caplog.text


def test_manual_api_rejects_missing_expired_and_cross_origin(tmp_path, monkeypatch):
    store, runner = setup(tmp_path, monkeypatch)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            assert (await client.post('/api/accounts/999/check-in')).status_code == 404
            assert (await client.post('/api/accounts/1/check-in', headers={'Origin': 'https://elsewhere.example'})).status_code == 403
            with store.connect() as db:
                db.execute("UPDATE accounts SET status='need_login'")
            assert (await client.post('/api/accounts/1/check-in')).status_code == 409
            assert not runner.tasks
    asyncio.run(scenario())


def test_scheduler_cutoff_preserves_running_manual_check_and_last_failure(tmp_path, monkeypatch):
    store, runner = setup(tmp_path, monkeypatch)
    current = datetime(2026, 10, 23, 23, 15, tzinfo=ZONE)
    runner.plan(current)
    with store.connect() as db:
        db.execute("UPDATE jobs SET status='running',message='Checking school record'")
    runner.plan(current)
    with store.connect() as db:
        row = db.execute('SELECT * FROM jobs').fetchone()
        assert row['status'] == 'running' and row['message'] == 'Checking school record'
        db.execute("UPDATE jobs SET status='retry',message='location_timeout'")
    runner.plan(current)
    with store.connect() as db:
        row = db.execute('SELECT * FROM jobs').fetchone()
        assert row['status'] == 'missed' and row['message'] == 'location_timeout'
        db.execute("UPDATE jobs SET message='Service was offline past the allowed window'")
    runner.plan(current)
    with store.connect() as db:
        assert db.execute('SELECT message FROM jobs').fetchone()[0] == 'automatic_window_missed'



def test_original_schedule_and_checked_state_survive_manual_checks_and_restart(tmp_path, monkeypatch):
    store, runner = setup(tmp_path, monkeypatch)
    current = datetime(2026, 10, 23, 21, tzinfo=ZONE)
    monkeypatch.setattr(main, 'now', lambda: current)
    monkeypatch.setattr(scheduler, 'now', lambda: current)
    runner.plan(current)
    with store.connect() as db:
        original = db.execute('SELECT scheduled_at FROM jobs').fetchone()[0]
    check = AsyncMock(side_effect=['window_not_open', 'success', 'transport_error'])
    monkeypatch.setattr(scheduler, 'run_checkin', check)

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url='http://test') as client:
            for expected_checked in (0, 1, 1):
                assert (await client.post('/api/accounts/1/check-in')).status_code == 202
                running = (await client.get('/api/state')).json()['jobs'][0]
                assert running['scheduled_at'] == original
                await asyncio.gather(*list(runner.tasks))
                job = (await client.get('/api/state')).json()['jobs'][0]
                assert job['scheduled_at'] == original and job['checked'] == expected_checked
            assert job['due'] != original, 'Retry timing must be independent of the displayed schedule'
    asyncio.run(scenario())
    reopened = Store(tmp_path)
    scheduler.Scheduler(reopened, None).plan(current)
    scheduler.Scheduler(reopened, None).plan(datetime(2026, 10, 24, 21, tzinfo=ZONE))
    with reopened.connect() as db:
        yesterday, today = db.execute('SELECT * FROM jobs ORDER BY date').fetchall()
        assert yesterday['scheduled_at'] == original and yesterday['checked'] == 1
        assert today['scheduled_at'] == today['due'] and today['checked'] == 0


def test_legacy_job_schedule_migration_is_idempotent(tmp_path):
    import sqlite3
    path = tmp_path / 'goodnight.sqlite3'
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE jobs (account_id INTEGER, date TEXT, due TEXT NOT NULL, cutoff TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'scheduled', submitted INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0, message TEXT, PRIMARY KEY(account_id,date));
            INSERT INTO jobs(account_id,date,due,cutoff,status,submitted)
                VALUES(1,'2026-10-23','2026-10-23T22:00:00+08:00','2026-10-23T23:10:30+08:00','success',1);
        ''')
    store = Store(tmp_path)
    with store.connect() as db:
        job = db.execute('SELECT * FROM jobs').fetchone()
        assert job['scheduled_at'] == job['due'] and job['checked'] == 1 and job['submitted'] == 1
        original = job['scheduled_at']
        db.execute("UPDATE jobs SET due='2026-10-23T22:02:00+08:00',status='retry'")
    with Store(tmp_path).connect() as db:
        job = db.execute('SELECT * FROM jobs').fetchone()
        assert job['scheduled_at'] == original and job['checked'] == 1
