from __future__ import annotations

import codecs
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import psutil

from .logs import LogBuffer


class ServiceProcess:
    """Controls only the Popen handle created by this object, never discovered PIDs."""

    def __init__(self, name: str, logs: LogBuffer):
        self.name, self.logs = name, logs
        self._process: subprocess.Popen | None = None
        self._controlled = False
        self._ready = False
        self._stopping_at: float | None = None
        self._lock = threading.RLock()
        self._owned = []

    def start(self, argv: list[str], cwd: Path, *, controlled: bool = False) -> None:
        with self._lock:
            if self._process and self._process.poll() is None:
                raise ValueError("服务已启动，请勿重复启动")
            env = os.environ.copy()
            env.update(PYTHONUTF8="1", PYTHONUNBUFFERED="1")
            process = subprocess.Popen(argv, cwd=cwd, env=env, shell=False,
                                       stdin=subprocess.PIPE if controlled else subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            self._process = process
            self._controlled, self._ready, self._stopping_at = controlled, False, None
            self._owned = []
            for stream, events in ((process.stdout, controlled), (process.stderr, False)):
                threading.Thread(target=self._read, args=(process, stream, events), daemon=True).start()
            self.logs.add(self.name, "进程已创建，等待就绪" if controlled else "进程已创建；不代表公网已连通")

    def _read(self, process, stream, events):
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        pending = ""
        dropping = False
        try:
            while chunk := stream.read1(4096):
                decoded = decoder.decode(chunk)
                if dropping:
                    if '\n' not in decoded:
                        continue
                    decoded = decoded.split('\n', 1)[1]
                    dropping = False
                pending += decoded
                while "\n" in pending:
                    line, pending = pending.split("\n", 1)
                    if len(line.encode('utf-8')) <= 16 * 1024:
                        self._line(process, line, events)
                    else:
                        self.logs.add(self.name, '[超长日志行已丢弃]')
                if len(pending) > 16 * 1024:
                    # Do not emit a fragment that could split a secret across records.
                    pending = ""
                    dropping = True
                    self.logs.add(self.name, "[超长日志行已丢弃]")
            pending += decoder.decode(b"", final=True)
            if pending and not dropping:
                self._line(process, pending, events)
        except (OSError, ValueError):
            pass
        finally:
            stream.close()

    def _line(self, process, line, events):
        if events:
            try:
                message = json.loads(line)
                if isinstance(message, dict) and message.get('desktop_event') == 'owned':
                    verified = []
                    for identity in message.get('processes', []):
                        try:
                            pid, created = identity
                            child = psutil.Process(pid)
                            if child.create_time() == created and process.pid in [p.pid for p in child.parents()]:
                                verified.append(child)
                        except (ValueError, TypeError, psutil.Error):
                            continue
                    with self._lock:
                        if self._process is process:
                            self._owned = verified
                    return
                if isinstance(message, dict) and message.get("desktop_event") == "ready":
                    with self._lock:
                        if self._process is process:
                            self._ready = True
                    self.logs.add(self.name, "Share 已成功监听，可以访问")
                    return
            except ValueError:
                pass
        self.logs.add(self.name, line)

    def snapshot(self) -> dict:
        with self._lock:
            code = self._process.poll() if self._process else None
            running = self._process is not None and code is None
            return {"running": running, "ready": self._ready and running,
                    "exit_code": code, "stopping": running and self._stopping_at is not None,
                    "timed_out": running and self._stopping_at is not None and time.monotonic() - self._stopping_at >= 15}

    def stop(self) -> None:
        with self._lock:
            if not self._process or self._process.poll() is not None or self._stopping_at is not None:
                return
            self._stopping_at = time.monotonic()
            if self._controlled:
                try:
                    self._process.stdin.write(b'{"command":"stop"}\n')
                    self._process.stdin.flush()
                except (OSError, ValueError):
                    self.logs.add(self.name, "停止管道不可用，请等待退出或手动强制停止")
            else:
                self._process.terminate()
                self.logs.add(self.name, "已终止受控进程（Windows）" if os.name == "nt" else "已发送 SIGTERM")

    def force_stop(self) -> None:
        with self._lock:
            for child in reversed(self._owned):
                try:
                    if child.is_running():
                        child.kill()
                except psutil.Error:
                    pass
            self._owned = []
            if self._process and self._process.poll() is None:
                self._process.kill()
                self.logs.add(self.name, "已强制结束本客户端创建的进程")
