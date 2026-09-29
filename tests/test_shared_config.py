import json
from uuid import uuid4

import pytest

from lan_codex_share.config_write import SessionConfigStore, config_lock
from lan_codex_share.lan_config import load_lan_config
from lan_codex_share.session_hub import LanSessionHub
from lan_codex_share.session_tasks import SessionTasks
from tests.test_session_tasks import Client
from tests.test_session_hub import FakeSessionService


def setup(tmp_path, mode='selected'):
    path = tmp_path / 'lan.toml'
    path.write_text(f'# keep comment\nworkspace = "."\npassword = "secret" # keep\nsession_mode = "{mode}"\nsession_ids = []\n', encoding='utf-8')
    client = Client(tmp_path)
    hub = LanSessionHub()
    store = SessionConfigStore(path)
    tasks = SessionTasks(tmp_path / 'state.json', client, tmp_path, hub.register_session,
                         lambda: hub.thread_ids, config_store=store, hub=hub)
    hub.configure_tasks(tasks, lambda entry: FakeSessionService(entry['id'], 'test'))
    hub.start()
    return path, store, tasks, hub, client


def test_selected_empty_and_add_remove_persist(tmp_path):
    path, store, tasks, hub, client = setup(tmp_path)
    config = load_lan_config(path)
    assert not config.auto_session and not config.discover_all_sessions
    assert hub.snapshot()['sessions'] == []
    sid = client.threads[0]['id']
    tasks.add(sid)
    assert store.read() == ('selected', [sid])
    assert sid in hub.thread_ids
    tasks.remove(sid, 'test')
    assert store.read() == ('selected', [])
    assert hub.snapshot(sid)['sessions'] == []
    assert '# keep comment' in path.read_text() and '"secret" # keep' in path.read_text()
    tasks.restore(); assert not hub.thread_ids


def test_release_then_write_failure_keeps_shared_item(tmp_path, monkeypatch):
    path, store, tasks, hub, client = setup(tmp_path)
    sid = client.threads[0]['id']; tasks.add(sid)
    service = hub._service(sid)[1]
    def fail(*args): raise OSError('disk full')
    monkeypatch.setattr('lan_codex_share.config_write.replace_config', fail)
    with pytest.raises(ValueError, match='保存失败'): tasks.remove(sid, 'test')
    assert service.released == ['test'] and not service.closed
    assert sid in hub.thread_ids and store.read()[1] == [sid]


def test_release_failure_does_not_change_file(tmp_path):
    path, store, tasks, hub, client = setup(tmp_path)
    sid = client.threads[0]['id']; tasks.add(sid)
    service = hub._service(sid)[1]
    def fail(source): raise ValueError('busy')
    service.release_session = fail
    before = path.read_bytes()
    with pytest.raises(ValueError, match='busy'): tasks.remove(sid, 'test')
    assert path.read_bytes() == before and sid in hub.thread_ids


def test_conversion_requires_confirmation_before_create(tmp_path):
    path, store, tasks, hub, client = setup(tmp_path, 'all')
    with pytest.raises(ValueError, match='确认'): tasks.create(str(tmp_path), str(uuid4()))
    assert not client.created
    tasks.add(client.threads[0]['id'], confirmed=True)
    assert store.read()[0] == 'selected'


def test_legacy_restore_requires_import(tmp_path):
    path, store, tasks, hub, client = setup(tmp_path)
    sid = client.threads[0]['id']
    tasks._state['session_ids'] = [sid]
    tasks.restore(); assert not hub.thread_ids
    assert tasks.management()['legacy_session_ids'] == [sid]
    tasks.migrate(True)
    assert store.read()[1] == [sid] and sid in hub.thread_ids
    tasks.remove(sid, 'test'); tasks.restore()
    assert not hub.thread_ids and not tasks.management()['legacy_session_ids']


def test_external_edit_and_concurrent_lock_rejected(tmp_path):
    path, store, tasks, hub, client = setup(tmp_path)
    with store.mutation([]) as (ids, save):
        with pytest.raises(ValueError, match='其他操作'):
            with config_lock(path): pass
        path.write_text(path.read_text() + '# external\n')
        with pytest.raises(ValueError, match='外部修改'): save([])
    assert '# external' in path.read_text()


def test_create_retry_does_not_duplicate_after_config_failure(tmp_path, monkeypatch):
    path, store, tasks, hub, client = setup(tmp_path)
    import lan_codex_share.config_write as writer
    original = writer.replace_config
    def fail(*args): raise OSError('disk')
    monkeypatch.setattr(writer, 'replace_config', fail)
    rid = str(uuid4())
    with pytest.raises(ValueError, match='会话已创建'): tasks.create(str(tmp_path), rid)
    monkeypatch.setattr(writer, 'replace_config', original)
    tasks.create(str(tmp_path), rid)
    assert len(client.created) == 1 and store.read()[1] == [client.created[0]['id']]


def test_unloaded_active_and_loaded_busy_are_not_removed(tmp_path):
    path, store, tasks, hub, client = setup(tmp_path)
    sid = client.threads[0]['id']; client.threads[0]['status'] = {'type': 'active'}
    tasks.add(sid)
    with pytest.raises(ValueError, match='执行中'): tasks.remove(sid, 'test')
    assert sid in hub.thread_ids and not hub._services_by_id


def test_remove_serializes_submit_and_reconnect(tmp_path):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    path, store, tasks, hub, client = setup(tmp_path)
    sid = client.threads[0]['id']; tasks.add(sid); service = hub._service(sid)[1]
    entered, proceed = threading.Event(), threading.Event()
    def release(source):
        entered.set(); assert proceed.wait(3)
    service.release_session = release
    with ThreadPoolExecutor(3) as executor:
        removal = executor.submit(tasks.remove, sid, 'test')
        assert entered.wait(3)
        submit = executor.submit(hub.submit, sid, 'no', [], 'test')
        reconnect = executor.submit(hub.reconnect_session, sid, 'test')
        proceed.set(); removal.result(3)
        for future in [submit, reconnect]:
            with pytest.raises(ValueError, match='共享列表'): future.result(3)
    assert not service.calls and not service.reconnected


def test_config_mode_legacy_and_invalid(tmp_path):
    path, store, tasks, hub, client = setup(tmp_path)
    for text, auto, all_sessions in [
        ('session_ids=[]', False, True), ('', True, False),
        ('session_ids=["a"]', False, False),
        ('session_mode="selected"\nsession_ids=[]', False, False),
        ('session_mode="auto"\nsession_ids=["a"]', True, False),
    ]:
        path.write_text('workspace="."\n' + text)
        config = load_lan_config(path)
        assert config.auto_session == auto and config.discover_all_sessions == all_sessions
    path.write_text('workspace="."\nsession_mode="invalid"')
    with pytest.raises(ValueError, match='session_mode'): load_lan_config(path)


def test_shared_management_http_and_legacy_release(tmp_path):
    import threading
    from lan_codex_share.lan_web import LanWebApplication
    from lan_codex_share.lan_store import ImageStore
    from tests.test_lan_web import request
    path, store, tasks, hub, client = setup(tmp_path)
    sid = client.threads[0]['id']; tasks.add(sid)
    app = LanWebApplication(hub, ImageStore(tmp_path / 'images', 1024, 4), {'127.0.0.1'}, max_request_bytes=10240, workspace=tmp_path)
    server = app.create_server('127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    headers = {'Origin': f'http://127.0.0.1:{server.server_port}', 'Content-Type':'application/json', 'X-CSRF-Token':app.csrf_token}
    try:
        assert request(server, 'GET', '/api/sessions/management')[0] == 200
        body = json.dumps({'session_id': sid})
        assert request(server, 'POST', '/api/session/release', body, headers)[0] == 200
        assert store.read()[1] == [sid]
        assert request(server, 'POST', '/api/sessions/remove', body, {**headers, 'X-CSRF-Token':'bad'})[0] == 403
        assert store.read()[1] == [sid]
        assert request(server, 'POST', '/api/sessions/remove', body, headers)[0] == 200
        assert store.read()[1] == []
        status, _, data = request(server, 'GET', '/api/snapshot?session_id=' + sid)
        assert status == 200 and json.loads(data)['sessions'] == []
    finally:
        server.shutdown(); server.server_close(); thread.join(2); hub.close()
