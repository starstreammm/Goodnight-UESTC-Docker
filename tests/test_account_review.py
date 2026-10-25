import json
from unittest.mock import AsyncMock

import httpx
import pytest

from goodnight import main
from goodnight.school import SchoolError
from tests.test_core import setup_api
from uestc_login.http import HttpSessions, USER_AGENT


def start_review(tmp_path, monkeypatch):
    client = setup_api(tmp_path)
    state = {'cookies': [{'name':'SESSION','value':'private-session'}], 'origins': []}
    monkeypatch.setattr(main.app.state.store.login, 'login', AsyncMock(return_value=state))
    ident = client.post('/api/accounts', json={'username':'fixture','password':'private-password','save_password':True}).json()['login_id']
    return client, ident


def test_review_requires_explicit_confirmation_and_saves_selected_location(tmp_path, monkeypatch):
    client, ident = start_review(tmp_path, monkeypatch)
    store = main.app.state.store
    assert client.post(f'/api/logins/{ident}/confirm', json={}).status_code == 409
    result = client.get(f'/api/logins/{ident}/wechat')
    assert result.status_code == 200 and result.json()['state'] == 'review'
    review = result.json()['review']
    assert review['alias'] == review['detail']['realName'] == 'School Name'
    assert review['schedule']['response']['data']['studentCheckinStartOffsetMinute'] == 1260
    location = review['locations'][0]
    assert location['radiusMeter'] == 100
    assert not client.get('/api/state').json()['accounts']
    assert not store.login.load('fixture').get('password')
    main.app.state.wechat.confirm.assert_not_awaited()
    assert 'private-session' not in result.text and 'private-password' not in result.text
    assert client.get(f'/api/logins/{ident}/wechat').json()['review'] == review
    main.app.state.wechat.poll.assert_awaited_once()
    assert client.post(f'/api/logins/{ident}/confirm', json={'key':'made-up'}).status_code == 409
    main.app.state.wechat.confirm.assert_not_awaited()
    assert client.post(f'/api/logins/{ident}/confirm', json={'key':location['key']}).json()['ok']
    assert store.login.load('fixture')['password'] == 'private-password'
    with store.connect() as db:
        account = db.execute('SELECT * FROM accounts').fetchone()
        assert account['location_key'] == location['key']
        assert account['location_name'] == location['name']
        assert json.loads(account['schedule']) == review['schedule']
    assert client.get('/api/accounts/1/info').json()['location_name'] == location['name']
    assert client.post(f'/api/logins/{ident}/confirm', json={}).status_code == 410
    main.app.state.wechat.confirm.assert_awaited_once()


@pytest.mark.parametrize('expired', [False, True])
def test_review_cancel_or_expiry_never_creates_account(tmp_path, monkeypatch, expired):
    client, ident = start_review(tmp_path, monkeypatch)
    assert client.get(f'/api/logins/{ident}/wechat').json()['state'] == 'review'
    if expired:
        main.app.state.pending_logins[ident].expires = 0
        assert client.post(f'/api/logins/{ident}/confirm', json={}).status_code == 410
    else:
        assert client.delete(f'/api/logins/{ident}').json()['ok']
    assert not client.get('/api/state').json()['accounts']
    assert not main.app.state.store.login.load('fixture').get('password')
    assert not main.app.state.logins and not main.app.state.pending_logins
    main.app.state.wechat.confirm.assert_not_awaited()
    main.app.state.wechat.cancel.assert_awaited_once()


def test_review_fetch_failure_can_retry_without_repeating_school_login(tmp_path, monkeypatch):
    client, ident = start_review(tmp_path, monkeypatch)
    original = main.school_request
    monkeypatch.setattr(main, 'school_request', AsyncMock(side_effect=SchoolError('transport_error')))
    response = client.get(f'/api/logins/{ident}/wechat')
    assert response.status_code == 502 and response.json()['detail']['code'] == 'review_unavailable'
    assert main.app.state.pending_logins[ident].review is None
    assert client.post(f'/api/logins/{ident}/confirm', json={}).status_code == 409
    monkeypatch.setattr(main, 'school_request', original)
    assert client.get(f'/api/logins/{ident}/wechat').json()['state'] == 'review'
    main.app.state.store.login.login.assert_awaited_once()
    client.delete(f'/api/logins/{ident}')


def test_http_login_through_web_api_sms_wechat_review_and_confirm(tmp_path):
    """Exercise the real login package through the app, with a synthetic school."""
    client = setup_api(tmp_path)
    paths = []
    def server(request):
        path = request.url.path
        paths.append(path)
        assert request.headers['user-agent'] == USER_AGENT
        if path.endswith('/bfp/info'):
            assert request.url.params['bfp'] == main.app.state.store.login.fingerprint('fixture')
            return httpx.Response(200)
        if path.endswith('/login') and request.method == 'POST':
            assert b'rememberMe=true' in request.content
            return httpx.Response(302, headers={'location':'/authserver/reAuthCheck/reAuthLoginView.do?isMultifactor=true',
                'set-cookie':'CASTGC=private-cas; Path=/authserver'})
        if path.endswith('/reAuthLoginView.do'): return httpx.Response(200)
        if path.endswith('/getDynamicCodeByReauth.do'): return httpx.Response(200, json={'res':'success'})
        if path.endswith('/reAuthSubmit.do'): return httpx.Response(200, json={'code':'reAuth_success'})
        if path.endswith('/login') and 'service' in request.url.params:
            return httpx.Response(302, headers={'location':'https://jzsz.uestc.edu.cn/?ticket=ST-private'})
        if path.endswith('/login'):
            return httpx.Response(200, text='<form id="pwdFromId"><input id="pwdEncryptSalt" value="0123456789abcdef"><input type="hidden" name="execution" value="fresh"></form>')
        if 'ticket' in request.url.params:
            return httpx.Response(302, headers={'location':'/', 'set-cookie':'SESSION=private-session; Path=/'})
        if path == '/': return httpx.Response(200)
        assert request.headers['cookie'] == 'SESSION=private-session'
        if path.endswith('/base-info'):
            return httpx.Response(200, json={'code':0,'data':{'realName':'Fixture Name'}})
        if path.endswith('/effective'):
            return httpx.Response(200, json={'code':0,'data':{'studentCheckinStartOffsetMinute':1200,'studentCheckinEndOffsetMinute':1400}})
        if path.endswith('/available-locations'):
            return httpx.Response(200, json={'code':0,'data':[{'name':'Campus','latitude':30.7,'longitude':104.0,'radiusMeter':200}]})
        raise AssertionError(path)
    main.app.state.sessions = HttpSessions(transport=httpx.MockTransport(server))
    start = client.post('/api/accounts', json={'username':'fixture','password':'private-password'})
    assert start.status_code == 201 and start.json()['state'] == 'sms'
    ident = start.json()['login_id']
    assert client.post(f'/api/logins/{ident}/code', json={'code':'123456'}).json()['state'] == 'wechat'
    result = client.get(f'/api/logins/{ident}/wechat')
    assert result.json()['state'] == 'review'
    assert result.json()['review']['detail']['realName'] == 'Fixture Name'
    assert not client.get('/api/state').json()['accounts']
    assert client.post(f'/api/logins/{ident}/confirm', json={}).json()['ok']
    assert client.get('/api/state').json()['accounts'][0]['location_name'] == 'Campus'
    assert '/authserver/checkNeedCaptcha.htl' not in paths
    assert '/authserver/index.do' not in paths
