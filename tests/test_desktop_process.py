import sys
import time

import pytest

from lan_codex_share.desktop.logs import LogBuffer
from lan_codex_share.desktop.process import ServiceProcess


def wait_for(predicate):
    end = time.monotonic() + 5
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(.03)
    raise AssertionError('child did not reach expected state')


def test_owned_child_stop_and_duplicate(tmp_path):
    process = ServiceProcess('Share', LogBuffer())
    code = 'import sys; print(\'{"desktop_event":"ready"}\',flush=True); sys.stdin.readline()'
    process.start([sys.executable, '-u', '-c', code], tmp_path, controlled=True)
    try:
        wait_for(lambda: process.snapshot()['ready'])
        with pytest.raises(ValueError):
            process.start([sys.executable, '-c', 'pass'], tmp_path)
        process.stop()
        wait_for(lambda: not process.snapshot()['running'])
        assert process.snapshot()['exit_code'] == 0
    finally:
        process.force_stop()


def test_failure_code_and_logs(tmp_path):
    logs = LogBuffer()
    process = ServiceProcess('frpc', logs)
    process.start([sys.executable, '-u', '-c', 'print("test-child"); raise SystemExit(7)'], tmp_path)
    wait_for(lambda: process.snapshot()['exit_code'] is not None)
    wait_for(lambda: bool(logs.filtered(query='test-child')))
    assert process.snapshot()['exit_code'] == 7


def test_force_does_not_kill_reused_child_identity():
    class OldChild:
        def is_running(self):
            return False
        def kill(self):
            raise AssertionError('must not kill an expired/reused identity')
    process = ServiceProcess('Share', LogBuffer())
    process._owned = [OldChild()]
    process.force_stop()
    assert process._owned == []
