from pathlib import Path
from types import SimpleNamespace
import json

import psutil
import pytest

from lan_codex_share.desktop import external_share as external
from lan_codex_share import share_instance as records


class Process:
    def __init__(self, pid, config, *, args=None, executable='python.exe', created=100, cwd=None):
        self.pid = pid
        self.info = {'name': Path(executable).name}
        self.args = args if args is not None else ['python.exe', '-m', 'lan_codex_share', '--config', str(config)]
        self.executable = executable
        self.created = created
        self.directory = str(cwd or config.parent)
        self.ancestors = []
        self.killed = False
        self.denied = False
        self.timeout = False

    def exe(self): return self.executable
    def cwd(self): return self.directory
    def cmdline(self): return self.args
    def create_time(self): return self.created
    def parents(self): return self.ancestors
    def is_running(self): return not self.killed
    def kill(self):
        if self.denied:
            raise psutil.AccessDenied(self.pid)
        self.killed = True
    def wait(self, timeout):
        if self.timeout:
            raise psutil.TimeoutExpired(timeout, self.pid)


@pytest.fixture
def world(tmp_path, monkeypatch):
    config = tmp_path / 'lan_config.toml'
    processes = {}
    listeners = []
    monkeypatch.setattr(external, 'load_lan_config', lambda p: SimpleNamespace(port=9000))
    monkeypatch.setattr(psutil, 'process_iter', lambda *a, **kw: list(processes.values()))
    monkeypatch.setattr(psutil, 'net_connections', lambda **kw: [
        SimpleNamespace(pid=pid, status=psutil.CONN_LISTEN, laddr=SimpleNamespace(port=9000)) for pid in listeners])

    def lookup(pid=None):
        pid = 10 if pid is None else pid
        if pid not in processes or processes[pid].killed:
            raise psutil.NoSuchProcess(pid)
        return processes[pid]
    monkeypatch.setattr(psutil, 'Process', lookup)
    return config, processes, listeners


@pytest.mark.parametrize('mode', ['module', 'share', 'script', 'frozen', 'worker', 'frozen-worker'])
def test_supported_explicit_entries(world, mode):
    config, processes, listeners = world
    argv = {
        'module': ['python.exe', '-u', '-m', 'lan_codex_share', '--config', config.name],
        'share': ['python.exe', '-m', 'lan_codex_share', 'share', f'--config={config}'],
        'script': ['python.exe', 'run_lan_codex_share.py', '--config', config.name],
        'frozen': ['lan_codex_share.exe', '--config', str(config)],
        'worker': ['python.exe', '-u', '-m', 'lan_codex_share.desktop.worker', str(config)],
        'frozen-worker': ['lan_codex_share.exe', '_desktop-worker', str(config)],
    }[mode]
    proc = Process(10, config, args=argv, executable=argv[0])
    processes[10] = proc
    listeners.append(10)
    result = external.inspect_share(config)
    assert result.status == 'running'
    assert result.identity.config_path == config


@pytest.mark.parametrize('args', [
    ['-m', 'lan_codex_share', 'cli', '--config', 'lan_config.toml'],
    ['-c', 'import lan_codex_share'],
    ['-m', 'lan_codex_share.desktop.app'],
    ['-m', 'lan_codex_share', '--help'],
    ['other.py', '--config', 'lan_config.toml'],
])
def test_not_a_share_entry(world, args):
    config, processes, _ = world
    processes[10] = Process(10, config, args=['python.exe', *args])
    assert external.inspect_share(config).status == 'stopped'


def test_default_config_and_unknown_module_location(world):
    config, processes, _ = world
    p = Process(10, config, args=['python.exe', '-m', 'lan_codex_share'])
    processes[10] = p
    assert external.inspect_share(config).status == 'unknown'
    package = config.parent / 'lan_codex_share'
    package.mkdir()
    (package / 'launcher.py').touch()
    assert external.inspect_share(config).identity.config_path == config
    p.args = ['python.exe', '-I', '-m', 'lan_codex_share']
    assert external.inspect_share(config).identity is None
    p.executable = str(config.parent / 'lan_codex_share.exe')
    p.args = [p.executable]
    assert external.inspect_share(config).identity.config_path == config


def test_starting_port_conflict_ambiguity_and_wrong_config(world):
    config, processes, listeners = world
    processes[10] = Process(10, config)
    assert external.inspect_share(config).status == 'starting'
    listeners.append(99)
    assert external.inspect_share(config).identity is None
    assert external.inspect_share(config).status == 'occupied'
    listeners.clear()
    processes[11] = Process(11, config)
    assert external.inspect_share(config).status == 'ambiguous'
    processes.clear()
    processes[10] = Process(10, config.parent / 'other.toml')
    assert external.inspect_share(config).status == 'stopped'


def test_venv_launcher_is_not_second_instance(world):
    config, processes, listeners = world
    parent = Process(10, config)
    child = Process(11, config, executable='other/python.exe', created=101)
    child.args = ['other/python.exe', *parent.args[1:]]
    child.ancestors = [parent]
    processes.update({10: parent, 11: child})
    listeners.append(11)
    assert external.inspect_share(config).identity.pid == 11


def test_permission_failure_never_returns_stopped(world, monkeypatch):
    config, processes, _ = world
    processes[10] = Process(10, config)
    monkeypatch.setattr(processes[10], 'cmdline', lambda: (_ for _ in ()).throw(psutil.AccessDenied(10)))
    assert external.inspect_share(config).status == 'unknown'
    monkeypatch.setattr(psutil, 'net_connections', lambda **kw: (_ for _ in ()).throw(psutil.AccessDenied()))
    assert external.inspect_share(config).identity is None


def test_force_old_instance_kills_only_confirmed_share(world):
    config, processes, _ = world
    p = processes[10] = Process(10, config)
    business = processes[20] = Process(20, config, args=['php.exe', 'start.php'], executable='php.exe')
    business.ancestors = [p]
    identity = external.inspect_share(config).identity
    assert '未验证' in external.force_close_share(identity)
    assert p.killed and not business.killed
    assert '已退出' in external.force_close_share(identity)


@pytest.mark.parametrize('change', ['pid-reuse', 'command', 'multiple', 'denied', 'timeout'])
def test_force_revalidates_and_reports_failure(world, change):
    config, processes, _ = world
    p = processes[10] = Process(10, config)
    identity = external.inspect_share(config).identity
    if change == 'pid-reuse': p.created += 1
    if change == 'command': p.args = ['python.exe', 'business.py']
    if change == 'multiple': processes[11] = Process(11, config)
    if change == 'denied': p.denied = True
    if change == 'timeout': p.timeout = True
    with pytest.raises(ValueError):
        external.force_close_share(identity)
    assert p.killed is (change == 'timeout')


def setup_record(world):
    config, processes, _ = world
    p = processes[10] = Process(10, config)
    endpoint = 'ws://127.0.0.1:4500'
    child = processes[20] = Process(20, config, executable='codex.exe', created=102,
                                   args=['codex.exe', 'app-server', '--listen', endpoint])
    child.ancestors = [p]
    host = SimpleNamespace(endpoint=endpoint, reusing_existing=False, _owned_processes=[child])
    records.write_instance(config, host, 9000)
    return p, child, external.inspect_share(config).identity


def test_record_only_verified_owned_appserver_is_killed(world):
    p, child, identity = setup_record(world)
    assert '已处理' in external.force_close_share(identity)
    assert p.killed and child.killed


@pytest.mark.parametrize('change', ['reused', 'stale', 'child-reused', 'business', 'unrelated', 'wrong-endpoint', 'no-record'])
def test_record_cannot_authorize_unverified_appserver(world, change):
    p, child, identity = setup_record(world)
    path = records.instance_path(identity.config_path)
    data = json.loads(path.read_text())
    if change == 'reused': data['reused'] = True
    if change == 'stale': data['created'] = 1
    if change == 'child-reused': child.created += 1
    if change == 'business': child.executable = 'php.exe'
    if change == 'unrelated': child.ancestors = []
    if change == 'wrong-endpoint': child.args[-1] = 'ws://127.0.0.1:4501'
    path.write_text(json.dumps(data))
    if change == 'no-record': path.unlink()
    external.force_close_share(identity)
    assert p.killed and not child.killed


def test_record_cleanup_only_removes_own_record(world):
    _, _, identity = setup_record(world)
    path = records.instance_path(identity.config_path)
    data = json.loads(path.read_text())
    data['created'] = 1
    path.write_text(json.dumps(data))
    records.remove_instance(identity.config_path)
    assert path.exists()
    data['created'] = identity.created
    path.write_text(json.dumps(data))
    records.remove_instance(identity.config_path)
    assert not path.exists()


def test_appserver_permission_failure_is_reported(world):
    p, child, identity = setup_record(world)
    child.denied = True
    message = external.force_close_share(identity)
    assert p.killed and not child.killed
    assert '未能关闭' in message


@pytest.mark.parametrize('change', ['command', 'executable'])
def test_appserver_command_change_after_parent_stop_not_killed(world, monkeypatch, change):
    p, child, identity = setup_record(world)
    def kill_parent():
        p.killed = True
        if change == 'command':
            child.args = ['php.exe', 'start.php']
        else:
            child.executable = 'php.exe'
    monkeypatch.setattr(p, 'kill', kill_parent)
    assert '未能关闭' in external.force_close_share(identity)
    assert not child.killed


def test_runtime_record_omits_unrelated_descendants_and_reused_servers(world):
    config, processes, _ = world
    p = processes[10] = Process(10, config)
    child = Process(20, config, args=['php.exe', 'start.php'], executable='php.exe')
    child.ancestors = [p]
    host = SimpleNamespace(endpoint='ws://127.0.0.1:4500', reusing_existing=False, _owned_processes=[child])
    records.write_instance(config, host, 9000)
    data = json.loads(records.instance_path(config).read_text())
    assert data['app_servers'] == []
    assert set(data) == {'pid', 'created', 'config', 'port', 'endpoint', 'reused', 'app_servers'}
    host.reusing_existing = True
    records.write_instance(config, host, 9000)
    assert json.loads(records.instance_path(config).read_text())['reused'] is True
