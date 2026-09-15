from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import threading


@dataclass(frozen=True)
class StaticAsset:
    body: bytes
    mime: str
    etag: str


class StaticAssets:
    """Only public application code, never HTML, user files or proxy content."""

    def __init__(self, root: Path, names=('app.js', 'history.js', 'realtime.js', 'style.css')):
        self.root = root
        self.names = names
        self._lock = threading.RLock()
        self._current = {}
        self._bodies = OrderedDict()

    def url(self, name: str) -> str:
        if name not in self.names:
            raise ValueError('Not a public static asset')
        with self._lock:
            path = self.root / name
            stat = path.stat()
            stamp = (stat.st_mtime_ns, stat.st_size)
            current = self._current.get(name)
            if current and current[0] == stamp:
                return current[1]
            body = path.read_bytes()
            digest = sha256(body).hexdigest()
            url = f'/assets/{path.stem}.{digest}{path.suffix}'
            mime = 'text/css; charset=utf-8' if path.suffix == '.css' else 'text/javascript; charset=utf-8'
            self._bodies[url] = StaticAsset(body, mime, f'"{digest}"')
            self._bodies.move_to_end(url)
            self._current[name] = (stamp, url)
            # Keep current files plus a bounded set of earlier fingerprints.
            pinned = {value[1] for value in self._current.values()}
            for key in list(self._bodies):
                if len(self._bodies) <= max(16, len(self.names)):
                    break
                if key not in pinned:
                    del self._bodies[key]
            return url

    def get(self, url: str) -> StaticAsset | None:
        with self._lock:
            for name in self.names:
                self.url(name)
            return self._bodies.get(url)
