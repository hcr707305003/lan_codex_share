from __future__ import annotations

import threading
from typing import Iterator

import websocket

from .jsonrpc import JsonRpcConnection


class _WebSocketReader:
    def __init__(self, socket):
        self.socket = socket

    def __iter__(self) -> Iterator[str]:
        while True:
            value = self.socket.recv()
            if value in {None, "", b""}:
                return
            if isinstance(value, bytes):
                value = value.decode("utf-8")
            yield str(value) + "\n"


class _WebSocketWriter:
    def __init__(self, socket):
        self.socket = socket

    def write(self, value: str) -> int:
        payload = value[:-1] if value.endswith("\n") else value
        self.socket.send(payload)
        return len(value)

    def flush(self) -> None:
        return None


class WebSocketJsonRpcConnection(JsonRpcConnection):
    def __init__(
        self,
        url: str,
        logger=None,
        *,
        connect_timeout: float = 10,
        websocket_socket=None,
    ):
        self.url = url
        self.socket = websocket_socket or websocket.create_connection(
            url,
            timeout=connect_timeout,
            enable_multithread=True,
            http_proxy_host=None,
            suppress_origin=True,
        )
        self.socket.settimeout(None) if hasattr(self.socket, "settimeout") else None
        self._socket_close_lock = threading.Lock()
        self._socket_closed = False
        super().__init__(_WebSocketReader(self.socket), _WebSocketWriter(self.socket), logger)
        self._reader_thread.name = "codex-websocket-jsonrpc-reader"

    def close(self) -> None:
        super().close()
        with self._socket_close_lock:
            if self._socket_closed:
                return
            self._socket_closed = True
            try:
                self.socket.close()
            except Exception:
                pass
