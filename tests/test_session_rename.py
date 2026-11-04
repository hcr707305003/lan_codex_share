import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lan_codex_share.codex_client import CodexClient, CodexClientError, JsonRpcError
from lan_codex_share.session_name import validate_session_name
from lan_codex_share.session_projection import SessionProjection
from lan_codex_share.session_hub import LanSessionHub
from tests.test_session_hub import FakeSessionService
from tests.test_lan_web import start_app, request


@pytest.mark.parametrize('name', ['', '   ', 'a\nb', 'a\x00b', 'a\u200bb', None, 12, '😀' * 101])
def test_invalid_names(name):
    with pytest.raises(ValueError):
        validate_session_name(name)


def test_client_writes_codex_name():
    client = CodexClient.__new__(CodexClient)
    client.start = Mock()
    client.rpc = SimpleNamespace(request=Mock(return_value={}))
    assert client.rename_thread('target', ' 名称 ') == '名称'
    client.rpc.request.assert_called_once_with('thread/name/set', {'threadId': 'target', 'name': '名称'}, timeout=15)
    client.rpc.request.side_effect = JsonRpcError(-32601, 'unknown method')
    with pytest.raises(CodexClientError, match='不支持'):
        client.rename_thread('target', '名称')
    assert validate_session_name('😀' * 100) == '😀' * 100


def test_projection_keeps_history_and_queue():
    projection = SessionProjection()
    projection.replace_thread({'id': 'a', 'turns': [{'id': 'turn', 'items': []}]})
    epoch = projection._history_epoch
    turns = projection._thread['turns']
    pending = projection._pending
    projection.set_name('new')
    assert projection._thread['name'] == 'new'
    assert projection._history_epoch == epoch
    assert projection._thread['turns'] is turns
    assert projection._pending is pending


def test_hub_renames_only_selected_session_and_preserves_failure():
    first = FakeSessionService('a', 'Alpha')
    second = FakeSessionService('b', 'Beta')
    first.rename_session = Mock(return_value='New')
    hub = LanSessionHub([first, second])
    hub.start()
    try:
        assert hub.rename_session('a', ' New ') == 'New'
        assert hub.snapshot('a')['thread']['name'] == 'New'
        assert hub.snapshot('b')['sessions'][1]['name'] == 'Beta'
        first.rename_session.side_effect = CodexClientError('failed')
        with pytest.raises(CodexClientError):
            hub.rename_session('a', 'Rejected')
        assert hub.snapshot('a')['thread']['name'] == 'New'
        with pytest.raises(ValueError):
            hub.rename_session('not-shared', 'New')
    finally:
        hub.close()


def test_http_rename_auth_validation_and_errors(tmp_path):
    app, service, server, thread = start_app(tmp_path)
    service.rename_session = Mock(return_value='New')
    headers = {'X-CSRF-Token': app.csrf_token, 'Content-Type': 'application/json',
               'Origin': f'http://127.0.0.1:{server.server_port}'}
    body = json.dumps({'session_id': 'thread-web', 'name': 'New'})
    try:
        assert request(server, 'POST', '/api/session/rename', body)[0] == 403
        status, _, data = request(server, 'POST', '/api/session/rename', body, headers)
        assert status == 200 and json.loads(data) == {'name': 'New'}
        service.rename_session.assert_called_once_with('thread-web', 'New')
        assert request(server, 'POST', '/api/session/rename', json.dumps({'name': ''}), headers)[0] == 400
        assert request(server, 'POST', '/api/session/rename', json.dumps({'session_id': 'other', 'name': 'New'}), headers)[0] == 400
        service.rename_session.side_effect = CodexClientError('当前 Codex 不支持会话重命名')
        assert request(server, 'POST', '/api/session/rename', body, headers)[0] == 502
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_catalog_inflight_cannot_overwrite_rename():
    import threading
    entered, release = threading.Event(), threading.Event()
    first = FakeSessionService('a', 'Old')
    first.rename_session = Mock(return_value='New')
    hub = LanSessionHub([first])
    hub.start()
    def listing():
        entered.set()
        assert release.wait(3)
        return [{'id': 'a', 'name': 'Old'}]
    hub.tasks = SimpleNamespace(client=SimpleNamespace(list_threads=listing))
    refresh = threading.Thread(target=hub.refresh_catalog)
    rename = threading.Thread(target=lambda: hub.rename_session('a', 'New'))
    try:
        refresh.start()
        assert entered.wait(2)
        rename.start()
        assert hub.submit('a', 'hello', [], 'local') == 'message-a'
        release.set()
        refresh.join(3)
        rename.join(3)
        assert not refresh.is_alive() and not rename.is_alive()
        assert hub.snapshot('a')['thread']['name'] == 'New'
    finally:
        release.set()
        hub.close()
