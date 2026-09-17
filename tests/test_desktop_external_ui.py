import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import threading
import time

import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop import external_monitor, window as window_module
from lan_codex_share.desktop.external_share import ExternalState, ShareIdentity


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def settle(app, window):
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        app.processEvents()
        if not (window.components.busy or window.external.scanning or window.external.busy or window.starting):
            return
        time.sleep(.005)
    raise AssertionError('UI jobs did not finish')


@pytest.fixture
def ui(app, tmp_path, monkeypatch):
    from lan_codex_share.desktop import tunnel_monitor
    from lan_codex_share.desktop.external_tunnels import TunnelState
    monkeypatch.setattr(tunnel_monitor, 'inspect_tunnels', lambda _: {n: TunnelState('stopped', '未发现外部运行实例') for n in ('frpc', 'Tunnel')})
    path = tmp_path / 'lan_config.toml'
    path.write_text('workspace="."\nport=9000\n', encoding='utf-8')
    identity = ShareIdentity(1234, 100, path, 'python.exe', ('python.exe', '-m', 'lan_codex_share'))
    state = [ExternalState('running', '运行中（外部启动）\nPID 1234', identity)]
    monkeypatch.setattr(external_monitor, 'inspect_share', lambda _: state[0])
    monkeypatch.setattr(window_module, 'inspect_share', lambda _: state[0])
    monkeypatch.setattr(external_monitor, 'force_close_share', lambda _: pytest.fail('unexpected external termination'))
    window = window_module.DesktopWindow(path)
    settle(app, window)
    yield window, state, identity
    settle(app, window)
    window.close()


def test_external_status_cancel_and_normal_window_close_never_kill(ui, monkeypatch):
    window, state, identity = ui
    assert '外部启动' in window.status_labels['Share'].text()
    assert window.buttons['Share'].text() == '强制关闭…'
    prompts = []
    def deny(*args, **kwargs):
        prompts.append((args, kwargs))
        return False
    monkeypatch.setattr(window_module, 'confirm_stop', deny)
    window.toggle_service('Share')
    assert len(prompts) == 1
    assert prompts[0][1]['force']
    assert str(identity.pid) in prompts[0][1]['details']
    assert not window.external.busy
    window.close()
    assert window.external.closed


def test_confirmed_force_is_async_blocks_repeated_clicks_and_updates(ui, app, monkeypatch):
    window, state, identity = ui
    release = threading.Event()
    calls = []
    def force(target):
        calls.append(target)
        assert release.wait(3)
        state[0] = ExternalState('stopped', '已停止')
        return '测试实例已关闭'
    monkeypatch.setattr(external_monitor, 'force_close_share', force)
    monkeypatch.setattr(window_module, 'confirm_stop', lambda *a, **kw: True)
    window.toggle_service('Share')
    try:
        assert window.external.busy
        assert not window.buttons['Share'].isEnabled()
        window.toggle_service('Share')
    finally:
        release.set()
    settle(app, window)
    assert calls == [identity]
    assert window.buttons['Share'].text() == '启动服务'
    assert any('测试实例已关闭' in row for row in window.logs.filtered())
    assert all(not process.snapshot()['running'] for process in window.services.values())


@pytest.mark.parametrize('status', ['occupied', 'unknown', 'ambiguous', 'checking'])
def test_unverified_status_disables_start_and_force(ui, app, status):
    window, state, _ = ui
    state[0] = ExternalState(status, '不可操作')
    window.external.scan()
    settle(app, window)
    assert not window.buttons['Share'].isEnabled()
    assert window.status_labels['Share'].text() == '不可操作'


def test_stale_stopped_status_rechecked_before_launch(ui, app, monkeypatch):
    window, _, _ = ui
    window.external.state = ExternalState('stopped', '已停止')
    monkeypatch.setattr(window.services['Share'], 'start', lambda *a, **kw: pytest.fail('duplicate launch'))
    window.toggle_service('Share')
    settle(app, window)
    assert '未启动新 Share' in window.failures['Share']


def test_identity_change_during_confirmation_is_not_accepted(ui, monkeypatch):
    window, _, _ = ui
    def confirm(*args, **kwargs):
        window.external.state = ExternalState('stopped', '已停止')
        return True
    monkeypatch.setattr(window_module, 'confirm_stop', confirm)
    window.toggle_service('Share')
    assert not window.external.busy
