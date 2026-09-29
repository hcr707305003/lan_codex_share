"""Headless service lifetime owner. No Qt, no network listener, no saved secrets."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import threading
import time

import psutil

from .logs import LogBuffer
from .process import ServiceProcess


def run_supervisor():
    # Bootstrap data comes from the private inherited pipe, not argv or a file.
    def input_lines():
        pending = b''
        while chunk := os.read(sys.stdin.fileno(), 4096):
            pending += chunk
            if len(pending) > 1024 * 1024:
                raise ValueError('Control input too large')
            while b'\n' in pending:
                line, pending = pending.split(b'\n', 1)
                yield line.decode('utf-8')
    lines = input_lines()
    spec = json.loads(next(lines))
    output_lock = threading.RLock()
    detached = threading.Event()
    stopping = threading.Event()

    def emit(message):
        with output_lock:
            if detached.is_set():
                return
            try:
                sys.stdout.write(json.dumps(message, ensure_ascii=True) + '\n')
                sys.stdout.flush()
            except (OSError, ValueError):
                stopping.set()

    class ServiceLogs(LogBuffer):
        def add(self, source, text):
            super().add(source, text)
            emit({'desktop_event': 'log', 'text': self.redact(text)})

    logs = ServiceLogs(Path(spec['logs']))
    logs.set_secrets(spec.get('secrets', []))
    service = ServiceProcess(spec['name'], logs)

    def commands():
        try:
            for line in lines:
                try:
                    command = json.loads(line)
                except ValueError:
                    continue
                if command == {'command': 'stop'}:
                    stopping.set()
                    return
                if command == {'command': 'detach'}:
                    # Commit before acknowledging; subsequent log writes stay on disk.
                    with output_lock:
                        detached.set()
                        sys.stdout.write('{"desktop_event":"detached"}\n')
                        sys.stdout.flush()
        except (OSError, ValueError):
            pass
        finally:
            if not detached.is_set():
                stopping.set()

    try:
        service.start(spec['argv'], Path(spec['cwd']), controlled=spec['controlled'])
        threading.Thread(target=commands, daemon=True).start()
        ready_sent = False
        owned_sent = None
        while service.snapshot()['running']:
            if stopping.is_set():
                service.stop()
            state = service.snapshot()
            if not ready_sent and (state['ready'] or not spec['controlled']):
                emit({'desktop_event': 'ready'})
                ready_sent = True
            with service._lock:
                owned = list(service._owned)
                try:
                    owned.insert(0, psutil.Process(service._process.pid))
                except psutil.Error:
                    pass
            identities = []
            for process in owned:
                try:
                    identities.append([process.pid, process.create_time()])
                except psutil.Error:
                    pass
            if identities != owned_sent:
                emit({'desktop_event': 'owned', 'processes': identities})
                owned_sent = identities
            time.sleep(.1)
        return service.snapshot()['exit_code'] or 0
    except Exception:
        logs.add(spec.get('name', 'Service'), '独立服务启动或运行失败，请检查程序与日志目录权限。')
        return 1
    finally:
        if service.snapshot()['running']:
            service.force_stop()
        logs.close()


if __name__ == '__main__':
    raise SystemExit(run_supervisor())
