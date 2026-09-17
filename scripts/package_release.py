from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
import zipfile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
from lan_codex_share import __version__


PLATFORMS = {
    "windows-x64": "lan_codex_share.exe",
    "linux-x64": "lan_codex_share",
    "linux-arm64": "lan_codex_share",
    "macos-x64": "lan_codex_share",
    "macos-arm64": "lan_codex_share",
}


def add_file(archive: zipfile.ZipFile, source: Path, destination: str, mode: int) -> None:
    info = zipfile.ZipInfo(destination)
    info.create_system = 3
    info.external_attr = mode << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    archive.writestr(info, source.read_bytes())


def package_release(
    version: str,
    platform_name: str,
    *,
    dist_directory: Path,
    output_directory: Path,
    project_root: Path,
    include_desktop: bool = False,
) -> Path:
    if version != __version__:
        raise ValueError(f"version {version} does not match package version {__version__}")
    executable_name = PLATFORMS[platform_name]
    executable = dist_directory / executable_name
    if not executable.is_file():
        raise FileNotFoundError(f"missing executable: {executable}")
    output_directory.mkdir(parents=True, exist_ok=True)
    archive_name = f"lan_codex_share-v{version}-{platform_name}.zip"
    archive_path = output_directory / archive_name
    root_name = archive_path.stem
    with zipfile.ZipFile(archive_path, "w") as archive:
        add_file(archive, executable, f"{root_name}/{executable_name}", 0o100755)
        add_file(
            archive,
            project_root / "lan_config.example.toml",
            f"{root_name}/lan_config.example.toml",
            0o100644,
        )
        add_file(archive, project_root / "RELEASE_README.md", f"{root_name}/README.md", 0o100644)
        if include_desktop:
            if platform_name.startswith("macos"):
                gui_root = dist_directory / "LAN Codex Share.app"
                prefix = f"{root_name}/LAN Codex Share.app"
                gui_executable = gui_root / "Contents" / "MacOS" / "lan_codex_desktop"
            else:
                gui_root = dist_directory / "lan_codex_desktop"
                prefix = root_name
                gui_executable = gui_root / ("lan_codex_desktop.exe" if platform_name.startswith("windows") else "lan_codex_desktop")
            if not gui_executable.is_file():
                raise FileNotFoundError(f"missing desktop executable: {gui_executable}")
            for source in sorted(gui_root.rglob("*")):
                if source.is_symlink():
                    if not source.resolve().is_relative_to(gui_root.resolve()):
                        raise ValueError("desktop distribution symlink escapes its root")
                    info = zipfile.ZipInfo(f"{prefix}/{source.relative_to(gui_root).as_posix()}")
                    info.create_system = 3
                    info.external_attr = 0o120777 << 16
                    archive.writestr(info, os.path.relpath(source.resolve(), source.parent).replace('\\', '/'))
                    continue
                if source.is_file():
                    relative = source.relative_to(gui_root).as_posix()
                    if source.name in {"lan_config.toml", "desktop_config.toml", "frpc.toml", "cloudflared.yml"} or source.suffix in {".log", ".tmp"}:
                        raise ValueError("private/runtime file found in desktop distribution")
                    if source.is_symlink() and not source.resolve().is_relative_to(gui_root.resolve()):
                        raise ValueError("desktop distribution symlink escapes its root")
                    mode = 0o100755 if source.stat().st_mode & 0o111 else 0o100644
                    add_file(archive, source, f"{prefix}/{relative}", mode)
            for name in ("desktop_config.example.toml", "frpc.example.toml", "cloudflared.example.yml", "THIRD_PARTY_DESKTOP.md"):
                add_file(archive, project_root / name, f"{root_name}/{name}", 0o100644)
    return archive_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Assemble one native LAN Codex Share release archive")
    parser.add_argument("--version", required=True)
    parser.add_argument("--platform", required=True, choices=sorted(PLATFORMS))
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"))
    parser.add_argument("--output-dir", type=Path, default=Path("release"))
    parser.add_argument("--with-desktop", action="store_true")
    args = parser.parse_args()
    project_root = Path(__file__).resolve().parents[1]
    path = package_release(
        args.version,
        args.platform,
        dist_directory=args.dist_dir.resolve(),
        output_directory=args.output_dir.resolve(),
        project_root=project_root,
        include_desktop=args.with_desktop,
    )
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
