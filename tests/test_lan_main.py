import pytest

from lan_codex_share.lan_main import SingleInstanceLock, _session_state_path, _share_urls, local_private_addresses, main


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


def test_fixed_sessions_use_distinct_safe_state_files(tmp_path):
    first = _session_state_path(tmp_path, "session/a")
    second = _session_state_path(tmp_path, "session:b")

    assert first.parent == tmp_path / "sessions"
    assert second.parent == tmp_path / "sessions"
    assert first != second
    assert "/" not in first.name and ":" not in second.name
    assert _session_state_path(tmp_path, None) == tmp_path / "state.json"
