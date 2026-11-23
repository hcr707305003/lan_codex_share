"""Prepare history edits without modifying any live Codex files.

Only unambiguous, completed rollout turns are accepted. Applying the plan must
be protected by native writer exclusion and a durable backup.
"""
from copy import deepcopy
from contextlib import contextmanager
from pathlib import Path
import hashlib
import json
import os
import threading
from uuid import UUID, uuid4


def native_path(value):
    """Compare resolved Windows extended paths and ordinary paths consistently."""
    def ordinary(raw):
        text = str(raw)
        if os.name == 'nt':
            if text.startswith('\\\\?\\UNC\\'):
                return '\\\\' + text[8:]
            if text.startswith('\\\\?\\'):
                return text[4:]
        return text
    return Path(ordinary(Path(ordinary(value)).expanduser().resolve()))


@contextmanager
def native_writer_guard(home, sid):
    """Windows byte-range locking interoperates with the installed native writer."""
    if os.name != 'nt':
        raise ValueError('当前仅验证了 Windows 原生会话编辑锁，其他系统暂不开放删除')
    import msvcrt
    sid = str(UUID(sid))
    directory = Path(home) / 'thread-writer-locks'
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (sid + '.lock')).open('a+b') as stream:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            raise ValueError('Codex 仍占用该会话，请在占用端关闭会话后重试；历史未修改') from exc
        try:
            yield
        finally:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)


class HistoryEditor:
    """Native history management, scoped to the hub's existing shared sessions."""
    def __init__(self, hub, migration):
        self.hub, self.migration = hub, migration
        self._jobs, self._busy = {}, set()
        self._lock = threading.RLock()

    def _path(self, sid):
        self.hub.resolve_session_id(sid)
        metadata = self.migration.tasks.client.read_thread_metadata(sid)
        path = native_path(metadata.get('path') or '')
        if not path.is_relative_to(native_path(self.migration.home / 'sessions')) or not path.is_file():
            raise ValueError('只能编辑本机原生 sessions 中的会话')
        return path

    def listing(self, sid, offset=0):
        from .history_rebuild import inspect_history
        return inspect_history(self._path(sid), sid, offset)

    def is_busy(self, sid):
        with self._lock:
            return sid in self._busy

    def status(self, sid, job_id):
        self.hub.resolve_session_id(sid)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job['session_id'] != sid:
                raise ValueError('删除任务不存在')
            return deepcopy(job)

    def start(self, sid, turn_ids, revision, source_ip, *, messages=False):
        if messages:
            if not isinstance(turn_ids, list) or not turn_ids or any(not isinstance(t, dict) or
                not isinstance(t.get('turn_id'), str) or not isinstance(t.get('item_id'), str) for t in turn_ids):
                raise ValueError('请选择单条消息记录')
            turn_ids = [dict(turn_id=t['turn_id'], item_id=t['item_id']) for t in turn_ids]
        elif not isinstance(turn_ids, list) or not turn_ids or any(not isinstance(t, str) or not t for t in turn_ids):
            raise ValueError('请选择完整轮次')
        if not isinstance(revision, str) or len(revision) != 64:
            raise ValueError('历史版本无效，请重新加载')
        self.hub.resolve_session_id(sid)
        with self._lock:
            if sid in self._busy:
                raise ValueError('当前会话正在清理，请等待完成')
            if len(self._jobs) >= 100:
                completed = next((key for key, job in self._jobs.items() if job['state'] in {'done', 'error'}), None)
                if completed:
                    self._jobs.pop(completed)
                else:
                    raise ValueError('清理任务过多，请稍后重试')
            jid = uuid4().hex
            self._busy.add(sid)
            self._jobs[jid] = {'id': jid, 'session_id': sid, 'state': 'running', 'message': '正在检查会话'}
        threading.Thread(target=self._run, args=(jid, sid, turn_ids, revision, source_ip, messages), daemon=True).start()
        return {'id': jid}

    def _run(self, jid, sid, turn_ids, revision, source_ip, messages=False):
        def update(**values):
            with self._lock:
                self._jobs[jid].update(values)
        service = None
        try:
            from .history_rebuild import inspect_history
            path = self._path(sid)
            inspection = inspect_history(path, sid)
            if inspection['compactions'] or path.stat().st_size > 32 * 1024 * 1024:
                with self.hub._service_create_lock:
                    _, service = self.hub._service(sid)
                self._run_rebuilt(sid, service, path, turn_ids, revision, source_ip, messages, update)
                return
            # Serialize creation/removal and all submissions/reconnections for this service.
            with self.hub._service_create_lock:
                _, service = self.hub._service(sid)
                with service._queued_lock:
                    path = self._path(sid)
                    original = path.read_bytes()
                    if hashlib.sha256(original).hexdigest() != revision:
                        raise ValueError('历史已变化，请重新加载后选择')
                    rows = [json.loads(line) for line in original.splitlines() if line.strip()]
                    client = self.migration.tasks.client
                    expected_items = None
                    if messages:
                        before = client.rpc.request('thread/read', {'threadId': sid, 'includeTurns': True}, timeout=60)['thread']
                        existing = {(t['id'], i['id']) for t in before.get('turns', []) for i in t.get('items', [])}
                        selected = {(r['turn_id'], r['item_id']) for r in turn_ids}
                        response_turns = {tid for tid, iid in selected if iid == '__response__'}
                        selected = {key for key in selected if key[1] != '__response__'}
                        for tid in response_turns:
                            response_items = {(t['id'], i['id']) for t in before.get('turns', []) if t['id'] == tid
                                for i in t.get('items', []) if i.get('type') != 'userMessage'}
                            if not response_items:
                                raise ValueError('所选 Codex 回复已变化或不存在，请重新加载')
                            selected.update(response_items)
                        process_turns = {tid for tid, iid in selected if iid == '__process__'}
                        selected = {key for key in selected if key[1] != '__process__'}
                        for tid in process_turns:
                            process_items = {(t['id'], i['id']) for t in before.get('turns', []) if t['id'] == tid
                                for i in t.get('items', []) if not (i.get('type') == 'userMessage' or
                                    (i.get('type') == 'agentMessage' and i.get('phase') != 'commentary'))}
                            if not process_items:
                                raise ValueError('所选查看过程已变化或不存在，请重新加载')
                            selected.update(process_items)
                        if not selected.issubset(existing):
                            raise ValueError('消息已变化，请重新加载')
                        native_items = {(t['id'], i['id']): i for t in before.get('turns', []) for i in t.get('items', [])}
                        turn_ids = [dict(r, _native=native_items.get((r['turn_id'], r['item_id']), {})) for r in turn_ids]
                        expected_items = [(t['id'], {k: v for k, v in i.items() if k != 'id'})
                            for t in before.get('turns', []) for i in t.get('items', []) if (t['id'], i['id']) not in selected]
                    expected = prepare_message_edit(rows, sid, turn_ids) if messages else prepare_history_edit(rows, sid, turn_ids)
                    retained = {r['payload']['turn_id'] for r in expected
                                if r.get('type') == 'event_msg' and r['payload'].get('type') == 'task_started'}
                    update(message='正在释放会话并备份')
                    resume_after = service.release_session(source_ip)
                    service._history_editing = True
                    def verify(_, session_id):
                        update(message='正在校验 Codex 原生历史')
                        client = self.migration.tasks.client
                        client.start()
                        native = client.rpc.request('thread/read', {'threadId': session_id, 'includeTurns': True}, timeout=60)['thread']
                        actual = {t['id'] for t in native.get('turns', [])}
                        actual_items = [(t['id'], {k: v for k, v in i.items() if k != 'id'})
                            for t in native.get('turns', []) for i in t.get('items', [])]
                        mismatch = actual_items != expected_items if messages else actual != retained
                        if mismatch:
                            raise ValueError('Codex 原生历史校验失败，已恢复文件')
                        service.projection.replace_thread(native)
                        service.projection.set_connection('released')
                    result = apply_history_edit(path, self.migration.home, sid, [] if messages else turn_ids,
                        writer_guard=native_writer_guard(self.migration.home, sid), verify=verify,
                        expected_revision=revision, selected_messages=turn_ids if messages else None)
            self._complete(service, source_ip, resume_after, result, '已删除并校验', update)
        except Exception as exc:
            update(state='error', message=str(exc))
        finally:
            if service is not None:
                with service._queued_lock:
                    service._history_editing = False
            with self._lock:
                self._busy.discard(sid)

    def _complete(self, service, source_ip, resume_after, result, message, update):
        result = dict(result, connection='released')
        if resume_after:
            update(message='历史已删除并校验，正在重新接管原 Session')
            try:
                service.reconnect_edited_session(source_ip)
                result['connection'] = 'connected'
            except Exception as exc:
                result['reconnect_error'] = str(exc)
        if result.get('reconnect_error'):
            message += '；删除成功，但重新接管失败，请重新连接：' + result['reconnect_error']
        elif result['connection'] == 'connected':
            message += '；已重新接管原 Session，可继续使用'
        else:
            message += '；保持删除前的释放状态'
        update(state='done', message=message, result=result)
        service._broadcast()

    def _run_rebuilt(self, sid, service, path, selection, revision, source_ip, messages, update):
        from .history_rebuild import apply_rebuilt_history
        from .history_native import native_history_signature
        def progress(message): update(message=message)
        # Do not hold the queue lock during IO: snapshots read queue_size while
        # holding the hub lock, so a long edit would otherwise block every session.
        with service._queued_lock:
            self.hub.resolve_session_id(sid)
            update(message='正在释放会话并读取原生分页记录')
            resume_after = service.release_session(source_ip)
            service._history_editing = True
        try:
            client = self.migration.tasks.client
            requested = selection if messages else []
            expected, native_records, _ = native_history_signature(client, sid,
                records=requested, deleted_turns=() if messages else selection)
            def verify(_, session_id):
                update(message='正在分页校验 Codex 原生历史与重建上下文')
                actual, _, turns = native_history_signature(client, session_id, retain=True)
                if actual != expected:
                    raise ValueError('Codex 原生历史校验失败，已恢复文件')
                metadata = client.read_thread_metadata(session_id)
                service.projection.replace_thread(dict(metadata, turns=turns))
                service.projection.set_connection('released')
            result = apply_rebuilt_history(path, self.migration.home, sid,
                records=native_records if messages else None, turn_ids=() if messages else selection,
                expected_revision=revision, writer_guard=native_writer_guard(self.migration.home, sid),
                verify=verify, progress=progress)
            self._complete(service, source_ip, resume_after, result,
                '已删除并重建近期上下文；旧摘要已清除，完整保留记录仍可查看', update)
        finally:
            with service._queued_lock:
                service._history_editing = False


def prepare_history_edit(rows, session_id, selected_turn_ids):
    selected = set(selected_turn_ids)
    if not selected:
        raise ValueError('请选择要删除的轮次')
    if not rows or rows[0].get('type') != 'session_meta' or rows[0].get('payload', {}).get('id') != session_id:
        raise ValueError('会话 ID 与历史文件不一致')
    groups, prefix = [], []
    seen_turn_ids = set()
    active = None
    for row in rows:
        payload = row.get('payload', {})
        event = payload.get('type')
        if row.get('type') == 'compacted' or event in {'thread_rolled_back', 'context_compacted'}:
            raise ValueError('含压缩或回退记录，尚不能安全清理；历史未修改')
        if row.get('type') == 'event_msg' and event == 'task_started':
            if active is not None:
                raise ValueError('历史轮次边界不完整')
            tid = payload.get('turn_id')
            if not tid or tid in seen_turn_ids:
                raise ValueError('历史轮次 ID 缺失或重复')
            seen_turn_ids.add(tid)
            active = [tid, [row]]
            groups.append(active)
        elif active is not None:
            active[1].append(row)
            if row.get('type') == 'event_msg' and event in {'task_complete', 'turn_aborted'}:
                if payload.get('turn_id') and payload.get('turn_id') != active[0]:
                    raise ValueError('历史结束记录与轮次不一致')
                active = None
        elif not groups:
            prefix.append(row)
        else:
            raise ValueError('存在轮次外记录，不能确定其归属')
    if active is not None:
        raise ValueError('存在未完成的轮次')
    if not selected.issubset(seen_turn_ids):
        raise ValueError('待删除轮次已变化，请重新加载')
    return deepcopy(prefix + [row for tid, group in groups if tid not in selected for row in group])

def prepare_message_edit(rows, session_id, records):
    """Delete only messages whose native event and model-input record map uniquely."""
    first = next((r['payload'].get('turn_id') for r in rows if r.get('type') == 'event_msg'
                  and r.get('payload', {}).get('type') == 'task_started'), None)
    prepare_history_edit(rows, session_id, [first])  # Validate completed, uncompressed boundaries.
    selected = {(r['turn_id'], r['item_id']) for r in records}
    if not selected:
        raise ValueError('请选择消息')
    groups, tid = {}, None
    for index, row in enumerate(rows):
        p = row.get('payload', {})
        if row.get('type') == 'event_msg' and p.get('type') == 'task_started':
            tid = p['turn_id']
        if tid: groups.setdefault(tid, []).append((index, row))
    removed, previews, found = set(), {}, set()
    response_turns = {tid for tid, iid in selected if iid == '__response__'}
    process_turns = {tid for tid, iid in selected if iid == '__process__'} | response_turns
    lifecycle = {'task_started', 'task_complete', 'turn_aborted', 'user_message', 'agent_message',
                 'token_count', 'thread_settings_applied'}
    for tid in process_turns:
        group = groups.get(tid)
        if group is None: raise ValueError('查看过程不存在')
        calls = {r['payload'].get('call_id') for _, r in group if r.get('type') == 'response_item'
                 and r.get('payload', {}).get('type') in {'function_call', 'custom_tool_call'}} - {None}
        outputs = {r['payload'].get('call_id') for _, r in group if r.get('type') == 'response_item'
                   and r.get('payload', {}).get('type') in {'function_call_output', 'custom_tool_call_output'}} - {None}
        if not outputs.issubset(calls) or any(r.get('type') == 'response_item' and r.get('payload', {}).get('call_id') in calls
            for other, entries in groups.items() if other != tid for _, r in entries):
            raise ValueError('查看过程存在跨轮工具关联，不能独立删除')
        for idx, row in group:
            p = row.get('payload', {})
            if row.get('type') == 'response_item' and (p.get('type') != 'message' or
                (p.get('role') == 'assistant' and p.get('phase') == 'commentary')): removed.add(idx)
            if row.get('type') == 'event_msg' and p.get('type') == 'agent_message' and p.get('phase') == 'commentary': removed.add(idx)
            if row.get('type') == 'event_msg' and p.get('type') not in lifecycle:
                if p.get('type') == 'item_completed':
                    item = p.get('item', {})
                    if item.get('type') == 'UserMessage' or (item.get('type') == 'AgentMessage' and item.get('phase') != 'commentary'): continue
                removed.add(idx)
        if (tid, '__process__') in selected: found.add((tid, '__process__'))
        if tid in response_turns:
            for idx, row in group:
                p = row.get('payload', {})
                if ((row.get('type') == 'response_item' and p.get('type') == 'message' and p.get('role') == 'assistant')
                    or (row.get('type') == 'event_msg' and (p.get('type') == 'agent_message'
                        or (p.get('type') == 'item_completed' and p.get('item', {}).get('type') == 'AgentMessage')))):
                    removed.add(idx)
                if row.get('type') == 'event_msg' and p.get('type') == 'task_complete':
                    previews.setdefault(tid, set()).add(p.get('last_agent_message'))
            found.add((tid, '__response__'))
    for tid, group in groups.items():
        for event_index, row in group:
            p = row.get('payload', {}); item = p.get('item', {})
            key = (tid, item.get('id'))
            if row.get('type') != 'event_msg' or p.get('type') != 'item_completed' or key not in selected:
                continue
            role = {'UserMessage': 'user', 'AgentMessage': 'assistant'}.get(item.get('type'))
            if role is None:
                raise ValueError('仅支持删除用户消息和 Codex 回复，工具记录不可单独删除')
            def text(content):
                if not isinstance(content, list) or any(not isinstance(b, dict) or b.get('type') not in
                    {'text', 'Text', 'input_text', 'output_text'} or not isinstance(b.get('text'), str) for b in content):
                    raise ValueError('该消息含非文本内容，尚不能安全独立删除')
                return ''.join(b['text'] for b in content)
            value = text(item.get('content'))
            candidates = []
            for idx, candidate in group:
                cp = candidate.get('payload', {})
                if candidate.get('type') == 'response_item' and cp.get('type') == 'message' and cp.get('role') == role:
                    try: matches = text(cp.get('content')) == value
                    except ValueError: matches = False
                    if matches: candidates.append(idx)
            exact = [idx for idx in candidates if rows[idx]['payload'].get('id') == item['id']]
            candidates = exact or candidates
            if len(candidates) != 1 or candidates[0] in removed:
                raise ValueError('消息与原生上下文无法唯一对应，未执行删除')
            # Older duplicate event formats require their own mapping; fail closed.
            if any(r.get('type') == 'event_msg' and r.get('payload', {}).get('type') in
                   {'user_message', 'agent_message'} for _, r in group):
                raise ValueError('旧格式消息暂不支持独立删除')
            removed.update((event_index, candidates[0])); found.add(key)
            if role == 'assistant': previews.setdefault(tid, set()).add(value)
    for record in records:
        key = (record['turn_id'], record['item_id'])
        if key in found: continue
        native = record.get('_native', {})
        role = {'userMessage': 'user', 'agentMessage': 'assistant'}.get(native.get('type'))
        if role is None: continue
        value = native.get('text') if role == 'assistant' else ''.join(
            b.get('text', '') for b in native.get('content', []) if b.get('type') == 'text')
        if not isinstance(value, str) or not value: continue
        group = groups.get(record['turn_id'], [])
        # Legacy APIs synthesize item-N IDs which change after deletion; bind
        # their native text to a unique source event and matching model message.
        event_type = 'user_message' if role == 'user' else 'agent_message'
        events = [idx for idx, row in group if row.get('type') == 'event_msg'
                  and row.get('payload', {}).get('type') == event_type and row['payload'].get('message') == value]
        responses = [idx for idx, row in group if row.get('type') == 'response_item'
            and row.get('payload', {}).get('type') == 'message' and row['payload'].get('role') == role
            and all(b.get('type') in {'input_text', 'output_text'} for b in row['payload'].get('content', []))
            and ''.join(b.get('text', '') for b in row['payload'].get('content', [])) == value]
        if len(events) != 1 or len(responses) != 1 or any(idx in removed for idx in events + responses):
            raise ValueError('消息与原生上下文无法唯一对应，未执行删除')
        removed.update(events + responses); found.add(key)
        if role == 'assistant': previews.setdefault(record['turn_id'], set()).add(value)
    if found != selected:
        raise ValueError('所选消息不存在或不支持独立删除，请重新加载')
    result = []; tid = None
    for idx, row in enumerate(rows):
        if idx in removed: continue
        row = deepcopy(row); p = row.get('payload', {})
        if row.get('type') == 'event_msg' and p.get('type') == 'task_started': tid = p['turn_id']
        if row.get('type') == 'event_msg' and p.get('type') == 'task_complete' and p.get('last_agent_message') in previews.get(tid, set()):
            p.pop('last_agent_message', None)
        result.append(row)
    return result


def apply_history_edit(path, home, session_id, selected_turn_ids, *, writer_guard, verify, expected_revision=None, selected_messages=None):
    """Apply only while caller holds Codex-compatible exclusive writer ownership.

    verify(path, session_id) must validate native history after replacement.
    Compacted and ambiguous histories remain deliberately unsupported.
    """
    import hashlib
    import json
    import os
    import tempfile
    from pathlib import Path
    from uuid import uuid4
    selected_turn_ids = frozenset(selected_turn_ids)
    path, home = native_path(path), native_path(home)
    if not path.is_relative_to(home / 'sessions') or not path.is_file():
        raise ValueError('只能修改本机 sessions 内的历史文件')
    with writer_guard:
        original = path.read_bytes()
        if expected_revision is not None and hashlib.sha256(original).hexdigest() != expected_revision:
            raise ValueError('历史已变化，请重新加载后选择')
        rows = [json.loads(line) for line in original.splitlines() if line.strip()]
        edited = prepare_message_edit(rows, session_id, selected_messages) if selected_messages is not None else prepare_history_edit(rows, session_id, selected_turn_ids)
        body = ''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in edited).encode('utf-8')
        backup_dir = home / 'history-edit-backups'
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / (uuid4().hex + '.jsonl')
        from .history_index import HistoryIndexEdit
        index = HistoryIndexEdit(home, session_id, backup)
        index.capture()
        with backup.open('xb') as stream:
            stream.write(original); stream.flush(); os.fsync(stream.fileno())
        fd, staged = tempfile.mkstemp(prefix='.history-edit-', dir=path.parent)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(body); stream.flush(); os.fsync(stream.fileno())
            if path.read_bytes() != original:
                raise ValueError('历史已发生变化，取消清理；原文件未覆盖')
            os.replace(staged, path)
            try:
                index.sync(path)
                verify(path, session_id)
            except Exception:
                if path.read_bytes() != body:
                    raise ValueError(f'校验失败且历史发生并发变化，未覆盖新数据；备份：{backup}')
                with open(staged, 'wb') as stream:
                    stream.write(original); stream.flush(); os.fsync(stream.fileno())
                os.replace(staged, path)
                index.restore()
                raise
            return {'session_id': session_id, 'backup': str(backup),
                    'deleted_turns': len(set(selected_turn_ids)),
                    'deleted_messages': len({(r['turn_id'], r['item_id']) for r in selected_messages}) if selected_messages is not None else 0,
                    'sha256': hashlib.sha256(body).hexdigest()}
        finally:
            Path(staged).unlink(missing_ok=True)
