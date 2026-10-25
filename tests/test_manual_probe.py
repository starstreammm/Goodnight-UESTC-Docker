"""Offline coverage of the session-based manual diagnostic."""
import asyncio
from datetime import datetime
import importlib.util
from pathlib import Path

import httpx
import pytest

from goodnight.policy import ZONE

spec = importlib.util.spec_from_file_location(
    'manual_test', Path(__file__).parents[1] / 'goodnight' / 'manual_test.py')
manual = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manual)


def test_session_probes_are_read_only(monkeypatch, caplog):
    monkeypatch.setattr(manual, 'now', lambda: datetime(2026, 10, 25, 22, tzinfo=ZONE))
    monkeypatch.setenv('UESTC_HTTP_TRACE', '1')
    locations = [{'name': 'Campus', 'latitude': 30.7, 'longitude': 104.0, 'radiusMeter': 500}]
    record = {'businessDate': '2026-10-25', 'recordStatusCode': 'PENDING'}
    schedule = {'studentCheckinStartOffsetMinute': 1260, 'studentCheckinEndOffsetMinute': 1380}
    responses = {
        '/daily-checkin/api/checkin-location/available-locations': locations,
        '/daily-checkin/api/student-checkin-record/today': record,
        '/daily-checkin/api/checkin-schedule/effective': schedule,
    }
    seen = []

    def server(request):
        assert request.method == 'GET'
        assert request.url.host == 'jzsz.uestc.edu.cn'
        assert request.headers['cookie'] == 'SESSION=synthetic-secret'
        assert request.headers['platform'] == 'h5'
        seen.append(request.url.path)
        return httpx.Response(200, json={'code': 0, 'data': responses[request.url.path]})

    result = asyncio.run(manual.inspect_session('SESSION=synthetic-secret', transport=httpx.MockTransport(server)))
    assert seen == list(responses)
    assert result['location']['data'] == locations
    assert result['status'] == {'ok': True, 'data': record, 'state': 'pending'}
    assert result['schedule'] == {'ok': True, 'data': schedule, 'window': 'open'}
    assert 'synthetic-secret' not in caplog.text
    assert 'synthetic-secret' not in str(result)


@pytest.mark.parametrize('response', [
    httpx.Response(302, headers={'location': 'https://idas.uestc.edu.cn/authserver/login'}),
    httpx.Response(200, json={'code': 5000}),
])
def test_expired_session(response):
    result = asyncio.run(manual.inspect_session('expired', transport=httpx.MockTransport(lambda _: response)))
    for key in ('location', 'status', 'schedule'):
        assert result[key]['ok'] is False
        assert result[key]['error'] == 'need_login'


def test_independent_failures_preserve_remaining_results():
    def server(request):
        if 'available-locations' in request.url.path:
            raise httpx.ConnectError('offline', request=request)
        if request.url.path.endswith('/today'):
            return httpx.Response(200, text='<html>invalid response</html>')
        return httpx.Response(200, json={'code': 0, 'data': []})

    result = asyncio.run(manual.inspect_session('synthetic', transport=httpx.MockTransport(server)))
    assert result['location']['error'] == 'transport_error'
    assert result['status']['error'] == 'invalid_api_response'
    assert result['schedule']['error'] == 'invalid_api_response'


@pytest.mark.parametrize('value', ['', 'SESSION=', 'abc; OTHER=value', 'abc\nInjected', '中文'])
def test_invalid_session(value):
    with pytest.raises(ValueError):
        asyncio.run(manual.inspect_session(value))


@pytest.mark.parametrize('ok, exit_code', [(True, 0), (False, 1)])
def test_cli_prompt_json_and_exit_code(monkeypatch, capsys, ok, exit_code):
    async def inspect(value):
        assert value == 'synthetic'
        return {key: {'ok': ok} for key in ('location', 'status', 'schedule')}

    monkeypatch.setattr(manual, 'getpass', lambda _: 'synthetic')
    monkeypatch.setattr(manual, 'inspect_session', inspect)
    assert manual.main([]) == exit_code
    assert '"schedule"' in capsys.readouterr().out
