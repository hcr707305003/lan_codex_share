"""Tunnel discovery and narrowly verified external FRP termination. No credential output."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import platform
import re

import psutil


@dataclass(frozen=True)
class TunnelIdentity:
    pid: int
    created_at: float
    executable: str
    argv: tuple[str, ...] = field(repr=False)
    config_path: Path


@dataclass(frozen=True)
class TunnelState:
    status: str
    message: str
    pids: tuple[int, ...] = ()
    identity: TunnelIdentity | None = None


def component_name(name):
    match = re.fullmatch(r'(frpc|cloudflared)(?:[-_](?:windows|linux|darwin)[-_](?:amd64|arm64|386))?(?:\.exe)?', name.lower())
    return ('frpc' if match[1] == 'frpc' else 'Tunnel') if match else None


def windows_services():
    if platform.system() != 'Windows':
        return []
    result = []
    for service in psutil.win_service_iter():
        try:
            # Never as_dict(): binpath may contain a plaintext tunnel token.
            result.append({'name': service.name(), 'pid': service.pid(), 'status': service.status()})
        except psutil.NoSuchProcess:
            continue
    return result


def run_config(component, args):
    """Return (option, path) for a runtime, None for non-runtime commands.

    Only paths are compared. Missing values or repeated options make
    configuration ownership uncertain, never authorize a new process launch.
    """
    words, options = [], {}
    uncertain = False
    flags = {'--no-autoupdate', '--no-tls-verify'}
    i = 0
    while i < len(args):
        arg = args[i]
        i += 1
        if arg in ('--help', '-h', '--version', '-v'):
            return None
        if not arg.startswith('-'):
            words.append(arg)
            continue
        key, equal, value = arg.partition('=')
        if key in flags:
            continue
        if not equal:
            if i >= len(args) or args[i].startswith('-'):
                uncertain = True
                continue
            value = args[i]
            i += 1
        if key in options:
            uncertain = True
        options[key] = value
    if component == 'frpc':
        if words:
            return None  # verify/status/reload/... are not the long-lived client.
        paths = [options[k] for k in ('-c', '--config') if k in options]
        return ('config', paths[0]) if len(paths) == 1 and not uncertain else ('', '')
    if not (words[:2] == ['tunnel', 'run'] and len(words) <= 3):
        if words == ['tunnel'] and '--url' in options:
            return '', ''  # Quick tunnel: active, but not the configured named tunnel.
        return None
    if uncertain or '--token' in options or '--url' in options:
        return '', ''
    if '--token-file' in options:
        return 'token-file', options['--token-file']
    return ('config', options['--config']) if '--config' in options else ('', '')


def _fingerprint(process):
    return process.create_time(), process.exe(), tuple(process.cmdline())


def inspect_tunnels(settings):
    keys = ('frpc', 'Tunnel')
    uncertain = set()
    candidates = {key: [] for key in keys}
    try:
        values = settings.load()
        targets = {'frpc': ('config', settings.resolve(values['frpc_config']))}
        token_mode = values['cloudflared_mode'] == 'token-file'
        value = values['cloudflared_token_file'] if token_mode else values['cloudflared_config']
        targets['Tunnel'] = ('token-file' if token_mode else 'config', settings.resolve(value) if value else None)
        for process in psutil.process_iter(['name']):
            key = component_name(process.info.get('name') or '')
            if key is None:
                continue
            try:
                fingerprint = _fingerprint(process)
                if component_name(Path(fingerprint[1]).name) != key:
                    uncertain.add(key)
                    continue
                config = run_config(key, fingerprint[2][1:])
                if config is None:
                    continue
                matches = False
                if config[1]:
                    path = Path(config[1]).expanduser()
                    if not path.is_absolute():
                        path = Path(process.cwd()) / path
                    matches = (config[0], path.resolve()) == targets[key]
                candidates[key].append((process, fingerprint, matches))
            except (psutil.Error, OSError, ValueError):
                uncertain.add(key)
        services = windows_services()
    except (psutil.Error, OSError, ValueError):
        return {key: TunnelState('unknown', '无法验证外部隧道，请检查权限或配置') for key in keys}

    result = {}
    for key in keys:
        found = candidates[key]
        pids = tuple(sorted(p.pid for p, _, _ in found))
        relevant = [s for s in services if (s['pid'] and s['pid'] in pids) or component_name(s['name']) == key]
        for process, fingerprint, _ in found:
            try:
                if not process.is_running() or _fingerprint(process) != fingerprint:
                    uncertain.add(key)
            except (psutil.Error, OSError):
                uncertain.add(key)
        active = [s for s in relevant if s['status'] != 'stopped']
        transition = any(s['status'] != 'running' for s in active)
        if any(s['status'] == 'running' and s['pid'] not in pids for s in active):
            uncertain.add(key)
        if key in uncertain:
            result[key] = TunnelState('unknown', '外部实例无法验证，请检查权限或等待重试', pids)
        elif transition:
            result[key] = TunnelState('transition', 'Windows 服务正在切换状态或已暂停\n请在服务管理器检查', pids)
        elif len(found) > 1:
            result[key] = TunnelState('multiple', '检测到多个外部实例，请检查\nPID ' + ', '.join(map(str, pids)), pids)
        elif found:
            matches = found[0][2]
            source = 'Windows 服务运行中' if any(s['pid'] == pids[0] for s in active) else '外部进程运行中'
            detail = '当前配置' if matches else '配置未确认'
            identity = None
            if key == 'frpc' and matches and not any(s['pid'] == pids[0] for s in active):
                fingerprint = found[0][1]
                identity = TunnelIdentity(pids[0], *fingerprint, targets[key][1])
            if key == 'frpc' and any(s['pid'] == pids[0] for s in active):
                detail += ' · 请在 Windows 服务管理器启停'
            result[key] = TunnelState('running' if matches else 'unverified',
                                      f'{source} · PID {pids[0]}\n{detail} · 公网连接未验证', pids, identity)
        else:
            result[key] = TunnelState('stopped', '未发现外部运行实例')
    return result


def close_external_frpc(settings, identity):
    """Called only after explicit UI confirmation; never terminate descendants."""
    if not isinstance(identity, TunnelIdentity):
        raise ValueError('没有可验证的外部 FRP 身份，请重新检测')
    current = inspect_tunnels(settings)['frpc']
    if current.status != 'running' or current.identity != identity:
        raise ValueError('外部 FRP 身份或配置已变化，已取消关闭，请重新检测')
    try:
        process = psutil.Process(identity.pid)
        fingerprint = _fingerprint(process)
        config = run_config('frpc', fingerprint[2][1:])
        if config is None or not config[1]:
            raise ValueError('FRP 启动配置已变化，已取消关闭')
        path = Path(config[1]).expanduser()
        if not path.is_absolute():
            path = Path(process.cwd()) / path
        if (not process.is_running() or fingerprint != (identity.created_at, identity.executable, identity.argv)
                or path.resolve() != identity.config_path):
            raise ValueError('FRP 进程身份已变化，已取消关闭')
        # psutil.terminate also checks PID reuse. Never use process-name or tree kills.
        process.terminate()
        try:
            process.wait(timeout=5)
        except psutil.TimeoutExpired:
            return '已请求关闭外部 FRP，但进程尚未退出；请重新检测或手动检查，不会自动强杀'
        return f'已关闭外部 FRP · PID {identity.pid}；Share 未关闭'
    except psutil.NoSuchProcess:
        return '外部 FRP 已退出，请重新检测'
    except (psutil.AccessDenied, OSError):
        raise ValueError('没有权限关闭外部 FRP，请使用原启动终端或服务管理器') from None
