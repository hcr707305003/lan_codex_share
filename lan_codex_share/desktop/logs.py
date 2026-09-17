from __future__ import annotations

from collections import deque
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
import threading


class LogBuffer:
    def __init__(self, directory: Path | None = None, *, limit: int = 10_000):
        self.records = deque(maxlen=limit)
        self.dropped = 0
        self.generation = 0
        self._secrets: set[str] = set()
        self._lock = threading.RLock()
        self._handler = None
        if directory:
            directory.mkdir(parents=True, exist_ok=True)
            self._handler = RotatingFileHandler(directory / "desktop.log", maxBytes=5 * 1024 * 1024,
                                               backupCount=2, encoding="utf-8")

    def set_secrets(self, secrets: list[str]) -> None:
        with self._lock:
            # Retain old values as running processes may still use previous configs.
            self._secrets.update(s for s in secrets if s)
            self._secrets.update(line for secret in secrets for line in secret.splitlines() if line)

    def redact(self, text: str) -> str:
        with self._lock:
            for secret in sorted(self._secrets, key=len, reverse=True):
                text = text.replace(secret, "[已隐藏]")
        text = re.sub(r"(?im)\b(authorization|cookie|set-cookie)\s*[:=].*$", r"\1: [已隐藏]", text)
        return re.sub(r'''(?i)(["']?(?:auth\.)?(?:password|token|secret|credential)["']?\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)''',
                      r"\1[已隐藏]", text)

    def add(self, source: str, text: str) -> None:
        with self._lock:
            for line in self.redact(text).splitlines():
                line = line.encode("utf-8")[:16 * 1024].decode("utf-8", errors="ignore")
                formatted = f"{datetime.now():%H:%M:%S}  [{source}]  {line}"
                if len(self.records) == self.records.maxlen:
                    self.dropped += 1
                self.records.append((source, formatted))
                self.generation += 1
                if self._handler:
                    self._handler.emit(logging.LogRecord("desktop", logging.INFO, "", 0, formatted, (), None))

    def filtered(self, source: str = "", query: str = "") -> list[str]:
        with self._lock:
            return [text for service, text in self.records
                    if (not source or service == source) and query.lower() in text.lower()]

    def clear(self) -> None:
        with self._lock:
            self.records.clear()
            self.dropped = 0
            self.generation += 1

    def close(self) -> None:
        with self._lock:
            if self._handler:
                self._handler.close()
                self._handler = None
