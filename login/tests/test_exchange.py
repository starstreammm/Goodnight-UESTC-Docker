"""The final CAS service exchange must precede a usable jzsz session."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from uestc_login import client

TICKET_URL = client.JZSZ + '?ticket=ST-fixture-only'
COOKIE = {'name':'SESSION','value':'fixture-session','domain':'jzsz.uestc.edu.cn','path':'/'}


def response(status, location=None):
    return SimpleNamespace(status=status, headers={'location':location} if location else {}, dispose=AsyncMock())


def context(responses, cookies=None):
    return SimpleNamespace(request=SimpleNamespace(get=AsyncMock(side_effect=responses)),
        cookies=AsyncMock(return_value=[COOKIE] if cookies is None else cookies),
        storage_state=AsyncMock(return_value={'cookies':[COOKIE],'origins':[]}))


def test_service_ticket_session_chain(monkeypatch):
    replies=[response(302,TICKET_URL),response(302,'/'),response(200)]
    ctx=context(replies)
    validation=AsyncMock(return_value={'realName':'Fixture'})
    monkeypatch.setattr(client,'validate',validation)
    result=asyncio.run(client.exchange(ctx))
    assert result['cookies'][0]['value']=='fixture-session'
    assert [c.args[0] for c in ctx.request.get.await_args_list]==[
        'https://idas.uestc.edu.cn/authserver/login?service=https%3A%2F%2Fjzsz.uestc.edu.cn%2F',
        TICKET_URL,client.JZSZ]
    assert all(c.kwargs['max_redirects']==0 for c in ctx.request.get.await_args_list)
    assert ctx.request.get.await_args_list[0].kwargs['headers']=={'Cache-Control':'no-cache'}
    assert all(c.kwargs['headers'] is None for c in ctx.request.get.await_args_list[1:])
    for reply in replies:reply.dispose.assert_awaited_once()
    validation.assert_awaited_once_with(ctx)


@pytest.mark.parametrize('reply,error', [
    (response(304),client.ServiceUnavailable),
    (response(304,TICKET_URL),client.ServiceUnavailable),
    (response(200),client.PasswordRequired),
    (response(503),client.ServiceUnavailable),
    (response(302,client.LOGIN_URL),client.PasswordRequired),
    (response(302,client.IDAS+'/reAuthCheck/reAuthLoginView.do?isMultifactor=true'),client.AdditionalVerification),
    (response(302,'https://untrusted.example/?ticket=ST-fixture'),client.LoginError),
    (response(302,'http://jzsz.uestc.edu.cn/?ticket=ST-fixture'),client.LoginError),
    (response(302,client.JZSZ),client.LoginError),
    (response(302,client.JZSZ+'?ticket=one&ticket=two'),client.LoginError),
])
def test_invalid_handoff_does_not_contact_redirect_or_save(reply,error):
    ctx=context([reply])
    with pytest.raises(error):asyncio.run(client.exchange(ctx))
    assert ctx.request.get.await_count==1
    ctx.storage_state.assert_not_awaited()


def test_missing_service_cookie_is_not_success(monkeypatch):
    ctx=context([response(302,TICKET_URL),response(200)],cookies=[])
    validation=AsyncMock();monkeypatch.setattr(client,'validate',validation)
    with pytest.raises(client.LoginError,match='SESSION'):asyncio.run(client.exchange(ctx))
    validation.assert_not_awaited();ctx.storage_state.assert_not_awaited()


def test_redirect_loop_is_bounded():
    ctx=context([response(302,TICKET_URL)]*10)
    with pytest.raises(client.ServiceUnavailable,match='redirect limit'):asyncio.run(client.exchange(ctx))
    assert ctx.request.get.await_count==10
    ctx.storage_state.assert_not_awaited()
