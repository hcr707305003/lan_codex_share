from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def script_text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_shell_launchers_are_posix_and_portable():
    for name in ("start_lan_codex_share.sh", "open_lan_codex_cli.sh"):
        script = script_text(name)
        assert script.startswith("#!/bin/sh\n")
        assert 'SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)' in script
        assert ".venv/bin/python" in script
        assert ".venv/Scripts/python.exe" in script
        assert "lan_config.toml" in script
        assert '"$@"' in script
        assert "C:\\Users\\" not in script


def test_shell_launchers_target_expected_modules():
    assert "-m lan_codex_share.lan_main" in script_text("start_lan_codex_share.sh")
    assert "-m lan_codex_share.lan_cli" in script_text("open_lan_codex_cli.sh")
