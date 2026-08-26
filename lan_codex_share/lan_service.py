from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import queue
import threading
import time
from typing import Any

from .codex_client import CodexClientError, CodexTurnTimeout
from .session_projection import SessionProjection


class LanChatService:
    def __init__(self, codex, projection: SessionProjection, logger=None):
        self.codex = codex
        self.projection = projection
        self.logger = logger
        self.thread_id: str | None = None
        self._queue: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self._queued_lock = threading.RLock()
        self._queued_tasks: dict[str, dict[str, Any]] = {}
        self._model_lock = threading.RLock()
        self._model_catalog: list[dict[str, Any]] = []
        self._model_settings: dict[str, str | None] = {
            "model": None, "reasoning_effort": None, "service_tier": None,
        }
        self._stop = threading.Event()
        self._active = threading.Event()
        self._worker = threading.Thread(target=self._work_loop, name="lan-codex-worker", daemon=True)
        self._subscribers: set[queue.Queue[int]] = set()
        self._subscriber_lock = threading.RLock()
        self._version_lock = threading.Lock()
        self._version = 0
        self._broadcast_interval = 0.075
        self._broadcast_timer_lock = threading.Lock()
        self._broadcast_timer: threading.Timer | None = None
        self._last_broadcast_at = 0.0
        self._last_error: str | None = None
        self._last_notice: str | None = None
        self.projection.add_change_handler(self._projection_changed)
        if hasattr(self.codex, "add_notification_handler"):
            self.codex.add_notification_handler(self.projection.apply_notification)
            self.codex.add_notification_handler(self._handle_codex_notification)
        if hasattr(self.codex, "add_thread_state_handler"):
            self.codex.add_thread_state_handler(lambda _busy: self._broadcast())

    def start(self) -> None:
        if self._worker.is_alive():
            return
        self.projection.set_connection("connecting")
        try:
            if hasattr(self.codex, "read_thread"):
                thread = self.codex.read_thread(include_turns=True)
            else:
                thread_id = str(self.codex.ensure_thread())
                thread = {"id": thread_id, "status": {"type": "idle"}, "turns": []}
            self.thread_id = str(thread["id"])
            self.projection.replace_thread(thread)
            self.projection.set_connection("connected")
            if hasattr(self.codex, "list_models"):
                try:
                    catalog = self.codex.list_models()
                    with self._model_lock:
                        self._model_catalog = catalog if isinstance(catalog, list) else []
                except Exception as exc:
                    if self.logger:
                        self.logger.warning("Cannot load Codex model catalog: %s", type(exc).__name__)
            settings = getattr(self.codex, "model_settings", None)
            if isinstance(settings, dict):
                with self._model_lock:
                    self._model_settings = {
                        "model": settings.get("model"),
                        "reasoning_effort": settings.get("reasoning_effort"),
                        "service_tier": settings.get("service_tier"),
                    }
        except Exception:
            self.projection.set_connection("disconnected")
            raise
        self._stop.clear()
        self._worker.start()
        self._broadcast()

    def snapshot(self) -> dict[str, Any]:
        projected = self.projection.snapshot()
        with self._version_lock:
            version = self._version
        connection = str(projected.get("connection") or "disconnected")
        status = "reconnecting" if connection != "connected" else (
            "processing" if self._active.is_set() or bool(getattr(self.codex, "thread_busy", False)) else "idle"
        )
        with self._model_lock:
            model_catalog = deepcopy(self._model_catalog)
            model_settings = dict(self._model_settings)
        return {
            "thread_id": self.thread_id,
            "status": status,
            "connection": connection,
            "queue_size": self.queue_size,
            "version": version,
            "thread": projected.get("thread", {}),
            "pending": projected.get("pending", []),
            "model_catalog": model_catalog,
            "model_settings": model_settings,
            "last_error": self._last_error,
            "last_notice": self._last_notice,
        }

    @property
    def queue_size(self) -> int:
        with self._queued_lock:
            return len(self._queued_tasks)

    def subscribe(self) -> queue.Queue[int]:
        subscriber: queue.Queue[int] = queue.Queue(maxsize=4)
        with self._subscriber_lock:
            self._subscribers.add(subscriber)
        return subscriber

    def unsubscribe(self, subscriber: queue.Queue[int]) -> None:
        with self._subscriber_lock:
            self._subscribers.discard(subscriber)

    def _broadcast(self) -> None:
        with self._broadcast_timer_lock:
            self._last_broadcast_at = time.monotonic()
        with self._version_lock:
            self._version += 1
            version = self._version
        with self._subscriber_lock:
            for subscriber in tuple(self._subscribers):
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

    def _projection_changed(self) -> None:
        """Coalesce token-level App Server deltas before waking every browser."""
        broadcast_now = False
        with self._broadcast_timer_lock:
            elapsed = time.monotonic() - self._last_broadcast_at
            if self._broadcast_timer is None and elapsed >= self._broadcast_interval:
                broadcast_now = True
            elif self._broadcast_timer is None:
                delay = max(0.001, self._broadcast_interval - elapsed)
                self._broadcast_timer = threading.Timer(delay, self._flush_projection_broadcast)
                self._broadcast_timer.daemon = True
                self._broadcast_timer.start()
        if broadcast_now:
            self._broadcast()

    def _flush_projection_broadcast(self) -> None:
        with self._broadcast_timer_lock:
            self._broadcast_timer = None
        self._broadcast()

    def _handle_codex_notification(self, method: str, params: dict[str, Any]) -> None:
        if method != "thread/settings/updated":
            return
        settings = params.get("threadSettings") or {}
        if not isinstance(settings, dict):
            return
        with self._model_lock:
            model = settings.get("model")
            if isinstance(model, str) and model.strip():
                self._model_settings["model"] = model.strip()
            if "effort" in settings:
                effort = settings.get("effort")
                self._model_settings["reasoning_effort"] = (
                    effort.strip() if isinstance(effort, str) and effort.strip() else None
                )
            if "serviceTier" in settings:
                tier = settings.get("serviceTier")
                self._model_settings["service_tier"] = (
                    tier.strip() if isinstance(tier, str) and tier.strip() else None
                )
        self._broadcast()

    def update_model_settings(
        self,
        model: str,
        reasoning_effort: str,
        service_tier: str | None,
        source_ip: str,
    ) -> dict[str, str | None]:
        selected_model = model.strip()
        selected_effort = reasoning_effort.strip()
        selected_tier = service_tier.strip() if isinstance(service_tier, str) and service_tier.strip() else None
        with self._queued_lock:
            if self._active.is_set() or bool(getattr(self.codex, "thread_busy", False)) or self._queued_tasks:
                raise ValueError("任务与队列完成后才可调整模型")
            with self._model_lock:
                entry = next((item for item in self._model_catalog if item.get("model") == selected_model), None)
            if entry is None:
                raise ValueError("所选模型不在当前可用模型列表中")
            supported = {str(item.get("value")) for item in entry.get("supported_reasoning_efforts", [])}
            if selected_effort not in supported:
                raise ValueError("所选模型不支持该思考强度")
            available_tiers = {str(item.get("id")) for item in entry.get("service_tiers", [])}
            if selected_tier is not None and selected_tier not in available_tiers:
                raise ValueError("所选模型不支持该速度档位")
            try:
                settings = self.codex.update_thread_settings(selected_model, selected_effort, selected_tier)
            except CodexClientError as exc:
                raise ValueError(f"模型调整失败：{exc}") from exc
        with self._model_lock:
            self._model_settings = {
                "model": settings.get("model"),
                "reasoning_effort": settings.get("reasoning_effort"),
                "service_tier": settings.get("service_tier"),
            }
            result = dict(self._model_settings)
        self._last_notice = f"{source_ip} 已将模型调整为 {entry.get('display_name') or selected_model}。"
        self._last_error = None
        self._broadcast()
        return result

    def submit(self, text: str, images: list[dict[str, str]], source_ip: str) -> str:
        cleaned = text.strip()
        if not cleaned and not images:
            raise ValueError("消息文字和图片不能同时为空")
        pending = self.projection.add_pending(cleaned, images, source_ip)
        task = {"message": pending, "images": images}
        with self._queued_lock:
            self._queued_tasks[str(pending["id"])] = task
            self._queue.put(task)
        self._last_error = None
        self._broadcast()
        return str(pending["id"])

    def cancel_queued(self, message_id: str, source_ip: str) -> bool:
        with self._queued_lock:
            task = self._queued_tasks.pop(str(message_id), None)
        if task is None:
            self._last_notice = "消息已经开始处理或不在队列中。"
            self._broadcast()
            return False
        self.projection.remove_pending({str(message_id)})
        self._delete_task_images(task)
        self._last_notice = f"{source_ip} 已取消一条排队消息。"
        self._broadcast()
        return True

    def clear_queued(self, source_ip: str) -> int:
        with self._queued_lock:
            tasks = list(self._queued_tasks.values())
            self._queued_tasks.clear()
        message_ids = {str(task["message"]["id"]) for task in tasks}
        self.projection.remove_pending(message_ids)
        for task in tasks:
            self._delete_task_images(task)
        count = len(tasks)
        self._last_notice = f"{source_ip} 已清空 {count} 条排队消息。" if count else "排队列表为空。"
        self._broadcast()
        return count

    def _delete_task_images(self, task: dict[str, Any]) -> None:
        for image in task.get("images", []):
            path = image.get("path")
            if not path:
                continue
            try:
                Path(str(path)).unlink(missing_ok=True)
            except OSError as exc:
                if self.logger:
                    self.logger.warning("Cannot delete cancelled queue image: %s", type(exc).__name__)

    def cancel(self, source_ip: str) -> bool:
        cancelled = bool(self.codex.interrupt_turn())
        self._last_notice = f"{source_ip} 已请求取消当前任务。" if cancelled else "当前没有活动任务。"
        self._broadcast()
        return cancelled

    def resync(self, source_ip: str) -> bool:
        if self._active.is_set() or bool(getattr(self.codex, "thread_busy", False)):
            self._last_notice = "任务执行中，完成后再重新同步。"
            self._broadcast()
            return False
        thread = self.codex.read_thread(include_turns=True)
        self.thread_id = str(thread["id"])
        self.projection.replace_thread(thread)
        self._last_notice = f"{source_ip} 已从真实 Session 重新同步。"
        self._last_error = None
        self._broadcast()
        return True

    def _work_loop(self) -> None:
        while not self._stop.is_set():
            if bool(getattr(self.codex, "thread_busy", False)):
                waiter = getattr(self.codex, "wait_for_thread_idle", None)
                if waiter:
                    waiter(0.25)
                else:
                    self._stop.wait(0.25)
                continue
            try:
                task = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if task is None:
                self._queue.task_done()
                break
            message = task["message"]
            images = task["images"]
            message_id = str(message["id"])
            with self._queued_lock:
                claimed = self._queued_tasks.pop(message_id, None)
            if claimed is not task:
                self._queue.task_done()
                continue
            self._active.set()
            self.projection.update_pending(message_id, "processing")
            self._broadcast()
            try:
                user_text = str(message.get("text") or "")
                items: list[dict[str, str]] = []
                if user_text:
                    items.append({"type": "text", "text": user_text})
                items.extend({"type": "localImage", "path": str(image["path"])} for image in images)
                source = str(message.get("sourceIp") or "未知")
                received = str(message.get("createdAt") or datetime.now().astimezone().isoformat(timespec="seconds"))
                context = {
                    "lan-web-source": {
                        "kind": "application",
                        "value": f"这条用户输入来自局域网页面，来源 IP：{source}，接收时间：{received}。",
                    }
                }
                self.codex.run_turn_items(
                    items,
                    client_user_message_id=message_id,
                    additional_context=context,
                )
                self.projection.update_pending(message_id, "completed", remove=True)
                self._last_error = None
            except CodexTurnTimeout:
                self.projection.update_pending(message_id, "failed")
                self._last_error = "Codex 任务执行超时，已请求中断。"
            except CodexClientError as exc:
                self.projection.update_pending(message_id, "failed")
                self._last_error = f"Codex 执行失败：{exc}"
            except Exception as exc:
                self.projection.update_pending(message_id, "failed")
                self._last_error = f"任务处理失败：{type(exc).__name__}"
                if self.logger:
                    self.logger.exception("LAN Shared Codex Session task failed")
            finally:
                self._active.clear()
                self._queue.task_done()
                self._broadcast()

    def close(self) -> None:
        self._stop.set()
        with self._broadcast_timer_lock:
            timer = self._broadcast_timer
            self._broadcast_timer = None
        if timer is not None:
            timer.cancel()
        if self._active.is_set():
            try:
                self.codex.interrupt_turn()
            except Exception:
                pass
        self._queue.put(None)
        if self._worker.is_alive():
            self._worker.join(timeout=10)
        self.codex.close()
