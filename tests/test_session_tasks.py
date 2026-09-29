import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest

from lan_codex_share.session_tasks import SessionTasks


class Client:
    def __init__(self, root):
        self.threads = [{"id": str(uuid4()), "name": "Alpha", "cwd": str(root), "turns": ["private"]}]
        self.created = []
        self.lists = 0

    def list_threads(self, max_items=None):
        self.lists += 1
        return self.threads[:max_items]

    def read_thread_metadata(self, session_id):
        return next(t for t in self.threads if t["id"] == session_id)

    def create_thread(self, workspace):
        result = {"id": str(uuid4()), "cwd": str(workspace), "name": "新会话"}
        self.created.append(result)
        self.threads.append(result)
        return result

    def close(self):
        pass


def setup(tmp_path):
    client = Client(tmp_path)
    registered = {}
    tasks = SessionTasks(tmp_path / "shared.json", client, tmp_path,
                         lambda t: registered.update({t["id"]: t}), lambda: tuple(registered))
    return tasks, client, registered


def test_add_persists_without_creating_or_leaking_body(tmp_path):
    tasks, client, entries = setup(tmp_path)
    sid = client.threads[0]["id"]
    assert tasks.add(sid)["session_id"] == sid
    assert "turns" not in entries[sid]
    assert client.created == []
    entries.clear()
    SessionTasks(tasks.path, client, tmp_path, lambda t: entries.update({t['id']: t}), lambda: tuple(entries)).restore()
    assert sid in entries
    assert tasks.add(sid)["already_shared"]


def test_candidates_are_bounded_cached_and_read_only(tmp_path):
    tasks, client, entries = setup(tmp_path)
    client.threads *= 1
    client.threads += [{"id": str(uuid4()), "name": f"Other {i}", "cwd": str(tmp_path)} for i in range(61)]
    page = tasks.candidates()
    assert len(page['items']) == 50
    assert len(tasks.candidates(cursor=page['next_cursor'])['items']) == 12
    assert len(tasks.candidates('alpha')['items']) == 1
    assert client.lists == 1
    assert not entries and not client.created
    assert 'turns' not in json.dumps(page)


def test_create_retry_persists_one_thread(tmp_path):
    tasks, client, entries = setup(tmp_path)
    request_id = str(uuid4())
    result = tasks.create(str(tmp_path), request_id)
    assert tasks.create(str(tmp_path), request_id)['session_id'] == result['session_id']
    assert len(client.created) == 1
    assert result['session_id'] in entries
    again = SessionTasks(tasks.path, client, tmp_path, lambda t: None, lambda: tuple(entries))
    assert again.create(str(tmp_path), request_id)['session_id'] == result['session_id']
    assert len(client.created) == 1


def test_timeout_does_not_retry_create(tmp_path):
    tasks, client, _ = setup(tmp_path)
    calls = []
    def timeout(workspace):
        calls.append(workspace)
        raise TimeoutError()
    client.create_thread = timeout
    rid = str(uuid4())
    with pytest.raises(ValueError, match='结果不确定'):
        tasks.create(str(tmp_path), rid)
    with pytest.raises(ValueError, match='结果不确定'):
        tasks.create(str(tmp_path), rid)
    assert len(calls) == 1


def test_invalid_and_corrupt_fail_closed(tmp_path):
    tasks, client, entries = setup(tmp_path)
    with pytest.raises(ValueError): tasks.add('../secrets')
    with pytest.raises(ValueError): tasks.create(str(tmp_path.parent), str(uuid4()))
    tasks.path.write_text('{bad', encoding='utf-8')
    bad = SessionTasks(tasks.path, client, tmp_path, lambda t: None, lambda: ())
    with pytest.raises(ValueError, match='共享列表'):
        bad.add(client.threads[0]['id'])
    assert tasks.path.read_text() == '{bad'
    assert not entries and not client.created


def test_concurrent_add_and_failed_write(tmp_path, monkeypatch):
    tasks, client, entries = setup(tmp_path)
    sid = client.threads[0]['id']
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(tasks.add, [sid] * 8))
    assert json.loads(tasks.path.read_text())['session_ids'] == [sid]
    other = dict(client.threads[0], id=str(uuid4()))
    client.threads.append(other)
    monkeypatch.setattr(tasks, '_save', lambda data: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(ValueError, match='保存'):
        tasks.add(other['id'])
    assert other['id'] not in entries


def test_restore_missing_session_keeps_other_sessions(tmp_path):
    tasks, client, entries = setup(tmp_path)
    sid = client.threads[0]['id']
    tasks.add(sid)
    client.threads.clear()
    entries.clear()
    tasks.restore()
    assert entries[sid]['error']


def test_created_id_is_recoverable_if_sharing_write_fails(tmp_path, monkeypatch):
    tasks, client, entries = setup(tmp_path)
    rid = str(uuid4())
    save = tasks._save
    def fail_on_shared(data):
        if data['session_ids']:
            raise OSError('disk full')
        save(data)
    monkeypatch.setattr(tasks, '_save', fail_on_shared)
    with pytest.raises(ValueError, match='会话已创建') as failure:
        tasks.create(str(tmp_path), rid)
    created = client.created[0]['id']
    assert created in str(failure.value)
    assert not entries
    restored = SessionTasks(tasks.path, client, tmp_path, lambda t: entries.update({t['id']: t}), lambda: tuple(entries))
    assert restored.create(str(tmp_path), rid)['session_id'] == created
    assert len(client.created) == 1


def test_projects_normalize_aliases_and_create_rejects_changed_retry(tmp_path):
    tasks, client, _ = setup(tmp_path)
    client.threads[0]['cwd'] = str(tmp_path / '.')
    projects = tasks.projects()['items']
    assert len(projects) == 1
    assert client.threads[0]['cwd'] in projects[0]['aliases']
    rid = str(uuid4())
    tasks.create(str(tmp_path), rid)
    with pytest.raises(ValueError, match='项目不一致'):
        tasks.create(str(tmp_path.parent), rid)


def test_create_uses_start_metadata_without_rereading_empty_thread(tmp_path):
    tasks, client, entries = setup(tmp_path)
    client.read_thread_metadata = lambda sid: (_ for _ in ()).throw(ValueError('not materialized'))
    result = tasks.create(str(tmp_path), str(uuid4()))
    assert result['session_id'] in entries
    assert len(client.created) == 1
