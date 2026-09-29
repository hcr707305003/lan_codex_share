import json
import threading

import psutil

from lan_codex_share.public_entries import PublicEntries
from lan_codex_share.lan_web import LanWebApplication
from lan_codex_share.lan_store import ImageStore
from tests.test_lan_web import FakeService, request


class Process:
    def __init__(self, name, args):
        self.info = {'name': name}
        self.args = args
    def exe(self): return self.info['name']
    def cmdline(self): return [self.exe(), *self.args]
    def is_running(self): return True
    def status(self): return psutil.STATUS_RUNNING


def test_only_configured_running_tunnels_and_no_credentials(monkeypatch):
    processes = [Process('frpc.exe', ['-c', 'secret.toml']),
                 Process('cloudflared', ['tunnel', 'run', '--token', 'PRIVATE'])]
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs: processes)
    entries = PublicEntries('https://frp.example', 'https://cf.example')
    assert entries.snapshot() == [{'kind': 'frp', 'origin': 'https://frp.example'},
                                  {'kind': 'cloudflare', 'origin': 'https://cf.example'}]
    assert 'PRIVATE' not in json.dumps(entries.snapshot())
    assert PublicEntries().snapshot() == []
    processes.clear()
    assert len(entries.snapshot()) == 2  # Bounded shared cache.
    entries._expires = 0
    assert entries.snapshot() == []


def test_skip_management_commands_and_unknown_process(monkeypatch):
    processes = [Process('frpc', ['verify', '-c', 'frpc.toml']),
                 Process('cloudflared', ['--version']), Process('other', [])]
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs: processes)
    assert PublicEntries('https://frp.example', 'https://cf.example').snapshot() == []


def test_access_denied_hides_entry(monkeypatch):
    process = Process('frpc', [])
    def denied(): raise psutil.AccessDenied()
    process.cmdline = denied
    monkeypatch.setattr(psutil, 'process_iter', lambda attrs: [process])
    assert PublicEntries('https://frp.example').snapshot() == []


def test_public_entries_requires_authentication(tmp_path):
    app = LanWebApplication(FakeService(), ImageStore(tmp_path / 'images', 1024, 4),
                            {'127.0.0.1'}, max_request_bytes=10240, password='test')
    app.public_entries.snapshot = lambda: [{'kind': 'frp', 'origin': 'https://frp.example'}]
    server = app.create_server('127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        assert request(server, 'GET', '/api/public-entries')[0] == 401
        app.password = ''
        status, _, body = request(server, 'GET', '/api/public-entries')
        assert status == 200 and json.loads(body)['items'][0]['kind'] == 'frp'
    finally:
        server.shutdown(); server.server_close(); thread.join(2)
