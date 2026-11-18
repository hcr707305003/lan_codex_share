"""Portable native Codex rollout packages. Never copy credentials or databases."""
from io import BytesIO
from pathlib import Path
from datetime import datetime
from uuid import UUID, uuid4
import hashlib
import json
import os
import threading
import time
import secrets
import zipfile
import tempfile

from .project_profiles import project_key, validate as validate_profile

def archive_source(data):
    return BytesIO(data) if isinstance(data, bytes) else data


def iter_rows(data):
    with zipfile.ZipFile(archive_source(data)) as z, z.open('rollout.jsonl') as stream:
        for line in stream:
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict) or not isinstance(row.get('payload'), dict):
                    raise ValueError('会话历史格式无效')
                yield row


def unpack(data):
    try:
        with zipfile.ZipFile(archive_source(data)) as z:
            if sorted(z.namelist()) != ['manifest.json', 'rollout.jsonl']:
                raise ValueError('迁移包成员无效')
            if z.getinfo('manifest.json').file_size > 1024 * 1024:
                raise ValueError('迁移清单异常过大')
            manifest = json.loads(z.read('manifest.json'))
            digest = hashlib.sha256()
            with z.open('rollout.jsonl') as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
        if manifest.get('format') != 'lan-codex-session' or manifest.get('version') != 1:
            raise ValueError('不支持的迁移包版本')
        sid = str(UUID(manifest['id']))
        if digest.hexdigest() != manifest.get('sha256'):
            raise ValueError('迁移包校验失败')
        first = None
        for row in iter_rows(data):
            if first is None:
                first = row
        if not first or first.get('type') != 'session_meta' or first['payload']['id'] != sid:
            raise ValueError('会话历史与迁移清单不一致')
        datetime.fromisoformat(first['payload']['timestamp'].replace('Z', '+00:00'))
        if not isinstance(manifest.get('name'), str) or len(manifest['name']) > 200:
            raise ValueError('会话名称无效')
        profile = manifest.get('profile')
        if profile is not None:
            validate_profile(profile.get('alias'), profile.get('notice_markdown'), 0)
        return manifest, iter_rows(data)
    except (KeyError, TypeError, AttributeError, UnicodeError, zipfile.BadZipFile, RuntimeError) as exc:
        raise ValueError('迁移包格式无效或已损坏') from exc


class SessionMigration:
    def __init__(self, tasks, home=None, registration_client_factory=None, ownership_dir=None):
        self.registration_client_factory = registration_client_factory
        self.ownership_dir = Path(ownership_dir) if ownership_dir else None
        self.tasks = tasks
        self.home = Path(home or os.environ.get('CODEX_HOME') or Path.home()/'.codex').resolve()
        self.lock = threading.Lock()
        self._downloads = {}
        self._download_lock = threading.Lock()

    def prepare_download(self, sid):
        path = self.export(sid)
        token = secrets.token_hex(32)
        with self._download_lock:
            self._downloads[token] = (path, str(sid), time.monotonic() + 86400)
        timer = threading.Timer(86400, self._expire_download, args=(token,))
        timer.daemon = True
        timer.start()
        return {'url': '/api/migration/download/' + token,
                'name': 'codex-session-' + str(sid) + '.zip', 'size': path.stat().st_size}

    def _expire_download(self, token):
        with self._download_lock:
            entry = self._downloads.get(token)
            if entry is None:
                return
            try:
                entry[0].unlink(missing_ok=True)
            except OSError:
                timer = threading.Timer(60, self._expire_download, args=(token,))
                timer.daemon = True
                timer.start()
                return
            self._downloads.pop(token, None)

    def download(self, token):
        with self._download_lock:
            entry = self._downloads.get(token)
        if entry is None or entry[2] <= time.monotonic():
            raise ValueError('下载链接已过期，请重新导出')
        path, sid, _ = entry
        if sid not in self.tasks.shared_ids():
            raise ValueError('会话已移出共享，不能继续下载')
        return path, 'codex-session-' + sid + '.zip'

    def export(self, sid):
        try:
            sid = str(UUID(str(sid)))
        except ValueError as exc:
            raise ValueError('请选择有效的会话 ID') from exc
        if sid not in self.tasks.shared_ids():
            raise ValueError('只能导出共享任务中的会话；该会话未共享或已移出')
        if self.tasks.hub:
            info = next((s for s in self.tasks.hub.session_summaries() if s['thread_id'] == sid), {})
            if info.get('status') == 'processing' or info.get('queue_size'):
                raise ValueError('请等待任务和队列完成后再导出')
        thread = self.tasks.client.read_thread_metadata(sid)
        path = Path(thread.get('path') or '').resolve()
        if not path.is_relative_to(self.home/'sessions') or not path.is_file():
            raise ValueError('未找到本机原生会话文件，暂不支持远程 App Server 导出')
        manifest = dict(format='lan-codex-session', version=1, id=sid,
                        name=thread.get('name') or '导出会话', cwd=thread.get('cwd'))
        profiles = getattr(self.tasks.hub, 'profiles', None)
        if profiles is not None:
            profile = profiles.get(project_key(thread.get('cwd') or ''))
            manifest['profile'] = {k: profile[k] for k in ('alias', 'notice_markdown')}
        fd, name = tempfile.mkstemp(prefix='codex-migration-', suffix='.zip')
        os.close(fd)
        out = Path(name)
        try:
            digest = hashlib.sha256()
            before = path.stat()
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as z:
                with path.open('rb') as src, z.open('rollout.jsonl', 'w', force_zip64=True) as dst:
                    while chunk := src.read(1024 * 1024):
                        digest.update(chunk)
                        dst.write(chunk)
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                    raise ValueError('会话历史正在变化，请结束任务后再导出')
                manifest['sha256'] = digest.hexdigest()
                z.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
            unpack(out)
            return out
        except Exception:
            out.unlink(missing_ok=True)
            raise

    def inspect(self, data):
        manifest, _ = unpack(data)
        return {k: manifest[k] for k in ('id', 'name', 'cwd')}

    def restore(self, data, project, *, as_copy=False):
        if type(as_copy) is not bool:
            raise ValueError('导入模式无效')
        manifest, rows = unpack(data)
        if not isinstance(project, str) or project not in {p['cwd'] for p in self.tasks.projects()['items']}:
            raise ValueError('请选择目标电脑已有项目目录；请先在 Codex 中打开该项目')
        cwd = str(Path(project).resolve())
        sid = str(uuid4()) if as_copy else manifest['id']
        name = (manifest['name'][:95] + '（副本）') if as_copy else manifest['name']
        with self.lock:
            # Refuse ambiguous read errors instead of treating them as absence.
            existing = self.tasks.client.list_threads(max_items=10000)
            if any(t['id'] == sid for t in existing) or any((self.home/'sessions').rglob('*'+sid+'*.jsonl')) or any((self.home/'archived_sessions').rglob('*'+sid+'*.jsonl')):
                raise ValueError('目标电脑已有同 ID 会话，不会覆盖')
            if self.tasks.config_store:
                with self.tasks.config_store.mutation(self.tasks.shared_ids(), True):
                    pass
            meta = next(iter_rows(data))['payload']
            date = datetime.fromisoformat(meta['timestamp'].replace('Z', '+00:00'))
            target = self.home/'sessions'/date.strftime('%Y/%m/%d')/('rollout-'+date.strftime('%Y-%m-%dT%H-%M-%S')+'-'+sid+'.jsonl')
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('x', encoding='utf-8') as f:
                for row in rows:
                    if as_copy and row['type'] == 'session_meta':
                        row['payload']['id'] = sid
                        if 'session_id' in row['payload']:
                            row['payload']['session_id'] = sid
                    if row['type'] in ('session_meta', 'turn_context'):
                        row['payload']['cwd'] = cwd
                        row['payload'].pop('project_id', None)
                        row['payload'].pop('projectId', None)
                    f.write(json.dumps(row, ensure_ascii=False)+'\n')
            client = self.registration_client_factory() if self.registration_client_factory else self.tasks.client
            try:
                client.start()
                result = client.rpc.request('thread/resume', {'threadId':sid,'path':str(target),
                    'cwd':cwd,'approvalPolicy':'never','sandbox':client.sandbox_mode}, timeout=60)
                if result['thread']['id'] != sid:
                    raise ValueError('Codex 返回了不同的会话 ID')
                client.rename_thread(sid, name)
                client.rpc.request('thread/unsubscribe', {'threadId':sid}, timeout=15)
                entry = client.read_thread_metadata(sid)
                if self.registration_client_factory:
                    client.close()
                if self.ownership_dir:
                    self.ownership_dir.mkdir(parents=True, exist_ok=True)
                    (self.ownership_dir / sid).touch()
                self.tasks._cache_until = 0
                result = self.tasks._persist_entry(entry, True)
                profiles = getattr(getattr(self.tasks, 'hub', None), 'profiles', None)
                if profiles is not None and manifest.get('profile'):
                    key = project_key(cwd)
                    previous = profiles.get(key)
                    if previous['revision'] == 0:
                        profiles.save(key, manifest['profile']['alias'], manifest['profile']['notice_markdown'], 0)
                return result
            except Exception as exc:
                # Native indexing may already have succeeded. Do not delete its
                # backing file or replay an import blindly after RPC timeout.
                raise ValueError(f'会话文件已导入（{sid}），登记或共享未完成；请在已有会话中查找此 ID，不要重复导入') from exc
            finally:
                if self.registration_client_factory:
                    client.close()
