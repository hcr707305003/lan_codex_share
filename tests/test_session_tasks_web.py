import json

from tests.test_lan_web import start_app, request
from tests.test_session_tasks import setup


def test_new_task_routes_do_not_require_already_shared_id_but_require_auth(tmp_path):
    app, service, server, worker = start_app(tmp_path, password='secret')
    tasks, client, entries = setup(tmp_path)
    service.tasks = tasks
    origin = f'http://127.0.0.1:{server.server_port}'
    headers = {'Origin': origin, 'X-CSRF-Token': app.csrf_token, 'Content-Type': 'application/json'}
    sid = client.threads[0]['id']
    try:
        for route in ['/api/sessions/candidates', '/api/sessions/projects']:
            assert request(server, 'GET', route)[0] == 401
        assert request(server, 'POST', '/api/sessions/add', json.dumps({'session_id': sid}), headers)[0] == 401
        status, response_headers, _ = request(server, 'POST', '/api/auth/login', json.dumps({'password': 'secret'}), headers)
        assert status == 200
        headers['Cookie'] = dict(response_headers)['Set-Cookie'].split(';')[0]
        for route in ['/api/sessions/candidates', '/api/sessions/projects']:
            assert request(server, 'GET', route, headers=headers)[0] == 200
        assert not entries
        assert request(server, 'POST', '/api/sessions/add', json.dumps({'session_id': sid}), dict(headers, Origin='http://evil.test'))[0] == 403
        assert request(server, 'POST', '/api/sessions/add', json.dumps({'session_id': sid}), {k: v for k, v in headers.items() if k != 'X-CSRF-Token'})[0] == 403
        status, _, body = request(server, 'POST', '/api/sessions/add', json.dumps({'session_id': sid}), headers)
        assert status == 200 and json.loads(body)['session_id'] == sid
        assert sid in entries
        assert not client.created
        from uuid import uuid4
        payload = json.dumps({'project': str(tmp_path), 'request_id': str(uuid4())})
        assert request(server, 'POST', '/api/sessions/create', payload, headers)[0] == 200
        assert request(server, 'POST', '/api/sessions/create', payload, headers)[0] == 200
        assert len(client.created) == 1
    finally:
        server.shutdown(); server.server_close(); worker.join(2)


def test_metadata_rpc_never_resumes_active_session(tmp_path):
    from lan_codex_share.codex_client import CodexClient
    from lan_codex_share.state_store import StateStore
    state = StateStore(tmp_path / 'state.json')
    state.set_thread_id('active')
    client = CodexClient(tmp_path, state, 60)
    calls = []
    class RPC:
        def request(self, method, params, **kwargs):
            calls.append((method, params))
            return {'thread': {'id': params.get('threadId', 'new'), 'cwd': str(tmp_path)}}
    client.rpc = RPC()
    client.start = lambda: None
    client.read_thread_metadata('other')
    client.create_thread(tmp_path)
    assert state.thread_id == 'active'
    assert [call[0] for call in calls] == ['thread/read', 'thread/start', 'thread/name/set']
    assert calls[0][1]['includeTurns'] is False
