from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path
import threading
from typing import Any, Callable
from uuid import uuid4


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class SessionProjection:
    def __init__(self, upload_directory: str | Path | None = None, max_text_chars: int = 524_288):
        self.upload_directory = Path(upload_directory).resolve() if upload_directory else None
        self.max_text_chars = max_text_chars
        self._lock = threading.RLock()
        self._thread: dict[str, Any] = {"id": None, "turns": [], "status": {"type": "notLoaded"}}
        self._pending: list[dict[str, Any]] = []
        self._client_metadata: dict[str, dict[str, Any]] = {}
        self._version = 0
        self._connection = "connecting"
        self._handlers: list[Callable[[], None]] = []

    def add_change_handler(self, handler: Callable[[], None]) -> None:
        self._handlers.append(handler)

    def _changed(self) -> None:
        with self._lock:
            self._version += 1
            handlers = list(self._handlers)
        for handler in handlers:
            try:
                handler()
            except Exception:
                pass

    def set_connection(self, state: str) -> None:
        with self._lock:
            if self._connection == state:
                return
            self._connection = state
        self._changed()

    def replace_thread(self, thread: dict[str, Any]) -> None:
        normalized = self._normalize_thread(thread)
        with self._lock:
            self._thread = normalized
        self._changed()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "version": self._version,
                "connection": self._connection,
                "thread": deepcopy(self._thread),
                "pending": deepcopy(self._pending),
            }

    def add_pending(
        self,
        text: str,
        images: list[dict[str, str]],
        source_ip: str,
        message_id: str | None = None,
    ) -> dict[str, Any]:
        pending = {
            "id": message_id or uuid4().hex,
            "type": "userMessage",
            "text": text,
            "images": [{key: image[key] for key in ("id", "name", "mime") if key in image} for image in images],
            "sourceIp": source_ip,
            "createdAt": _now(),
            "status": "queued",
        }
        with self._lock:
            self._pending.append(pending)
            self._client_metadata[str(pending["id"])] = deepcopy(pending)
        self._changed()
        return deepcopy(pending)

    def update_pending(self, message_id: str, status: str, *, remove: bool = False) -> bool:
        changed = False
        with self._lock:
            for pending in self._pending:
                if pending.get("id") == message_id:
                    pending["status"] = status
                    changed = True
                    break
            if remove:
                before = len(self._pending)
                self._pending = [item for item in self._pending if item.get("id") != message_id]
                changed = changed or len(self._pending) != before
        if changed:
            self._changed()
        return changed

    def remove_pending(self, message_ids: set[str]) -> int:
        ids = {str(message_id) for message_id in message_ids}
        if not ids:
            return 0
        with self._lock:
            before = len(self._pending)
            self._pending = [item for item in self._pending if str(item.get("id")) not in ids]
            removed = before - len(self._pending)
            for message_id in ids:
                self._client_metadata.pop(message_id, None)
        if removed:
            self._changed()
        return removed

    def apply_notification(self, method: str, params: dict[str, Any]) -> bool:
        thread_id = params.get("threadId")
        with self._lock:
            current_id = self._thread.get("id")
            if thread_id and current_id and str(thread_id) != str(current_id):
                return False
            changed = self._apply_notification_locked(method, params)
        if changed:
            self._changed()
        return changed

    def _apply_notification_locked(self, method: str, params: dict[str, Any]) -> bool:
        if method in {"turn/started", "turn/completed"}:
            turn = params.get("turn") or {}
            if not turn.get("id"):
                return False
            existing = self._ensure_turn(str(turn["id"]))
            existing.update(self._safe_value({key: value for key, value in turn.items() if key != "items"}))
            if method == "turn/started":
                existing["items"] = [self._normalize_item(item) for item in turn.get("items", [])]
            else:
                for item in turn.get("items", []):
                    normalized = self._normalize_item(item)
                    old = self._find_item(existing, str(normalized["id"]))
                    if old:
                        metadata = {key: old[key] for key in ("sourceIp", "createdAt", "images", "progress") if key in old}
                        old.clear()
                        old.update(normalized)
                        old.update(metadata)
                    else:
                        existing["items"].append(normalized)
            return True

        if method in {"item/started", "item/completed"}:
            item = params.get("item") or {}
            turn_id = params.get("turnId")
            if not turn_id or not item.get("id"):
                return False
            normalized = self._normalize_item(item)
            turn = self._ensure_turn(str(turn_id))
            old = self._find_item(turn, str(item["id"]))
            if old:
                metadata = {key: old[key] for key in ("sourceIp", "createdAt", "images", "progress") if key in old}
                old.clear()
                old.update(normalized)
                old.update(metadata)
            else:
                turn["items"].append(normalized)
            return True

        turn_id = params.get("turnId")
        item_id = params.get("itemId")
        if method == "turn/diff/updated" and turn_id:
            self._ensure_turn(str(turn_id))["diff"] = self._limit_text(params.get("diff", ""))
            return True
        if method == "error":
            error = self._safe_value(params.get("error") or params)
            if turn_id:
                self._ensure_turn(str(turn_id))["error"] = error
            else:
                self._thread["error"] = error
            return True
        if not turn_id or not item_id:
            return False

        item_type = {
            "item/agentMessage/delta": "agentMessage",
            "item/plan/delta": "plan",
            "item/reasoning/summaryTextDelta": "reasoning",
            "item/reasoning/summaryPartAdded": "reasoning",
            "item/reasoning/textDelta": "reasoning",
            "item/commandExecution/outputDelta": "commandExecution",
            "item/fileChange/outputDelta": "fileChange",
            "item/mcpToolCall/progress": "mcpToolCall",
        }.get(method, "activity")
        item = self._ensure_item(str(turn_id), str(item_id), item_type)
        delta = self._limit_text(params.get("delta", ""))
        if method == "item/agentMessage/delta":
            item["text"] = self._limit_text(str(item.get("text", "")) + delta)
        elif method == "item/plan/delta":
            item["text"] = self._limit_text(str(item.get("text", "")) + delta)
        elif method == "item/reasoning/summaryPartAdded":
            summaries = item.setdefault("summary", [])
            index = int(params.get("summaryIndex", len(summaries)))
            while len(summaries) <= index:
                summaries.append("")
        elif method == "item/reasoning/summaryTextDelta":
            summaries = item.setdefault("summary", [])
            index = int(params.get("summaryIndex", 0))
            while len(summaries) <= index:
                summaries.append("")
            summaries[index] = self._limit_text(str(summaries[index]) + delta)
        elif method == "item/reasoning/textDelta":
            # Raw reasoning text is intentionally not projected to the LAN UI.
            return False
        elif method in {"item/commandExecution/outputDelta", "item/fileChange/outputDelta"}:
            item["aggregatedOutput"] = self._limit_text(str(item.get("aggregatedOutput", "")) + delta)
        elif method == "item/mcpToolCall/progress":
            progress = item.setdefault("progress", [])
            progress.append(self._limit_text(params.get("message", "")))
            if len(progress) > 100:
                del progress[:-100]
        else:
            return False
        return True

    def _normalize_thread(self, thread: dict[str, Any]) -> dict[str, Any]:
        allowed = ("id", "sessionId", "name", "cwd", "modelProvider", "status", "createdAt", "updatedAt", "preview")
        normalized = {key: self._safe_value(thread.get(key)) for key in allowed if key in thread}
        normalized["id"] = normalized.get("id")
        normalized["turns"] = [self._normalize_turn(turn) for turn in thread.get("turns", []) if isinstance(turn, dict)]
        return normalized

    def _normalize_turn(self, turn: dict[str, Any]) -> dict[str, Any]:
        allowed = ("id", "status", "error", "startedAt", "completedAt", "durationMs", "diff")
        normalized = {key: self._safe_value(turn.get(key)) for key in allowed if key in turn}
        normalized["items"] = [self._normalize_item(item) for item in turn.get("items", []) if isinstance(item, dict)]
        return normalized

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        if item.get("type") == "reasoning":
            normalized = {
                "id": str(item.get("id") or uuid4().hex),
                "type": "reasoning",
                "summary": [self._limit_text(part) for part in item.get("summary", []) if isinstance(part, str)],
            }
        elif item.get("type") == "userMessage":
            normalized = self._safe_value(item)
            normalized["content"] = [self._normalize_user_input(value) for value in item.get("content", []) if isinstance(value, dict)]
        else:
            normalized = self._safe_value(item)
        normalized.setdefault("id", str(item.get("id") or uuid4().hex))
        normalized.setdefault("type", str(item.get("type") or "activity"))
        client_id = normalized.get("clientId")
        if client_id and str(client_id) in self._client_metadata:
            metadata = self._client_metadata[str(client_id)]
            normalized.update({key: deepcopy(metadata[key]) for key in ("sourceIp", "createdAt", "images") if key in metadata})
            self._pending = [pending for pending in self._pending if pending.get("id") != str(client_id)]
        return normalized

    def _normalize_user_input(self, value: dict[str, Any]) -> dict[str, Any]:
        kind = str(value.get("type") or "unknown")
        if kind == "text":
            return {"type": "text", "text": self._limit_text(value.get("text", ""))}
        if kind == "localImage":
            path = Path(str(value.get("path") or ""))
            result = {"type": "localImage", "name": path.name or "图片"}
            try:
                resolved = path.resolve()
                if self.upload_directory and self.upload_directory in resolved.parents and len(resolved.stem) == 32:
                    result["imageId"] = resolved.stem
            except OSError:
                pass
            return result
        return self._safe_value(value)

    def _ensure_turn(self, turn_id: str) -> dict[str, Any]:
        for turn in self._thread.setdefault("turns", []):
            if str(turn.get("id")) == turn_id:
                return turn
        turn = {"id": turn_id, "status": "inProgress", "items": []}
        self._thread["turns"].append(turn)
        return turn

    @staticmethod
    def _find_item(turn: dict[str, Any], item_id: str) -> dict[str, Any] | None:
        for item in turn.setdefault("items", []):
            if str(item.get("id")) == item_id:
                return item
        return None

    def _ensure_item(self, turn_id: str, item_id: str, item_type: str) -> dict[str, Any]:
        turn = self._ensure_turn(turn_id)
        item = self._find_item(turn, item_id)
        if item is None:
            item = {"id": item_id, "type": item_type, "status": "inProgress"}
            turn["items"].append(item)
        return item

    def _limit_text(self, value: Any) -> str:
        text = str(value or "")
        if len(text) <= self.max_text_chars:
            return text
        return text[: self.max_text_chars] + "\n…[输出已截断]"

    def _safe_value(self, value: Any, depth: int = 0) -> Any:
        if depth > 8:
            return "[内容层级过深]"
        if isinstance(value, str):
            return self._limit_text(value)
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, list):
            return [self._safe_value(item, depth + 1) for item in value[:200]]
        if isinstance(value, dict):
            return {str(key): self._safe_value(item, depth + 1) for key, item in list(value.items())[:200]}
        return self._limit_text(value)
