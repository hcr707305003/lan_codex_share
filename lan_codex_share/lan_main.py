from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
import hashlib
import importlib
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import socket
import sys

import psutil

from .codex_client import CodexClient, CodexClientError
from .lan_app_server import AppServerHost, AppServerHostError
from .lan_access import is_lan_client
from .lan_config import LanConfigError, load_lan_config
from .lan_service import LanChatService
from .lan_store import ImageStore
from .lan_web import LanWebApplication
from .session_hub import LanSessionHub
from .session_projection import SessionProjection
from .state_store import StateStore


def _lock_stream(stream, platform_name: str | None = None) -> None:
    platform_name = platform_name or os.name
    if platform_name == "nt":
        lock_module = importlib.import_module("msvcrt")
        stream.seek(0)
        lock_module.locking(stream.fileno(), lock_module.LK_NBLCK, 1)
        return
    lock_module = importlib.import_module("fcntl")
    lock_module.flock(stream.fileno(), lock_module.LOCK_EX | lock_module.LOCK_NB)


def _unlock_stream(stream, platform_name: str | None = None) -> None:
    platform_name = platform_name or os.name
    if platform_name == "nt":
        lock_module = importlib.import_module("msvcrt")
        stream.seek(0)
        lock_module.locking(stream.fileno(), lock_module.LK_UNLCK, 1)
        return
    lock_module = importlib.import_module("fcntl")
    lock_module.flock(stream.fileno(), lock_module.LOCK_UN)


class SingleInstanceLock(AbstractContextManager):
    def __init__(self, path: Path):
        self.path = path
        self._stream = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._stream = self.path.open("a+b")
        if self._stream.seek(0, 2) == 0:
            self._stream.write(b"0")
            self._stream.flush()
        self._stream.seek(0)
        try:
            _lock_stream(self._stream)
        except OSError as exc:
            self._stream.close()
            self._stream = None
            raise RuntimeError("局域网共享 Codex 会话服务已经在运行") from exc
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._stream:
            try:
                _unlock_stream(self._stream)
            finally:
                self._stream.close()
                self._stream = None
        return False


def _configure_logging(runtime: Path, level: str) -> None:
    runtime.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(runtime / "server.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    console = logging.StreamHandler()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=[file_handler, console],
        force=True,
    )


def local_private_addresses() -> set[str]:
    addresses = {"127.0.0.1", "::1"}
    for entries in psutil.net_if_addrs().values():
        for entry in entries:
            value = str(entry.address).split("%", 1)[0]
            if entry.family in {socket.AF_INET, socket.AF_INET6} and is_lan_client(value):
                addresses.add(value)
    return addresses


def _share_urls(addresses, port: int) -> list[str]:
    return [f"http://{address}:{port}/" for address in sorted(set(addresses)) if ":" not in address and address != "127.0.0.1"] or [
        f"http://127.0.0.1:{port}/"
    ]


def _session_state_path(runtime: Path, session_id: str | None) -> Path:
    if not session_id:
        return runtime / "state.json"
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:16]
    return runtime / "sessions" / f"{digest}.json"


def run(config_path: str | Path) -> int:
    config_path = Path(config_path).expanduser().resolve()
    runtime = config_path.parent / "runtime" / "lan"
    try:
        config = load_lan_config(config_path)
    except LanConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        print(f"请将 lan_config.example.toml 复制为：{config_path}", file=sys.stderr)
        return 2

    _configure_logging(runtime, config.log_level)
    if not (shutil.which("codex.cmd") or shutil.which("codex.exe") or shutil.which("codex")):
        logging.error("找不到 codex 命令，请先安装并登录 Codex CLI")
        return 3

    addresses = local_private_addresses()
    allowed_hosts = set(addresses) | {"localhost", socket.gethostname().lower()}
    if config.host not in {"0.0.0.0", "::"}:
        allowed_hosts.add(config.host)

    image_store = ImageStore(runtime / "uploads", config.max_image_bytes, config.max_images)
    configured_sessions: tuple[str | None, ...] = config.session_ids or (None,)
    services: list[LanChatService] = []
    for index, session_id in enumerate(configured_sessions, start=1):
        state = StateStore(_session_state_path(runtime, session_id))
        if session_id:
            state.set_thread_id(session_id)
        projection = SessionProjection(image_store.directory)
        codex = CodexClient(
            config.workspace,
            state,
            config.turn_timeout_seconds,
            thread_name=f"局域网共享 Codex 会话 {index}" if len(configured_sessions) > 1 else "局域网共享 Codex 会话",
            remote_url=f"ws://127.0.0.1:{config.app_server_port}",
            strict_resume=True,
            sandbox_mode=config.permission_mode,
        )
        services.append(LanChatService(codex, projection, logging.getLogger(f"lan.service.{index}")))
    app_server = AppServerHost(
        "127.0.0.1",
        config.app_server_port,
        cwd=config.workspace,
        logger=logging.getLogger("lan.app_server"),
    )
    hub = LanSessionHub(services, logging.getLogger("lan.sessions"))
    request_limit = config.max_images * ((config.max_image_bytes + 2) // 3 * 4) + 1024 * 1024
    app = LanWebApplication(
        hub,
        image_store,
        allowed_hosts,
        max_request_bytes=request_limit,
        workspace=config.workspace,
        preview_roots=config.preview_roots,
        logger=logging.getLogger("lan.web"),
    )
    server = None
    try:
        with SingleInstanceLock(runtime / "server.lock"):
            try:
                app_server.start()
                hub.start()
                server = app.create_server(config.host, config.port)
                actual_port = int(server.server_address[1])
                print("=" * 72)
                print("局域网共享 Codex 会话已启动")
                for url in _share_urls(addresses, actual_port):
                    print(f"分享地址：{url}")
                print(f"Session 数量：{len(hub.thread_ids)}")
                for index, thread_id in enumerate(hub.thread_ids, start=1):
                    print(f"Session {index}：{thread_id}")
                if getattr(sys, "frozen", False):
                    cli_command = f'"{sys.executable}" cli --config="{config_path}"'
                else:
                    cli_command = f'python -m lan_codex_share cli --config="{config_path}"'
                print(f"本机 CLI：{cli_command}（连接 127.0.0.1:{config.app_server_port}）")
                print(f"工作目录：{config.workspace}")
                print(f"权限：{config.permission_mode} / approval never")
                if config.permission_mode == "danger-full-access":
                    print("警告：局域网内无需登录，任何访问者都可以修改本机项目和工作区外文件。")
                elif config.permission_mode == "workspace-write":
                    print("警告：局域网内无需登录，任何访问者都可以修改工作区文件。")
                else:
                    print("提示：局域网内无需登录，任何访问者都可以读取授权范围内的文件。")
                print("若其他设备无法连接，请检查操作系统防火墙，并允许 Python/Codex 访问局域网。")
                print("按 Ctrl+C 停止服务。")
                print("=" * 72)
                logging.info("LAN Shared Codex Session listening on %s:%s", config.host, actual_port)
                server.serve_forever(poll_interval=0.5)
            except KeyboardInterrupt:
                logging.info("正在关闭局域网共享 Codex 会话服务")
            except (OSError, ValueError, CodexClientError, AppServerHostError) as exc:
                logging.error("启动失败：%s", exc)
                return 4
            finally:
                if server:
                    server.stopping.set()  # type: ignore[attr-defined]
                    server.server_close()
                hub.close()
                app_server.close()
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 5
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="局域网共享 Codex 会话")
    parser.add_argument("--config", default="lan_config.toml")
    args = parser.parse_args(argv)
    config_path = Path(args.config).expanduser()
    if not config_path.is_absolute():
        config_path = Path.cwd() / config_path
    return run(config_path)


if __name__ == "__main__":
    raise SystemExit(main())
