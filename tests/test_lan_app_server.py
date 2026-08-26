from pathlib import Path
import socket
import sys
import time

import pytest

from lan_codex_share.lan_app_server import AppServerHost, AppServerHostError


def free_port():
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    listener.close()
    return port


def test_app_server_host_starts_and_stops_injected_process(tmp_path):
    port = free_port()
    script = tmp_path / "fake_listener.py"
    script.write_text(
        "import socket, sys, time\n"
        "url = sys.argv[-1]\n"
        "port = int(url.rsplit(':', 1)[1])\n"
        "s = socket.socket(); s.bind(('127.0.0.1', port)); s.listen()\n"
        "while True:\n"
        "    conn, _ = s.accept(); conn.close()\n",
        encoding="utf-8",
    )
    host = AppServerHost("127.0.0.1", port, command=(sys.executable, str(script)), cwd=tmp_path, startup_timeout=2)

    host.start()
    try:
        assert host.endpoint == f"ws://127.0.0.1:{port}"
        assert host.process and host.process.poll() is None
    finally:
        host.close()
    assert host.process is None


def test_app_server_host_rejects_occupied_port(tmp_path):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    try:
        host = AppServerHost("127.0.0.1", port, command=(sys.executable, "unused.py"), cwd=tmp_path)
        with pytest.raises(AppServerHostError, match="已被占用"):
            host.start()
    finally:
        listener.close()


def test_app_server_host_reuses_compatible_existing_port(tmp_path, monkeypatch):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    try:
        host = AppServerHost("127.0.0.1", port, command=(sys.executable, "unused.py"), cwd=tmp_path)
        monkeypatch.setattr(host, "_probe_existing", lambda: True)
        host.start()
        assert host.reusing_existing
        assert host.process is None
        host.close()
    finally:
        listener.close()


def test_app_server_host_stops_spawned_process_tree(tmp_path):
    port = free_port()
    child = tmp_path / "child_listener.py"
    child.write_text(
        "import socket, sys\n"
        "port = int(sys.argv[-1].rsplit(':', 1)[1])\n"
        "s = socket.socket(); s.bind(('127.0.0.1', port)); s.listen()\n"
        "while True:\n"
        "    conn, _ = s.accept(); conn.close()\n",
        encoding="utf-8",
    )
    wrapper = tmp_path / "wrapper.py"
    wrapper.write_text(
        "import subprocess, sys, time\n"
        "subprocess.Popen([sys.executable, sys.argv[1], sys.argv[-1]])\n"
        "while True: time.sleep(1)\n",
        encoding="utf-8",
    )
    host = AppServerHost(
        "127.0.0.1",
        port,
        command=(sys.executable, str(wrapper), str(child)),
        cwd=tmp_path,
        startup_timeout=2,
    )

    host.start()
    assert host._port_open()
    host.close()
    deadline = time.monotonic() + 2
    while host._port_open() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not host._port_open()
