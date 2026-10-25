import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from uestc_login import LoginManager, PasswordRequired
from uestc_login import store, client

STATE = {'cookies': [{'name': 'SESSION', 'value': 'private-session', 'domain': 'jzsz.uestc.edu.cn', 'path': '/'}], 'origins': []}


def test_password_login_reuses_fingerprint_but_starts_with_fresh_cookies(tmp_path, monkeypatch):
    manager = LoginManager(tmp_path)
    fingerprint = manager.fingerprint('student')
    manager.save('student', {'cookies': [*STATE['cookies'],
        {'name': 'MULTIFACTOR_USERS', 'value': 'old-trust', 'domain': 'idas.uestc.edu.cn', 'path': '/'}]})
    login = AsyncMock(return_value=STATE)
    monkeypatch.setattr(store, 'sign_in', login)
    asyncio.run(manager.login(None, 'student', 'password'))
    asyncio.run(LoginManager(tmp_path).login(None, 'student', 'password'))
    for call in login.await_args_list:
        assert call.kwargs == {'fingerprint': fingerprint}


def test_password_opt_in_encryption_stable_fingerprint_and_revocation(tmp_path):
    manager = LoginManager(tmp_path)
    fingerprint = manager.fingerprint('student')
    assert len(fingerprint) == 32 and fingerprint == LoginManager(tmp_path).fingerprint('student')
    manager.save('student', STATE, 'private-password', False)
    assert manager.load('student')['password'] is None
    manager.save('student', STATE, 'private-password', True)
    encrypted = manager.path('student').read_bytes()
    assert b'private-password' not in encrypted and b'private-session' not in encrypted
    assert manager.path('student').stat().st_mode & 0o777 == 0o600
    assert manager.load('student')['password'] == 'private-password'
    manager.forget_password('student')
    assert manager.metadata('student')['save_password'] is False
    manager.delete('student')
    assert manager.load('student') == {}


def test_seven_day_limit_cannot_be_extended_by_valid_long_lived_cookie(tmp_path, monkeypatch):
    manager = LoginManager(tmp_path)
    monkeypatch.setattr(store.time, 'time', lambda: 1000)
    manager.save('u', STATE)
    original = manager.load('u')['expires_at']
    ctx = SimpleNamespace(storage_state=AsyncMock(return_value=STATE), close=AsyncMock())
    sessions = SimpleNamespace(new_context=AsyncMock(return_value=ctx))
    valid = AsyncMock(return_value={'realName':'Example'})
    monkeypatch.setattr(store, 'validate', valid)
    monkeypatch.setattr(store.time, 'time', lambda: original - 1)
    assert asyncio.run(manager.session(sessions, 'u', STATE)) == STATE
    assert manager.load('u')['expires_at'] == original
    monkeypatch.setattr(store.time, 'time', lambda: original)
    with pytest.raises(PasswordRequired):
        asyncio.run(manager.session(sessions, 'u', STATE))
    assert sessions.new_context.await_count == 1


def test_cas_renewal_preserves_lease(tmp_path, monkeypatch):
    manager = LoginManager(tmp_path); manager.save('u', STATE)
    expiry = manager.metadata('u')['uestc_expires_at']
    ctx = SimpleNamespace(close=AsyncMock())
    sessions = SimpleNamespace(new_context=AsyncMock(return_value=ctx))
    monkeypatch.setattr(store, 'validate', AsyncMock(side_effect=PasswordRequired()))
    exchange = AsyncMock(return_value=STATE)
    monkeypatch.setattr(store, 'exchange', exchange)
    assert asyncio.run(manager.session(sessions, 'u')) == STATE
    assert exchange.await_count == 1 and ctx.close.await_count == 2
    assert manager.metadata('u')['uestc_expires_at'] == expiry


def test_saved_password_renews_expired_lease_but_never_sends_background_sms(tmp_path, monkeypatch):
    manager = LoginManager(tmp_path); manager.save('u', STATE, 'secret', True)
    data=manager.load('u');data['expires_at']=0;manager.write('u',data)
    login=AsyncMock(return_value=STATE);monkeypatch.setattr(manager,'login',login)
    assert asyncio.run(manager.session(None, 'u')) == STATE
    assert login.await_args.kwargs == {'interactive': False}
    assert manager.metadata('u')['uestc_expires_at'] > 0


def test_outage_does_not_submit_credentials_or_replace_session(tmp_path, monkeypatch):
    manager=LoginManager(tmp_path);manager.save('u',STATE,'secret',True)
    old=manager.load('u')
    ctx=SimpleNamespace(close=AsyncMock())
    sessions=SimpleNamespace(new_context=AsyncMock(return_value=ctx))
    monkeypatch.setattr(store,'validate',AsyncMock(side_effect=client.ServiceUnavailable()))
    login=AsyncMock();monkeypatch.setattr(manager,'login',login)
    with pytest.raises(client.ServiceUnavailable):asyncio.run(manager.session(sessions,'u'))
    login.assert_not_awaited();assert manager.load('u')==old


def test_sms_contract_and_service_exchange(monkeypatch):
    response=SimpleNamespace(status=200,json=AsyncMock(return_value={'code':'reAuth_success'}),dispose=AsyncMock())
    ctx=SimpleNamespace(request=SimpleNamespace(post=AsyncMock(return_value=response)))
    reauth=client.Reauth(ctx,'fixture-student')
    exchange=AsyncMock(return_value=STATE);monkeypatch.setattr(client,'exchange',exchange)
    assert asyncio.run(client.submit_sms(reauth,'123456'))==STATE
    call=ctx.request.post.await_args
    assert call.args[0].endswith('/reAuthCheck/reAuthSubmit.do')
    assert call.kwargs['form']['skipTmpReAuth']=='true'
    assert call.kwargs['form']['dynamicCode']=='123456'
    assert call.kwargs['form']['reAuthType']=='3'
    response.json.return_value={'code':'invalid'}
    with pytest.raises(client.InvalidCode):asyncio.run(client.submit_sms(reauth,'bad'))
    assert exchange.await_count==1


@pytest.mark.parametrize('status,payload,error',[(302,{},PasswordRequired),(200,{'code':5000},PasswordRequired),(503,{},client.ServiceUnavailable),(200,[],client.ServiceUnavailable)])
def test_validate_distinguishes_outage_and_expiry(status,payload,error):
    response=SimpleNamespace(status=status,json=AsyncMock(return_value=payload),dispose=AsyncMock())
    ctx=SimpleNamespace(request=SimpleNamespace(get=AsyncMock(return_value=response)))
    with pytest.raises(error):asyncio.run(client.validate(ctx))
    response.dispose.assert_awaited_once()


def test_service_skill_returns_only_session_string(tmp_path,monkeypatch):
    from uestc_login.skill.jzsz import session
    manager=LoginManager(tmp_path)
    monkeypatch.setattr(manager,'session',AsyncMock(return_value=STATE))
    assert asyncio.run(session(manager,None,'u'))=='private-session'
