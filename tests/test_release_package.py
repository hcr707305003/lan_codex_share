from pathlib import Path
import zipfile

import pytest

from lan_codex_share import __version__
from scripts.package_release import package_release


def create_release_inputs(root: Path, executable_name: str) -> Path:
    dist = root / "dist"
    dist.mkdir()
    (dist / executable_name).write_bytes(b"native-executable")
    (root / "lan_config.example.toml").write_text('workspace = "../workspace"\n', encoding="utf-8")
    (root / "RELEASE_README.md").write_text("# Release\n", encoding="utf-8")
    return dist


@pytest.mark.parametrize(
    ("platform_name", "executable_name"),
    [("windows-x64", "lan_codex_share.exe"), ("linux-arm64", "lan_codex_share")],
)
def test_release_archive_contains_only_public_distribution_files(tmp_path, platform_name, executable_name):
    dist = create_release_inputs(tmp_path, executable_name)

    archive_path = package_release(
        __version__,
        platform_name,
        dist_directory=dist,
        output_directory=tmp_path / "release",
        project_root=tmp_path,
    )

    with zipfile.ZipFile(archive_path) as archive:
        names = archive.namelist()
        root = archive_path.stem
        assert names == [
            f"{root}/{executable_name}",
            f"{root}/lan_config.example.toml",
            f"{root}/README.md",
        ]
        assert not any("lan_config.toml" in name or "runtime" in name or ".log" in name for name in names)


def test_release_archive_rejects_wrong_version(tmp_path):
    dist = create_release_inputs(tmp_path, "lan_codex_share")

    with pytest.raises(ValueError, match="does not match"):
        package_release(
            "9.9.9",
            "linux-x64",
            dist_directory=dist,
            output_directory=tmp_path / "release",
            project_root=tmp_path,
        )


def test_pyinstaller_spec_includes_web_assets():
    spec = (Path(__file__).resolve().parents[1] / "lan_codex_share.spec").read_text(encoding="utf-8")

    assert '"lan_codex_share" / "web"' in spec
    assert 'name="lan_codex_share"' in spec
