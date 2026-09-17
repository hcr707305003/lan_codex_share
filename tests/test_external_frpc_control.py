import psutil
import pytest
from tests.test_external_tunnels import world
from lan_codex_share.desktop import external_tunnels as detection


def test_matching_identity_and_close_only_target(world, monkeypatch):
    process = world.add('frpc.exe', '-c', 'frpc.toml')
    calls = []
    monkeypatch.setattr(process, 'terminate', lambda: calls.append('terminate'), raising=False)
    monkeypatch.setattr(process, 'wait', lambda timeout: calls.append(('wait', timeout)), raising=False)
    monkeypatch.setattr(detection.psutil, 'Process', lambda pid: process)
    state = detection.inspect_tunnels(world.settings)['frpc']
    assert state.identity.pid == process.pid
    assert '已关闭' in detection.close_external_frpc(world.settings, state.identity)
    assert calls == ['terminate', ('wait', 5)]


@pytest.mark.parametrize('change', ['pid_reused', 'config', 'multiple', 'service', 'permission'])
def test_changed_identity_never_terminated(world, monkeypatch, change):
    process = world.add('frpc.exe', '-c', 'frpc.toml')
    identity = detection.inspect_tunnels(world.settings)['frpc'].identity
    assert identity is not None
    monkeypatch.setattr(process, 'terminate', lambda: pytest.fail('must not terminate'), raising=False)
    monkeypatch.setattr(detection.psutil, 'Process', lambda pid: process)
    if change == 'pid_reused':
        process.created += 1
    elif change == 'config':
        world.settings.save({'frpc_config': 'other.toml'})
    elif change == 'multiple':
        world.add('frpc.exe', '-c', 'frpc.toml', pid=101)
    elif change == 'service':
        world.services.append({'name':'custom-frp', 'pid':process.pid, 'status':'running'})
    else:
        process.denied = True
    with pytest.raises(ValueError):
        detection.close_external_frpc(world.settings, identity)


def test_fingerprint_rechecked_immediately_before_terminate(world, monkeypatch):
    process = world.add('frpc.exe', '-c', 'frpc.toml')
    identity = detection.inspect_tunnels(world.settings)['frpc'].identity
    def lookup(pid):
        process.created += 1
        return process
    monkeypatch.setattr(detection.psutil, 'Process', lookup)
    monkeypatch.setattr(process, 'terminate', lambda: pytest.fail('must not terminate'), raising=False)
    with pytest.raises(ValueError):
        detection.close_external_frpc(world.settings, identity)


def test_no_cloudflare_identity_and_no_secret_in_repr(world):
    process = world.add('frpc.exe', '-c', 'frpc.toml', '--token', 'test-secret')
    state = detection.inspect_tunnels(world.settings)['frpc']
    assert state.identity is not None
    assert 'test-secret' not in repr(state)
    world.add('cloudflared.exe', 'tunnel', '--config', 'cloudflared.yml', 'run', pid=101)
    assert detection.inspect_tunnels(world.settings)['Tunnel'].identity is None


def test_timeout_reports_without_force_kill(world, monkeypatch):
    process = world.add('frpc.exe', '-c', 'frpc.toml')
    calls=[]
    monkeypatch.setattr(process, 'terminate', lambda: calls.append('terminate'), raising=False)
    def wait(timeout):
        raise psutil.TimeoutExpired(timeout, process.pid)
    monkeypatch.setattr(process, 'wait', wait, raising=False)
    monkeypatch.setattr(detection.psutil, 'Process', lambda pid: process)
    identity = detection.inspect_tunnels(world.settings)['frpc'].identity
    assert '未退出' in detection.close_external_frpc(world.settings, identity)
    assert calls == ['terminate']
