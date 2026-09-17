import io
import threading

from lan_codex_share.desktop.worker import listen_control


def test_worker_accepts_only_stop():
    event = threading.Event()
    listen_control(io.StringIO('{"command":"unknown"}\n{"command":"stop"}\n'), event)
    assert event.is_set()


def test_parent_disconnect_requests_cleanup():
    event = threading.Event()
    listen_control(io.StringIO(''), event)
    assert event.is_set()


def test_share_stop_event_closes_loopback_listener(tmp_path, monkeypatch):
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from types import SimpleNamespace
    from lan_codex_share import lan_main
    from lan_codex_share.lan_config import LanConfig

    stopped = threading.Event()
    flags = []
    class Host:
        _owned_processes = []
        def __init__(self, *args, **kwargs):
            pass
        def start(self):
            flags.append('host-start')
        def close(self):
            flags.append('host-close')
    class Web:
        def __init__(self, *args, **kwargs):
            pass
        def create_server(self, host, port):
            server = ThreadingHTTPServer(('127.0.0.1', 0), BaseHTTPRequestHandler)
            server.stopping = threading.Event()
            return server
    hub = SimpleNamespace(thread_ids=[], start=lambda: flags.append('hub-start'), close=lambda: flags.append('hub-close'))
    monkeypatch.setattr(lan_main, 'load_lan_config', lambda p: LanConfig(workspace=tmp_path))
    monkeypatch.setattr(lan_main, '_configure_logging', lambda *a: None)
    monkeypatch.setattr(lan_main.shutil, 'which', lambda name: 'unused-test-command')
    monkeypatch.setattr(lan_main, 'AppServerHost', Host)
    monkeypatch.setattr(lan_main, 'LanWebApplication', Web)
    monkeypatch.setattr(lan_main, '_build_session_hub', lambda *a: hub)
    results = []
    thread = threading.Thread(target=lambda: results.append(lan_main.run(tmp_path / 'lan.toml', stop_event=stopped, on_ready=stopped.set)), daemon=True)
    thread.start()
    thread.join(4)
    assert not thread.is_alive(), 'shutdown must not deadlock serve_forever'
    assert results == [0]
    assert flags[-2:] == ['hub-close', 'host-close']
