"""Read-only tunnel process detection; never claims public reachability."""
from pathlib import Path
import threading
import time

import psutil

from .desktop.external_tunnels import component_name, run_config


class PublicEntries:
    def __init__(self, frp='', cloudflare=''):
        self.origins = {'frpc': frp, 'Tunnel': cloudflare}
        self._lock = threading.Lock()
        self._expires = 0
        self._items = []

    def snapshot(self):
        with self._lock:
            if time.monotonic() < self._expires:
                return list(self._items)
            running = set()
            if any(self.origins.values()):
                try:
                    for process in psutil.process_iter(['name']):
                        kind = component_name(process.info.get('name') or '')
                        if kind not in self.origins or not self.origins[kind]:
                            continue
                        try:
                            if (process.is_running() and process.status() != psutil.STATUS_ZOMBIE
                                    and component_name(Path(process.exe()).name) == kind
                                    and run_config(kind, process.cmdline()[1:]) is not None):
                                running.add(kind)
                        except (psutil.Error, OSError, ValueError):
                            continue
                except (psutil.Error, OSError):
                    running.clear()
            self._items = [dict(kind=kind, origin=self.origins[key])
                           for key, kind in [('frpc', 'frp'), ('Tunnel', 'cloudflare')]
                           if key in running and self.origins[key]]
            self._expires = time.monotonic() + 5
            return list(self._items)
