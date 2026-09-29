import json
import pytest

from lan_codex_share.project_profiles import ProjectProfiles, ProfileConflict, project_key


def test_roundtrip_and_conflict(tmp_path):
    path = tmp_path / 'profiles.json'
    store = ProjectProfiles(path)
    key = project_key(str(tmp_path))
    assert key == project_key(str(tmp_path / '.'))
    saved = store.save(key, ' 后端 ', '# 公告\n[网站](https://example.com)', 0)
    assert saved['alias'] == '后端' and saved['revision'] == 1
    assert ProjectProfiles(path).get(key) == saved
    with pytest.raises(ProfileConflict):
        store.save(key, '旧编辑', '', 0)
    assert store.save(key, '', '', 1)['revision'] == 2


@pytest.mark.parametrize('alias,notice,revision', [
    ('x' * 101, '', 0), ('a\nb', '', 0), ('x\x00', '', 0),
    ('', '中' * 22000, 0), (None, '', 0), ('', None, 0), ('', '', True), ('', '', -1),
], ids=['long-alias', 'newline', 'control', 'long-notice', 'null-alias', 'null-notice', 'bool-version', 'negative-version'])
def test_validation(tmp_path, alias, notice, revision):
    with pytest.raises(ValueError):
        ProjectProfiles(tmp_path / 'p.json').save('project', alias, notice, revision)


def test_corrupt_file_not_overwritten(tmp_path):
    path = tmp_path / 'p.json'
    path.write_text('{broken', encoding='utf-8')
    store = ProjectProfiles(path)
    for action in [lambda: store.get('p'), lambda: store.save('p', '', '', 0)]:
        with pytest.raises(ValueError, match='损坏'):
            action()
    assert path.read_text() == '{broken'


def test_failed_replace_preserves_old_data(tmp_path, monkeypatch):
    from pathlib import Path
    path = tmp_path / 'p.json'
    store = ProjectProfiles(path)
    previous = store.save('p', 'old', '', 0)
    def fail(*args):
        raise OSError('disk error')
    monkeypatch.setattr(Path, 'replace', fail)
    with pytest.raises(ValueError, match='保存失败'):
        store.save('p', 'new', '', 1)
    assert store.get('p') == previous
    assert json.loads(path.read_text())['projects']['p'] == previous


def test_concurrent_save_has_one_winner(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = ProjectProfiles(tmp_path / 'p.json')
    def save(alias):
        try:
            return store.save('p', alias, '', 0)['revision']
        except ProfileConflict:
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(save, ['a', 'b']), key=str) == [1, 'conflict']


def make_hub(tmp_path):
    from lan_codex_share.session_hub import LanSessionHub
    from tests.test_session_hub import FakeSessionService
    service = FakeSessionService('session-a', 'Original session')
    summary = service.summary
    service.summary = lambda: dict(summary(), cwd=str(tmp_path))
    hub = LanSessionHub([service])
    hub.profiles = ProjectProfiles(tmp_path / 'profiles.json')
    hub.start()
    return hub


def test_hub_profile_is_metadata_only_and_damage_does_not_break_chat(tmp_path):
    hub = make_hub(tmp_path)
    key = hub.project_summaries()[0]['id']
    subscriber = hub.subscribe()
    try:
        with pytest.raises(ValueError):
            hub.project_profile('unknown', {'alias': 'a', 'notice_markdown': '', 'revision': 0})
        hub.project_profile(key, {'alias': '后端', 'notice_markdown': 'secret notice', 'revision': 0})
        assert subscriber.get_nowait() > 0
        project = hub.project_summaries()[0]
        assert project['name'] == '后端' and project['has_notice']
        assert 'notice_markdown' not in project
        assert project['sessions'][0]['name'] == 'Original session'
        assert hub.preview_roots == ()
        assert not hub._services[0].calls
        hub.profiles.path.write_text('broken', encoding='utf-8')
        hub.profiles = ProjectProfiles(hub.profiles.path)
        assert hub.project_summaries()[0]['profile_error']
        assert hub.snapshot('session-a')['thread_id'] == 'session-a'
    finally:
        hub.close()


def test_profile_http_guards_and_conflict(tmp_path):
    from urllib.parse import urlencode
    from tests.test_lan_web import start_app, request
    app, _, server, worker = start_app(tmp_path, password='secret')
    hub = make_hub(tmp_path)
    app.service = hub
    key = project_key(str(tmp_path))
    route = '/api/projects/profile'
    url = route + '?' + urlencode({'project_id': key})
    headers = {'Origin': f'http://127.0.0.1:{server.server_port}', 'X-CSRF-Token': app.csrf_token,
               'Content-Type': 'application/json'}
    body = json.dumps({'project_id': key, 'alias': 'Alias', 'notice_markdown': '# Notice', 'revision': 0})
    try:
        assert request(server, 'GET', url)[0] == 401
        assert request(server, 'POST', route, body, headers)[0] == 401
        status, response_headers, _ = request(server, 'POST', '/api/auth/login', json.dumps({'password': 'secret'}), headers)
        assert status == 200
        headers['Cookie'] = dict(response_headers)['Set-Cookie'].split(';')[0]
        assert request(server, 'POST', route, body, dict(headers, Origin='http://evil.test'))[0] == 403
        assert request(server, 'POST', route, body, {k:v for k,v in headers.items() if k != 'X-CSRF-Token'})[0] == 403
        assert request(server, 'GET', url, headers=dict(headers, Host='evil.test'))[0] == 403
        assert request(server, 'POST', route, body, headers)[0] == 200
        assert request(server, 'POST', route, body, headers)[0] == 409
        status, _, data = request(server, 'GET', url, headers=headers)
        assert status == 200 and json.loads(data)['alias'] == 'Alias'
        assert request(server, 'GET', route + '?project_id=unknown', headers=headers)[0] == 400
    finally:
        server.shutdown(); server.server_close(); worker.join(2); hub.close()
