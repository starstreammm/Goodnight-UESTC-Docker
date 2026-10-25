import asyncio
import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from goodnight import school
from goodnight.policy import ZONE
from tests.test_manual_checkin import setup


def scenario(monkeypatch, outcome, record_status='PENDING', verification_error=None):
    posts = []
    async def request(ctx, path, body=None):
        if path.endswith('/today'):
            if posts and verification_error:
                raise verification_error
            return {'code': 0, 'data': {'businessDate': '2026-10-23',
                    'recordStatusCode': record_status if posts else 'PENDING'}}
        if path.endswith('/effective'):
            return {'code': 0, 'data': {'studentCheckinStartOffsetMinute': 1260,
                                      'studentCheckinEndOffsetMinute': 1410}}
        if path.endswith('/available-locations'):
            return {'code': 0, 'data': [{'latitude': 30.7, 'longitude': 104.0, 'radiusMeter': 100}]}
        if path.endswith('/checkin'):
            posts.append(body)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return {'code': 0, 'data': 'Address'}
    monkeypatch.setattr(school, 'request', request)
    monkeypatch.setattr(school, 'authenticate', AsyncMock())
    monkeypatch.setattr(school, 'now', lambda: datetime(2026, 10, 23, 22, tzinfo=ZONE))
    monkeypatch.setattr(school.asyncio, 'sleep', AsyncMock())
    return SimpleNamespace(), posts


@pytest.mark.parametrize('outcome,expected', [
    ({'code': 46001, 'msg': 'secret upstream text'}, 'checkin_authorization_required'),
    ({'code': 46002}, 'checkin_authorization_required'),
    ({'code': 46003}, 'checkin_authorization_required'),
    ({'code': 4001, 'ok': False}, 'checkin_rejected'),
    ({'code': 4001, 'ok': True}, 'unconfirmed'),
    ({'code': 0}, 'unconfirmed'),
    (school.SchoolError('need_login', http_status=200, api_code=5000), 'need_login'),
    (school.SchoolError('need_login', http_status=403, api_code=46001), 'checkin_authorization_required'),
    (school.SchoolError('transport_error'), 'unconfirmed'),
    (ValueError('secret upstream text'), 'unconfirmed'),
])
def test_submission_outcome_is_preserved_without_reposting(monkeypatch, outcome, expected):
    ctx, posts = scenario(monkeypatch, outcome)
    diagnostics = []
    result = asyncio.run(school.run_checkin(ctx, '2026-10-23', False, lambda: True,
                                          on_submission=diagnostics.append))
    assert result == expected and len(posts) == 1
    assert len(diagnostics) == 1 and 'secret upstream text' not in json.dumps(diagnostics)
    # A subsequent manual check (or restart) must retain the diagnosis and never POST.
    result = asyncio.run(school.run_checkin(ctx, '2026-10-23', True,
                         lambda: pytest.fail('Must not submit twice'),
                         submission_diagnostic=diagnostics[0]))
    assert result == expected and len(posts) == 1


@pytest.mark.parametrize('outcome', [{'code': 46001}, {'code': 4001}, school.SchoolError('transport_error')])
def test_saved_success_takes_precedence_over_submission_error(monkeypatch, outcome):
    ctx, posts = scenario(monkeypatch, outcome, record_status='CHECKED_IN')
    assert asyncio.run(school.run_checkin(ctx, '2026-10-23', False, lambda: True)) == 'success'
    assert len(posts) == 1


@pytest.mark.parametrize('code', [4001, 46001])
def test_rejection_requires_fresh_pending_record(monkeypatch, code):
    ctx, _ = scenario(monkeypatch, {'code': code}, verification_error=school.SchoolError('transport_error'))
    assert asyncio.run(school.run_checkin(ctx, '2026-10-23', False, lambda: True)) == 'unconfirmed'


@pytest.mark.parametrize('status,body,reason,code', [
    (200, {'code': 46001}, None, 46001),
    (403, {'code': 46002}, 'need_login', 46002),
    (400, {'code': 46003}, 'http_error', 46003),
    (401, ValueError('secret body'), 'need_login', None),
    (200, ValueError('secret body'), 'invalid_api_response', None),
    (200, {'code': 5000}, 'need_login', 5000),
])
def test_request_preserves_http_and_api_codes(status, body, reason, code):
    response = SimpleNamespace(status=status, dispose=AsyncMock(), json=AsyncMock())
    if isinstance(body, Exception):
        response.json.side_effect = body
    else:
        response.json.return_value = body
    ctx = SimpleNamespace(request=SimpleNamespace(fetch=AsyncMock(return_value=response)))
    if reason:
        with pytest.raises(school.SchoolError, match=reason) as caught:
            asyncio.run(school.request(ctx, '/student-checkin-record/checkin', {}))
        assert caught.value.api_code == code and caught.value.http_status == status
    else:
        assert asyncio.run(school.request(ctx, '/student-checkin-record/checkin', {}))['code'] == code
    response.dispose.assert_awaited_once()


def test_scheduler_persists_diagnosis_and_keeps_it_after_restart(tmp_path, monkeypatch, caplog):
    store, runner = setup(tmp_path, monkeypatch)
    ctx, posts = scenario(monkeypatch, {'code': 46001, 'msg': 'secret upstream text'})
    ctx.storage_state = AsyncMock(return_value={})
    ctx.close = AsyncMock()
    runner.sessions.new_context.return_value = ctx
    runner.plan(datetime(2026, 10, 23, 22, tzinfo=ZONE))
    with store.connect() as db:
        job = dict(db.execute('SELECT * FROM jobs').fetchone())
    asyncio.run(runner.execute(job, manual=True))
    from goodnight.db import Store
    from goodnight.scheduler import Scheduler
    reopened = Store(tmp_path)
    with reopened.connect() as db:
        job = dict(db.execute('SELECT * FROM jobs').fetchone())
    assert job['submitted'] == 1 and job['status'] == 'checkin_authorization_required'
    assert json.loads(job['submission_diagnostic']) == {'code': 46001}
    assert '46001' in caplog.text and 'secret upstream text' not in caplog.text
    restarted = Scheduler(reopened, runner.sessions)
    asyncio.run(restarted.execute(job, manual=True))
    with reopened.connect() as db:
        assert db.execute('SELECT status FROM jobs').fetchone()[0] == 'checkin_authorization_required'
    assert len(posts) == 1
