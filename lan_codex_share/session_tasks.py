"""Explicit sharing and creation, separate from the active conversation."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import threading
import time
from uuid import UUID


def session_id(value):
    if not isinstance(value, str) or len(value.strip()) != 36:
        raise ValueError("请输入完整的 Session ID")
    try:
        return str(UUID(value.strip()))
    except ValueError as exc:
        raise ValueError("Session ID 格式无效") from exc


def metadata(raw):
    return {key: raw.get(key) for key in (
        'id', 'name', 'cwd', 'projectId', 'updatedAt', 'createdAt', 'recencyAt', 'status'
    ) if key in raw}


class SessionTasks:
    def __init__(self, path, client, workspace, register, shared_ids):
        self.path = Path(path)
        self.client = client
        self.workspace = Path(workspace).resolve()
        self.register = register
        self.shared_ids = shared_ids
        self._lock = threading.RLock()
        self._cache_lock = threading.Lock()
        self._cache = []
        self._cache_until = 0
        self._error = None
        self._state = {'version': 1, 'session_ids': [], 'requests': {}}
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding='utf-8'))
                if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('session_ids'), list) or not isinstance(data.get('requests'), dict):
                    raise ValueError()
                data['session_ids'] = list(dict.fromkeys(session_id(sid) for sid in data['session_ids']))
                for rid, record in data['requests'].items():
                    session_id(rid)
                    if not isinstance(record, dict) or not isinstance(record.get('project'), str):
                        raise ValueError()
                    if record.get('session_id'):
                        session_id(record['session_id'])
                self._state = data
        except (ValueError, OSError, TypeError):
            self._error = '共享列表文件无法读取，请检查 runtime/lan/shared_sessions.json；原文件未覆盖'

    def _check(self):
        if self._error:
            raise ValueError(self._error)

    def _save(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix('.tmp')
        with temp.open('w', encoding='utf-8') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temp.replace(self.path)
        self._state = data

    def _write(self, data):
        try:
            self._save(data)
        except OSError as exc:
            raise ValueError('共享列表保存失败，请检查文件写入权限和磁盘空间') from exc

    def _threads(self):
        with self._cache_lock:
            if time.monotonic() >= self._cache_until:
                try:
                    self._cache = [metadata(t) for t in self.client.list_threads(max_items=10000)
                                   if not t.get('archived') and not t.get('ephemeral') and not t.get('parentThreadId')]
                except Exception as exc:
                    raise ValueError('无法读取已有会话列表，请稍后重试') from exc
                self._cache_until = time.monotonic() + 30
            return deepcopy(self._cache)

    def candidates(self, query='', cursor=None):
        if not isinstance(query, str) or len(query) > 200:
            raise ValueError('搜索内容过长')
        try:
            offset = int(cursor or 0)
        except (ValueError, TypeError) as exc:
            raise ValueError('候选分页位置无效') from exc
        if not 0 <= offset <= 10000:
            raise ValueError('候选分页位置无效')
        query = query.strip().casefold()
        rows = [t for t in self._threads() if not query or query in str(t.get('name', '')).casefold() or query in str(t.get('id', '')).casefold()]
        shared = set(self.shared_ids())
        items = [dict(t, shared=t['id'] in shared) for t in rows[offset:offset + 50]]
        return {'items': items, 'next_cursor': str(offset + 50) if offset + 50 < len(rows) else None}

    def projects(self):
        # Configuration/current shared projects remain usable if listing is unavailable.
        warning = None
        try:
            rows = self._threads()
        except ValueError as exc:
            rows, warning = [], str(exc)
        paths = {self.workspace: [str(self.workspace)]}
        for row in rows:
            raw = row.get('cwd')
            if isinstance(raw, str) and raw.strip():
                try:
                    path = Path(raw).expanduser().resolve()
                    if path.is_dir():
                        paths.setdefault(path, []).append(raw)
                except (OSError, ValueError):
                    continue
        return {'items': [{'cwd': str(p), 'name': p.name or str(p), 'aliases': list(dict.fromkeys(aliases))}
                          for p, aliases in paths.items() if p.is_dir()], 'warning': warning}

    def _read(self, sid):
        try:
            raw = self.client.read_thread_metadata(sid)
            if raw.get('id') != sid or raw.get('archived') or raw.get('ephemeral') or raw.get('parentThreadId'):
                raise ValueError()
            cwd = raw.get('cwd')
            if not isinstance(cwd, str) or not cwd.strip() or not Path(cwd).is_dir():
                raise ValueError()
            return metadata(raw)
        except Exception as exc:
            raise ValueError('会话不存在、不可读取、已归档或工作目录不可用') from exc

    def restore(self):
        with self._lock:
            self._check()
            for sid in self._state['session_ids']:
                try:
                    entry = self._read(sid)
                except ValueError as exc:
                    entry = {'id': sid, 'name': sid, 'error': str(exc)}
                self.register(entry)

    def add(self, value):
        sid = session_id(value)
        with self._lock:
            self._check()
            if sid in self.shared_ids():
                return {'session_id': sid, 'already_shared': True}
            entry = self._read(sid)
            return self._persist_entry(entry)

    def _persist_entry(self, entry):
        sid = entry['id']
        already_shared = sid in self.shared_ids()
        data = deepcopy(self._state)
        if sid not in data['session_ids']:
            data['session_ids'].append(sid)
        self._write(data)
        self.register(entry)
        return {'session_id': sid, 'already_shared': already_shared}

    def create(self, project, request_id):
        rid = session_id(request_id)
        if not isinstance(project, str) or not project.strip():
            raise ValueError('请选择项目工作目录')
        with self._lock:
            self._check()
            record = self._state['requests'].get(rid)
            if record:
                if record['project'] != project:
                    raise ValueError('重试请求的项目不一致，请重新打开新任务')
                if not record.get('session_id'):
                    raise ValueError('创建结果不确定，请刷新已有会话列表确认；不会自动重复创建')
                if record['session_id'] in self._state['session_ids'] and record['session_id'] in self.shared_ids():
                    return {'session_id': record['session_id'], 'already_shared': True}
                return self._persist_entry(self._read(record['session_id']))
            if project not in {p['cwd'] for p in self.projects()['items']}:
                raise ValueError('工作目录不在已有项目中或已不可用')
            if len(self._state['requests']) >= 10000:
                raise ValueError('创建记录已达上限，请维护共享列表文件')
            data = deepcopy(self._state)
            data['requests'][rid] = {'project': project, 'status': 'pending'}
            self._write(data)
            try:
                entry = metadata(self.client.create_thread(Path(project)))
                sid = session_id(entry.get('id'))
            except Exception as exc:
                raise ValueError('创建结果不确定，请刷新已有会话列表确认；不会自动重复创建') from exc
            data = deepcopy(self._state)
            data['requests'][rid].update(status='created', session_id=sid)
            # Keep a known ID even if disk fails; same-process retries must not create again.
            self._state = data
            self._cache_until = 0
            try:
                self._write(data)
                # A fresh empty thread may not yet be readable via thread/read.
                # Use the authoritative thread/start result, never create a second thread.
                entry['cwd'] = project
                entry['name'] = entry.get('name') or '新会话'
                result = self._persist_entry(entry)
            except ValueError as exc:
                raise ValueError(f'会话已创建（{sid}），共享保存失败；请使用此 ID 添加已有会话') from exc
            return result

    def close(self):
        self.client.close()
