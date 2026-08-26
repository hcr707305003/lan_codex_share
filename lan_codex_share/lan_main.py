from __future__ import annotations

import argparse
from contextlib import AbstractContextManager
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import shutil
import socket
import sys

import msvcrt
import psutil

from .codex_client import CodexClient, CodexClientError
from .lan_app_server import AppServerHost, AppServerHostError
from .lan_access import is_lan_client
from .lan_config import LanConfigError, load_lan_config
from .lan_service import LanChatService
from .lan_store import ImageStore
from .lan_web import LanWebApplication
from .session_projection import SessionProjection
from .state_store import StateStore


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
            msvcrt.locking(self._stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            self._stream.close()
            self._stream = None
            raise RuntimeError("局域网共享 Codex 会话服务已经在运行") from exc
        return self

    def __exit__(self, exc_type, exc, traceback):
        if self._stream:
            self._stream.seek(0)
            try:
                msvcrt.locking(self._stream.fileno(), msvcrt.LK_UNLCK, 1)
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="局域网共享 Codex 会话")
    parser.add_argument("--config", default="lan_config.toml")
    args = parser.parse_args(argv)
    base = Path.cwd()
    runtime = base / "runtime" / "lan"
    try:
        config = load_lan_config(base / args.config)
    except LanConfigError as exc:
        print(f"配置错误：{exc}", file=sys.stderr)
        print("请复制 lan_config.example.toml 为 lan_config.toml 并检查工作区。", file=sys.stderr)
        return 2

    _configure_logging(runtime, config.log_level)
    if not (shutil.which("codex.cmd") or shutil.which("codex.exe") or shutil.which("codex")):
        logging.error("找不到 codex 命令，请先安装并登录 Codex CLI")
        return 3

    addresses = local_private_addresses()
    allowed_hosts = set(addresses) | {"localhost", socket.gethostname().lower()}
    if config.host not in {"0.0.0.0", "::"}:
        allowed_hosts.add(config.host)

    state = StateStore(runtime / "state.json")
    if config.session_id:
        state.set_thread_id(config.session_id)
    image_store = ImageStore(runtime / "uploads", config.max_image_bytes, config.max_images)
    projection = SessionProjection(image_store.directory)
    codex = CodexClient(
        config.workspace,
        state,
        config.turn_timeout_seconds,
        thread_name="局域网共享 Codex 会话",
        remote_url=f"ws://127.0.0.1:{config.app_server_port}",
        strict_resume=True,
        sandbox_mode=config.permission_mode,
    )
    app_server = AppServerHost(
        "127.0.0.1",
        config.app_server_port,
        cwd=config.workspace,
        logger=logging.getLogger("lan.app_server"),
    )
    service = LanChatService(codex, projection, logging.getLogger("lan.service"))
    request_limit = config.max_images * ((config.max_image_bytes + 2) // 3 * 4) + 1024 * 1024
    app = LanWebApplication(
        service,
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
                service.start()
                server = app.create_server(config.host, config.port)
                actual_port = int(server.server_address[1])
                print("=" * 72)
                print("局域网共享 Codex 会话已启动")
                for url in _share_urls(addresses, actual_port):
                    print(f"分享地址：{url}")
                print(f"Session ID：{service.thread_id}")
                print(f"本机 CLI：双击 open_lan_codex_cli.cmd（连接 127.0.0.1:{config.app_server_port}）")
                print(f"工作目录：{config.workspace}")
                print(f"权限：{config.permission_mode} / approval never")
                if config.permission_mode == "danger-full-access":
                    print("警告：局域网内无需登录，任何访问者都可以修改本机项目和工作区外文件。")
                elif config.permission_mode == "workspace-write":
                    print("警告：局域网内无需登录，任何访问者都可以修改工作区文件。")
                else:
                    print("提示：局域网内无需登录，任何访问者都可以读取授权范围内的文件。")
                print("若其他设备无法连接，请手动允许 Python 访问 Windows 专用网络。")
                print("按 Ctrl+C 停止服务。")
                print("=" * 72)
                logging.info("LAN Shared Codex Session listening on %s:%s", config.host, actual_port)
                server.serve_forever(poll_interval=0.5)
            except KeyboardInterrupt:
                logging.info("正在关闭局域网共享 Codex 会话服务")
            except (OSError, CodexClientError, AppServerHostError) as exc:
                logging.error("启动失败：%s", exc)
                return 4
            finally:
                if server:
                    server.stopping.set()  # type: ignore[attr-defined]
                    server.server_close()
                service.close()
                app_server.close()
    except RuntimeError as exc:
        logging.error("%s", exc)
        return 5
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
