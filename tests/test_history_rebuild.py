from contextlib import nullcontext
from io import BytesIO
import json
from pathlib import Path
import pytest

from lan_codex_share.history_rebuild import inspect_history, rewrite_history, apply_rebuilt_history, digest_file
from tests.test_history_edit import message_history


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b''.join((json.dumps(r) + '\n').encode() for r in rows))


def compacted_history():
    rows = message_history()
    rows.insert(3, {'type': 'compacted', 'payload': {'message': 'DELETED_STALE_SUMMARY', 'replacement_history': [
        {'type': 'compaction', 'encrypted_content': 'DELETED_OPAQUE_CONTEXT'}]}})
    rows.append({'type': 'world_state', 'payload': {'full': True, 'state': {'stale': 'DELETED_WORLD_STATE'}}})
    return rows


@pytest.mark.parametrize('selection,retained,deleted', [
    ('__response__', 'question', 'answer'), ('u', 'answer', 'question')])
def test_compacted_edit_clears_all_derived_context_and_preserves_other_record(tmp_path, selection, retained, deleted):
    source = tmp_path / 'original.jsonl'; write(source, compacted_history())
    before = source.read_bytes(); target = BytesIO()
    result = rewrite_history(source, target, 'original', records=[{'turn_id': 'turn', 'item_id': selection}])
    output = target.getvalue().decode(); rows = [json.loads(line) for line in output.splitlines()]
    assert retained in output and deleted not in output
    assert all(marker not in output for marker in ['DELETED_STALE_SUMMARY', 'DELETED_OPAQUE_CONTEXT', 'DELETED_WORLD_STATE'])
    assert rows[0]['payload']['id'] == 'original'
    assert sum(r['type'] == 'compacted' for r in rows) == 1
    assert rows[-1]['type'] == 'compacted'
    assert retained in json.dumps(rows[-1]['payload']['replacement_history'])
    assert result['context_reset'] and result['deleted_messages'] == 1 and result['removed_compactions'] == 1
    assert before == source.read_bytes()


def test_inspection_allows_compaction_and_blocks_rollback_without_read_bytes(tmp_path, monkeypatch):
    path = tmp_path / 'history'; write(path, compacted_history())
    monkeypatch.setattr(Path, 'read_bytes', lambda *_: pytest.fail('must stream'))
    result = inspect_history(path, 'original')
    assert result['blocked_reason'] is None and result['compactions'] == 1
    assert '近期' in result['context_notice'] and result['items'][0]['text'] == 'question'
    assert result['revision'] == digest_file(path)
    with path.open('ab') as stream:
        stream.write(b'{"type":"event_msg","payload":{"type":"thread_rolled_back"}}\n')
    assert inspect_history(path, 'original')['blocked_reason']


def test_many_compactions_bound_recent_context_without_truncating_visible_records(tmp_path):
    rows = compacted_history()
    for n in range(120):
        for row in message_history()[1:]:
            row['payload']['turn_id'] = 'turn-' + str(n)
            if row['type'] == 'response_item': row['payload']['content'][0]['text'] = f'KEEP_{n}_' + '文' * 10000
            rows.append(row)
        rows.append({'type': 'compacted', 'payload': {'message': 'STALE_' + str(n)}})
    source = tmp_path / 'original'; write(source, rows); target = BytesIO()
    result = rewrite_history(source, target, 'original', turn_ids=['turn'])
    data = target.getvalue(); edited = [json.loads(line) for line in data.splitlines()]
    assert sum(r['type'] == 'response_item' for r in edited) == 240
    assert sum(r['type'] == 'compacted' for r in edited) == 1
    assert result['context_bytes'] <= 16384 and result['context_omitted'] > 0
    assert 'KEEP_119_' in json.dumps(edited[-1], ensure_ascii=False)
    assert 'KEEP_0_' in data.decode() and 'KEEP_0_' not in json.dumps(edited[-1])
    assert b'STALE_' not in data


@pytest.mark.parametrize('failed', [False, True])
def test_streamed_transaction_backup_native_verification_and_rollback(tmp_path, monkeypatch, failed):
    path = tmp_path / 'sessions' / 'rollout'; write(path, compacted_history()); before = path.read_bytes()
    revision = digest_file(path)
    monkeypatch.setattr(Path, 'read_bytes', lambda *_: pytest.fail('must stream'))
    def verify(p, sid):
        assert sid == 'original'
        with p.open(encoding='utf-8') as stream: assert 'DELETED_STALE_SUMMARY' not in stream.read()
        if failed: raise ValueError('native mismatch')
    args = dict(records=[{'turn_id': 'turn', 'item_id': '__response__'}], expected_revision=revision,
                writer_guard=nullcontext(), verify=verify)
    if failed:
        with pytest.raises(ValueError, match='native mismatch'): apply_rebuilt_history(path, tmp_path, 'original', **args)
        with path.open('rb') as stream: assert stream.read() == before
    else:
        result = apply_rebuilt_history(path, tmp_path, 'original', **args)
        assert result['sha256'] == digest_file(path)
    with next((tmp_path / 'history-edit-backups').glob('*.jsonl')).open('rb') as stream: assert stream.read() == before


def test_stale_revision_and_invalid_selection_never_replace(tmp_path):
    path = tmp_path / 'sessions' / 'rollout'; write(path, compacted_history()); before = path.read_bytes()
    with pytest.raises(ValueError, match='历史已变化'):
        apply_rebuilt_history(path, tmp_path, 'original', turn_ids=['turn'], expected_revision='0' * 64, verify=lambda *_: None)
    with pytest.raises(ValueError, match='已变化'):
        apply_rebuilt_history(path, tmp_path, 'original', turn_ids=['missing'], expected_revision=digest_file(path), verify=lambda *_: None)
    assert path.read_bytes() == before


def test_selected_historical_interrupted_turn_is_closed_without_touching_next_turn(tmp_path):
    rows = message_history()[:-1]
    next_turn = message_history()[1:]
    for row in next_turn: row['payload']['turn_id'] = 'next'
    rows += next_turn
    path = tmp_path / 'rollout'; write(path, rows); target = BytesIO()
    rewrite_history(path, target, 'original', records=[{'turn_id': 'turn', 'item_id': '__response__'}])
    result = [json.loads(line) for line in target.getvalue().splitlines()]
    assert sum(r['payload'].get('type') == 'turn_aborted' for r in result) == 1
    assert sum(r['payload'].get('id') == 'a' for r in result) == 1  # next answer remains


def test_rollback_rejected_and_original_untouched(tmp_path):
    path = tmp_path / 'rollout'; rows = compacted_history()
    rows.append({'type': 'event_msg', 'payload': {'type': 'thread_rolled_back'}}); write(path, rows)
    with pytest.raises(ValueError, match='回退'):
        rewrite_history(path, BytesIO(), 'original', turn_ids=['turn'])


def test_cross_turn_tool_link_never_leaves_an_orphan(tmp_path):
    rows = message_history()
    rows.insert(-1, {'type': 'response_item', 'payload': {'type': 'function_call', 'call_id': 'cross'}})
    following = message_history()[1:]
    for row in following: row['payload']['turn_id'] = 'next'
    following.insert(1, {'type': 'response_item', 'payload': {'type': 'function_call_output', 'call_id': 'cross'}})
    rows += following
    path = tmp_path / 'rollout'; write(path, rows)
    with pytest.raises(ValueError, match='跨轮工具'):
        rewrite_history(path, BytesIO(), 'original', records=[{'turn_id': 'turn', 'item_id': '__response__'}])


def test_concurrent_change_before_replace_is_preserved(tmp_path):
    path = tmp_path / 'sessions' / 'rollout'; write(path, compacted_history())
    # Simulate an uncooperative external writer at the second revision check.
    with path.open('ab') as stream:
        for _ in range(5000): stream.write(b'{"type":"event_msg","payload":{"type":"token_count"}}\n')
    revision = digest_file(path)
    from unittest.mock import patch
    original = digest_file
    calls = []
    def digest(p):
        calls.append(p)
        if len(calls) == 2:
            with path.open('ab') as stream: stream.write(b'\n')
        return original(p)
    with patch('lan_codex_share.history_rebuild.digest_file', side_effect=digest):
        with pytest.raises(ValueError, match='发生变化'):
            apply_rebuilt_history(path, tmp_path, 'original', turn_ids=['turn'], expected_revision=revision, verify=lambda *_: None)
    assert digest_file(path) != revision
    with path.open('rb') as stream: assert b'DELETED_STALE_SUMMARY' in stream.read()


def test_replacement_context_starts_on_new_line_when_original_has_no_trailing_newline(tmp_path):
    path = tmp_path / 'rollout'; write(path, compacted_history())
    path.write_bytes(path.read_bytes().rstrip(b'\n'))
    output = BytesIO()
    rewrite_history(path, output, 'original', records=[{'turn_id': 'turn', 'item_id': '__response__'}])
    rows = [json.loads(line) for line in output.getvalue().splitlines()]
    assert rows[-1]['type'] == 'compacted'
