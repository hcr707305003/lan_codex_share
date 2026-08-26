import pytest

from lan_codex_share.lan_main import SingleInstanceLock, _share_urls, local_private_addresses, main


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
