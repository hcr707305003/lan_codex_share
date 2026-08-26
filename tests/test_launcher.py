from pathlib import Path
import sys

import pytest

from lan_codex_share import __version__
from lan_codex_share.launcher import main, program_directory, resolve_config_path


def test_default_config_is_next_to_executable(tmp_path):
    executable_directory = tmp_path / "application"

    assert resolve_config_path(None, executable_directory=executable_directory) == executable_directory / "lan_config.toml"


def test_explicit_relative_config_is_from_current_directory(tmp_path):
    current_directory = tmp_path / "caller"
    current_directory.mkdir()

    assert resolve_config_path(
        "configs/team.toml",
        executable_directory=tmp_path / "application",
        current_directory=current_directory,
    ) == current_directory / "configs" / "team.toml"


def test_explicit_absolute_config_is_preserved(tmp_path):
    config_path = tmp_path / "team.toml"

    assert resolve_config_path(str(config_path), executable_directory=tmp_path / "application") == config_path


def test_program_directory_uses_frozen_executable(tmp_path, monkeypatch):
    executable = tmp_path / "bundle" / "lan_codex_share.exe"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))

    assert program_directory() == executable.parent


def test_launcher_defaults_to_share(tmp_path):
    calls = []

    result = main(
        [],
        executable_directory=tmp_path / "app",
        current_directory=tmp_path / "caller",
        share_runner=lambda config: calls.append(("share", config)) or 7,
    )

    assert result == 7
    assert calls == [("share", tmp_path / "app" / "lan_config.toml")]


@pytest.mark.parametrize("arguments", [["--config=configs/team.toml"], ["--config", "configs/team.toml"]])
def test_launcher_accepts_both_config_forms(tmp_path, arguments):
    calls = []

    result = main(
        arguments,
        executable_directory=tmp_path / "app",
        current_directory=tmp_path,
        share_runner=lambda config: calls.append(config) or 0,
    )

    assert result == 0
    assert calls == [tmp_path / "configs" / "team.toml"]


def test_launcher_routes_cli_session(tmp_path):
    calls = []

    result = main(
        ["cli", "--config=team.toml", "--session", "session-a"],
        executable_directory=tmp_path / "app",
        current_directory=tmp_path,
        cli_runner=lambda config, session: calls.append((config, session)) or 4,
    )

    assert result == 4
    assert calls == [(tmp_path / "team.toml", "session-a")]


def test_launcher_supports_explicit_share_mode(tmp_path):
    calls = []

    result = main(
        ["share", "--config", "team.toml"],
        current_directory=tmp_path,
        share_runner=lambda config: calls.append(config) or 0,
    )

    assert result == 0
    assert calls == [tmp_path / "team.toml"]


def test_launcher_prints_version(capsys):
    with pytest.raises(SystemExit, match="0"):
        main(["--version"])

    assert __version__ in capsys.readouterr().out
