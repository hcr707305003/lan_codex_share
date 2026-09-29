"""Shared human-readable project metadata; never part of a Codex prompt."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import unicodedata


def project_key(cwd: str) -> str:
    if not cwd or not cwd.strip():
        return ''
    try:
        return os.path.normcase(str(Path(cwd).expanduser().resolve()))
    except (OSError, ValueError):
        return os.path.normcase(cwd)


class ProfileConflict(ValueError):
    pass


def validate(alias, notice, revision):
    if not isinstance(alias, str) or len(alias) > 100 or any(unicodedata.category(c) == 'Cc' for c in alias):
        raise ValueError('别名最多 100 字符，不能包含换行或控制字符')
    if not isinstance(notice, str) or len(notice.encode('utf-8')) > 65536:
        raise ValueError('Markdown 公告不能超过 64 KiB')
    if type(revision) is not int or revision < 0:
        raise ValueError('资料版本无效，请重新加载')


class ProjectProfiles:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()
        self._projects = {}
        self._error = None
        try:
            if path.exists():
                data = json.loads(path.read_text(encoding='utf-8'))
                if not isinstance(data, dict) or data.get('version') != 1 or not isinstance(data.get('projects'), dict):
                    raise ValueError('无效格式')
                for key, record in data['projects'].items():
                    if not isinstance(key, str) or not key or not isinstance(record, dict):
                        raise ValueError('无效记录')
                    validate(record.get('alias'), record.get('notice_markdown'), record.get('revision'))
                    if not isinstance(record.get('updated_at'), str):
                        raise ValueError('无效时间')
                self._projects = data['projects']
        except (OSError, ValueError, UnicodeError):
            self._error = '项目资料文件无法读取或已损坏，请备份并修复后重启服务'

    def get(self, key):
        with self._lock:
            if self._error:
                raise ValueError(self._error)
            return deepcopy(self._projects.get(key, {
                'alias': '', 'notice_markdown': '', 'revision': 0, 'updated_at': '',
            }))

    def save(self, key, alias, notice_markdown, revision):
        validate(alias, notice_markdown, revision)
        with self._lock:
            previous = self.get(key)
            if previous['revision'] != revision:
                raise ProfileConflict('资料已被其他人更新；当前编辑已保留，请重新加载后再修改')
            record = dict(alias=alias.strip(), notice_markdown=notice_markdown,
                          revision=revision + 1, updated_at=datetime.now(timezone.utc).isoformat())
            projects = {**self._projects, key: record}
            temp = self.path.with_suffix('.tmp')
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with temp.open('w', encoding='utf-8') as stream:
                    json.dump({'version': 1, 'projects': projects}, stream, ensure_ascii=False)
                    stream.flush()
                    os.fsync(stream.fileno())
                temp.replace(self.path)
            except OSError as exc:
                raise ValueError('项目资料保存失败，请检查磁盘权限与空间后重试') from exc
            self._projects = projects
            return deepcopy(record)
