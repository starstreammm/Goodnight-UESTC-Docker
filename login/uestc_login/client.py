"""IDAS password login, optional SMS reauthentication, and CAS service handoff."""
import asyncio
import logging
import time
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse
import httpx
from .crypto import encrypt_password
from .form import PasswordForm
from .browser import IDAS, LOGIN_URL, JZSZ, SERVICE_LOGIN_URL, REQUEST_TIMEOUT_MS, REQUEST_DELAY


class LoginError(Exception):
    code = 'login_failed'


class ServiceUnavailable(LoginError):
    code = 'login_unavailable'

    def __init__(self, message='', *, stage=None, http_status=None, reason=None):
        super().__init__(message)
        self.stage, self.http_status, self.reason = stage, http_status, reason


class AdditionalVerification(LoginError):
    code = 'sms_required'


class InvalidCode(LoginError):
    code = 'invalid_code'


class PasswordRequired(LoginError):
    code = 'password_required'


class LoginRejected(LoginError):
    code = 'login_rejected'


class SessionEstablishmentError(LoginError):
    code = 'school_session_failed'


@dataclass
class Reauth:
    context: object
    username: str
    url: str = IDAS + '/reAuthCheck/reAuthLoginView.do?isMultifactor=true'


@dataclass
class ServiceHandoff:
    url: str


async def check_session(context):
    """Reject only confirmed expiry; an outage must not trigger another login."""
    try:
        response = await context.request.get(JZSZ + 'api/isLoginFailure',
            params={'_t': str(int(time.time() * 1000))}, max_redirects=0,
            timeout=REQUEST_TIMEOUT_MS)
    except httpx.RequestError as error:
        raise ServiceUnavailable('Could not check the school session. Try again later.',
            stage='session_validate', reason='timeout' if isinstance(error, httpx.TimeoutException) else 'network') from None
    try:
        trace_response('session_validate', response.status)
        if response.status in (301, 302, 303, 307, 308, 401, 403):
            raise PasswordRequired('School session is not authenticated.')
        if response.status != 200:
            raise ServiceUnavailable('The school session check is temporarily unavailable.',
                stage='session_validate', http_status=response.status)
        try:
            payload = await response.json()
        except ValueError:
            raise ServiceUnavailable('The school session check returned invalid JSON.',
                stage='session_validate', reason='invalid_response') from None
        if not isinstance(payload, dict) or type(payload.get('code')) is not int:
            raise ServiceUnavailable('The school session check returned an invalid response.',
                stage='session_validate', reason='invalid_response')
        if payload['code'] in (401, 403, 5000):
            raise PasswordRequired('School session is not authenticated.')
        if payload['code'] != 200 or payload.get('status') is not True or type(payload.get('data')) is not bool:
            raise ServiceUnavailable('The school session check returned an invalid response.',
                stage='session_validate', reason='invalid_response')
        if not payload['data']:
            raise PasswordRequired('School session is not authenticated.')
        if not any(cookie['name'] == 'SESSION' and cookie.get('value') and
                   cookie['domain'].lstrip('.') == 'jzsz.uestc.edu.cn'
                   for cookie in await context.cookies(JZSZ)):
            raise PasswordRequired('No usable school SESSION cookie was returned.')
    finally:
        await response.dispose()


async def validate(context):
    try:
        response = await context.request.get(JZSZ + 'platform-app/api/h5/user/base-info',
            headers={'platform': 'mp-weixin'}, max_redirects=0, timeout=REQUEST_TIMEOUT_MS)
    except httpx.RequestError as error:
        raise ServiceUnavailable('Could not load the school profile. Try again later.',
            stage='profile_validate', reason='timeout' if isinstance(error, httpx.TimeoutException) else 'network') from None
    try:
        trace_response('profile_validate', response.status)
        if response.status in (301, 302, 303, 401, 403):
            raise PasswordRequired('School session is not authenticated.')
        if response.status != 200:
            raise ServiceUnavailable('The school service is temporarily unavailable.',
                stage='profile_validate', http_status=response.status)
        try:
            payload = await response.json()
        except ValueError:
            raise ServiceUnavailable('The school returned an invalid response.',
                stage='profile_validate', reason='invalid_response') from None
        logging.getLogger('uestc_login').info('IDAS stage=profile_result code=%s',
            payload.get('code') if isinstance(payload, dict) and type(payload.get('code')) is int else 'invalid')
        if isinstance(payload, dict) and payload.get('code') == 5000:
            raise PasswordRequired('School session is not authenticated.')
        if not isinstance(payload, dict) or type(payload.get('code')) is not int or payload.get('code') != 0 or payload.get('ok') is False or not isinstance(payload.get('data'), dict) or not payload['data']:
            raise ServiceUnavailable('The school returned an invalid response.',
                stage='profile_validate', reason='invalid_response')
        return payload['data']
    finally:
        await response.dispose()


async def exchange(context, *, start_url=None, referer=SERVICE_LOGIN_URL, check_existing=True):
    """Exchange the IDAS login for a fresh, verified jzsz SESSION.

    Follow Location explicitly so a successful IDAS page alone is never treated
    as application login. HTTP requests share one cookie jar.
    """
    if check_existing and any(cookie['name'] == 'SESSION' and cookie.get('value')
                              for cookie in await context.cookies(JZSZ)):
        try:
            await check_session(context)
        except PasswordRequired:
            pass
        else:
            return await context.storage_state()
    cookies = await context.cookies(LOGIN_URL)
    logging.getLogger('uestc_login').info('IDAS stage=service_start cas_cookie=%s session_cookie=%s',
        any(c['name'] == 'CASTGC' and c.get('value') for c in cookies),
        any(c['name'] == 'JSESSIONID' and c.get('value') for c in cookies))
    url, has_ticket = start_url or SERVICE_LOGIN_URL, False
    if start_url:
        destination = urlparse(start_url)
        tickets = parse_qs(destination.query).get('ticket', [])
        if (destination.scheme != 'https' or destination.netloc != 'jzsz.uestc.edu.cn'
                or destination.path != '/' or len(tickets) != 1 or not tickets[0].strip()):
            raise LoginError('Unexpected CAS ticket destination.')
        has_ticket = True
    # Ten redirects plus the login-status and profile probes each retain their
    # own network deadline; pacing must not consume that deadline.
    async with asyncio.timeout(12 * (REQUEST_TIMEOUT_MS / 1000 + REQUEST_DELAY)):
        for step in range(10):
            portal = urlparse(url).netloc == 'jzsz.uestc.edu.cn'
            response = await context.request.get(url, max_redirects=0, timeout=REQUEST_TIMEOUT_MS,
                referer='https://idas.uestc.edu.cn/' if portal else referer,
                site='same-site' if portal else 'same-origin')
            try:
                status, location = response.status, response.headers.get('location')
                trace_response('service_exchange', status, location)
            finally:
                await response.dispose()
            if status in (301, 302, 303, 307, 308) and location:
                target = urljoin(url, location)
                destination = urlparse(target)
                if destination.scheme != 'https':
                    raise LoginError('Unexpected CAS redirect destination.')
                if destination.netloc == 'idas.uestc.edu.cn':
                    if destination.path.startswith('/authserver/reAuthCheck/'):
                        error = AdditionalVerification('SMS reauthentication is required.')
                        error.reauth_url = target
                        raise error
                    raise PasswordRequired('Sign in with your school password again.')
                if destination.netloc != 'jzsz.uestc.edu.cn':
                    raise LoginError('Unexpected CAS redirect destination.')
                if not has_ticket:
                    tickets = parse_qs(destination.query).get('ticket', [])
                    if destination.path != '/' or len(tickets) != 1 or not tickets[0].strip():
                        raise LoginError('CAS did not provide a jzsz service ticket.')
                    has_ticket = True
                url = target
                continue
            if status in (401, 403) or (status == 200 and not has_ticket):
                raise PasswordRequired('Sign in with your school password again.')
            if status != 200 or not has_ticket:
                raise ServiceUnavailable('The school service handoff failed.',
                    stage='service_exchange', http_status=status)
            cookies = await context.cookies(JZSZ)
            if not any(c['name'] == 'SESSION' and c.get('value') and
                       c['domain'].lstrip('.') == 'jzsz.uestc.edu.cn' for c in cookies):
                raise LoginError('The school did not issue a jzsz SESSION cookie.')
            await check_session(context)
            try:
                await validate(context)
            except PasswordRequired:
                # Portal authentication succeeded. A separate profile rejection
                # must not cause the manager to request yet another SESSION.
                raise SessionEstablishmentError('The school session is logged in, but mini-program profile access was rejected.') from None
            logging.getLogger('uestc_login').info('IDAS stage=service_validated result=success')
            return await context.storage_state()
    raise ServiceUnavailable('The school service exceeded its redirect limit.')


def trace_response(stage, status, location=None):
    # Fixed categories only: no usernames, query strings, tickets or cookie values.
    destination = urlparse(location or '')
    path = destination.path
    origin = ('idas' if destination.hostname == 'idas.uestc.edu.cn' else
              'jzsz' if destination.hostname == 'jzsz.uestc.edu.cn' else
              'external' if destination.hostname else 'relative')
    scheme = destination.scheme if destination.scheme in ('http', 'https', '') else 'other'
    route = ('reauth' if path.startswith('/authserver/reAuthCheck/') else
             'login' if path == '/authserver/login' else
             'index' if path == '/authserver/index.do' else 'other' if location else 'none')
    logging.getLogger('uestc_login').info('IDAS stage=%s http=%s redirect=%s origin=%s scheme=%s', stage, status, route, origin, scheme or 'relative')


async def follow_login_redirect(context, location):
    """Reach SMS or the IDAS success landing; do not enter its unrelated portal."""
    url = urljoin(LOGIN_URL, location)
    referer = SERVICE_LOGIN_URL
    for _ in range(10):
        target = urlparse(url)
        if target.scheme != 'https' or target.netloc not in ('idas.uestc.edu.cn', 'jzsz.uestc.edu.cn'):
            raise LoginError('Unexpected authentication destination.')
        if target.netloc == 'idas.uestc.edu.cn' and target.path == '/authserver/index.do':
            # This is the success landing from the captured password POST. Its
            # own redirects enter the campus portal, not the requested service.
            return False
        if target.netloc == 'jzsz.uestc.edu.cn':
            return ServiceHandoff(url)
        response = await context.request.get(url,
            referer=SERVICE_LOGIN_URL if target.path.startswith('/authserver/reAuthCheck/') else referer)
        try:
            status, next_url = response.status, response.headers.get('location')
            trace_response('post_redirect', status, next_url)
            if status in (301, 302, 303, 307, 308) and next_url:
                referer = url
                url = urljoin(url, next_url)
                continue
            if status != 200:
                raise ServiceUnavailable(f'The school login redirect returned HTTP {status}.',
                    stage='post_redirect', http_status=status)
            if target.netloc == 'idas.uestc.edu.cn':
                if target.path.startswith('/authserver/reAuthCheck/'):
                    return url
                if PasswordForm(await response.text()).found:
                    raise LoginRejected('The school returned to its password form after submission. Login was not completed.')
            return False
        finally:
            await response.dispose()
    raise ServiceUnavailable('The school login exceeded its redirect limit.')


async def send_sms(reauth):
    response = await reauth.context.request.post(IDAS + '/dynamicCode/getDynamicCodeByReauth.do',
        form={'userName': reauth.username, 'authCodeTypeName': 'reAuthDynamicCodeType'},
        referer=reauth.url, max_redirects=0, timeout=REQUEST_TIMEOUT_MS)
    try:
        trace_response('sms_send', response.status)
        if response.status != 200 or (await response.json()).get('res') != 'success':
            raise LoginError('The school could not send an SMS code. Please try again.')
    finally:
        await response.dispose()


async def sign_in(sessions, username, password, *, fingerprint, state=None, challenge=None, interactive=True, check_captcha=False):
    context = await sessions.new_context(storage_state=state)
    handed_off = False
    stage = 'session_validate' if state else 'login_form'
    try:
        async with asyncio.timeout(300):
            if state:
                try:
                    await check_session(context)
                except PasswordRequired:
                    # A new password flow starts with a fresh browser cookie jar.
                    await context.close()
                    context = await sessions.new_context()
                else:
                    return await context.storage_state()
            stage = 'login_form'
            response = await context.request.get(SERVICE_LOGIN_URL, timeout=REQUEST_TIMEOUT_MS,
                site='none', cookie_names=())
            try:
                if response.status != 200:
                    raise ServiceUnavailable(f'The school login page returned HTTP {response.status}.',
                        stage=stage, http_status=response.status)
                form = PasswordForm(await response.text())
            finally:
                await response.dispose()
            action = urljoin(SERVICE_LOGIN_URL, form.action or SERVICE_LOGIN_URL)
            target = urlparse(action)
            if not form.found or not form.fields.get('execution') or not form.salt:
                raise LoginError('The school password form is missing required fields.')
            if target.scheme != 'https' or target.netloc != 'idas.uestc.edu.cn' or target.path != '/authserver/login':
                raise LoginError('Unexpected authentication destination.')
            stage = 'fingerprint_register'
            response = await context.request.get(IDAS + '/bfp/info',
                params={'bfp': fingerprint, '_': str(int(time.time() * 1000))},
                referer=SERVICE_LOGIN_URL)
            try:
                if response.status != 200:
                    raise ServiceUnavailable('Browser identity registration failed.', stage=stage, http_status=response.status)
            finally:
                await response.dispose()
            if check_captcha:
                stage = 'captcha_check'
                response = await context.request.get(IDAS + '/checkNeedCaptcha.htl',
                    params={'username':username, '_':str(int(time.time() * 1000))},
                    referer=SERVICE_LOGIN_URL)
                try:
                    if response.status != 200:
                        raise ServiceUnavailable('The school CAPTCHA check failed.', stage=stage, http_status=response.status)
                    captcha = await response.json()
                    if not isinstance(captcha, dict) or type(captcha.get('isNeed')) is not bool:
                        raise ServiceUnavailable('The school returned an invalid CAPTCHA requirement.', stage=stage, reason='invalid_response')
                finally:
                    await response.dispose()
                if captcha['isNeed']:
                    if not interactive or challenge is None:
                        raise AdditionalVerification('Complete the school CAPTCHA to continue.')
                    await challenge(context)
            try:
                encrypted = encrypt_password(password, form.salt)
            except ValueError:
                raise LoginError('The school password encryption key is invalid.') from None
            fields = {**form.fields, 'username':username, 'password':encrypted,
                      'captcha':'', '_eventId':'submit', 'cllt':'userNameLogin', 'dllt':'generalLogin',
                      'rememberMe':'true'}
            fields.pop('passwordText', None)
            stage = 'password_submit'
            response = await context.request.post(action, form=fields, timeout=REQUEST_TIMEOUT_MS,
                referer=SERVICE_LOGIN_URL)
            password = None
            fields.clear()
            try:
                status, location = response.status, response.headers.get('location')
                trace_response('password_submit', status, location)
                if status == 200:
                    raise LoginRejected('The school returned the login form after password submission. Login was not completed.')
                if status not in (301, 302, 303, 307, 308) or not location:
                    unavailable = 'IDS is Unavailable' in await response.text()
                    raise ServiceUnavailable(f'The school password submission returned HTTP {status}.',
                        stage=stage, http_status=status,
                        reason='ids_unavailable' if unavailable else None)
            finally:
                await response.dispose()
            stage = 'post_redirect'
            needs_sms = await follow_login_redirect(context, location)
            if not needs_sms or isinstance(needs_sms, ServiceHandoff):
                try:
                    stage = 'service_exchange'
                    return await exchange(context,
                        start_url=needs_sms.url if isinstance(needs_sms, ServiceHandoff) else None,
                        check_existing=False)
                except AdditionalVerification as error:
                    if not getattr(error, 'reauth_url', None):
                        raise
                    needs_sms = await follow_login_redirect(context, error.reauth_url)
                    if isinstance(needs_sms, ServiceHandoff):
                        return await exchange(context, start_url=needs_sms.url, check_existing=False)
                    if not needs_sms:
                        raise SessionEstablishmentError('The school session could not complete reauthentication.') from None
                except PasswordRequired:
                    raise SessionEstablishmentError('Your password was submitted, but the subsequent school session exchange was not authenticated. This is not a missing-password error.') from None
            if not interactive:
                raise AdditionalVerification('Sign in again to complete SMS verification.')
            reauth = Reauth(context, username, needs_sms)
            stage = 'sms_send'
            await send_sms(reauth)
            handed_off = True
            return reauth
    except httpx.TimeoutException:
        raise ServiceUnavailable('The school HTTP request timed out. Check the container network and try again.',
            stage=stage, reason='timeout') from None
    except httpx.RequestError:
        raise ServiceUnavailable('Could not connect to the school authentication service. Check the container network.',
            stage=stage, reason='network') from None
    except TimeoutError:
        raise LoginError('School sign-in timed out.') from None
    finally:
        password = None
        if not handed_off:
            await context.close()


async def submit_sms(reauth, code):
    response = await reauth.context.request.post(IDAS + '/reAuthCheck/reAuthSubmit.do',
        form={'service': parse_qs(urlparse(reauth.url).query).get('service', [''])[0],
              'reAuthType': '3', 'isMultifactor': 'true', 'password': '',
              'dynamicCode': code, 'uuid': '', 'answer1': '', 'answer2': '', 'otpCode': '', 'skipTmpReAuth': 'true'},
        referer=reauth.url, timeout=REQUEST_TIMEOUT_MS, max_redirects=0)
    try:
        trace_response('sms_verify', response.status)
        if response.status != 200 or (await response.json()).get('code') != 'reAuth_success':
            raise InvalidCode('The school rejected the SMS code. Try again.')
    finally:
        await response.dispose()
    return await exchange(reauth.context, referer=reauth.url, check_existing=False)
