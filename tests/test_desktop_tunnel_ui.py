import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time

import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop import external_monitor, tunnel_monitor, window as window_module
from lan_codex_share.desktop.external_share import ExternalState
from lan_codex_share.desktop.external_tunnels import TunnelState, TunnelIdentity


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def settle(app, window):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if not (window.tunnels.scanning or window.external.scanning or window.components.busy or window.starting):
            return
        time.sleep(.005)
    raise AssertionError('UI did not settle')


@pytest.fixture
def ui(app, tmp_path, monkeypatch):
    path = tmp_path / 'lan_config.toml'
    path.write_text('workspace="."\nport=9000\n', encoding='utf-8')
    states = {name: TunnelState('stopped', '未发现外部运行实例') for name in ('frpc', 'Tunnel')}
    monkeypatch.setattr(external_monitor, 'inspect_share', lambda _: ExternalState('stopped', '已停止'))
    monkeypatch.setattr(tunnel_monitor, 'inspect_tunnels', lambda _: dict(states))
    monkeypatch.setattr(window_module, 'inspect_tunnels', lambda _: dict(states))
    window = window_module.DesktopWindow(path)
    settle(app, window)
    yield window, states
    settle(app, window)
    window.close()


@pytest.mark.parametrize('name', ['frpc', 'Tunnel'])
@pytest.mark.parametrize('status', ['running', 'unverified', 'unknown', 'multiple', 'transition'])
def test_external_states_block_duplicate_starts_and_never_stop(ui, app, monkeypatch, name, status):
    window, states = ui
    states[name] = TunnelState(status, 'Windows 服务运行中 · PID 100\n配置未确认 · 公网连接未验证', (100,))
    window.tunnels.scan()
    settle(app, window)
    assert 'PID 100' in window.status_labels[name].text()
    assert not window.buttons[name].isEnabled()
    assert '已停止' not in window.statusBar().currentMessage().split(name + ': ')[1].split(' · ')[0]
    monkeypatch.setattr(window.services[name], 'start', lambda *a, **kw: pytest.fail('duplicate start'))
    monkeypatch.setattr(window.services[name], 'stop', lambda: pytest.fail('external stop'))
    window.toggle_service(name)
    window.close()
    assert window.tunnels.closed


@pytest.mark.parametrize('name', ['frpc', 'Tunnel'])
def test_fresh_check_before_launch(ui, app, monkeypatch, name):
    window, states = ui
    window.available[name] = True
    states[name] = TunnelState('unverified', '检测到外部实例')
    monkeypatch.setattr(window.services[name], 'start', lambda *a, **kw: pytest.fail('duplicate start'))
    monkeypatch.setattr(window, 'command', lambda _: pytest.fail('should check before preparing command'))
    window.toggle_service(name)
    settle(app, window)
    assert '未启动新隧道' in window.failures[name]


def test_owned_process_status_wins(ui, app, monkeypatch):
    window, states = ui
    states['Tunnel'] = TunnelState('unverified', '外部实例')
    window.tunnels.scan()
    settle(app, window)
    service = window.services['Tunnel']
    owned = {**service.snapshot(), 'running': True}
    with monkeypatch.context() as patch:
        patch.setattr(service, 'snapshot', lambda: owned)
        window.refresh()
        assert window.buttons['Tunnel'].text() == '停止服务'
        assert window.buttons['Tunnel'].isEnabled()
        assert '外部实例' not in window.status_labels['Tunnel'].text()


def test_external_disappearance_restores_controls(ui, app):
    window, states = ui
    states['frpc'] = TunnelState('unverified', '外部实例')
    window.tunnels.scan()
    settle(app, window)
    states['frpc'] = TunnelState('stopped', '未发现外部运行实例')
    window.tunnels.scan()
    settle(app, window)
    assert window.buttons['frpc'].isEnabled()
    assert window.buttons['frpc'].text() in ('启动服务', '安装 / 选择程序')


@pytest.mark.parametrize('accepted', [True, False])
def test_verified_external_frpc_close_button(ui, app, monkeypatch, accepted):
    window, states = ui
    identity = TunnelIdentity(100, 10, 'frpc.exe', ('frpc.exe', '-c', 'frpc.toml'), window.config_path.parent / 'frpc.toml')
    states['frpc'] = TunnelState('running', '外部 FRP', (100,), identity)
    window.tunnels.scan()
    settle(app, window)
    assert window.buttons['frpc'].text() == '关闭外部 FRP…'
    assert window.buttons['frpc'].isEnabled()
    calls=[]
    monkeypatch.setattr(window_module, 'confirm_stop', lambda *args, **kwargs: accepted)
    monkeypatch.setattr(window.tunnels, 'close_frpc', lambda value: calls.append(value) or True)
    window.buttons['frpc'].click()
    assert calls == ([identity] if accepted else [])
    assert window.services['Share'].snapshot()['running'] is False


def test_external_frpc_close_in_background_ignores_old_scan(app, tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    identity = TunnelIdentity(100, 10, 'frpc.exe', (), tmp_path / 'frpc.toml')
    monitor = tunnel_monitor.ExternalTunnelMonitor(object())
    monitor.states['frpc'] = TunnelState('running', '外部', (100,), identity)
    messages=[]
    monitor.completed.connect(messages.append)
    def close(settings, selected):
        entered.set()
        assert release.wait(3)
        return '已关闭'
    monkeypatch.setattr(tunnel_monitor, 'close_external_frpc', close)
    monkeypatch.setattr(tunnel_monitor, 'inspect_tunnels', lambda _: {n:TunnelState('stopped', '已停止') for n in ('frpc', 'Tunnel')})
    assert monitor.close_frpc(identity)
    assert entered.wait(1)
    assert monitor.busy
    assert not monitor.close_frpc(identity)
    monitor.finish(0, 'scan', {})
    assert monitor.states['frpc'].identity == identity
    release.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline and (monitor.busy or monitor.scanning):
        app.processEvents()
        time.sleep(.005)
    assert messages == ['已关闭']
    assert monitor.states['frpc'].status == 'stopped'
    monitor.close()


def test_entry_buttons_open_only_on_click_and_refresh_after_save(ui, monkeypatch):
    window, _ = ui
    opened = []
    monkeypatch.setattr(window_module.QDesktopServices, 'openUrl', lambda url: opened.append(url.toString()))
    assert not opened
    window.entry_buttons['Share'].click()
    assert opened == ['http://localhost:9000']
    assert not window.entry_buttons['frpc'].isEnabled()
    window.config_path.write_text('workspace="."\nport=9001\ncloudflare_origin="https://share.example.invalid"\n', encoding='utf-8')
    window.configuration_saved(window.config_path)
    assert '9001' in window.entry_labels['Share'].text()
    window.entry_buttons['Tunnel'].click()
    assert opened[-1] == 'https://share.example.invalid'


@pytest.mark.parametrize('accept', [True, False])
def test_owned_stop_dialog_keeps_control_boundary(ui, monkeypatch, accept):
    window, _ = ui
    service = window.services['frpc']
    snapshot = {**service.snapshot(), 'running': True}
    calls = []
    with monkeypatch.context() as patch:
        patch.setattr(service, 'snapshot', lambda: snapshot)
        patch.setattr(window_module, 'confirm_stop', lambda *a, **kw: accept)
        patch.setattr(service, 'stop', lambda: calls.append('stop'))
        window.toggle_service('frpc')
    assert calls == (['stop'] if accept else [])


def test_window_exit_confirmation_only_stops_owned_services(ui, monkeypatch):
    window, states = ui
    states['Tunnel'] = TunnelState('running', 'Windows 服务运行中')
    service = window.services['frpc']
    snapshot = {**service.snapshot(), 'running': True}
    stopped = []
    with monkeypatch.context() as patch:
        patch.setattr(service, 'snapshot', lambda: snapshot)
        patch.setattr(window_module, 'confirm_stop', lambda *a, **kw: True)
        # ServiceProcess.stop is a no-op for unowned/stopped services.
        patch.setattr(service, 'stop', lambda: stopped.append('frpc'))
        window.close()
    assert stopped == ['frpc']
    window.exiting = False


def test_late_scan_result_ignored_on_close(app, tmp_path, monkeypatch):
    entered, release, done = threading.Event(), threading.Event(), threading.Event()
    def scan(_):
        entered.set()
        assert release.wait(3)
        done.set()
        return {n: TunnelState('running', 'late') for n in ('frpc', 'Tunnel')}
    monkeypatch.setattr(tunnel_monitor, 'inspect_tunnels', scan)
    monitor = tunnel_monitor.ExternalTunnelMonitor(object())
    calls = []
    monitor.changed.connect(lambda: calls.append(True))
    monitor.start()
    assert entered.wait(2)
    monitor.scan()  # overlapping timer requests must not start another job
    monitor.close()
    release.set()
    assert done.wait(2)
    for _ in range(10):
        app.processEvents()
        time.sleep(.005)
    assert not calls
    assert all(s.status == 'checking' for s in monitor.states.values())
