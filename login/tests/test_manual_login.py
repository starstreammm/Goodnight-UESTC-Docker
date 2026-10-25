"""Exercise the interactive diagnostic with synthetic HTTP responses only."""
import asyncio
import importlib.util
import io
from pathlib import Path
from urllib.parse import parse_qs
import httpx
import pytest

spec = importlib.util.spec_from_file_location('manual_login', Path(__file__).parents[1] / 'manual_login.py')
manual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual)
FORM = '<form id="pwdFromId"><input type="hidden" id="pwdEncryptSalt" value="0123456789abcdef"><input type="hidden" name="execution" value="fixture-execution"></form>'


def test_browser_fingerprint_persists_across_runs(tmp_path):
    path = tmp_path / 'data' / 'fingerprint'
    first = manual.load_fingerprint(path)
    assert manual.valid_fingerprint(first)
    assert manual.load_fingerprint(path) == first
    assert path.read_text().strip() == first
    assert path.stat().st_mode & 0o777 == 0o600


def test_explicit_fingerprint_replaces_saved_identity(tmp_path):
    path = tmp_path / 'fingerprint'
    manual.load_fingerprint(path)
    supplied = 'aB' * 16
    assert manual.load_fingerprint(path, supplied) == supplied
    assert manual.load_fingerprint(path) == supplied


def test_invalid_saved_fingerprint_is_not_silently_replaced(tmp_path):
    path = tmp_path / 'fingerprint'
    path.write_text('invalid')
    with pytest.raises(ValueError, match='Invalid saved fingerprint'):
        manual.load_fingerprint(path)
    assert path.read_text() == 'invalid'
    assert manual.load_fingerprint(path, 'F' * 32) == 'F' * 32


@pytest.mark.parametrize('sms', [False, True])
def test_manual_raw_trace_complete_flow(sms):
    requests=[];prompts=[];output=io.StringIO()
    def server(request):
        requests.append(request)
        path=request.url.path
        if path.endswith('/bfp/info'):return httpx.Response(200)
        if path.endswith('/login') and request.method=='POST':
            form=parse_qs(request.content.decode())
            assert form['username']==['fixture-user']
            assert form['password']!=['private-plaintext-password']
            return httpx.Response(302,headers=[('location',manual.IDAS+('/reAuthCheck/reAuthLoginView.do?isMultifactor=true' if sms else '/index.do')),
                ('set-cookie','CASTGC=tgt-fixture; Path=/authserver'),('set-cookie','CASTGC=; Max-Age=0; Path=/authserver/')])
        if path.endswith('/reAuthLoginView.do'):return httpx.Response(200,text='SMS page')
        if path.endswith('/getDynamicCodeByReauth.do'):return httpx.Response(200,json={'res':'success'})
        if path.endswith('/reAuthSubmit.do'):
            assert parse_qs(request.content.decode())['dynamicCode']==['123456']
            return httpx.Response(200,json={'code':'reAuth_success'})
        if path.endswith('/login') and 'service' in request.url.params:
            assert 'CASTGC=tgt-fixture' in request.headers['cookie']
            return httpx.Response(302,headers={'location':manual.SERVICE+'?ticket=ST-fixture'})
        if path.endswith('/login'):return httpx.Response(200,text=FORM,headers={'set-cookie':'JSESSIONID=fixture; Path=/authserver'})
        if 'ticket' in request.url.params:return httpx.Response(302,headers={'location':'/','set-cookie':'SESSION=fixture-session; Path=/'})
        if path=='/':return httpx.Response(200,text='Portal')
        if path=='/api/isLoginFailure':
            assert request.method=='GET'
            assert request.headers['cookie']=='SESSION=fixture-session'
            assert request.url.params['_t'].isdigit()
            assert request.headers['Accept']=='application/json, text/plain, */*'
            return httpx.Response(200,json={'status':True,'code':200,'data':True,'message':'已登录','url':None})
        if path.endswith('/base-info'):
            assert request.headers['cookie']=='SESSION=fixture-session'
            return httpx.Response(200,json={'code':0,'data':{'realName':'Fixture'}})
        raise AssertionError(path)
    def ask(prompt):prompts.append(prompt);return ''
    values=iter(['private-plaintext-password','123456'])
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            await manual.ManualLogin(client,manual.Trace(output),ask=ask,secret=lambda _:next(values)).run('fixture-user','F'*32)
    asyncio.run(run())
    text=output.getvalue()
    assert len(requests)==(11 if sms else 8)
    assert [r.url.path for r in requests[-2:]]==['/api/isLoginFailure','/platform-app/api/h5/user/base-info']
    assert sum('Send this request?' in p for p in prompts)==len(requests)
    assert 'private-plaintext-password' not in text
    assert 'POST /authserver/login HTTP/1.1' in text
    assert 'set-cookie: CASTGC=tgt-fixture; Path=/authserver' in text
    assert 'set-cookie: CASTGC=; Max-Age=0; Path=/authserver/' in text
    assert 'SESSION=fixture-session' in text and 'PROFILE VALIDATION PASSED' in text
    assert ('dynamicCode=123456' in text)==sms


def test_quitting_before_request_sends_nothing():
    def server(request):raise AssertionError('Must not send a request after q')
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            tester=manual.ManualLogin(client,manual.Trace(io.StringIO()),ask=lambda _:'q')
            with pytest.raises(manual.Stopped):await tester.request('Stop test','GET',manual.LOGIN)
    asyncio.run(run())


def test_optional_probes_restore_original_cookie_jar():
    cookies=[];output=io.StringIO();choices=iter(['1','2','3',''])
    def server(request):
        cookies.append(request.headers['cookie'])
        if request.url.path.endswith('/user-info'):
            assert request.url.params['sessionId']=='original'
        return httpx.Response(200,json={'code':5000},headers={'set-cookie':'SESSION=replaced-by-api; Path=/'})
    def ask(prompt):return next(choices) if prompt.startswith('\nOptional probes:') else ''
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(server)) as client:
            client.cookies.set('SESSION','original',domain='jzsz.uestc.edu.cn',path='/')
            tester=manual.ManualLogin(client,manual.Trace(output),ask=ask)
            await tester.profile(list(client.cookies.jar))
    asyncio.run(run())
    assert cookies==['SESSION=original','SESSION=replaced-by-api']+['SESSION=original']*3
    assert 'PROFILE VALIDATION FAILED' in output.getvalue()


@pytest.mark.parametrize('sms', [False, True])
def test_production_requests_match_successful_manual_sequence(sms, monkeypatch):
    from uestc_login import client as production
    from uestc_login.http import HttpSessions, USER_AGENT
    # Fixed ciphertext lets us compare form fields and Content-Length directly.
    monkeypatch.setattr(manual, 'encrypt_password', lambda *args: 'encrypted+fixture/=')
    monkeypatch.setattr(production, 'encrypt_password', lambda *args: 'encrypted+fixture/=')
    traces = [[], []]
    reauth = manual.IDAS + '/reAuthCheck/reAuthLoginView.do?isMultifactor=true&service=https%3A%2F%2Fjzsz.uestc.edu.cn%2F'
    def transport(index):
        def server(request):
            traces[index].append((request.method, request.url.host, request.url.path,
                {k:v for k,v in request.url.params.items() if k!='_'},
                dict(request.headers), parse_qs(request.content.decode(), keep_blank_values=True)))
            path = request.url.path
            if path.endswith('/bfp/info'):
                return httpx.Response(200, headers={'set-cookie': 'MULTIFACTOR_BROWSER_FINGERPRINT='+'F'*32+'; Path=/'})
            if path.endswith('/login') and request.method=='POST':
                return httpx.Response(302, headers=[('location', reauth if sms else manual.IDAS+'/index.do'),
                    ('set-cookie', 'CASTGC=fixture; Path=/authserver'), ('set-cookie', 'CASTGC=; Max-Age=0; Path=/authserver/')])
            if path.endswith('/reAuthLoginView.do'): return httpx.Response(200, text='SMS')
            if path.endswith('/getDynamicCodeByReauth.do'): return httpx.Response(200, json={'res':'success'})
            if path.endswith('/reAuthSubmit.do'):
                assert parse_qs(request.content.decode())['service']==[manual.SERVICE]
                return httpx.Response(200, json={'code':'reAuth_success'})
            if path.endswith('/login') and 'service' in request.url.params:
                return httpx.Response(302, headers={'location':manual.SERVICE+'?ticket=ST-fixture'})
            if path.endswith('/login'):
                return httpx.Response(200, text=FORM, headers={'set-cookie':'JSESSIONID=fixture; Path=/authserver'})
            if 'ticket' in request.url.params:
                return httpx.Response(302, headers={'location':'/', 'set-cookie':'SESSION=fixture; Path=/'})
            if path=='/': return httpx.Response(200)
            if path=='/api/isLoginFailure':
                return httpx.Response(200, json={'status':True,'code':200,'data':True,'message':'已登录','url':None})
            if path.endswith('/base-info'):
                return httpx.Response(200, json={'code':0,'data':{'realName':'Fixture'}})
            raise AssertionError(f'Unexpected extra request: {request.url.path}')
        return httpx.MockTransport(server)
    async def run():
        values=iter(['password','123456'])
        async with httpx.AsyncClient(transport=transport(0), headers={'User-Agent':manual.DEFAULT_UA,'Accept':'*/*'}) as context:
            await manual.ManualLogin(context, manual.Trace(io.StringIO()), ask=lambda _: '', secret=lambda _:next(values)).run('fixture','F'*32)
        result=await production.sign_in(HttpSessions(transport=transport(1)), 'fixture','password',fingerprint='F'*32)
        if sms:
            try: await production.submit_sms(result,'123456')
            finally: await result.context.close()
    asyncio.run(run())
    assert manual.DEFAULT_UA==USER_AGENT
    # The interactive diagnostic also traces the portal's login-status endpoint.
    assert [r for r in traces[0] if r[2]!='/api/isLoginFailure']==traces[1]
