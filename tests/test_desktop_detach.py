from pathlib import Path
import subprocess
import sys
import time

import psutil
import pytest

from lan_codex_share.desktop.logs import LogBuffer
from lan_codex_share.desktop.process import ServiceProcess

ROOT = Path(__file__).resolve().parents[1]


def exited(process):
    try:
        return not process.is_running() or process.status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return True


def wait_for(predicate, timeout=8):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.05)
    raise AssertionError('timeout waiting for isolated service')


def make_service(tmp_path, controlled=False):
    logs = LogBuffer()
    logs.set_secrets(['private-fixture-secret'])
    service = ServiceProcess('fixture', logs)
    code = '''import os, sys, time, threading
from pathlib import Path
Path('child.pid').write_text(str(os.getpid()))
print('{"desktop_event":"ready"}', flush=True)
def control():
    sys.stdin.readline()
    os._exit(0)
if sys.argv[1] == 'controlled':
    threading.Thread(target=control, daemon=True).start()
while True:
    print('heartbeat private-fixture-secret', flush=True)
    time.sleep(.05)
'''
    service.start_supervised([sys.executable, '-u', '-c', code, 'controlled' if controlled else 'tunnel'],
        tmp_path, controlled=controlled,
        supervisor=[sys.executable, '-u', '-m', 'lan_codex_share.desktop.supervisor'],
        supervisor_cwd=ROOT, log_directory=tmp_path / 'logs')
    wait_for(lambda: (tmp_path / 'child.pid').exists() and service.snapshot()['ready'])
    child = psutil.Process(int((tmp_path / 'child.pid').read_text()))
    return service, child


@pytest.mark.parametrize('controlled', [False, True])
def test_detach_survives_parent_pipe_closure_and_keeps_redacted_logs(tmp_path, controlled):
    service, child = make_service(tmp_path, controlled)
    try:
        service.detach()
        service._process.stdin.close()
        log = tmp_path / 'logs' / 'desktop.log'
        size = log.stat().st_size
        wait_for(lambda: log.stat().st_size > size + 100)
        assert child.is_running()
        assert service.snapshot()['running']
        assert 'private-fixture-secret' not in log.read_text(encoding='utf-8')
        assert '[已隐藏]' in log.read_text(encoding='utf-8')
    finally:
        if child.is_running():
            child.kill()
        service._process.wait(timeout=8)


@pytest.mark.parametrize('controlled', [False, True])
def test_parent_loss_without_detach_stops_owned_service(tmp_path, controlled):
    service, child = make_service(tmp_path, controlled)
    try:
        service._process.stdin.close()
        service._process.wait(timeout=8)
        wait_for(lambda: exited(child))
    finally:
        if child.is_running():
            child.kill()
        service.force_stop()


def test_legacy_service_cannot_detach(tmp_path):
    service = ServiceProcess('legacy', LogBuffer())
    service.start([sys.executable, '-c', 'import time; time.sleep(30)'], tmp_path)
    try:
        assert not service.can_detach()
        with pytest.raises(ValueError, match='旧启动方式'):
            service.detach()
    finally:
        service.force_stop()
        service._process.wait(timeout=5)


@pytest.mark.parametrize('controlled', [False, True])
def test_explicit_stop_still_works_with_supervisor(tmp_path, controlled):
    service, child = make_service(tmp_path, controlled)
    try:
        service.stop()
        service._process.wait(timeout=8)
        wait_for(lambda: exited(child))
    finally:
        if child.is_running():
            child.kill()
        service.force_stop()


def test_supervisor_has_no_qt_dependency():
    result = subprocess.run([sys.executable, '-c',
        'import sys; import lan_codex_share.desktop.supervisor; assert "PySide6" not in sys.modules'],
        cwd=ROOT, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr


def test_real_parent_process_exits_while_child_keeps_logging(tmp_path):
    parent = '''import sys
from pathlib import Path
from tests.test_desktop_detach import make_service
p, child = make_service(Path(sys.argv[1]), True)
p.detach()
print(str(p._process.pid) + ':' + str(child.pid), flush=True)
'''
    # Load helper by path; tests is not an installed package.
    parent = parent.replace('from tests.test_desktop_detach import make_service',
        'import runpy; make_service = runpy.run_path("tests/test_desktop_detach.py")["make_service"]')
    result = subprocess.run([sys.executable, '-c', parent, str(tmp_path)], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr
    supervisor_pid, child_pid = map(int, result.stdout.strip().split(':'))
    child = psutil.Process(child_pid)
    supervisor = psutil.Process(supervisor_pid)
    try:
        log = tmp_path / 'logs' / 'desktop.log'
        size = log.stat().st_size
        wait_for(lambda: log.stat().st_size > size + 100)
        assert child.is_running() and supervisor.is_running()
    finally:
        child.kill()
        wait_for(lambda: exited(supervisor))


def test_qt_console_really_exits_without_stopping_service(tmp_path):
    pytest.importorskip('PySide6')
    script = '''import os, sys, runpy
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop.window import DesktopWindow
from lan_codex_share.desktop.close_dialog import CloseDialog
from lan_codex_share.desktop.external_monitor import ExternalShareMonitor
from lan_codex_share.desktop.tunnel_monitor import ExternalTunnelMonitor
ExternalShareMonitor.start = lambda self: None
ExternalTunnelMonitor.start = lambda self: None
CloseDialog.exec = lambda self: CloseDialog.DETACH
make_service = runpy.run_path('tests/test_desktop_detach.py')['make_service']
app = QApplication([])
root = Path(sys.argv[1])
window = DesktopWindow(root / 'lan_config.toml')
service, child = make_service(root, True)
window.services['Share'] = service
print(str(service._process.pid) + ':' + str(child.pid), flush=True)
window.show()
def close_when_ready():
    if window.components.busy:
        QTimer.singleShot(50, close_when_ready)
    else:
        window.close()
QTimer.singleShot(50, close_when_ready)
QTimer.singleShot(10000, lambda: app.exit(99))
raise SystemExit(app.exec())
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    supervisor_pid, child_pid = map(int, result.stdout.strip().split(':'))
    child = psutil.Process(child_pid)
    supervisor = psutil.Process(supervisor_pid)
    try:
        assert result.returncode == 0, result.stderr
        log = tmp_path / 'logs' / 'desktop.log'
        size = log.stat().st_size
        wait_for(lambda: log.stat().st_size > size + 100)
        assert child.is_running() and supervisor.is_running()
    finally:
        child.kill()
        wait_for(lambda: exited(supervisor))
