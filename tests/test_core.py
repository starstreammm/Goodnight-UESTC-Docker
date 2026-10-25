import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from goodnight.db import Store
from goodnight.models import Config, Login
from goodnight.policy import bounds, choose_time, checkin_window, today_state, ZONE
from goodnight.scheduler import Scheduler
from goodnight import school
from goodnight.main import app
from uestc_login import Reauth


def response(data):
    return {'code':0,'data':data}


@pytest.mark.parametrize('window', ['23:00_21:00','21:00_21:00','9:00_23:00','24:00_23:00','21:60_23:00','21:00-23:00'])
def test_invalid_window(window):
    with pytest.raises(ValidationError):
        Config(checkin_time=window)


def test_random_bounds():
    low, high = bounds('2026-10-23','21:00_23:30')
    assert low.strftime('%H:%M:%S') == '21:19:30'
    assert high.strftime('%H:%M:%S') == '23:10:30'
    samples = [choose_time('2026-10-23','21:00_23:30') for _ in range(100)]
    assert all(low <= s <= high for s in samples)
    assert len(set(samples)) == 100


def test_persistence_and_delete(tmp_path):
    store=Store(tmp_path)
    state={'cookies':[{'name':'SESSION','value':'secret-cookie'}],'origins':[]}
    store.save_session('student','Alias',state)
    with store.connect() as db:
        row=db.execute('SELECT * FROM accounts').fetchone()
        assert b'secret-cookie' not in row['session']
        assert store.state(row)==state
        assert 'password' not in row.keys()
    scheduler=Scheduler(store,None)
    current=datetime(2026,10,23,20,tzinfo=ZONE)
    scheduler.plan(current)
    with store.connect() as db:
        first=dict(db.execute('SELECT * FROM jobs').fetchone())
    Scheduler(Store(tmp_path),None).plan(current+timedelta(minutes=30))
    with store.connect() as db:
        assert dict(db.execute('SELECT * FROM jobs').fetchone())==first
        db.execute('DELETE FROM accounts')
        assert not db.execute('SELECT * FROM jobs').fetchall()


def test_missed_and_config_stable(tmp_path):
    store=Store(tmp_path); store.save_session('u','a',{})
    scheduler=Scheduler(store,None)
    scheduler.plan(datetime(2026,10,23,20,tzinfo=ZONE))
    with store.connect() as db:
        original=db.execute('SELECT due FROM jobs').fetchone()[0]
        db.execute('UPDATE config SET value=?',(Config(checkin_time='20:00_21:00').model_dump_json(),))
    scheduler.plan(datetime(2026,10,23,20,30,tzinfo=ZONE))
    with store.connect() as db:
        assert db.execute('SELECT due FROM jobs').fetchone()[0]==original
    scheduler.plan(datetime(2026,10,23,23,59,tzinfo=ZONE))
    with store.connect() as db:
        assert db.execute('SELECT status FROM jobs').fetchone()[0]=='missed'


def test_school_policy():
    date='2026-10-23'
    schedule=response({'studentCheckinStartOffsetMinute':1260,'studentCheckinEndOffsetMinute':1410})
    assert checkin_window(schedule,date,datetime(2026,10,23,20,tzinfo=ZONE))=='window_not_open'
    assert checkin_window(schedule,date,datetime(2026,10,23,22,tzinfo=ZONE))=='open'
    assert checkin_window(schedule,date,datetime(2026,10,23,23,25,tzinfo=ZONE))=='window_missed'
    assert today_state(response({'businessDate':'2026-10-22','recordStatusCode':'CHECKED_IN'}),date)=='unknown'
    assert today_state(response({'businessDate':date,'recordStatusCode':'EXEMPT'}),date)=='done'


def test_journal_never_reposts(monkeypatch):
    requests=[]
    async def request(ctx,path,body=None):
        requests.append((path,body))
        return response({'businessDate':'2026-10-23','recordStatusCode':'PENDING'})
    monkeypatch.setattr(school,'authenticate',AsyncMock())
    monkeypatch.setattr(school,'request',request)
    result=asyncio.run(school.run_checkin(None,'2026-10-23',True,lambda:pytest.fail('must not submit')))
    assert result=='unconfirmed'
    assert requests==[('/student-checkin-record/today',None)]


def test_submit_requires_readback(monkeypatch):
    record_reads=0; posts=[]; marked=[]
    async def request(ctx,path,body=None):
        nonlocal record_reads
        if path.endswith('/today'):
            record_reads+=1
            return response({'businessDate':'2026-10-23','recordStatusCode':'PENDING'})
        if path.endswith('/effective'):
            return response({'studentCheckinStartOffsetMinute':1260,'studentCheckinEndOffsetMinute':1410})
        if path.endswith('/available-locations'):
            return response([{'latitude':30.7,'longitude':104.0,'radiusMeter':100}])
        if path.endswith('/checkin'):
            posts.append(body);return response({})
        return response('Address')
    monkeypatch.setattr(school,'request',request)
    monkeypatch.setattr(school,'authenticate',AsyncMock())
    monkeypatch.setattr(school,'now',lambda:datetime(2026,10,23,22,tzinfo=ZONE))
    monkeypatch.setattr(school.asyncio,'sleep',AsyncMock())
    ctx=SimpleNamespace()
    result=asyncio.run(school.run_checkin(ctx,'2026-10-23',False,lambda:marked.append(True) or True))
    assert result=='unconfirmed' and len(posts)==1 and marked==[True] and record_reads==5


def setup_api(tmp_path):
    app.state.store = Store(tmp_path)
    app.state.scheduler = SimpleNamespace(busy=set())
    def reply(data):
        return SimpleNamespace(status=200, json=AsyncMock(return_value={'code':0,'data':data}), dispose=AsyncMock())
    async def new_context(*, storage_state=None):
        async def fetch(url, **kwargs):
            if url.endswith('/effective'):
                return reply({'studentCheckinStartOffsetMinute':1260,'studentCheckinEndOffsetMinute':1410})
            if url.endswith('/available-locations'):
                return reply([{'id':1,'locationName':'School location','latitude':30.7,'longitude':104.0,'radiusMeter':100}])
            raise AssertionError(url)
        return SimpleNamespace(close=AsyncMock(), storage_state=AsyncMock(return_value=storage_state),
            request=SimpleNamespace(get=AsyncMock(return_value=reply({'realName':'School Name'})), fetch=fetch))
    app.state.sessions = SimpleNamespace(new_context=AsyncMock(side_effect=new_context))
    app.state.wechat = SimpleNamespace(start=AsyncMock(return_value={'session_id':'qr-test','image_base64':'data:image/jpeg;base64,test'}),
        poll=AsyncMock(return_value={'status':'authorized'}), confirm=AsyncMock(return_value={'id':10}),
        cancel=AsyncMock(), delete=AsyncMock(), info=AsyncMock(return_value={'credential_expires_at':123}))
    app.state.logins = set()
    app.state.pending_logins = {}
    app.state.login_lock = asyncio.Lock()
    return TestClient(app)


def test_api_token_free_and_secret_redaction(tmp_path):
    client = setup_api(tmp_path)
    assert client.get('/api/state').status_code == 200
    payload = {'username':'u','alias':'a','password':['do-not-echo-this-password']}
    result = client.post('/api/accounts', json=payload)
    assert result.status_code == 422 and 'do-not-echo' not in result.text
    result = client.put('/api/config', headers={'Origin':'https://evil.example'}, json=Config().model_dump())
    assert result.status_code == 403
    result = client.put('/api/config', json={'checkin_time':'23:00_01:00','log':'info'})
    assert result.status_code == 422
    assert client.get('/api/logins/old/screenshot').status_code == 404
    assert 'hunter2' not in repr(Login(username='u', alias='a', password='hunter2'))


def test_backend_login_saves_session(tmp_path, monkeypatch):
    from goodnight import main
    client = setup_api(tmp_path)
    session = {'cookies':[{'name':'SESSION','value':'school-cookie','domain':'jzsz.uestc.edu.cn'}], 'origins':[]}
    sign_in = AsyncMock(return_value=session)
    monkeypatch.setattr(app.state.store.login, 'login', sign_in)
    result = client.post('/api/accounts', json={'username':'student','alias':'Me','password':'ephemeral-password'})
    assert result.status_code == 201 and result.json()['state'] == 'wechat'
    assert not client.get('/api/state').json()['accounts']
    assert client.get(f"/api/logins/{result.json()['login_id']}/wechat").json()['state'] == 'review'
    assert client.post(f"/api/logins/{result.json()['login_id']}/confirm", json={}).json()['ok']
    assert not app.state.logins
    assert sign_in.await_args.args == (app.state.sessions, 'student', 'ephemeral-password')
    with app.state.store.connect() as db:
        account = db.execute('SELECT * FROM accounts').fetchone()
        assert app.state.store.state(account) == session
        assert 'password' not in account.keys()
    assert 'school-cookie' not in client.get('/api/state').text
    assert client.delete(f"/api/accounts/{account['id']}").status_code == 200
    assert not client.get('/api/state').json()['accounts']


@pytest.mark.parametrize('failure,expected', [
    ('challenge', 400), ('network', 502),
])
def test_failed_login_preserves_session_and_releases_account(tmp_path, monkeypatch, failure, expected):
    from goodnight import main
    from uestc_login.client import LoginError
    client = setup_api(tmp_path)
    old_session = {'cookies':[], 'origins':[]}
    app.state.store.save_session('student', 'Original', old_session)
    error = LoginError('The school requires SMS/MFA verification') if failure == 'challenge' else RuntimeError('secret-upstream-body')
    async def fail(*args, **kwargs):
        assert app.state.scheduler.busy
        raise error
    monkeypatch.setattr(app.state.store.login, 'login', fail)
    result = client.post('/api/accounts', json={'username':'student','alias':'New','password':'ephemeral-password'})
    assert result.status_code == expected
    assert 'ephemeral-password' not in result.text and 'secret-upstream-body' not in result.text
    assert not app.state.logins and not app.state.scheduler.busy
    with app.state.store.connect() as db:
        account = db.execute('SELECT * FROM accounts').fetchone()
        assert account['alias'] == 'Original'
        assert app.state.store.state(account) == old_session


def test_reauth_preserves_submission_journal(tmp_path):
    store=Store(tmp_path);store.save_session('u','a',{})
    Scheduler(store,None).plan(datetime(2026,10,23,20,tzinfo=ZONE))
    with store.connect() as db:
        db.execute("UPDATE jobs SET submitted=1,status='need_login'")
    store.save_session('u','new alias',{})
    with store.connect() as db:
        job=db.execute('SELECT * FROM jobs').fetchone()
        assert job['submitted']==1 and job['status']=='scheduled'


def test_password_mfa_signals_sms_fallback(tmp_path, monkeypatch):
    from goodnight import main
    from uestc_login.client import AdditionalVerification
    client = setup_api(tmp_path)
    monkeypatch.setattr(app.state.store.login, 'login', AsyncMock(side_effect=AdditionalVerification('Use SMS login')))
    result = client.post('/api/accounts', json={'username':'u','alias':'a','password':'secret'})
    assert result.status_code == 400
    assert result.json()['detail']['code'] == 'sms_required'
    assert not app.state.logins


def test_sms_retains_context_retries_and_saves_only_session(tmp_path, monkeypatch):
    from goodnight import main
    from uestc_login.client import InvalidCode
    client = setup_api(tmp_path)
    ctx = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(app.state.store.login, 'login', AsyncMock(return_value=Reauth(ctx, 'u')))
    result = client.post('/api/accounts', json={'username':'u','alias':'a','password':'secret'})
    assert result.status_code == 201
    ident = result.json()['login_id']
    assert 299 <= result.json()['expires_in'] <= 300 and app.state.logins == {'u'}
    ctx.close.assert_not_awaited()
    assert not client.get('/api/state').json()['accounts']
    assert client.post('/api/accounts', json={'username':'u','alias':'a','password':'secret'}).status_code == 409
    invalid_input = client.post(f'/api/logins/{ident}/code', json={'code':'do-not-echo'})
    assert invalid_input.status_code == 422 and 'do-not-echo' not in invalid_input.text
    session = {'cookies':[{'name':'SESSION','value':'private-session'}],'origins':[]}
    submit = AsyncMock(side_effect=[InvalidCode('Incorrect code'), session])
    monkeypatch.setattr(main, 'submit_sms', submit)
    invalid = client.post(f'/api/logins/{ident}/code', json={'code':'123456'})
    assert invalid.json()['detail']['code'] == 'invalid_code'
    assert ident in app.state.pending_logins
    assert client.post(f'/api/logins/{ident}/code', json={'code':'654321'}).json()['state'] == 'wechat'
    assert client.get(f'/api/logins/{ident}/wechat').json()['state'] == 'review'
    assert client.post(f'/api/logins/{ident}/confirm', json={}).json()['ok']
    assert submit.await_args.args[0].context == ctx
    assert submit.await_args.args[1] == '654321'
    ctx.close.assert_awaited_once()
    assert not app.state.logins and not app.state.pending_logins
    with app.state.store.connect() as db:
        account = db.execute('SELECT * FROM accounts').fetchone()
        assert app.state.store.state(account) == session
        assert 'password' not in account.keys() and 'code' not in account.keys()


@pytest.mark.parametrize('exit_path', ['cancel', 'expire', 'reap', 'attempt_limit', 'failure'])
def test_sms_cleanup(tmp_path, monkeypatch, exit_path):
    from goodnight import main
    from uestc_login.client import InvalidCode
    client = setup_api(tmp_path)
    app.state.store.save_session('u', 'Original', {})
    ctx = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(app.state.store.login, 'login', AsyncMock(return_value=Reauth(ctx, 'u')))
    ident = client.post('/api/accounts', json={'username':'u','alias':'New','password':'secret'}).json()['login_id']
    assert app.state.scheduler.busy
    assert client.delete('/api/accounts/1').status_code == 409
    if exit_path == 'cancel':
        assert client.delete(f'/api/logins/{ident}').status_code == 200
    elif exit_path in ('expire', 'reap'):
        app.state.pending_logins[ident].expires = 0
        if exit_path == 'reap':
            asyncio.run(main.expire_logins())
        else:
            assert client.post(f'/api/logins/{ident}/code', json={'code':'123456'}).status_code == 410
    else:
        if exit_path == 'attempt_limit':
            app.state.pending_logins[ident].attempts = 4
            error = InvalidCode('Incorrect code')
        else:
            error = RuntimeError('private-code-123456')
        monkeypatch.setattr(main, 'submit_sms', AsyncMock(side_effect=error))
        result = client.post(f'/api/logins/{ident}/code', json={'code':'123456'})
        assert result.status_code in (400,502) and '123456' not in result.text
    ctx.close.assert_awaited_once()
    assert not app.state.logins and not app.state.pending_logins and not app.state.scheduler.busy
    assert client.get('/api/state').json()['accounts'][0]['alias'] == 'Original'


def test_sms_start_failure_releases_reservation(tmp_path, monkeypatch):
    from goodnight import main
    from uestc_login.client import LoginError
    client = setup_api(tmp_path)
    monkeypatch.setattr(app.state.store.login, 'login', AsyncMock(side_effect=LoginError('CAPTCHA required')))
    result = client.post('/api/accounts', json={'username':'u','alias':'a','password':'secret'})
    assert result.status_code == 400 and 'CAPTCHA' in result.text
    assert not app.state.logins and not app.state.pending_logins


@pytest.mark.parametrize('points', [
    [{'x':0.1,'y':0.5,'t':0}],
    [{'x':0.1,'y':0.5,'t':1}, {'x':0.5,'y':0.5,'t':100}],
    [{'x':0.1,'y':0.5,'t':0}, {'x':0.5,'y':0.5,'t':20}],
    [{'x':0.1,'y':0.5,'t':0}, {'x':0.5,'y':0.5,'t':16000}],
    [{'x':0.1,'y':0.5,'t':0}, {'x':1.1,'y':0.5,'t':100}],
    [{'x':0.1,'y':0.5,'t':0}, {'x':float('nan'),'y':0.5,'t':100}],
    [{'x':0.1,'y':0.5,'t':0}, {'x':0.5,'y':0.5,'t':200}, {'x':0.6,'y':0.5,'t':100}],
    [{'x':0.1,'y':0.5,'t':i} for i in range(301)],
])
def test_captcha_rejects_unbounded_or_invalid_gestures(points):
    from goodnight.models import CaptchaGesture
    with pytest.raises(ValidationError):
        CaptchaGesture(ticket='fixture', points=points)


def test_rename_preserves_session_and_jobs(tmp_path):
    client = setup_api(tmp_path)
    store = app.state.store
    store.save_session('student', 'Original', {'cookies': [], 'origins': []})
    Scheduler(store, None).plan(datetime(2026, 10, 23, 20, tzinfo=ZONE))
    with store.connect() as db:
        db.execute("UPDATE jobs SET submitted=1,status='unconfirmed'")
        account_before = dict(db.execute('SELECT * FROM accounts').fetchone())
        job_before = dict(db.execute('SELECT * FROM jobs').fetchone())
    assert client.patch('/api/accounts/1', json={'alias': '  New name  '}).status_code == 200
    with store.connect() as db:
        assert dict(db.execute('SELECT * FROM accounts').fetchone()) == {**account_before, 'alias': 'New name'}
        assert dict(db.execute('SELECT * FROM jobs').fetchone()) == job_before
    for payload in ({'alias': '   '}, {'alias': 'a' * 81}, {'alias': 'Name', 'username': 'other'}):
        assert client.patch('/api/accounts/1', json=payload).status_code == 422
    assert client.patch('/api/accounts/999', json={'alias': 'Name'}).status_code == 404
    assert client.patch('/api/accounts/1', json={'alias': 'Name'}, headers={'Origin': 'https://evil.example'}).status_code == 403
    app.state.scheduler.busy.add(1)
    assert client.patch('/api/accounts/1', json={'alias': 'Name'}).status_code == 409
    assert client.get('/api/state').json()['accounts'][0]['alias'] == 'New name'


@pytest.mark.parametrize('status', ['ready', 'need_login'])
def test_relogin_updates_existing_account_without_losing_journal(tmp_path, monkeypatch, status):
    from goodnight import main
    client = setup_api(tmp_path)
    store = app.state.store
    store.save_session('student', 'Me', {})
    Scheduler(store, None).plan(datetime(2026, 10, 23, 20, tzinfo=ZONE))
    with store.connect() as db:
        db.execute('UPDATE accounts SET status=?', (status,))
        db.execute("UPDATE jobs SET submitted=1,status='need_login'")
    session = {'cookies': [], 'origins': []}
    async def sign_in(*args, **kwargs):
        assert 1 in app.state.scheduler.busy
        assert client.patch('/api/accounts/1', json={'alias': 'Concurrent rename'}).status_code == 409
        return session
    monkeypatch.setattr(app.state.store.login, 'login', sign_in)
    result = client.post('/api/accounts', json={'username': 'student', 'alias': 'Me', 'password': 'temporary'})
    assert result.status_code == 201
    assert client.get(f"/api/logins/{result.json()['login_id']}/wechat").json()['state'] == 'review'
    assert client.post(f"/api/logins/{result.json()['login_id']}/confirm", json={}).json()['ok']
    with store.connect() as db:
        accounts = db.execute('SELECT * FROM accounts').fetchall()
        assert len(accounts) == 1 and accounts[0]['id'] == 1
        assert accounts[0]['alias'] == 'Me' and accounts[0]['status'] == 'ready'
        assert store.state(accounts[0]) == session
        assert db.execute('SELECT submitted FROM jobs').fetchone()[0] == 1
    assert not app.state.scheduler.busy


def test_missing_password_is_distinct_from_failed_school_session(tmp_path, monkeypatch):
    from uestc_login.client import SessionEstablishmentError
    client = setup_api(tmp_path)
    missing = client.post('/api/accounts', json={'username':'student'})
    assert missing.status_code == 400 and missing.json()['detail']['code'] == 'password_missing'
    sign_in = AsyncMock(side_effect=SessionEstablishmentError('School session exchange did not complete.'))
    monkeypatch.setattr(app.state.store.login, 'login', sign_in)
    result = client.post('/api/accounts', json={'username':'student','password':'fixture-password'})
    assert sign_in.await_args.args[2] == 'fixture-password'
    assert result.status_code == 400 and result.json()['detail']['code'] == 'school_session_failed'
    assert 'fixture-password' not in result.text
