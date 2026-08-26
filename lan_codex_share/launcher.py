from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys
from typing import Callable

from . import __version__
from .lan_cli import run as run_cli
from .lan_main import run as run_share


Runner = Callable[..., int]


def configure_console() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except (AttributeError, OSError):
        pass
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def program_directory() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resolve_config_path(
    raw_path: str | None,
    *,
    executable_directory: str | Path | None = None,
    current_directory: str | Path | None = None,
) -> Path:
    executable_directory = Path(executable_directory or program_directory()).resolve()
    current_directory = Path(current_directory or Path.cwd()).resolve()
    if raw_path is None:
        return executable_directory / "lan_config.toml"
    config_path = Path(raw_path).expanduser()
    if not config_path.is_absolute():
        config_path = current_directory / config_path
    return config_path.resolve()


def _parser(mode: str, program_name: str) -> argparse.ArgumentParser:
    if mode == "cli":
        parser = argparse.ArgumentParser(
            prog=f"{program_name} cli",
            description="打开局域网共享 Codex Session 的本机 CLI",
        )
        parser.add_argument("--session", help="要打开的 Session ID；未指定时使用配置或状态中的默认会话")
    else:
        parser = argparse.ArgumentParser(
            prog=program_name if mode == "share-default" else f"{program_name} share",
            description="启动局域网共享 Codex 会话服务",
            epilog=f"打开本机 CLI：{program_name} cli [--config PATH] [--session SESSION_ID]",
        )
    parser.add_argument("--config", help="配置文件路径；默认读取程序同目录的 lan_config.toml")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    executable_directory: str | Path | None = None,
    current_directory: str | Path | None = None,
    share_runner: Runner = run_share,
    cli_runner: Runner = run_cli,
) -> int:
    configure_console()
    args = list(sys.argv[1:] if argv is None else argv)
    program_name = Path(sys.argv[0]).stem or "lan_codex_share"
    if program_name in {"__main__", "run_lan_codex_share"}:
        program_name = "lan_codex_share"
    mode = "share-default"
    if args and args[0] in {"share", "cli"}:
        mode = args.pop(0)
    parser = _parser(mode, program_name)
    parsed = parser.parse_args(args)
    config_path = resolve_config_path(
        parsed.config,
        executable_directory=executable_directory,
        current_directory=current_directory,
    )
    if mode == "cli":
        return cli_runner(config_path, parsed.session)
    return share_runner(config_path)
