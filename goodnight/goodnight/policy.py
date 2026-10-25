import math
import random
from datetime import datetime
from zoneinfo import ZoneInfo

ZONE = ZoneInfo('Asia/Shanghai')
TERMINAL = {'CHECKED_IN', 'STUDENT_REPORTED', 'INSTRUCTOR_REPORTED', 'EXEMPT'}


def now():
    return datetime.now(ZONE)


def succeeded(r):
    return isinstance(r, dict) and type(r.get('code')) is int and r['code'] == 0 and r.get('ok') is not False


def today_state(r, date):
    d = r.get('data') or {}
    if not succeeded(r) or not isinstance(d, dict) or d.get('businessDate') != date:
        return 'unknown'
    status = d.get('recordStatusCode')
    return 'done' if status in TERMINAL else 'pending' if status == 'PENDING' else 'unknown'


def bounds(date, window, *, padding=True):
    start, end = [datetime.fromisoformat(f'{date}T{x}').replace(tzinfo=ZONE) for x in window.split('_')]
    if not padding:
        return start, end
    span = end - start
    return start + span * .13, start + span * .87


def choose_time(date, window, *, padding=True):
    low, high = bounds(date, window, padding=padding)
    return low + (high - low) * random.SystemRandom().random()


def checkin_window(r, date, current):
    d = r.get('data') or {}
    values = [d.get('studentCheckinStartOffsetMinute'), d.get('studentCheckinEndOffsetMinute')]
    if not succeeded(r) or date != current.date().isoformat() or any(type(v) not in (int, float) or not math.isfinite(v) for v in values):
        return 'invalid_schedule'
    start, end = values[0], min(values[1], 1440) - 5
    if start < 0 or start >= end:
        return 'invalid_schedule'
    minute = (current - current.replace(hour=0, minute=0, second=0, microsecond=0)).total_seconds() / 60
    return 'window_not_open' if minute < start else 'open' if minute < end else 'window_missed'
