import json
from types import SimpleNamespace
from tests.test_lan_web import start_app, request


def test_history_routes_auth_csrf_confirmation_and_session_scope(tmp_path):
    app, service, server, worker = start_app(tmp_path, password='secret')
    calls = []
    service.resolve_session_id = lambda sid: 'shared' if sid == 'shared' else (_ for _ in ()).throw(ValueError('not shared'))
    service.history_editor = SimpleNamespace(
        listing=lambda sid, offset: {'items': [], 'revision': 'a'*64, 'total': 0, 'next': None},
        status=lambda sid, job: {'state': 'done'},
        start=lambda *args: calls.append(args) or {'id': 'job'})
    headers = {'Origin': f'http://127.0.0.1:{server.server_port}', 'X-CSRF-Token': app.csrf_token,
               'Content-Type': 'application/json'}
    payload = {'session_id': 'shared', 'turn_ids': ['turn'], 'revision': 'a'*64, 'confirmed': True}
    try:
        assert request(server, 'GET', '/api/history/manage?session_id=shared')[0] == 401
        _, response_headers, _ = request(server, 'POST', '/api/auth/login', json.dumps({'password': 'secret'}), headers)
        headers['Cookie'] = dict(response_headers)['Set-Cookie'].split(';')[0]
        assert request(server, 'GET', '/api/history/manage?session_id=shared', headers=headers)[0] == 200
        assert request(server, 'GET', '/api/history/manage?session_id=other', headers=headers)[0] == 400
        no_csrf = {k: v for k, v in headers.items() if k != 'X-CSRF-Token'}
        assert request(server, 'POST', '/api/history/delete', json.dumps(payload), no_csrf)[0] == 403
        assert request(server, 'POST', '/api/history/delete', json.dumps(dict(payload, confirmed=False)), headers)[0] == 400
        assert not calls
        assert request(server, 'POST', '/api/history/delete', json.dumps(payload), headers)[0] == 202
        assert len(calls) == 1 and calls[0][0] == 'shared'
        assert request(server, 'GET', '/api/history/delete-status?session_id=shared&job_id=job', headers=headers)[0] == 200
    finally:
        server.shutdown(); server.server_close(); worker.join(2)
