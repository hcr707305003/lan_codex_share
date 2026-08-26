from __future__ import annotations

from concurrent.futures import Future
import json
import logging
import threading
from typing import Any, Callable, TextIO


class JsonRpcError(RuntimeError):
    def __init__(self, code: int, message: str, data: Any = None):
        super().__init__(f"JSON-RPC {code}: {message}")
        self.code = code
        self.message = message
        self.data = data


class JsonRpcClosed(RuntimeError):
    pass


class JsonRpcConnection:
    def __init__(self, reader: TextIO, writer: TextIO, logger: logging.Logger | None = None):
        self.reader = reader
        self.writer = writer
        self.logger = logger or logging.getLogger(__name__)
        self._write_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._pending: dict[int, Future[Any]] = {}
        self._next_id = 1
        self._notification_handlers: list[Callable[[str, dict[str, Any]], None]] = []
        self._server_request_handler: Callable[[dict[str, Any]], None] | None = None
        self._closed = threading.Event()
        self._reader_thread = threading.Thread(target=self._read_loop, name="codex-jsonrpc-reader", daemon=True)

    def start(self) -> None:
        self._reader_thread.start()

    def add_notification_handler(self, handler: Callable[[str, dict[str, Any]], None]) -> None:
        self._notification_handlers.append(handler)

    def set_server_request_handler(self, handler: Callable[[dict[str, Any]], None]) -> None:
        self._server_request_handler = handler

    def request(self, method: str, params: dict[str, Any], timeout: float = 30) -> Any:
        with self._state_lock:
            if self._closed.is_set():
                raise JsonRpcClosed("JSON-RPC connection is closed")
            request_id = self._next_id
            self._next_id += 1
            future: Future[Any] = Future()
            self._pending[request_id] = future
        self._send({"method": method, "id": request_id, "params": params})
        try:
            return future.result(timeout=timeout)
        finally:
            with self._state_lock:
                self._pending.pop(request_id, None)

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"method": method, "params": params})

    def _send(self, payload: dict[str, Any]) -> None:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._write_lock:
            if self._closed.is_set():
                raise JsonRpcClosed("JSON-RPC connection is closed")
            self.writer.write(line + "\n")
            self.writer.flush()

    def _read_loop(self) -> None:
        try:
            for raw_line in self.reader:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    self.logger.warning("App Server emitted a non-JSON stdout line")
                    continue
                self._dispatch(message)
        except Exception as exc:
            if not self._closed.is_set():
                self.logger.error("App Server JSON-RPC reader stopped: %s", type(exc).__name__)
        finally:
            self.close()

    def _dispatch(self, message: dict[str, Any]) -> None:
        if "id" in message and ("result" in message or "error" in message):
            request_id = message.get("id")
            with self._state_lock:
                future = self._pending.get(request_id)
            if not future or future.done():
                return
            if "error" in message:
                error = message["error"] or {}
                future.set_exception(JsonRpcError(error.get("code", -1), error.get("message", "Unknown error"), error.get("data")))
            else:
                future.set_result(message.get("result"))
            return

        if "method" in message and "id" in message:
            if self._server_request_handler:
                self._server_request_handler(message)
            return

        method = message.get("method")
        params = message.get("params") or {}
        if method:
            for handler in list(self._notification_handlers):
                try:
                    handler(method, params)
                except Exception:
                    self.logger.exception("Notification handler failed for %s", method)

    def respond_error(self, request_id: int, code: int, message: str) -> None:
        self._send({"id": request_id, "error": {"code": code, "message": message}})

    def close(self) -> None:
        if self._closed.is_set():
            return
        self._closed.set()
        with self._state_lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(JsonRpcClosed("JSON-RPC connection closed"))
