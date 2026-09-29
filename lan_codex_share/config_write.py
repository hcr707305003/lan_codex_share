"""Shared desktop/server config write coordination; never logs file contents."""
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import tempfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def config_lock(path):
    path = Path(path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_name(path.name + '.lock').open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError('配置正在被其他操作保存，请稍后重试') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def replace_config(path, text, expected):
    """Caller holds config_lock. Check external edits again before replace."""
    path = Path(path)
    fd, name = tempfile.mkstemp(prefix='.share-config-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='') as stream:
            stream.write(text); stream.flush(); os.fsync(stream.fileno())
        if digest(path) != expected:
            raise ValueError('配置已被外部修改，请重新加载后重试')
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


class SessionConfigStore:
    def __init__(self, path):
        self.path = Path(path).resolve()

    def read(self):
        from .lan_config import load_lan_config
        config = load_lan_config(self.path)
        mode = 'auto' if config.auto_session else 'all' if config.discover_all_sessions else 'selected'
        return mode, list(config.session_ids or ())

    @contextmanager
    def mutation(self, current_ids, confirmed=False):
        import tomlkit
        try:
            with config_lock(self.path):
                before = digest(self.path)
                mode, ids = self.read()
                if mode != 'selected' and confirmed is not True:
                    raise ValueError('请先确认将当前共享名单固定为指定会话模式')
                if mode != 'selected':
                    ids = list(dict.fromkeys(current_ids))
                document = tomlkit.parse(self.path.read_text(encoding='utf-8-sig'))
                def save(values):
                    document.pop('session_id', None)
                    document['session_mode'] = 'selected'
                    document['session_ids'] = list(dict.fromkeys(values))
                    replace_config(self.path, tomlkit.dumps(document), before)
                yield ids, save
        except OSError:
            raise ValueError('共享配置保存失败，请检查写入权限和磁盘空间') from None
