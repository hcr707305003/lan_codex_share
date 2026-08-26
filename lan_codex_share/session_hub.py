from __future__ import annotations

from copy import deepcopy
import queue
import threading
from typing import Any, Iterable


class LanSessionHub:
    """Route browser operations to isolated chat services and fan out live updates."""

    def __init__(self, services: Iterable[Any], logger=None):
        self._services = list(services)
        if not self._services:
            raise ValueError("至少需要一个 Session 服务")
        self.logger = logger
        self._services_by_id: dict[str, Any] = {}
        self._default_session_id: str | None = None
        self._subscribers: set[queue.Queue[int]] = set()
        self._lock = threading.RLock()
        self._version = 0
        for service in self._services:
            service.add_change_handler(self._service_changed)

    @property
    def thread_ids(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._services_by_id)

    def start(self) -> None:
        mapped: dict[str, Any] = {}
        for service in self._services:
            service.start()
            thread_id = str(service.thread_id or "").strip()
            if not thread_id:
                raise ValueError("Session 服务启动后未返回 Session ID")
            if thread_id in mapped:
                raise ValueError(f"Session ID 重复：{thread_id}")
            mapped[thread_id] = service
        with self._lock:
            self._services_by_id = mapped
            self._default_session_id = next(iter(mapped))
        self._broadcast()

    def resolve_session_id(self, session_id: Any = None) -> str:
        if session_id is not None and not isinstance(session_id, str):
            raise ValueError("session_id 必须是字符串")
        requested = session_id.strip() if isinstance(session_id, str) else ""
        with self._lock:
            selected = requested or self._default_session_id
            if not selected or selected not in self._services_by_id:
                raise ValueError("指定的 Session 不在共享列表中")
            return selected

    def _service(self, session_id: Any = None):
        selected = self.resolve_session_id(session_id)
        with self._lock:
            return selected, self._services_by_id[selected]

    def snapshot(self, session_id: Any = None) -> dict[str, Any]:
        selected, service = self._service(session_id)
        snapshot = service.snapshot()
        snapshot["selected_session_id"] = selected
        snapshot["sessions"] = self.session_summaries()
        with self._lock:
            snapshot["hub_version"] = self._version
        return snapshot

    def session_summaries(self) -> list[dict[str, Any]]:
        with self._lock:
            services = list(self._services_by_id.items())
        summaries: list[dict[str, Any]] = []
        for thread_id, service in services:
            value = deepcopy(service.summary())
            value["thread_id"] = thread_id
            summaries.append(value)
        return summaries

    def submit(self, session_id: Any, text: str, images: list[dict[str, str]], source_ip: str) -> str:
        return self._service(session_id)[1].submit(text, images, source_ip)

    def cancel_queued(self, session_id: Any, message_id: str, source_ip: str) -> bool:
        return self._service(session_id)[1].cancel_queued(message_id, source_ip)

    def clear_queued(self, session_id: Any, source_ip: str) -> int:
        return self._service(session_id)[1].clear_queued(source_ip)

    def cancel(self, session_id: Any, source_ip: str) -> bool:
        return self._service(session_id)[1].cancel(source_ip)

    def resync(self, session_id: Any, source_ip: str) -> bool:
        return self._service(session_id)[1].resync(source_ip)

    def update_model_settings(
        self,
        session_id: Any,
        model: str,
        reasoning_effort: str,
        service_tier: str | None,
        source_ip: str,
    ) -> dict[str, str | None]:
        return self._service(session_id)[1].update_model_settings(
            model, reasoning_effort, service_tier, source_ip
        )

    def subscribe(self) -> queue.Queue[int]:
        subscriber: queue.Queue[int] = queue.Queue(maxsize=4)
        with self._lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[int]) -> None:
        with self._lock:
            self._subscribers.discard(subscriber)

    def _service_changed(self) -> None:
        self._broadcast()

    def _broadcast(self) -> None:
        with self._lock:
            self._version += 1
            version = self._version
            subscribers = tuple(self._subscribers)
        for subscriber in subscribers:
            try:
                subscriber.put_nowait(version)
            except queue.Full:
                try:
                    subscriber.get_nowait()
                except queue.Empty:
                    pass
                try:
                    subscriber.put_nowait(version)
                except queue.Full:
                    pass

    def close(self) -> None:
        for service in reversed(self._services):
            try:
                service.close()
            except Exception as exc:
                if self.logger:
                    self.logger.warning("Cannot close LAN Session service: %s", type(exc).__name__)
