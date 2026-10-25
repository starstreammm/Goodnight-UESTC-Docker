import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from goodnight.wechat import WeChat, WeChatError, APP_ID, credentials
from goodnight.school import checkin_ticket, SchoolError
from goodnight import main
from tests.test_core import setup_api


def test_adapter_authenticates_privately_and_extracts_wx_code(tmp_path):
    async def scenario():
        wx=WeChat(tmp_path);calls=[]
        def handler(request):
            calls.append(request)
            path=request.url.path
            if path=='/accounts' and 'yyb_session=private' not in request.headers.get('cookie',''):
                return httpx.Response(401,json={'code':401})
            if path=='/login':
                assert json.loads(request.content)['password']==wx.credentials['password']
                return httpx.Response(200,json={'code':0,'data':{}},headers={'set-cookie':'yyb_session=private; Path=/; HttpOnly'})
            if path=='/accounts':
                return httpx.Response(200,json={'code':0,'data':[{'id':7,'credential_expires_at':123,'nickname':'Name'}]})
            assert path=='/wxapp/getCode'
            assert request.headers['Authorization']=='Bearer '+wx.credentials['token']
            assert json.loads(request.content)=={'ref':'7','app_id':APP_ID}
            return httpx.Response(200,json={'code':0,'data':{'result':{'code':'one-use-code','errMsg':'login:ok'}}})
        await wx.http.aclose();wx.http=httpx.AsyncClient(base_url='http://127.0.0.1:8001',transport=httpx.MockTransport(handler))
        assert (await wx.info(7))['credential_expires_at']==123
        assert await wx.code(7)=='one-use-code'
        assert len(calls)==4
        await wx.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('value',[{'code':''},{'code':'secret','errcode':1},'not-json',{'data':{'ret':-1,'code':'secret'}}])
def test_wx_code_fails_closed(tmp_path,monkeypatch,value):
    async def scenario():
        wx=WeChat(tmp_path)
        monkeypatch.setattr(wx,'request',AsyncMock(return_value={'result':value}))
        with pytest.raises(WeChatError):await wx.code(1)
        await wx.close()
    asyncio.run(scenario())


def test_ticket_exchange_uses_same_context_and_rejects_expired_ticket():
    response=SimpleNamespace(status=200,json=AsyncMock(return_value={'code':0,'data':{'ticket':'one-use-ticket','expiresAt':str(int((time.time()+60)*1000))}}),dispose=AsyncMock())
    ctx=SimpleNamespace(request=SimpleNamespace(post=AsyncMock(return_value=response)))
    assert asyncio.run(checkin_ticket(ctx,'one-use-code'))=='one-use-ticket'
    call=ctx.request.post.await_args
    assert call.kwargs['data']=={'code':'one-use-code'}
    assert call.kwargs['headers']['platform']=='mp-weixin'
    response.json.return_value['data']['expiresAt']='0'
    with pytest.raises(SchoolError,match='ticket_expired'):asyncio.run(checkin_ticket(ctx,'new-code'))


def test_complete_login_defaults_alias_and_does_not_expose_secrets(tmp_path,monkeypatch):
    client=setup_api(tmp_path)
    state={'cookies':[{'name':'SESSION','value':'session-secret'}],'origins':[]}
    monkeypatch.setattr(main.app.state.store.login,'login',AsyncMock(return_value=state))
    result=client.post('/api/accounts',json={'username':'fixture','password':'password-secret','save_password':True})
    ident=result.json()['login_id']
    assert result.json()['state']=='wechat'
    assert not client.get('/api/state').json()['accounts']
    assert client.get(f'/api/logins/{ident}/wechat').json()['state'] == 'review'
    assert client.post(f'/api/logins/{ident}/confirm', json={}).json()['ok']
    account=client.get('/api/state').json()['accounts'][0]
    assert account['alias']=='School Name' and account['save_password']
    assert 'password-secret' not in client.get('/api/state').text
    assert 'session-secret' not in client.get('/api/accounts/1/info').text
    assert client.delete('/api/accounts/1/password').status_code==200
    assert not main.app.state.store.login.metadata('fixture')['save_password']


def test_private_control_credentials_are_stable(tmp_path):
    first=credentials(tmp_path)
    assert first==credentials(tmp_path)
    assert (tmp_path/'wechat-control.json').stat().st_mode & 0o777==0o600


def test_qr_confirmation_pending_can_retry(tmp_path,monkeypatch):
    client=setup_api(tmp_path)
    monkeypatch.setattr(main.app.state.store.login,'login',AsyncMock(return_value={'cookies':[],'origins':[]}))
    main.app.state.wechat.confirm.side_effect=[WeChatError('wechat_pending'),{'id':10}]
    ident=client.post('/api/accounts',json={'username':'fixture','password':'secret'}).json()['login_id']
    assert client.get(f'/api/logins/{ident}/wechat').json()['state']=='review'
    assert client.post(f'/api/logins/{ident}/confirm', json={}).json()['detail']['code']=='wechat_pending'
    assert ident in main.app.state.pending_logins
    assert client.get(f'/api/logins/{ident}/wechat').json()['state'] == 'review'
    assert client.post(f'/api/logins/{ident}/confirm', json={}).json()['ok']


def test_run_checkin_forwards_fresh_ticket_and_complete_body(monkeypatch):
    from datetime import datetime
    from goodnight import school
    from goodnight.policy import ZONE
    posted=[];events=[]
    async def request(ctx,path,body=None,**kwargs):
        if path.endswith('/today'):
            return {'code':0,'data':{'businessDate':'2026-10-25','recordStatusCode':'CHECKED_IN' if posted else 'PENDING'}}
        if path.endswith('/effective'):
            return {'code':0,'data':{'studentCheckinStartOffsetMinute':1260,'studentCheckinEndOffsetMinute':1410}}
        if path.endswith('/available-locations'):
            return {'code':0,'data':[{'latitude':30.7,'longitude':104.0,'radiusMeter':100}]}
        if path.endswith('/checkin'):
            assert kwargs['headers']['X-Checkin-Ticket']=='fresh-ticket'
            assert body['coordinateSystemCode']=='gcj02'
            assert all(key in body for key in ('locationDurationMs','networkTypeCode','locationEnabled','locationAuthorized','locationAccuracy','errorMessage'))
            posted.append(body);events.append('post');return {'code':0,'data':{}}
        return {'code':0,'data':'School location'}
    async def ticket(ctx):events.append('ticket');return 'fresh-ticket'
    def mark():events.append('journal');return True
    monkeypatch.setattr(school,'request',request)
    monkeypatch.setattr(school,'authenticate',AsyncMock())
    monkeypatch.setattr(school,'now',lambda:datetime(2026,10,25,22,tzinfo=ZONE))
    monkeypatch.setattr(school.asyncio,'sleep',AsyncMock())
    ctx=SimpleNamespace()
    assert asyncio.run(school.run_checkin(ctx,'2026-10-25',False,mark,ticket_provider=ticket))=='success'
    assert events==['ticket','journal','post']


def test_fetched_school_window_replaces_fallback_and_allows_late_catchup(tmp_path,monkeypatch):
    from datetime import datetime
    from goodnight.db import Store
    from goodnight import scheduler
    from goodnight.policy import ZONE
    store=Store(tmp_path);store.save_session('u','Alias',{})
    runner=scheduler.Scheduler(store,None)
    date='2026-10-25'
    runner.plan(datetime(2026,10,25,12,tzinfo=ZONE))
    with store.connect() as db:
        db.execute('UPDATE accounts SET schedule=?',(json.dumps({'date':date,'response':{'code':0,'data':{'studentCheckinStartOffsetMinute':1080,'studentCheckinEndOffsetMinute':1200}}}),))
    current=datetime(2026,10,25,19,50,tzinfo=ZONE)
    monkeypatch.setattr(scheduler,'now',lambda:current)
    runner.reschedule(1)
    with store.connect() as db:
        job=db.execute('SELECT * FROM jobs').fetchone()
        assert job['status']=='scheduled'
        assert job['due']==current.isoformat()
        assert datetime.fromisoformat(job['cutoff']).strftime('%H:%M')=='19:55'
