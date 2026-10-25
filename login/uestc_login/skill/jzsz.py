from ..client import LoginError


async def session(manager, sessions, username) -> str:
    """Return the raw jzsz SESSION string; never log or expose it publicly."""
    state = await manager.session(sessions, username)
    for cookie in state['cookies']:
        if cookie['name'] == 'SESSION' and cookie['domain'].lstrip('.') == 'jzsz.uestc.edu.cn':
            return cookie['value']
    raise LoginError('The school did not issue a SESSION cookie.')
