import asyncio
import base64
from urllib.parse import parse_qs
import httpx
import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from uestc_login.client import sign_in, submit_sms, Reauth, LoginError, ServiceUnavailable, AdditionalVerification, SERVICE_LOGIN_URL
from uestc_login.http import HttpSessions, HttpSession

FORM = '''<form id="phoneFromId"><input type="hidden" name="execution" value="wrong"></form>
<form id="pwdFromId" action="/authserver/login"><input type="hidden" id="pwdEncryptSalt" value="0123456789abcdef">
<input type="hidden" name="execution" value="fresh-execution"><input type="hidden" name="lt" value="">
<input type="hidden" name="cllt" value="userNameLogin"></form>'''


def decrypt(ciphertext, key=b'0123456789abcdef'):
    cipher = Cipher(algorithms.AES(key), modes.CBC(bytes(16))).decryptor()
    padded = cipher.update(base64.b64decode(ciphertext)) + cipher.finalize()
    unpad = padding.PKCS7(128).unpadder()
    return (unpad.update(padded)+unpad.finalize())[64:].decode()


@pytest.mark.parametrize('sms', [False, True])
def test_full_http_login_cookie_paths_sms_and_cas(sms):
    seen = []
    def server(request):
        path = request.url.path
        seen.append((request.method,path))
        if path == '/authserver/login' and request.method == 'GET' and 'service' not in request.url.params:
            return httpx.Response(200,text=FORM,headers={'set-cookie':'JSESSIONID=fixture; Path=/authserver; HttpOnly'})
        if path.endswith('/bfp/info'):
            assert request.url.params['bfp']=='F'*32
            assert 'JSESSIONID=fixture' in request.headers['cookie']
            return httpx.Response(200,headers={'set-cookie':'MULTIFACTOR_BROWSER_FINGERPRINT='+ 'F'*32+'; Path=/'})
        if path.endswith('/checkNeedCaptcha.htl'):
            return httpx.Response(200,json={'isNeed':False})
        if path == '/authserver/login' and request.method == 'POST':
            body=parse_qs(request.content.decode(),keep_blank_values=True)
            assert body['execution']==['fresh-execution'] and body['username']==['fixture-user']
            assert decrypt(body['password'][0])=='fixture-密码+&'
            assert 'passwordText' not in body
            target='/authserver/reAuthCheck/reAuthLoginView.do?isMultifactor=true' if sms else '/authserver/index.do'
            return httpx.Response(302,headers=[('location',target),('set-cookie','CASTGC=tgt-fixture; Path=/authserver'),('set-cookie','CASTGC=; Max-Age=0; Path=/authserver/')])
        if path == '/authserver/index.do':
            raise AssertionError('Do not enter the unrelated campus portal after password success')
        if path.endswith('/reAuthLoginView.do'):
            assert 'CASTGC=tgt-fixture' in request.headers['cookie']
            return httpx.Response(200,text='SMS')
        if path.endswith('/getDynamicCodeByReauth.do'):
            return httpx.Response(200,json={'res':'success'})
        if path.endswith('/reAuthSubmit.do'):
            assert parse_qs(request.content.decode())['dynamicCode']==['123456']
            return httpx.Response(200,json={'code':'reAuth_success'})
        if path == '/authserver/login' and 'service' in request.url.params:
            assert str(request.url)==SERVICE_LOGIN_URL
            assert 'CASTGC=tgt-fixture' in request.headers['cookie']
            return httpx.Response(302,headers={'location':'https://jzsz.uestc.edu.cn/?ticket=ST-fixture'})
        if path == '/' and 'ticket' in request.url.params:
            assert 'cookie' not in request.headers
            return httpx.Response(302,headers={'location':'/','set-cookie':'SESSION=fixture-session; Path=/; HttpOnly'})
        if path == '/':return httpx.Response(200)
        if path.endswith('/base-info'):
            assert request.headers['cookie']=='SESSION=fixture-session'
            return httpx.Response(200,json={'code':0,'data':{'realName':'Fixture'}})
        raise AssertionError(path)
    async def run():
        sessions=HttpSessions(transport=httpx.MockTransport(server))
        result=await sign_in(sessions,'fixture-user','fixture-密码+&',fingerprint='F'*32)
        if sms:
            assert isinstance(result,Reauth)
            try:state=await submit_sms(result,'123456')
            finally:await result.context.close()
        else:state=result
        assert any(c['name']=='SESSION' and c['value']=='fixture-session' for c in state['cookies'])
        restored=await sessions.new_context(storage_state=state)
        try:
            await restored.get('https://jzsz.uestc.edu.cn/platform-app/api/h5/user/base-info')
            assert len([c for c in await restored.cookies() if c['name']=='CASTGC'])==1
        finally:await restored.close()
    asyncio.run(run())
    assert sum(method=='POST' and path=='/authserver/login' for method,path in seen)==1


@pytest.mark.parametrize('failure,error', [('network',ServiceUnavailable),('rejected',LoginError),('server',ServiceUnavailable),('captcha',AdditionalVerification)])
def test_login_failures_do_not_wait_for_browser_navigation(failure,error):
    def server(request):
        if failure=='network':raise httpx.ConnectError('private URL must not leak',request=request)
        if request.url.path.endswith('/bfp/info'):return httpx.Response(200)
        if request.url.path.endswith('/checkNeedCaptcha.htl'):return httpx.Response(200,json={'isNeed':failure=='captcha'})
        if request.method=='POST':return httpx.Response(200 if failure=='rejected' else 503,text=FORM)
        return httpx.Response(200,text=FORM)
    async def run():
        with pytest.raises(error) as exc:
            await sign_in(HttpSessions(transport=httpx.MockTransport(server)),'fixture','password',fingerprint='F'*32,check_captcha=failure=='captcha')
        assert 'private URL' not in str(exc.value)
    asyncio.run(run())


def test_json_and_form_encoding_remain_distinct():
    def server(request):
        if request.url.path=='/form':
            assert request.headers['content-type'].startswith('application/x-www-form-urlencoded')
            assert parse_qs(request.content.decode())=={'password':['a+b/=']}
        else:
            assert request.headers['content-type']=='application/json'
            assert request.content==b'{"code":"wx-fixture"}'
        return httpx.Response(200,json={'ok':True})
    async def run():
        ctx=HttpSession(transport=httpx.MockTransport(server))
        try:
            await ctx.post('https://fixture.test/form',form={'password':'a+b/='})
            await ctx.post('https://fixture.test/json',data={'code':'wx-fixture'})
        finally:await ctx.close()
    asyncio.run(run())


@pytest.mark.parametrize('sms_stage', ['post_redirect', 'service_exchange'])
def test_sms_can_be_reached_through_intermediate_redirects(sms_stage, caplog):
    from uestc_login.client import IDAS
    caplog.set_level('INFO', logger='uestc_login')
    seen=[]
    def server(request):
        path=request.url.path;seen.append(path)
        if path.endswith('/bfp/info'):return httpx.Response(200)
        if path.endswith('/checkNeedCaptcha.htl'):return httpx.Response(200,json={'isNeed':False})
        if request.method=='POST' and path.endswith('/login'):
            return httpx.Response(302,headers={'location':IDAS+('/login?execution=private-must-not-be-logged' if sms_stage=='post_redirect' else '/index.do')})
        if path.endswith('/login') and 'execution' in request.url.params:
            return httpx.Response(302,headers={'location':IDAS+'/reAuthCheck/reAuthLoginView.do?isMultifactor=true'})
        if path.endswith('/index.do'):
            raise AssertionError('Do not enter the campus portal')
        if path.endswith('/login') and 'service' in request.url.params:
            return httpx.Response(302,headers={'location':IDAS+'/reAuthCheck/reAuthLoginView.do?isMultifactor=true'})
        if path.endswith('/reAuthLoginView.do'):return httpx.Response(200,text='SMS verification')
        if path.endswith('/getDynamicCodeByReauth.do'):return httpx.Response(200,json={'res':'success'})
        return httpx.Response(200,text=FORM)
    async def run():
        result=await sign_in(HttpSessions(transport=httpx.MockTransport(server)), 'fixture-user', 'secret-test-password', fingerprint='F'*32)
        try:assert isinstance(result, Reauth)
        finally:await result.context.close()
    asyncio.run(run())
    assert '/authserver/index.do' not in seen
    assert '/authserver/reAuthCheck/reAuthLoginView.do' in seen
    assert seen[-1].endswith('/getDynamicCodeByReauth.do')
    assert 'secret-test-password' not in caplog.text and 'must-not-be-logged' not in caplog.text
    assert 'stage=password_submit' in caplog.text


def test_service_exchange_failure_does_not_claim_password_was_missing():
    from uestc_login.client import SessionEstablishmentError
    def server(request):
        path=request.url.path
        if path.endswith('/bfp/info'):return httpx.Response(200)
        if path.endswith('/checkNeedCaptcha.htl'):return httpx.Response(200,json={'isNeed':False})
        if request.method=='POST':return httpx.Response(302,headers={'location':'/authserver/index.do'})
        if path.endswith('/index.do'):return httpx.Response(200,text='IDAS account home')
        return httpx.Response(200,text=FORM)
    async def run():
        with pytest.raises(SessionEstablishmentError) as exc:
            await sign_in(HttpSessions(transport=httpx.MockTransport(server)),'fixture-user','fixture-password',fingerprint='F'*32)
        assert exc.value.code=='school_session_failed'
    asyncio.run(run())
