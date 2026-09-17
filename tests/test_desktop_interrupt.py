import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import signal
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QDialog
from lan_codex_share.desktop.app import console_interrupts


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def pump(app, seconds=0.25):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)


def test_interrupt_queued_and_handler_restored(app):
    calls = []
    window = SimpleNamespace(close=lambda: calls.append('close'), exiting=False)
    previous = signal.getsignal(signal.SIGINT)
    with console_interrupts(window):
        signal.raise_signal(signal.SIGINT)
        assert calls == []
        pump(app)
        assert calls == ['close']
        # A cancelled close may be requested again.
        signal.raise_signal(signal.SIGINT)
        pump(app)
        assert calls == ['close', 'close']
    assert signal.getsignal(signal.SIGINT) is previous


def test_repeated_interrupt_does_not_reenter_close_or_cleanup(app):
    calls = []

    def close():
        calls.append('close')
        signal.raise_signal(signal.SIGINT)
        signal.raise_signal(signal.SIGINT)
        pump(app)
        window.exiting = True

    window = SimpleNamespace(close=close, exiting=False)
    with console_interrupts(window):
        signal.raise_signal(signal.SIGINT)
        pump(app)
        signal.raise_signal(signal.SIGINT)
        pump(app)
    assert calls == ['close']


def test_interrupt_waits_for_modal_and_restores_on_exception(app):
    calls = []
    window = SimpleNamespace(close=lambda: calls.append('close'), exiting=False)
    previous = signal.getsignal(signal.SIGINT)
    dialog = QDialog()
    dialog.setModal(True)
    try:
        with pytest.raises(ValueError), console_interrupts(window):
            dialog.show()
            signal.raise_signal(signal.SIGINT)
            pump(app)
            assert calls == []
            dialog.close()
            pump(app)
            assert calls == ['close']
            raise ValueError('test cleanup')
    finally:
        dialog.close()
    assert signal.getsignal(signal.SIGINT) is previous


def test_real_desktop_entry_exits_on_sigint_without_traceback(tmp_path):
    code = '''
import signal, sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop.app import main
app = QApplication([])
QTimer.singleShot(500, lambda: signal.raise_signal(signal.SIGINT))
QTimer.singleShot(5000, lambda: app.exit(99))
sys.exit(main(['--config', sys.argv[1]]))
'''
    result = subprocess.run([sys.executable, '-c', code, str(tmp_path / 'lan_config.toml')],
                            capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    assert b'KeyboardInterrupt' not in result.stderr
    assert b'Traceback' not in result.stderr
