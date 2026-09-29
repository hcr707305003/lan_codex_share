import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from types import SimpleNamespace
from unittest.mock import Mock
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop import window as module
from lan_codex_share.desktop.close_dialog import CloseDialog


@pytest.fixture
def state(monkeypatch):
    app = QApplication.instance() or QApplication([])
    service = Mock()
    service.snapshot.return_value = {'running': True, 'timed_out': False}
    window = SimpleNamespace(
        choosing_close=False, exiting=False, exit_requested=False,
        external=SimpleNamespace(busy=False, close=Mock()),
        tunnels=SimpleNamespace(busy=False, close=Mock()),
        confirming_external=False, confirming_frpc=False, starting=set(),
        config_page=SimpleNamespace(discard=Mock(return_value=True)),
        components=SimpleNamespace(busy=False, discard=Mock(return_value=True), cancel=Mock()),
        services={'frpc': service}, tray=Mock(), hide=Mock(),
        timer=Mock(), logs=Mock())
    monkeypatch.setattr(module.QSystemTrayIcon, 'isSystemTrayAvailable', lambda: True)
    yield app, window, service


def choose(monkeypatch, result):
    monkeypatch.setattr(CloseDialog, '__init__', lambda self, parent, available: None)
    monkeypatch.setattr(CloseDialog, 'exec', lambda self: result)


def test_background_keeps_services_drafts_and_monitors(state, monkeypatch):
    _, window, service = state
    choose(monkeypatch, CloseDialog.BACKGROUND)
    event = Mock()
    module.DesktopWindow.closeEvent(window, event)
    window.tray.show.assert_called_once()
    window.hide.assert_called_once()
    event.ignore.assert_called_once()
    service.stop.assert_not_called()
    window.config_page.discard.assert_not_called()
    window.components.cancel.set.assert_not_called()
    window.timer.stop.assert_not_called()
    window.external.close.assert_not_called()


def test_cancel_does_nothing(state, monkeypatch):
    _, window, service = state
    choose(monkeypatch, CloseDialog.Rejected)
    module.DesktopWindow.closeEvent(window, Mock())
    service.stop.assert_not_called()
    window.hide.assert_not_called()


def test_exit_stops_only_owned_services_then_cleans_up(state, monkeypatch):
    _, window, service = state
    window.exit_requested = True
    monkeypatch.setattr(module, 'confirm_stop', lambda *a, **kw: True)
    event = Mock()
    module.DesktopWindow.closeEvent(window, event)
    service.stop.assert_called_once()
    assert window.exiting
    event.accept.assert_not_called()
    service.snapshot.return_value = {'running': False}
    module.DesktopWindow.closeEvent(window, event)
    event.accept.assert_called_once()
    window.tray.hide.assert_called_once()
    window.logs.close.assert_called_once()


def test_unavailable_tray_disables_background(state):
    dialog = CloseDialog(None, False)
    assert not dialog.background.isEnabled()
    assert dialog.cancel.isDefault()
    assert dialog.detach.isEnabled()
    dialog.deleteLater()


def test_restore_and_tray_exit(state):
    _, window, _ = state
    window.showNormal, window.raise_, window.activateWindow = Mock(), Mock(), Mock()
    module.DesktopWindow.restore_window(window)
    window.showNormal.assert_called_once()
    window.activateWindow.assert_called_once()
    window.restore_window = Mock()
    observed = []
    window.close = lambda: observed.append(window.exit_requested)
    module.DesktopWindow.request_exit(window)
    assert observed == [True]
    assert not window.exit_requested


def test_detach_choice_checks_drafts_and_starts_handoff(state, monkeypatch):
    _, window, service = state
    window.detach_services = Mock()
    choose(monkeypatch, CloseDialog.DETACH)
    event = Mock()
    module.DesktopWindow.closeEvent(window, event)
    window.detach_services.assert_called_once()
    window.config_page.discard.assert_called_once()
    service.stop.assert_not_called()
    event.accept.assert_not_called()


def test_detach_choice_cancelled_unsaved_drafts_keeps_services(state, monkeypatch):
    _, window, service = state
    window.detach_services = Mock()
    window.config_page.discard.return_value = False
    choose(monkeypatch, CloseDialog.DETACH)
    module.DesktopWindow.closeEvent(window, Mock())
    window.detach_services.assert_not_called()
    service.stop.assert_not_called()


def test_detached_exit_only_closes_ui(state):
    _, window, service = state
    window.exit_preserving = True
    event = Mock()
    module.DesktopWindow.closeEvent(window, event)
    event.accept.assert_called_once()
    service.stop.assert_not_called()
    window.tray.hide.assert_called_once()
    window.logs.close.assert_called_once()


def test_legacy_process_prevents_handoff(state, monkeypatch):
    _, window, service = state
    service.can_detach.return_value = False
    monkeypatch.setattr(module.QMessageBox, 'warning', Mock())
    module.DesktopWindow.detach_services(window)
    module.QMessageBox.warning.assert_called_once()
    service.detach.assert_not_called()
    service.stop.assert_not_called()


def test_failed_handoff_keeps_console_open(state, monkeypatch):
    _, window, service = state
    window.detaching = True
    window.setEnabled = Mock()
    window.close = Mock()
    monkeypatch.setattr(module.QMessageBox, 'warning', Mock())
    module.DesktopWindow.detach_finished(window, 'test timeout')
    assert not window.detaching
    window.setEnabled.assert_called_once_with(True)
    window.close.assert_not_called()
    service.stop.assert_not_called()


def test_hidden_window_keeps_qt_event_loop_alive():
    import subprocess
    import sys
    script = '''
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QTimer
app = QApplication([])
window = QWidget()
window.show()
QTimer.singleShot(20, window.hide)
def verify():
    assert not window.isVisible()
    print('background-alive', flush=True)
    app.quit()
QTimer.singleShot(150, verify)
app.exec()
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True,
                            text=True, timeout=10, env=os.environ.copy())
    assert result.returncode == 0, result.stderr
    assert 'background-alive' in result.stdout
