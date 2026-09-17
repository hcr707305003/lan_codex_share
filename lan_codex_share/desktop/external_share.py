"""Read-only external discovery; termination requires an exact confirmed identity."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

import psutil

from ..lan_config import load_lan_config


@dataclass(frozen=True)
class ShareIdentity:
    pid: int
    created: float
    config_path: Path
    executable: str
    argv: tuple[str, ...]


@dataclass(frozen=True)
class ExternalState:
    status: str
    message: str
    identity: ShareIdentity | None = None


def _python(name):
    return re.fullmatch(r'pythonw?(?:\d+(?:\.\d+)*)?(?:\.exe)?', name.lower()) is not None


def process_config(process):
    """Return config only for known Share entry points, never substring matches."""
    executable = Path(process.exe())
    args = list(process.cmdline())[1:]
    isolated = '-I' in args[:args.index('-m')] if '-m' in args else False
    default = None
    cwd = None

    def absolute(value):
        nonlocal cwd
        path = Path(value).expanduser()
        if path.is_absolute():
            return path.resolve()
        if cwd is None:
            cwd = Path(process.cwd())
        return (cwd / path).resolve()

    if _python(executable.name):
        while args and args[0] in ('-u', '-B', '-E', '-s', '-S', '-I'):
            args.pop(0)
        if len(args) >= 2 and args[0] == '-m':
            module, args = args[1], args[2:]
            if module == 'lan_codex_share.desktop.worker':
                return absolute(args[0]) if len(args) == 1 else None
            if module not in ('lan_codex_share', 'lan_codex_share.lan_main'):
                return None
            # Explicit config does not depend on Python module search paths.
            if not args or args == ['share']:
                root = Path(process.cwd())
                if module == 'lan_codex_share' and (isolated or not (root / 'lan_codex_share/launcher.py').is_file()):
                    raise ValueError('无法确认模块默认配置目录')
                default = root / 'lan_config.toml'
        elif args and Path(args[0]).name == 'run_lan_codex_share.py':
            script = absolute(args.pop(0))
            default = script.parent / 'lan_config.toml'
        else:
            return None
    elif executable.name.lower() in ('lan_codex_share', 'lan_codex_share.exe'):
        default = executable.parent / 'lan_config.toml'
    else:
        return None
    if args and args[0] == '_desktop-worker':
        return absolute(args[1]) if len(args) == 2 else None
    if args and args[0] == 'share':
        args.pop(0)
    if not args:
        return default.resolve() if default else None
    if len(args) == 2 and args[0] == '--config':
        return absolute(args[1])
    if len(args) == 1 and args[0].startswith('--config=') and args[0][9:]:
        return absolute(args[0][9:])
    return None


def identity_of(process):
    config = process_config(process)
    if config is None:
        return None
    return ShareIdentity(process.pid, process.create_time(), config,
                         process.exe(), tuple(process.cmdline()))


def inspect_share(config_path):
    config_path = Path(config_path).resolve()
    try:
        port = load_lan_config(config_path).port
    except (OSError, ValueError):
        return ExternalState('invalid', '配置不可用，请先编辑配置')
    candidates = []
    unknown = False
    try:
        for process in psutil.process_iter(['name']):
            name = (process.info.get('name') or '').lower()
            if not (_python(name) or name in ('lan_codex_share', 'lan_codex_share.exe')):
                continue
            try:
                identity = identity_of(process)
                if identity and identity.config_path == config_path:
                    candidates.append((process, identity))
            except psutil.NoSuchProcess:
                continue
            except (psutil.AccessDenied, OSError, ValueError):
                unknown = True
        listeners = {c.pid for c in psutil.net_connections(kind='tcp')
                     if c.status == psutil.CONN_LISTEN and c.laddr.port == port}
    except (psutil.Error, OSError):
        return ExternalState('unknown', '无法验证进程或监听端口，请检查权限')
    # Windows venv/one-file launchers may retain an identical waiting parent.
    wrappers = set()
    try:
        for process, identity in candidates:
            parents = {p.pid for p in process.parents()}
            for _, other in candidates:
                same_runtime = (other.executable == identity.executable or
                                (_python(Path(other.executable).name) and _python(Path(identity.executable).name)))
                if (other.pid in parents and same_runtime and other.argv[1:] == identity.argv[1:]
                        and other.pid not in listeners):
                    wrappers.add(other.pid)
    except psutil.NoSuchProcess:
        return ExternalState('checking', '进程状态正在变化，等待重新检测')
    except psutil.AccessDenied:
        return ExternalState('unknown', '无法验证进程父子关系，请检查权限')
    candidates = [(p, i) for p, i in candidates if i.pid not in wrappers]
    if len(candidates) > 1:
        return ExternalState('ambiguous', '发现多个匹配的 Share 实例，请手动检查')
    if candidates:
        _, identity = candidates[0]
        if listeners and listeners != {identity.pid}:
            return ExternalState('occupied', '配置端口被其他进程占用，无法确认 Share 监听身份')
        status = 'running' if identity.pid in listeners else 'starting'
        text = '运行中' if status == 'running' else '启动中 / 尚未监听'
        return ExternalState(status, f'{text}（外部启动）\nPID {identity.pid}', identity)
    if listeners:
        return ExternalState('occupied', '端口被其他程序占用或进程身份无法确认')
    if unknown:
        return ExternalState('unknown', '部分候选进程无法验证，请检查权限')
    return ExternalState('stopped', '已停止')


def force_close_share(identity):
    """Called only after UI confirmation. Never acts on a port or name alone."""
    from ..share_instance import verified_app_servers

    try:
        process = psutil.Process(identity.pid)
        if not process.is_running():
            return '外部 Share 已退出。'
        if identity_of(process) != identity:
            raise ValueError('进程身份已改变，已取消强制关闭，请重新检测')
        current = inspect_share(identity.config_path)
        if current.identity != identity:
            raise ValueError('检测结果已改变或无法确认唯一实例，已取消强制关闭')
        children, note = verified_app_servers(identity)
        if identity_of(process) != identity or not process.is_running():
            raise ValueError('进程身份已改变，已取消强制关闭')
        process.kill()
        process.wait(timeout=5)
    except psutil.NoSuchProcess:
        return '外部 Share 已退出。'
    except psutil.AccessDenied:
        raise ValueError('没有权限关闭该 Share，未尝试关闭关联进程') from None
    except psutil.TimeoutExpired:
        raise ValueError('Share 关闭超时，请重新检测；未关闭关联进程') from None
    failures = 0
    for child, command in children:
        try:
            # Stored psutil handles protect against PID reuse; do not rediscover descendants.
            if child.is_running():
                if (child.exe(), tuple(child.cmdline())) != command:
                    failures += 1
                    continue
                child.kill()
                child.wait(timeout=2)
        except psutil.NoSuchProcess:
            pass
        except (psutil.AccessDenied, psutil.TimeoutExpired):
            failures += 1
    suffix = '部分关联 App Server 未能关闭，请手动检查。' if failures else note
    return f'已强制关闭外部 Share（PID {identity.pid}）。{suffix}'
