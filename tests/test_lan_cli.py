from pathlib import Path

import pytest

from lan_codex_share.lan_cli import build_cli_command, run
from lan_codex_share.lan_config import LanConfig


def test_build_cli_command_uses_remote_session(tmp_path, monkeypatch):
    monkeypatch.setattr("lan_codex_share.lan_cli._codex_command", lambda: "codex.cmd")
    config = LanConfig(workspace=tmp_path, app_server_port=4555, permission_mode="workspace-write")

    command = build_cli_command(config, "00000000-0000-0000-0000-000000000001")

    assert command[:5] == [
        "codex.cmd",
        "resume",
        "--remote",
        "ws://127.0.0.1:4555",
        "00000000-0000-0000-0000-000000000001",
    ]
    assert command[-6:] == ["-C", str(tmp_path), "-s", "workspace-write", "-a", "never"]


def test_build_cli_command_requires_session(tmp_path):
    with pytest.raises(ValueError, match="Session ID"):
        build_cli_command(LanConfig(workspace=tmp_path), None)


def test_cli_reads_auto_session_state_next_to_config(tmp_path, monkeypatch):
    config_directory = tmp_path / "config"
    config_directory.mkdir()
    config_path = config_directory / "team.toml"
    config_path.write_text(f'workspace = "{str(tmp_path).replace(chr(92), chr(92) * 2)}"\n', encoding="utf-8")
    state_directory = config_directory / "runtime" / "lan"
    state_directory.mkdir(parents=True)
    (state_directory / "state.json").write_text('{"thread_id": "saved-session"}', encoding="utf-8")
    captured = []
    monkeypatch.setattr(
        "lan_codex_share.lan_cli.build_cli_command",
        lambda config, session: captured.append(session) or ["codex", "resume"],
    )
    monkeypatch.setattr("lan_codex_share.lan_cli.subprocess.call", lambda command, cwd: 0)

    assert run(config_path) == 0
    assert captured == ["saved-session"]
