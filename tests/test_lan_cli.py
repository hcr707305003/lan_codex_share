from pathlib import Path

import pytest

from lan_codex_share.lan_cli import build_cli_command
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
