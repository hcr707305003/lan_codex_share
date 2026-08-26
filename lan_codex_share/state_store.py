from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any


def _empty_state() -> dict[str, Any]:
    return {"thread_id": None}


class StateStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_state()
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                thread_id = loaded.get("thread_id")
                return {"thread_id": str(thread_id) if thread_id else None}
            return _empty_state()
        except (OSError, json.JSONDecodeError):
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            backup = self.path.with_suffix(f".corrupt-{stamp}.json")
            try:
                self.path.replace(backup)
            except OSError:
                pass
            return _empty_state()

    def _save(self) -> None:
        temp = self.path.with_suffix(self.path.suffix + ".tmp")
        temp.write_text(
            json.dumps(self._state, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.path)

    @property
    def thread_id(self) -> str | None:
        with self._lock:
            value = self._state.get("thread_id")
            return str(value) if value else None

    def set_thread_id(self, thread_id: str | None) -> None:
        with self._lock:
            self._state["thread_id"] = thread_id
            self._save()
