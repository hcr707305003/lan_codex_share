import pytest
from pathlib import Path
from lan_codex_share.history_edit import prepare_history_edit


def history():
    rows=[{'type':'session_meta','payload':{'id':'original'}}]
    for tid in ['first','middle','last']:
        rows.extend([{'type':'event_msg','payload':{'type':'task_started','turn_id':tid}},
                     {'type':'response_item','payload':{'text':tid}},
                     {'type':'event_msg','payload':{'type':'task_complete','turn_id':tid}}])
    return rows


def test_preserves_id_and_later_turns_without_mutating_source():
    rows=history()
    result=prepare_history_edit(rows,'original',['middle'])
    assert len(rows)==10 and len(result)==7
    assert result[0]['payload']['id']=='original'
    assert [r['payload']['text'] for r in result if r['type']=='response_item']==['first','last']


def test_rejects_compacted_or_incomplete_history():
    rows=history()
    for bad in [rows[:-1], rows+[{'type':'compacted','payload':{'message':'old summary'}}]]:
        with pytest.raises(ValueError): prepare_history_edit(bad,'original',['middle'])
    with pytest.raises(ValueError): prepare_history_edit(rows,'original',['missing'])
    with pytest.raises(ValueError): prepare_history_edit(rows,'wrong',['middle'])


def test_rejects_duplicate_turn_after_completed_turn():
    rows = history()
    rows.extend(rows[1:4])
    with pytest.raises(ValueError, match='重复'):
        prepare_history_edit(rows, 'original', ['middle'])


def test_bulk_selection_keeps_original_order():
    rows = history()
    result = prepare_history_edit(rows, 'original', ['last', 'first', 'first'])
    assert [r['payload']['text'] for r in result if r['type'] == 'response_item'] == ['middle']

@pytest.mark.parametrize('fail', [False, True])
def test_transaction_backup_and_failed_verification_restore(tmp_path, fail):
    import json
    from contextlib import nullcontext
    from lan_codex_share.history_edit import apply_history_edit
    path=tmp_path/'sessions'/'thread.jsonl';path.parent.mkdir()
    original=''.join(json.dumps(row)+'\n' for row in history()).encode()
    path.write_bytes(original)
    def verify(path, sid):
        assert sid=='original'
        assert b'middle' not in path.read_bytes()
        if fail: raise RuntimeError('native verification failed')
    if fail:
        with pytest.raises(RuntimeError):
            apply_history_edit(path,tmp_path,'original',['middle'],writer_guard=nullcontext(),verify=verify)
        assert path.read_bytes()==original
    else:
        result=apply_history_edit(path,tmp_path,'original',iter(['middle']),writer_guard=nullcontext(),verify=verify)
        assert result['deleted_turns']==1
        assert b'middle' not in path.read_bytes()
    assert next((tmp_path/'history-edit-backups').glob('*.jsonl')).read_bytes()==original


def test_manager_transaction_and_stale_revision(tmp_path, monkeypatch):
    import hashlib
    import json
    import threading
    from contextlib import nullcontext
    from types import SimpleNamespace as NS
    from lan_codex_share.history_edit import HistoryEditor
    path = tmp_path / 'sessions' / 'rollout.jsonl'
    path.parent.mkdir()
    path.write_text(''.join(json.dumps(row) + '\n' for row in history()), encoding='utf-8')
    released, projected = [], []
    class RPC:
        def request(self, method, params, **kwargs):
            assert method == 'thread/read' and params['includeTurns'] is True
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            return {'thread': {'id': 'original', 'turns': [
                {'id': r['payload']['turn_id']} for r in rows
                if r.get('type') == 'event_msg' and r['payload'].get('type') == 'task_started']}}
    client = NS(read_thread_metadata=lambda sid: {'path': str(path)}, start=lambda: None, rpc=RPC())
    service = NS(_queued_lock=threading.RLock(), release_session=lambda ip: released.append(ip),
                 projection=NS(replace_thread=projected.append, set_connection=lambda value: None), _broadcast=lambda: None)
    def resolve(sid):
        if sid != 'original': raise ValueError('not shared')
        return sid
    hub = NS(resolve_session_id=resolve, _service_create_lock=threading.RLock(), _service=lambda sid: (sid, service))
    editor = HistoryEditor(hub, NS(home=tmp_path, tasks=NS(client=client)))
    monkeypatch.setattr('lan_codex_share.history_edit.native_writer_guard', lambda *_: nullcontext())
    listing = editor.listing('original')
    assert [item['id'] for item in listing['items']] == ['last', 'middle', 'first']
    assert listing['revision'] == hashlib.sha256(path.read_bytes()).hexdigest()
    editor._jobs['job'] = {'session_id': 'original'}
    editor._busy.add('original')
    editor._run('job', 'original', ['middle'], listing['revision'], 'test')
    job = editor.status('original', 'job')
    assert job['state'] == 'done' and job['result']['deleted_turns'] == 1
    assert released == ['test'] and [t['id'] for t in projected[0]['turns']] == ['first', 'last']
    assert Path(job['result']['backup']).is_file()
    editor._run('job', 'original', ['last'], listing['revision'], 'test')
    assert editor.status('original', 'job')['state'] == 'error'
    assert released == ['test']


def test_revision_mismatch_never_writes_or_backs_up(tmp_path):
    import json
    from contextlib import nullcontext
    from lan_codex_share.history_edit import apply_history_edit
    path = tmp_path / 'sessions' / 'rollout.jsonl'; path.parent.mkdir()
    body = ''.join(json.dumps(row) + '\n' for row in history()).encode()
    path.write_bytes(body)
    with pytest.raises(ValueError, match='变化'):
        apply_history_edit(path, tmp_path, 'original', ['middle'], writer_guard=nullcontext(),
                           verify=lambda *_: None, expected_revision='0' * 64)
    assert path.read_bytes() == body and not (tmp_path / 'history-edit-backups').exists()


@pytest.mark.parametrize('initially_released, reconnect_failure', [(False, False), (True, False), (False, True)])
def test_long_delete_restores_previous_ownership_after_verified_write(tmp_path, monkeypatch, initially_released, reconnect_failure):
    from types import SimpleNamespace as NS
    from lan_codex_share.history_edit import HistoryEditor
    from tests.test_lan_service import make_service
    service, codex = make_service(tmp_path)
    try:
        if initially_released:
            service.release_session('before')
        hub = NS(resolve_session_id=lambda sid: sid)
        metadata = {'id': service.thread_id, 'turns': []}
        editor = HistoryEditor(hub, NS(home=tmp_path, tasks=NS(client=NS(read_thread_metadata=lambda _: metadata))))
        turns = [{'id': 'kept', 'status': 'completed', 'items': []}]
        monkeypatch.setattr('lan_codex_share.history_native.native_history_signature', lambda *_, **__: ({}, [], turns))
        monkeypatch.setattr('lan_codex_share.history_edit.native_writer_guard', lambda *_: None)
        writing, applied, calls, updates = [], [], [], []
        def apply(path, home, sid, **kwargs):
            writing.append(True)
            kwargs['verify'](path, sid)
            writing.clear()
            applied.append(True)
            return {'context_reset': True, 'deleted_messages': 2, 'backup': 'saved'}
        monkeypatch.setattr('lan_codex_share.history_rebuild.apply_rebuilt_history', apply)
        def read(include_turns=True):
            assert not writing, 'Resume must happen after the edit writer lock is released'
            assert service._history_editing
            calls.append(include_turns)
            if reconnect_failure:
                raise ValueError('active writer')
            return metadata
        codex.read_thread = read
        editor._run_rebuilt(service.thread_id, service, tmp_path / 'unused', [], 'r', 'test', True,
                            lambda **values: updates.append(values))
        completed = updates[-1]
        assert completed['state'] == 'done' and applied == [True]
        assert completed['result']['deleted_messages'] == 2
        assert calls == ([] if initially_released else [False])
        connected = not (initially_released or reconnect_failure)
        assert completed['result']['connection'] == ('connected' if connected else 'released')
        assert service.snapshot()['connection'] == completed['result']['connection']
        assert bool(completed['result'].get('reconnect_error')) == reconnect_failure
        assert not service._history_editing
        assert service.snapshot()['thread']['turns'][0]['id'] == 'kept'
    finally:
        service.close()


@pytest.mark.parametrize('failed', [False, True])
def test_long_edit_does_not_hold_queue_lock_and_always_clears_reconnect_guard(tmp_path, monkeypatch, failed):
    import threading
    from types import SimpleNamespace as NS
    from lan_codex_share.history_edit import HistoryEditor
    entered, finish, readable = threading.Event(), threading.Event(), threading.Event()
    service = NS(_queued_lock=threading.RLock(), release_session=lambda _: None,
                 _broadcast=lambda: None)
    hub = NS(resolve_session_id=lambda sid: sid)
    editor = HistoryEditor(hub, NS(home=tmp_path, tasks=NS(client=object())))
    monkeypatch.setattr('lan_codex_share.history_edit.native_writer_guard', lambda *_: None)
    def native_read(*_, **__):
        entered.set()
        assert finish.wait(3)
        return {}, [], []
    monkeypatch.setattr('lan_codex_share.history_native.native_history_signature', native_read)
    def apply(*_, **__):
        if failed: raise ValueError('verification failed')
        return {'context_reset': True}
    monkeypatch.setattr('lan_codex_share.history_rebuild.apply_rebuilt_history', apply)
    outcomes = []
    def run():
        try:
            editor._run_rebuilt('s', service, tmp_path / 'unused', [], 'r', 'test', True, lambda **_: None)
        except ValueError as exc:
            outcomes.append(str(exc))
    worker = threading.Thread(target=run)
    worker.start()
    try:
        assert entered.wait(3) and service._history_editing
        def snapshot():
            with service._queued_lock: readable.set()
        reader = threading.Thread(target=snapshot)
        reader.start()
        assert readable.wait(1), 'Long IO must not block queue snapshots'
        reader.join(1)
    finally:
        finish.set(); worker.join(3)
    assert not worker.is_alive() and not service._history_editing
    assert outcomes == (['verification failed'] if failed else [])


@pytest.mark.skipif(__import__('os').name != 'nt', reason='Windows extended path format')
def test_windows_extended_path_is_same_location_but_outside_remains_outside(tmp_path):
    from lan_codex_share.history_edit import native_path
    sessions = tmp_path / 'sessions'; sessions.mkdir()
    file = sessions / 'rollout.jsonl'; file.touch()
    extended = '\\\\?\\' + str(file.resolve())
    assert native_path(extended) == native_path(file)
    assert native_path(extended).is_relative_to(native_path(sessions))
    outside = tmp_path / 'unrelated.jsonl'; outside.touch()
    assert not native_path('\\\\?\\' + str(outside.resolve())).is_relative_to(native_path(sessions))


def message_history():
    rows = [{'type': 'session_meta', 'payload': {'id': 'original'}},
            {'type': 'event_msg', 'payload': {'type': 'task_started', 'turn_id': 'turn'}}]
    for role, text, iid, kind in [('user', 'question', 'u', 'UserMessage'), ('assistant', 'answer', 'a', 'AgentMessage')]:
        rows.append({'type': 'response_item', 'payload': {'type': 'message', 'id': iid, 'role': role,
            'content': [{'type': 'input_text' if role == 'user' else 'output_text', 'text': text}]}})
        rows.append({'type': 'event_msg', 'payload': {'type': 'item_completed', 'turn_id': 'turn',
            'item': {'type': kind, 'id': iid, 'content': [{'type': 'text' if role == 'user' else 'Text', 'text': text}]}}})
    rows.append({'type': 'event_msg', 'payload': {'type': 'task_complete', 'turn_id': 'turn', 'last_agent_message': 'answer'}})
    return rows


@pytest.mark.parametrize('selected,remaining', [('u', 'a'), ('a', 'u')])
def test_independent_message_removal_preserves_other_message(selected, remaining):
    from lan_codex_share.history_edit import prepare_message_edit
    original = message_history()
    result = prepare_message_edit(original, 'original', [{'turn_id': 'turn', 'item_id': selected}])
    assert [r['payload']['id'] for r in result if r['type'] == 'response_item'] == [remaining]
    assert [r['payload']['item']['id'] for r in result if r['payload'].get('type') == 'item_completed'] == [remaining]
    assert original[-1]['payload']['last_agent_message'] == 'answer'
    if selected == 'a': assert 'last_agent_message' not in result[-1]['payload']


def test_process_is_grouped_and_preserves_user_and_final_answer():
    from lan_codex_share.history_edit import prepare_message_edit
    rows = message_history()
    rows[-1:-1] = [
        {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'call', 'name': 'test'}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'call', 'output': 'result'}},
        {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {'type': 'McpToolCall', 'id': 'tool'}}}]
    result = prepare_message_edit(rows, 'original', [{'turn_id': 'turn', 'item_id': '__process__'}])
    assert result == message_history()


@pytest.mark.parametrize('legacy', [False, True])
def test_grouped_codex_response_removes_process_and_reply_but_keeps_user(legacy):
    from lan_codex_share.history_edit import prepare_message_edit
    from copy import deepcopy
    rows = message_history()
    if legacy:
        for row in rows:
            p = row['payload']
            if p.get('type') == 'item_completed':
                item = p['item']
                row['payload'] = {'type': 'user_message' if item['type'] == 'UserMessage' else 'agent_message',
                                  'message': item['content'][0]['text']}
    rows[-1:-1] = [
        {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'call'}},
        {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'call', 'output': 'result'}},
        {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {'type': 'McpToolCall', 'id': 'tool'}}}]
    original = deepcopy(rows)
    result = prepare_message_edit(rows, 'original', [{'turn_id': 'turn', 'item_id': '__response__'}])
    assert rows == original
    assert [r['payload']['id'] for r in result if r['type'] == 'response_item'] == ['u']
    assert len(result) == 5  # metadata, start, two user rows, completion
    assert 'last_agent_message' not in result[-1]['payload']
    with pytest.raises(ValueError):
        prepare_message_edit(rows, 'original', [{'turn_id': 'missing', 'item_id': '__response__'}])


def test_message_removal_refuses_missing_or_ambiguous_mapping():
    from lan_codex_share.history_edit import prepare_message_edit
    rows = message_history()
    rows.insert(2, dict(rows[1]))  # Duplicate task boundary remains rejected.
    with pytest.raises(ValueError): prepare_message_edit(rows, 'original', [{'turn_id': 'turn', 'item_id': 'a'}])
    with pytest.raises(ValueError): prepare_message_edit(message_history(), 'original', [{'turn_id': 'turn', 'item_id': 'missing'}])
