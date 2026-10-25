import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from goodnight import main, school, scheduler
from tests.test_core import setup_api
from tests.test_automatic_location import FIRST, SECOND


def test_location_api_default_choice_refresh_and_validation(tmp_path, monkeypatch):
    client = setup_api(tmp_path)
    store = main.app.state.store
    store.save_session('student', 'Me', {'cookies': [], 'origins': []})
    ctx = SimpleNamespace(close=AsyncMock(), storage_state=AsyncMock(return_value={'cookies': [], 'origins': []}))
    monkeypatch.setattr(main.app.state, 'sessions', SimpleNamespace(new_context=AsyncMock(return_value=ctx)))
    monkeypatch.setattr(main, 'authenticate', AsyncMock())
    monkeypatch.setattr(store.login, 'session', AsyncMock(return_value={'cookies': [], 'origins': []}))
    request = AsyncMock(return_value={'code': 0, 'data': [FIRST, SECOND]})
    monkeypatch.setattr(main, 'school_request', request)
    response = client.get('/api/accounts/1/locations')
    assert response.status_code == 200
    data = response.json()
    first, second = data['locations']
    assert [first['name'], second['name']] == ['First dorm', 'Second dorm']
    assert data['selected_key'] == first['key'] and data['automatic']
    assert client.get('/api/state').json()['accounts'][0]['location_name'] == 'First dorm'
    assert client.put('/api/accounts/1/location', json={'key': second['key']}).status_code == 200
    with store.connect() as db:
        saved = dict(db.execute('SELECT * FROM accounts').fetchone())
        assert saved['location_name'] == 'Second dorm' and saved['location_key'] == second['key']
    store.save_session('student', 'Renamed', {'cookies': [], 'origins': []})
    assert client.get('/api/accounts/1/locations').json()['selected_key'] == second['key']
    # Always validate against the current school response before saving.
    request.return_value = {'code': 0, 'data': [FIRST]}
    unavailable = client.get('/api/accounts/1/locations').json()
    assert unavailable['unavailable'] and unavailable['selected_key'] is None
    assert client.put('/api/accounts/1/location', json={'key': second['key']}).status_code == 409
    assert client.put('/api/accounts/1/location', json={'key': None}).status_code == 200
    assert client.get('/api/accounts/1/locations').json()['automatic']
    assert client.put('/api/accounts/1/location', json={'key': 'invented', 'latitude': 30}).status_code == 422
    assert client.get('/api/accounts/99/locations').status_code == 404
    assert client.put('/api/accounts/1/location', json={'key': None}, headers={'Origin': 'https://other.example'}).status_code == 403
    main.app.state.scheduler.busy.add(1)
    assert client.get('/api/accounts/1/locations').status_code == 409
    assert client.put('/api/accounts/1/location', json={'key': None}).status_code == 409
    main.app.state.scheduler.busy.clear()
    request.side_effect = school.SchoolError('transport_error')
    assert client.get('/api/accounts/1/locations').status_code == 502
    assert not main.app.state.scheduler.busy
    assert all(call.args[1] == '/checkin-location/available-locations' for call in request.await_args_list)


def test_probe_populates_automatic_location_name(tmp_path, monkeypatch):
    setup_api(tmp_path)
    store = main.app.state.store
    store.save_session('student', 'Me', {})
    ctx = SimpleNamespace(close=AsyncMock(), storage_state=AsyncMock(return_value={}))
    runner = scheduler.Scheduler(store, SimpleNamespace(new_context=AsyncMock(return_value=ctx)))
    monkeypatch.setattr(scheduler, 'authenticate', AsyncMock(return_value={'realName':'Name'}))
    async def request(ctx,path):
        return {'code': 0, 'data': [FIRST, SECOND] if path.endswith('available-locations') else {}}
    monkeypatch.setattr(scheduler, 'request', request)
    asyncio.run(runner.probe(1))
    with store.connect() as db:
        row = db.execute('SELECT * FROM accounts').fetchone()
        assert row['location_key'] is None and row['location_name'] == 'First dorm'
