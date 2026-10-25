#!/usr/bin/env python3
"""Read location, today's status, and school schedule using a jzsz SESSION.

Run from the repository root:
    uv run --project goodnight python goodnight/manual_test.py
"""

import argparse
import asyncio
from getpass import getpass
import json
import sys

from uestc_login.http import HttpSession
from goodnight.policy import checkin_window, now, succeeded, today_state
from goodnight.school import SchoolError, available_locations, request


def session_value(value):
    value = value.strip()
    if value.startswith('SESSION='):
        value = value[len('SESSION='):]
    if not value or any(ord(c) < 33 or ord(c) > 126 or c in ';,"\\' for c in value):
        raise ValueError('Enter a SESSION value or SESSION=value, without other cookies or attributes.')
    return value


async def inspect_session(session, *, transport=None):
    """Return independent read-only probe results; never submit attendance."""
    value = session_value(session)
    ctx = HttpSession({'cookies': [{
        'name': 'SESSION', 'value': value, 'domain': 'jzsz.uestc.edu.cn',
        'path': '/', 'secure': True,
    }]}, transport=transport)
    # This diagnostic reports data, not credentials, even when HTTP tracing is enabled.
    ctx.trace = False
    ctx.client.event_hooks = {'request': [], 'response': []}
    current = now()
    date = current.date().isoformat()
    result = {'checked_at': current.isoformat()}
    probes = (
        ('location', '/checkin-location/available-locations'),
        ('status', '/student-checkin-record/today'),
        ('schedule', '/checkin-schedule/effective'),
    )
    try:
        for name, path in probes:
            try:
                payload = await request(ctx, path)
                if not succeeded(payload):
                    raise SchoolError('api_error', http_status=200, api_code=payload['code'])
                data = payload.get('data')
                if name == 'location':
                    available_locations(payload)
                elif not isinstance(data, dict):
                    raise SchoolError('invalid_api_response', http_status=200)
                entry = {'ok': True, 'data': data}
                if name == 'status':
                    entry['state'] = today_state(payload, date)
                elif name == 'schedule':
                    entry['window'] = checkin_window(payload, date, current)
                result[name] = entry
            except SchoolError as error:
                result[name] = {
                    'ok': False, 'error': str(error),
                    'http_status': error.http_status, 'api_code': error.api_code,
                }
    finally:
        await ctx.close()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--session', help='jzsz SESSION cookie; omitted: hidden terminal prompt.')
    args = parser.parse_args(argv)
    try:
        session = args.session if args.session is not None else getpass('jzsz SESSION (hidden): ')
        result = asyncio.run(inspect_session(session))
    except (ValueError, EOFError, KeyboardInterrupt) as error:
        print(f'ERROR: {error or "interrupted"}', file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(result[key]['ok'] for key in ('location', 'status', 'schedule')) else 1


if __name__ == '__main__':
    sys.exit(main())
