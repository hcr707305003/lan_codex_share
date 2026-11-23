"""Streaming native rollout edits and a bounded context made from retained text.

Old encrypted compactions cannot be selectively edited. Retain visible source
records, discard derived context, and start a fresh recent-text context instead.
No model or network is used by this module.
"""
from collections import deque
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4
import hashlib
import json
import os
import shutil
import tempfile


def digest_file(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def inspect_history(path, session_id, offset=0):
    """Hash all bytes while keeping only the requested tail of turn previews."""
    if offset < 0:
        raise ValueError('分页位置无效')
    recent = deque(maxlen=offset + 50)
    count, compactions, rollback, current = 0, 0, False, None
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        first = True
        for raw in stream:
            digest.update(raw)
            if not raw.strip(): continue
            row = json.loads(raw); p = row.get('payload', {})
            if first:
                if row.get('type') != 'session_meta' or p.get('id') != session_id:
                    raise ValueError('会话 ID 与历史文件不一致')
                first = False
            if row.get('type') == 'compacted': compactions += 1
            if p.get('type') == 'thread_rolled_back': rollback = True
            if row.get('type') == 'event_msg' and p.get('type') == 'task_started':
                current = {'id': p.get('turn_id'), 'text': '', 'time': row.get('timestamp', '')}
                recent.append(current); count += 1
            elif current and row.get('type') == 'event_msg':
                value = p.get('message') if p.get('type') == 'user_message' else None
                if p.get('type') == 'item_completed' and p.get('item', {}).get('type') == 'UserMessage':
                    value = ''.join(b.get('text', '') for b in p['item'].get('content', []) if isinstance(b, dict))
                if isinstance(value, str): current['text'] = (current['text'] + '\n' + value[:600]).strip()[:600]
    if first: raise ValueError('原生历史为空')
    items = list(reversed(recent))
    reset = compactions or Path(path).stat().st_size > 32 * 1024 * 1024
    return {'items': items[offset:offset + 50], 'total': count, 'next': offset + 50 if offset + 50 < count else None,
            'revision': digest.hexdigest(), 'compactions': compactions,
            'blocked_reason': '此会话含回退记录，当前不能安全删除。' if rollback else None,
            'context_notice': ('删除时将清除旧压缩摘要，并用保留消息重建近期文字上下文；'
                               '较早记录和附件仍可查看，但不会全部传给下一次模型请求。') if reset else None}


def _derived(row):
    p = row['payload']
    return row.get('type') in {'compacted', 'world_state'} or (row.get('type') == 'event_msg' and
        (p.get('type') in {'context_compacted', 'token_count'} or
         (p.get('type') == 'item_completed' and p.get('item', {}).get('type') == 'ContextCompaction')))


class RecentContext:
    """Bounded verbatim text excerpts, never a purported semantic summary."""
    def __init__(self):
        self.limit = 16 * 1024
        self.items = deque()
        self.size = 0
        self.omitted = 0

    def feed(self, row):
        p = row['payload']
        if row.get('type') == 'event_msg' and p.get('type') == 'task_started':
            window = p.get('model_context_window')
            if isinstance(window, int) and window > 0:
                self.limit = min(32768, max(512, window // 4))
                self._trim()
        if row.get('type') != 'response_item' or p.get('type') != 'message' or p.get('role') not in {'user', 'assistant'}:
            return
        text = ''.join(b.get('text', '') for b in p.get('content', [])
                       if isinstance(b, dict) and b.get('type') in {'text', 'input_text', 'output_text'} and isinstance(b.get('text'), str))
        if not text: return
        cap = min(8192, self.limit // 2)
        encoded = text.encode('utf-8')
        if len(encoded) > cap:
            head = cap // 3
            text = (encoded[:head].decode('utf-8', errors='ignore') + '\n[中段省略，完整内容保留在会话历史]\n'
                    + encoded[-(cap - head):].decode('utf-8', errors='ignore'))
            self.omitted += 1
        item = {'type': 'message', 'role': p['role'], 'content': [
            {'type': 'input_text' if p['role'] == 'user' else 'output_text', 'text': text}]}
        size = len(json.dumps(item, ensure_ascii=False).encode('utf-8'))
        self.items.append((item, size)); self.size += size
        self._trim()

    def _trim(self):
        while self.items and self.size > self.limit:
            _, size = self.items.popleft(); self.size -= size; self.omitted += 1

    def row(self):
        notice = ('会话历史已由用户多选删除并重建上下文。以下仅为保留消息的近期文字摘录，'
                  '不是完整历史或语义摘要；较早内容和附件仍保存在同一会话历史中，需要时请先核对原始记录。')
        replacement = [{'type': 'message', 'role': 'developer', 'content': [{'type': 'input_text', 'text': notice}]}]
        replacement.extend(item for item, _ in self.items)
        window = str(uuid4())
        return {'timestamp': datetime.now(timezone.utc).isoformat(), 'type': 'compacted', 'payload': {'message': '', 'replacement_history': replacement,
                'window_number': 1, 'first_window_id': window, 'window_id': window, 'previous_window_id': None}}


def rewrite_history(source, target, session_id, *, records=None, turn_ids=(), backup=None, progress=lambda _: None):
    """Keep memory bounded by one selected turn plus one decoded source line."""
    from .history_edit import prepare_message_edit
    selected_turns = set(turn_ids)
    selected_records = {}
    for record in records or []: selected_records.setdefault(record['turn_id'], []).append(record)
    if not selected_turns and not selected_records: raise ValueError('请选择要删除的记录')
    meta, active, group, seen, found = None, None, [], set(), set()
    completed, compactions = False, 0
    last_ordinal = None
    tool_owners = {}
    selected_processes = selected_turns | {r['turn_id'] for r in records or [] if r['item_id'] in {'__response__', '__process__'}}
    context = RecentContext()
    digest = hashlib.sha256()
    written = hashlib.sha256()

    def emit(raw, row):
        if not raw.endswith(b'\n'): raw += b'\n'
        target.write(raw); written.update(raw); context.feed(row)

    def encode(row):
        return (json.dumps(row, ensure_ascii=False) + '\n').encode('utf-8')

    def flush():
        nonlocal group
        if active is None: return
        if active in selected_turns:
            found.add(active); group = []; return
        if active not in selected_records: return
        entries = [row for _, row in group]
        if not completed:
            entries.append({'timestamp': datetime.now(timezone.utc).isoformat(), 'type': 'event_msg',
                            'payload': {'type': 'turn_aborted', 'turn_id': active, 'reason': 'interrupted'}})
        edited = prepare_message_edit([meta] + entries, session_id, selected_records[active])
        for row in edited[1:]: emit(encode(row), row)
        found.add(active); group = []

    with Path(source).open('rb') as stream:
        for line_number, raw in enumerate(stream, 1):
            digest.update(raw)
            if backup is not None: backup.write(raw)
            if not raw.strip(): continue
            row = json.loads(raw); p = row.get('payload', {})
            if isinstance(row.get('ordinal'), int): last_ordinal = row['ordinal']
            if not isinstance(p, dict): raise ValueError('原生历史格式无效')
            if meta is None:
                if row.get('type') != 'session_meta' or p.get('id') != session_id:
                    raise ValueError('会话 ID 与历史文件不一致')
                meta = row; emit(raw, row); continue
            if p.get('type') == 'thread_rolled_back': raise ValueError('含回退记录，当前不能安全重建')
            if row.get('type') == 'compacted': compactions += 1
            if _derived(row): continue
            if row.get('type') == 'event_msg' and p.get('type') == 'task_started':
                flush()
                active = p.get('turn_id'); completed = False
                if not active or active in seen: raise ValueError('历史轮次 ID 缺失或重复')
                seen.add(active)
            elif row.get('type') == 'event_msg' and p.get('type') in {'task_complete', 'turn_aborted'}:
                if p.get('turn_id') and p['turn_id'] != active: raise ValueError('历史结束记录与轮次不一致')
                completed = True
            if row.get('type') == 'response_item' and p.get('type') in {
                    'function_call', 'custom_tool_call', 'function_call_output', 'custom_tool_call_output'} and p.get('call_id'):
                owner = tool_owners.setdefault(p['call_id'], active)
                if owner != active and (owner in selected_processes or active in selected_processes):
                    raise ValueError('所选过程存在跨轮工具关联，不能安全删除')
            if active in selected_records: group.append((raw, row))
            elif active not in selected_turns: emit(raw, row)
            if line_number % 5000 == 0: progress(f'已处理 {line_number} 条原生记录')
    flush()
    if meta is None: raise ValueError('原生历史为空')
    if found != selected_turns | set(selected_records): raise ValueError('所选记录已变化，请重新加载')
    rebuilt = context.row()
    if last_ordinal is not None: rebuilt['ordinal'] = last_ordinal + 1
    raw = encode(rebuilt); target.write(raw); written.update(raw)
    return {'source_revision': digest.hexdigest(), 'sha256': written.hexdigest(), 'removed_compactions': compactions,
            'context_bytes': context.size, 'context_omitted': context.omitted,
            'context_reset': True, 'retained_turns': len(seen - selected_turns),
            'deleted_turns': len(selected_turns),
            'deleted_messages': len({(r['turn_id'], r['item_id']) for r in records or []})}


def apply_rebuilt_history(path, home, session_id, *, records=None, turn_ids=(), expected_revision,
                          writer_guard=None, verify, progress=lambda _: None):
    from .history_edit import native_path
    path, home = native_path(path), native_path(home)
    if not path.is_file() or not path.is_relative_to(home / 'sessions'):
        raise ValueError('只能修改本机 sessions 内的历史文件')
    with writer_guard if writer_guard is not None else nullcontext():
        if digest_file(path) != expected_revision: raise ValueError('历史已变化，请重新加载后选择')
        directory = home / 'history-edit-backups'; directory.mkdir(parents=True, exist_ok=True)
        backup_path = directory / (uuid4().hex + '.jsonl')
        from .history_index import HistoryIndexEdit
        index = HistoryIndexEdit(home, session_id, backup_path)
        index.capture()
        fd, staged_name = tempfile.mkstemp(prefix='.history-rebuild-', dir=path.parent)
        staged = Path(staged_name)
        try:
            with os.fdopen(fd, 'wb') as target, backup_path.open('xb') as backup:
                result = rewrite_history(path, target, session_id, records=records, turn_ids=turn_ids, backup=backup, progress=progress)
                target.flush(); os.fsync(target.fileno()); backup.flush(); os.fsync(backup.fileno())
            if result['source_revision'] != expected_revision or digest_file(path) != expected_revision:
                raise ValueError('历史已发生变化，取消删除；原文件未覆盖')
            progress('已备份，正在替换历史与重建上下文')
            os.replace(staged, path)
            try:
                index.sync(path)
                verify(path, session_id)
            except Exception:
                if digest_file(path) != result['sha256']:
                    raise ValueError(f'校验失败且历史发生并发变化，未覆盖新数据；备份：{backup_path}')
                with backup_path.open('rb') as src, staged.open('wb') as dst:
                    shutil.copyfileobj(src, dst, 1024 * 1024); dst.flush(); os.fsync(dst.fileno())
                os.replace(staged, path)
                index.restore()
                raise
            return dict(result, session_id=session_id, backup=str(backup_path))
        finally:
            staged.unlink(missing_ok=True)
