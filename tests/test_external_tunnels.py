from types import SimpleNamespace

import psutil
import pytest

from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop import external_tunnels as detection


class Process:
    def __init__(self, root, name, args, pid=100):
        self.pid = pid
        self.info = {'name': name}
        self.binary = str(root / name)
        self.args = [self.binary, *args]
        self.root = root
        self.live = True
        self.created = 10
        self.denied = False

    def exe(self):
        if self.denied:
            raise psutil.AccessDenied(self.pid)
        return self.binary

    def cmdline(self):
        return self.args[:]

    def cwd(self):
        return str(self.root)

    def create_time(self):
        return self.created

    def is_running(self):
        return self.live


@pytest.fixture
def world(tmp_path, monkeypatch):
    processes, services = [], []
    settings = DesktopSettings(tmp_path / 'lan_config.toml')
    monkeypatch.setattr(detection.psutil, 'process_iter', lambda *a: iter(processes))
    monkeypatch.setattr(detection, 'windows_services', lambda: services)
    def add(name, *args, pid=100):
        process = Process(tmp_path, name, args, pid)
        processes.append(process)
        return process
    return SimpleNamespace(settings=settings, add=add, processes=processes, services=services, root=tmp_path)


@pytest.mark.parametrize('name,args,key', [
    ('frpc.exe', ['-c', 'frpc.toml'], 'frpc'),
    ('frpc', ['--config=frpc.toml'], 'frpc'),
    ('frpc_windows_amd64.exe', ['--config', './frpc.toml'], 'frpc'),
    ('cloudflared.exe', ['tunnel', '--config', 'cloudflared.yml', 'run'], 'Tunnel'),
    ('cloudflared-linux-arm64', ['--no-autoupdate', 'tunnel', 'run', '--config=cloudflared.yml'], 'Tunnel'),
])
def test_matching_config(world, name, args, key):
    world.add(name, *args)
    result = detection.inspect_tunnels(world.settings)[key]
    assert result.status == 'running'
    assert result.pids == (100,)
    assert '连接未验证' in result.message


@pytest.mark.parametrize('name,args', [
    ('frps.exe', ['-c', 'frpc.toml']),
    ('frpc.exe', ['--version']), ('frpc.exe', ['verify', '-c', 'frpc.toml']),
    ('frpc.exe', ['status', '-c', 'frpc.toml']),
    ('cloudflared.exe', ['tunnel', 'run', '--help']),
    ('cloudflared.exe', ['tunnel', 'list']),
    ('cloudflared.exe', ['access', 'tcp', '--hostname', 'example.invalid']),
    ('cloudflared.exe', ['service', 'install', 'test-secret']),
    ('python.exe', ['cloudflared', 'tunnel', 'run']),
])
def test_non_runtime_commands_excluded(world, name, args):
    world.add(name, *args)
    assert all(s.status == 'stopped' for s in detection.inspect_tunnels(world.settings).values())


@pytest.mark.parametrize('name,args,key', [
    ('frpc.exe', [], 'frpc'),
    ('frpc.exe', ['-c', 'different.toml'], 'frpc'),
    ('cloudflared.exe', ['tunnel', 'run', '--token', 'test-secret'], 'Tunnel'),
    ('cloudflared.exe', ['tunnel', '--url', 'http://localhost:9000'], 'Tunnel'),
    ('cloudflared.exe', ['tunnel', 'run'], 'Tunnel'),
])
def test_unmatched_or_implicit_config_is_not_claimed_current(world, name, args, key):
    world.add(name, *args)
    result = detection.inspect_tunnels(world.settings)[key]
    assert result.status == 'unverified'
    assert '配置未确认' in result.message
    assert 'test-secret' not in repr(result)


def test_token_file_matches_path_without_reading_content(world):
    world.settings.save({'cloudflared_mode': 'token-file', 'cloudflared_token_file': 'missing-token.txt'})
    world.add('cloudflared.exe', 'tunnel', 'run', '--token-file', 'missing-token.txt')
    assert detection.inspect_tunnels(world.settings)['Tunnel'].status == 'running'


def test_windows_service_associated_by_live_pid_and_not_name(world):
    world.add('cloudflared.exe', 'tunnel', 'run', '--token', 'test-secret')
    world.services.append({'name': 'custom-service', 'pid': 100, 'status': 'running'})
    result = detection.inspect_tunnels(world.settings)['Tunnel']
    assert result.status == 'unverified'
    assert 'Windows 服务' in result.message and '100' in result.message
    assert 'test-secret' not in repr(result)


@pytest.mark.parametrize('status', ['start_pending', 'stop_pending', 'paused'])
def test_service_transition_with_no_pid_blocks_start(world, status):
    world.services.append({'name': 'Cloudflared', 'pid': 0, 'status': status})
    assert detection.inspect_tunnels(world.settings)['Tunnel'].status == 'transition'


def test_running_service_without_verified_process_is_unknown(world):
    world.services.append({'name': 'Cloudflared', 'pid': 999, 'status': 'running'})
    assert detection.inspect_tunnels(world.settings)['Tunnel'].status == 'unknown'


def test_stopped_service_does_not_block(world):
    world.services.append({'name': 'Cloudflared', 'pid': 0, 'status': 'stopped'})
    assert detection.inspect_tunnels(world.settings)['Tunnel'].status == 'stopped'


def test_multiple_and_denied_are_not_stopped(world):
    world.add('frpc.exe', '-c', 'frpc.toml')
    world.add('frpc.exe', '-c', 'other.toml', pid=101)
    denied = world.add('cloudflared.exe', 'tunnel', 'run', pid=102)
    denied.denied = True
    result = detection.inspect_tunnels(world.settings)
    assert result['frpc'].status == 'multiple'
    assert result['Tunnel'].status == 'unknown'


@pytest.mark.parametrize('change', ['exit', 'pid', 'argv', 'exe'])
def test_changing_process_does_not_report_stable_running(world, monkeypatch, change):
    process = world.add('frpc.exe', '-c', 'frpc.toml')
    def changed_services():
        if change == 'exit':
            process.live = False
        elif change == 'pid':
            process.created = 11
        elif change == 'argv':
            process.args.append('--version')
        else:
            process.binary = str(world.root / 'other.exe')
        return []
    monkeypatch.setattr(detection, 'windows_services', changed_services)
    assert detection.inspect_tunnels(world.settings)['frpc'].status == 'unknown'


def test_service_access_failure_blocks_both(world, monkeypatch):
    def denied():
        raise psutil.AccessDenied()
    monkeypatch.setattr(detection, 'windows_services', denied)
    assert all(s.status == 'unknown' for s in detection.inspect_tunnels(world.settings).values())


def test_non_windows_does_not_query_service_api(monkeypatch):
    monkeypatch.setattr(detection.platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(detection.psutil, 'win_service_iter', lambda: pytest.fail('Windows API on Linux'), raising=False)
    assert detection.windows_services() == []


def test_windows_adapter_reads_only_safe_service_fields(monkeypatch):
    monkeypatch.setattr(detection.platform, 'system', lambda: 'Windows')
    service = SimpleNamespace(name=lambda: 'Cloudflared', pid=lambda: 100, status=lambda: 'running')
    monkeypatch.setattr(detection.psutil, 'win_service_iter', lambda: iter([service]), raising=False)
    assert detection.windows_services() == [{'name': 'Cloudflared', 'pid': 100, 'status': 'running'}]
