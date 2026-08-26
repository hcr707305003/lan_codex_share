from pathlib import Path

import pytest

from lan_codex_share.lan_config import LanConfigError, load_lan_config


def write_config(path: Path, workspace: Path, extra: str = "") -> None:
    path.write_text(
        f'workspace = "{str(workspace).replace(chr(92), chr(92) * 2)}"\n{extra}',
        encoding="utf-8",
    )


def test_load_lan_config_defaults(tmp_path):
    config_path = tmp_path / "lan_config.toml"
    write_config(config_path, tmp_path)

    config = load_lan_config(config_path)

    assert config.workspace == tmp_path.resolve()
    assert config.host == "0.0.0.0"
    assert config.port == 8765
    assert config.app_server_port == 4500
    assert config.max_image_bytes == 10 * 1024 * 1024
    assert config.max_images == 4
    assert config.preview_roots == ()
    assert config.session_id is None
    assert config.permission_mode == "danger-full-access"


def test_loads_session_and_permission_mode(tmp_path):
    config_path = tmp_path / "lan_config.toml"
    write_config(
        config_path,
        tmp_path,
        'session_id = "session-test"\npermission_mode = "workspace-write"\n',
    )

    config = load_lan_config(config_path)

    assert config.session_id == "session-test"
    assert config.permission_mode == "workspace-write"


def test_load_lan_config_preview_roots(tmp_path):
    workspace = tmp_path / "workspace"
    preview_root = tmp_path / "linked-project"
    workspace.mkdir()
    preview_root.mkdir()
    config_path = tmp_path / "lan_config.toml"
    escaped = str(preview_root).replace(chr(92), chr(92) * 2)
    write_config(config_path, workspace, f'preview_roots = ["{escaped}"]\n')

    config = load_lan_config(config_path)

    assert config.preview_roots == (preview_root.resolve(),)


def test_relative_paths_resolve_from_config_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    workspace = tmp_path / "workspace"
    preview_root = tmp_path / "preview"
    unrelated = tmp_path / "unrelated"
    project.mkdir()
    workspace.mkdir()
    preview_root.mkdir()
    unrelated.mkdir()
    config_path = project / "lan_config.toml"
    config_path.write_text(
        'workspace = "../workspace"\npreview_roots = ["../preview"]\n',
        encoding="utf-8",
    )
    monkeypatch.chdir(unrelated)

    config = load_lan_config(config_path)

    assert config.workspace == workspace.resolve()
    assert config.preview_roots == (preview_root.resolve(),)


def test_rejects_missing_preview_root(tmp_path):
    config_path = tmp_path / "lan_config.toml"
    missing = str(tmp_path / "missing").replace(chr(92), chr(92) * 2)
    write_config(config_path, tmp_path, f'preview_roots = ["{missing}"]\n')

    with pytest.raises(LanConfigError, match="预览目录不存在"):
        load_lan_config(config_path)


@pytest.mark.parametrize(
    "extra",
    ["port = 0\n", "port = 70000\n", "app_server_port = 0\n", "max_image_bytes = 0\n", "max_images = 0\n"],
)
def test_reject_invalid_lan_config(tmp_path, extra):
    config_path = tmp_path / "lan_config.toml"
    write_config(config_path, tmp_path, extra)

    with pytest.raises(LanConfigError):
        load_lan_config(config_path)


@pytest.mark.parametrize("value", ["full", "write", "none", ""])
def test_rejects_invalid_permission_mode(tmp_path, value):
    config_path = tmp_path / "lan_config.toml"
    write_config(config_path, tmp_path, f'permission_mode = "{value}"\n')

    with pytest.raises(LanConfigError, match="permission_mode"):
        load_lan_config(config_path)


def test_rejects_non_string_session_id(tmp_path):
    config_path = tmp_path / "lan_config.toml"
    write_config(config_path, tmp_path, "session_id = 42\n")

    with pytest.raises(LanConfigError, match="session_id"):
        load_lan_config(config_path)
