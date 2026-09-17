import subprocess
import sys


def test_desktop_help_does_not_start_services():
    result = subprocess.run([sys.executable, 'run_lan_codex_desktop.py', '--help'], capture_output=True)
    assert result.returncode == 0
    assert b'--config' in result.stdout


def test_existing_launcher_does_not_import_qt():
    result = subprocess.run([sys.executable, '-c', 'import sys; import lan_codex_share.launcher; assert "PySide6" not in sys.modules'], capture_output=True)
    assert result.returncode == 0
