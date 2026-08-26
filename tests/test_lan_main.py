import pytest
from types import SimpleNamespace

from lan_codex_share.lan_main import (
    SingleInstanceLock,
    _lock_stream,
    _session_state_path,
    _share_urls,
    _unlock_stream,
    local_private_addresses,
    main,
)


class FakeStream:
    def __init__(self):
        self.seeks = []

    def fileno(self):
        return 17

    def seek(self, offset, whence=0):
        self.seeks.append((offset, whence))


def test_share_urls_are_http_addresses():
    assert _share_urls(["192.168.1.20", "10.0.0.5"], 8765) == [
        "http://10.0.0.5:8765/",
        "http://192.168.1.20:8765/",
    ]


def test_local_addresses_include_loopback():
    assert "127.0.0.1" in local_private_addresses()


def test_missing_config_returns_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["--config", "missing.toml"]) == 2


def test_single_instance_lock(tmp_path):
    path = tmp_path / "server.lock"
    with SingleInstanceLock(path):
        with pytest.raises(RuntimeError, match="已经在运行"):
            with SingleInstanceLock(path):
                pass
    with SingleInstanceLock(path):
        pass


def test_windows_stream_lock_uses_msvcrt(monkeypatch):
    calls = []
    module = SimpleNamespace(
        LK_NBLCK=1,
        LK_UNLCK=2,
        locking=lambda fd, mode, size: calls.append((fd, mode, size)),
    )
    monkeypatch.setattr("lan_codex_share.lan_main.importlib.import_module", lambda name: module if name == "msvcrt" else None)
    stream = FakeStream()

    _lock_stream(stream, "nt")
    _unlock_stream(stream, "nt")

    assert calls == [(17, 1, 1), (17, 2, 1)]
    assert stream.seeks == [(0, 0), (0, 0)]


def test_posix_stream_lock_uses_fcntl(monkeypatch):
    calls = []
    module = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=4,
        LOCK_UN=8,
        flock=lambda fd, operation: calls.append((fd, operation)),
    )
    monkeypatch.setattr("lan_codex_share.lan_main.importlib.import_module", lambda name: module if name == "fcntl" else None)
    stream = FakeStream()

    _lock_stream(stream, "posix")
    _unlock_stream(stream, "posix")

    assert calls == [(17, 5), (17, 8)]
    assert stream.seeks == []


def test_fixed_sessions_use_distinct_safe_state_files(tmp_path):
    first = _session_state_path(tmp_path, "session/a")
    second = _session_state_path(tmp_path, "session:b")

    assert first.parent == tmp_path / "sessions"
    assert second.parent == tmp_path / "sessions"
    assert first != second
    assert "/" not in first.name and ":" not in second.name
    assert _session_state_path(tmp_path, None) == tmp_path / "state.json"
