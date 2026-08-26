from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import psutil
import shutil
import socket
import subprocess
import threading
import time

import websocket


class AppServerHostError(RuntimeError):
    pass


class AppServerHost:
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4500,
        *,
        command: tuple[str, ...] | None = None,
        cwd: str | Path | None = None,
        startup_timeout: float = 15,
        logger: logging.Logger | None = None,
    ):
        self.host = host
        self.port = port
        self.command = command or self._default_command()
        self.cwd = Path(cwd).resolve() if cwd else None
        self.startup_timeout = startup_timeout
        self.logger = logger or logging.getLogger(__name__)
        self.process: subprocess.Popen[str] | None = None
        self.reusing_existing = False
        self._drainers: list[threading.Thread] = []
        self._owned_processes: list[psutil.Process] = []

    @staticmethod
    def _default_command() -> tuple[str, ...]:
        candidates = ("codex.cmd", "codex.exe", "codex") if os.name == "nt" else ("codex",)
        for candidate in candidates:
            resolved = shutil.which(candidate)
            if resolved:
                return (resolved, "app-server")
        return ("codex", "app-server")

    @property
    def endpoint(self) -> str:
        return f"ws://{self.host}:{self.port}"

    def _port_open(self) -> bool:
        try:
            with socket.create_connection((self.host, self.port), timeout=0.15):
                return True
        except OSError:
            return False

    def _probe_existing(self) -> bool:
        connection = None
        try:
            connection = websocket.create_connection(
                self.endpoint,
                timeout=2,
                enable_multithread=True,
                http_proxy_host=None,
                suppress_origin=True,
            )
            connection.send(
                json.dumps(
                    {
                        "method": "initialize",
                        "id": 1,
                        "params": {
                            "clientInfo": {
                                "name": "lan_codex_share_probe",
                                "title": "LAN Shared Codex Session Probe",
                                "version": "1.0.0",
                            },
                            "capabilities": {},
                        },
                    }
                )
            )
            response = json.loads(connection.recv())
            return response.get("id") == 1 and isinstance(response.get("result"), dict)
        except (OSError, ValueError, websocket.WebSocketException):
            return False
        finally:
            if connection:
                connection.close()

    def _capture_process_tree(self) -> None:
        if not self.process:
            return
        try:
            root = psutil.Process(self.process.pid)
            self._owned_processes = [root, *root.children(recursive=True)]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            self._owned_processes = []

    def start(self) -> None:
        if self.process and self.process.poll() is None:
            return
        if self._port_open():
            if self._probe_existing():
                self.reusing_existing = True
                self.logger.info("复用现有 Codex App Server：%s", self.endpoint)
                return
            raise AppServerHostError(f"App Server 端口 {self.host}:{self.port} 已被占用")
        self.reusing_existing = False
        self.process = subprocess.Popen(
            [*self.command, "--listen", self.endpoint],
            cwd=str(self.cwd) if self.cwd else None,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        for name, stream in (("stdout", self.process.stdout), ("stderr", self.process.stderr)):
            if stream:
                thread = threading.Thread(target=self._drain, args=(name, stream), daemon=True, name=f"app-server-{name}")
                thread.start()
                self._drainers.append(thread)
        deadline = time.monotonic() + self.startup_timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                code = self.process.returncode
                self.close()
                raise AppServerHostError(f"App Server 启动失败，退出码 {code}")
            if self._port_open():
                self._capture_process_tree()
                return
            time.sleep(0.05)
        self.close()
        raise AppServerHostError("App Server 启动超时")

    def _drain(self, name: str, stream) -> None:
        for line in stream:
            if line.strip():
                self.logger.debug("App Server %s output received", name)

    def close(self) -> None:
        process = self.process
        self.process = None
        owned = list(self._owned_processes)
        self._owned_processes = []
        for child in reversed(owned):
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        _, alive = psutil.wait_procs(owned, timeout=5)
        for child in alive:
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        psutil.wait_procs(alive, timeout=5)
        if process:
            try:
                process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for thread in self._drainers:
            if thread.is_alive():
                thread.join(timeout=1)
        self._drainers = []
