import json
from datetime import datetime, timedelta

import pytest

from goodnight import main, scheduler
from goodnight.db import Store
from goodnight.main import app
from goodnight.policy import ZONE
from goodnight.scheduler import Scheduler
from tests.test_core import setup_api


CURRENT = datetime(2026, 10, 25, 20, tzinfo=ZONE)


def save_school(store, start=1260, end=1410, date='2026-10-25'):
    response = {'code': 0, 'data': {
        'studentCheckinStartOffsetMinute': start, 'studentCheckinEndOffsetMinute': end}}
    with store.connect() as db:
        db.execute('UPDATE accounts SET schedule=? WHERE id=1', (json.dumps({'date': date, 'response': response}),))


@pytest.fixture
def client(tmp_path, monkeypatch):
    client = setup_api(tmp_path)
    app.state.store.save_session('student', 'Me', {})
    app.state.scheduler = Scheduler(app.state.store, None)
    monkeypatch.setattr(main, 'now', lambda: CURRENT)
    monkeypatch.setattr(scheduler, 'now', lambda: CURRENT)
    save_school(app.state.store)
    app.state.scheduler.plan(CURRENT)
    return client


def job():
    with app.state.store.connect() as db:
        return dict(db.execute('SELECT * FROM jobs WHERE account_id=1').fetchone())


def test_save_range_reschedules_and_survives_restart(client):
    assert client.patch('/api/accounts/1', json={'alias': 'Me', 'checkin_time': '21:00_22:00'}).status_code == 200
    account = client.get('/api/state').json()['accounts'][0]
    assert account['checkin_time'] == '21:00_22:00'
    assert account['school_window'] == '21:00_23:25'
    saved = job()
    assert '2026-10-25T21:00' <= saved['scheduled_at'] < '2026-10-25T22:00'
    assert saved['cutoff'] == '2026-10-25T22:00:00+08:00'
    store = Store(app.state.store.directory)
    Scheduler(store, None).plan(CURRENT + timedelta(minutes=1))
    assert job() == saved
    save_school(store, date='2026-10-26')
    Scheduler(store, None).plan(CURRENT + timedelta(days=1))
    with store.connect() as db:
        next_job = db.execute("SELECT * FROM jobs WHERE date='2026-10-26'").fetchone()
        assert '2026-10-26T21:00' <= next_job['due'] < '2026-10-26T22:00'
    assert client.patch('/api/accounts/1', json={'alias': 'Renamed'}).status_code == 200
    assert client.get('/api/state').json()['accounts'][0]['checkin_time'] == '21:00_22:00'


@pytest.mark.parametrize('window', ['20:59_22:00', '21:00_23:26', '22:00_21:00', '21:00_21:00', 'bad'])
def test_invalid_range_is_atomic(client, window):
    original = job()
    assert client.patch('/api/accounts/1', json={'alias': 'Changed', 'checkin_time': window}).status_code == 422
    account = client.get('/api/state').json()['accounts'][0]
    assert account['alias'] == 'Me' and account['checkin_time'] is None
    assert job() == original


def test_missing_school_hours_do_not_allow_range_changes(client):
    save_school(app.state.store, date='2026-10-24')
    assert client.get('/api/state').json()['accounts'][0]['school_window'] is None
    assert client.patch('/api/accounts/1', json={'alias': 'Me', 'checkin_time': '21:00_22:00'}).status_code == 409
    assert client.patch('/api/accounts/1', json={'alias': 'Renamed'}).status_code == 200


@pytest.mark.parametrize('status,submitted', [('scheduled', 1), ('retry', 1), ('success', 1), ('already_done', 0), ('running', 0)])
def test_range_change_preserves_submitted_and_completed_jobs(client, status, submitted):
    with app.state.store.connect() as db:
        db.execute('UPDATE jobs SET status=?,submitted=?', (status, submitted))
    original = job()
    assert client.patch('/api/accounts/1', json={'alias': 'Me', 'checkin_time': '21:00_22:00'}).status_code == 200
    assert job() == original


def test_changed_school_hours_intersect_preference_and_skip_disjoint_window(client):
    client.patch('/api/accounts/1', json={'alias': 'Me', 'checkin_time': '21:00_22:00'})
    save_school(app.state.store, start=1290)
    app.state.scheduler.reschedule(1)
    assert '2026-10-25T21:30' <= job()['due'] < '2026-10-25T22:00'
    save_school(app.state.store, start=1350)
    app.state.scheduler.reschedule(1)
    assert job()['status'] == 'missed' and job()['message'] == 'random_window_unavailable'
    save_school(app.state.store)
    app.state.scheduler.reschedule(1)
    assert job()['status'] == 'scheduled'
    assert '2026-10-25T21:00' <= job()['due'] < '2026-10-25T22:00'


def test_late_edits_do_not_schedule_outside_preference(client, monkeypatch):
    monkeypatch.setattr(scheduler, 'now', lambda: CURRENT.replace(hour=22, minute=30))
    client.patch('/api/accounts/1', json={'alias': 'Me', 'checkin_time': '21:00_22:00'})
    assert job()['status'] == 'missed'
    assert '2026-10-25T21:00' <= job()['scheduled_at'] < '2026-10-25T22:00'


def test_independent_accounts_and_daily_disjoint_window(client):
    app.state.store.save_session('other', 'Other', {})
    client.patch('/api/accounts/1', json={'alias': 'Me', 'checkin_time': '21:00_22:00'})
    save_school(app.state.store, start=1350, date='2026-10-26')
    app.state.scheduler.plan(CURRENT + timedelta(days=1))
    with app.state.store.connect() as db:
        first = db.execute("SELECT * FROM jobs WHERE account_id=1 AND date='2026-10-26'").fetchone()
        second = db.execute("SELECT * FROM jobs WHERE account_id=2 AND date='2026-10-26'").fetchone()
    assert first['status'] == 'missed' and first['message'] == 'random_window_unavailable'
    assert second['status'] == 'scheduled'
