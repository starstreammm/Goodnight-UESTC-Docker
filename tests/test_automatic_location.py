import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from goodnight import school
from goodnight.db import Store
from goodnight.policy import ZONE
from goodnight.scheduler import Scheduler

FIRST = {'locationName': 'First dorm', 'latitude': 30.7, 'longitude': 104.0, 'radiusMeter': 100}
SECOND = {**FIRST, 'locationName': 'Second dorm', 'latitude': 31.7}


def test_select_first_valid_location_in_school_order():
    invalid = [None, {}, {**FIRST, 'latitude': True}, {**FIRST, 'longitude': float('nan')}, {**FIRST, 'radiusMeter': 0}]
    rows = school.available_locations({'code': 0, 'data': invalid + [FIRST, SECOND]})
    assert rows == [FIRST, SECOND]
    assert school.choose_location(rows) == FIRST
    assert school.choose_location(list(reversed(rows))) == SECOND



@pytest.mark.parametrize('response,code', [
    ({'code': 0, 'data': []}, 'no_available_locations'),
    ({'code': 0, 'data': [{}]}, 'no_available_locations'),
    ({'code': 0, 'data': [{**FIRST, 'latitude': 91}]}, 'no_available_locations'),
    ({'code': 0, 'data': None}, 'locations_unavailable'),
    ({'code': 4001, 'data': [FIRST]}, 'locations_unavailable'),
])
def test_unusable_location_list_has_specific_error(response, code):
    with pytest.raises(school.SchoolError, match=code):
        school.available_locations(response)


@pytest.mark.parametrize('selected', [False, True])
@pytest.mark.parametrize('rows', [[FIRST, SECOND], [SECOND], []])
def test_checkin_selects_fresh_location_without_device_or_setup(monkeypatch, rows, selected):
    posts = []; paths = []
    async def request(ctx, path, body=None):
        paths.append(path)
        if path.endswith('/today'):
            return {'code': 0, 'data': {'businessDate': '2026-10-23', 'recordStatusCode': 'CHECKED_IN' if posts else 'PENDING'}}
        if path.endswith('/effective'):
            return {'code': 0, 'data': {'studentCheckinStartOffsetMinute': 1260, 'studentCheckinEndOffsetMinute': 1410}}
        if path.endswith('/available-locations'):
            return {'code': 0, 'data': rows}
        if path.endswith('/checkin'):
            posts.append(body)
        return {'code': 0, 'data': 'School address'}
    monkeypatch.setattr(school, 'request', request)
    monkeypatch.setattr(school, 'authenticate', AsyncMock())
    monkeypatch.setattr(school, 'now', lambda: datetime(2026, 10, 23, 22, tzinfo=ZONE))
    monkeypatch.setattr(school.asyncio, 'sleep', AsyncMock())
    ctx = SimpleNamespace()
    mark = []
    options = {'location_key': school.location_option(SECOND)['key']} if selected else {}
    if rows:
        result = asyncio.run(school.run_checkin(ctx, '2026-10-23', False, lambda: mark.append(True) or True, **options))
        assert result == 'success' and len(posts) == 1 and mark == [True]
        expected = SECOND if selected else rows[0]
        assert {k: posts[0][k] for k in ('latitude', 'longitude', 'accuracy')} == {'latitude': expected['latitude'], 'longitude': expected['longitude'], 'accuracy': 20}
        assert 'locationName' not in posts[0] and 'radiusMeter' not in posts[0]
    else:
        with pytest.raises(school.SchoolError, match='no_available_locations'):
            asyncio.run(school.run_checkin(ctx, '2026-10-23', False, lambda: mark.append(True) or True, **options))
        assert not posts and not mark
    assert paths.count('/checkin-location/available-locations') == 1


@pytest.mark.parametrize('legacy_location', [None, 'invalid legacy data'])
def test_scheduled_worker_needs_no_saved_location(tmp_path, monkeypatch, legacy_location):
    from goodnight import scheduler as scheduler_module
    store = Store(tmp_path)
    store.save_session('student', 'Alias', {'cookies': [], 'origins': []})
    with store.connect() as db:
        # Existing installations may retain an unused legacy column.
        db.execute('ALTER TABLE accounts ADD COLUMN location TEXT')
        db.execute('UPDATE accounts SET location=?', (legacy_location,))
    current = datetime(2026, 10, 23, 22, tzinfo=ZONE)
    monkeypatch.setattr(scheduler_module, 'now', lambda: current)
    ctx = SimpleNamespace(close=AsyncMock(), storage_state=AsyncMock(return_value={'cookies': [], 'origins': []}))
    runner = Scheduler(store, SimpleNamespace(new_context=AsyncMock(return_value=ctx)))
    runner.plan(current)
    with store.connect() as db:
        job = dict(db.execute('SELECT * FROM jobs').fetchone())
    check = AsyncMock(return_value='success')
    monkeypatch.setattr(scheduler_module, 'run_checkin', check)
    asyncio.run(runner.execute(job))
    assert check.await_args.kwargs['location_key'] is None
    assert callable(check.await_args.kwargs['on_location'])
    assert len(check.await_args.args) == 4


def test_removed_selection_never_silently_uses_a_different_location():
    with pytest.raises(school.SchoolError, match='selected_location_unavailable'):
        school.choose_location([FIRST], school.location_option(SECOND)['key'])
