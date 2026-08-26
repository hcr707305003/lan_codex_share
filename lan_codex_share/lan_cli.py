from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

from .lan_config import LanConfig, LanConfigError, load_lan_config


def _codex_command() -> str:
    resolved = shutil.which("codex.cmd") or shutil.which("codex.exe") or shutil.which("codex")
    if not resolved:
        raise RuntimeError("找不到 codex 命令")
    return resolved


def build_cli_command(config: LanConfig, thread_id: str | None) -> list[str]:
    if not thread_id:
        raise ValueError("尚未找到共享 Session ID，请先启动局域网共享服务")
    return [
        _codex_command(),
        "resume",
        "--remote",
        f"ws://127.0.0.1:{config.app_server_port}",
        thread_id,
        "-C",
        str(config.workspace),
        "-s",
        config.permission_mode,
        "-a",
        "never",
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="打开局域网共享 Codex session 的本机 CLI")
    parser.add_argument("--config", default="lan_config.toml")
    args = parser.parse_args(argv)
    base = Path.cwd()
    try:
        config = load_lan_config(base / args.config)
        state_path = base / "runtime" / "lan" / "state.json"
        state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.is_file() else {}
        command = build_cli_command(config, config.session_id or state.get("thread_id"))
    except (LanConfigError, ValueError, RuntimeError, OSError, json.JSONDecodeError) as exc:
        print(f"无法打开共享 CLI：{exc}", file=sys.stderr)
        return 2
    return subprocess.call(command, cwd=str(config.workspace))


if __name__ == "__main__":
    raise SystemExit(main())
