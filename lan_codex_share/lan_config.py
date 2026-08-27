from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


class LanConfigError(ValueError):
    pass


PERMISSION_MODES = {"read-only", "workspace-write", "danger-full-access"}


@dataclass(frozen=True)
class LanConfig:
    workspace: Path
    host: str = "0.0.0.0"
    port: int = 8765
    app_server_port: int = 4500
    turn_timeout_seconds: float = 1800
    max_image_bytes: int = 10 * 1024 * 1024
    max_images: int = 4
    log_level: str = "INFO"
    preview_roots: tuple[Path, ...] = ()
    session_ids: tuple[str, ...] | None = None
    permission_mode: str = "danger-full-access"
    password: str = ""

    @property
    def session_id(self) -> str | None:
        """Return the first configured session for legacy single-session callers."""
        return self.session_ids[0] if self.session_ids else None

    @property
    def auto_session(self) -> bool:
        return self.session_ids is None

    @property
    def discover_all_sessions(self) -> bool:
        return self.session_ids == ()


def load_lan_config(path: str | Path) -> LanConfig:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise LanConfigError(f"配置文件不存在：{config_path}")
    with config_path.open("rb") as stream:
        data = tomllib.load(stream)

    workspace_raw = str(data.get("workspace", "")).strip()
    if not workspace_raw:
        raise LanConfigError("workspace 不能为空")
    workspace = Path(workspace_raw).expanduser()
    if not workspace.is_absolute():
        workspace = config_path.parent / workspace
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise LanConfigError(f"workspace 目录不存在：{workspace}")

    host = str(data.get("host", "0.0.0.0")).strip()
    if not host:
        raise LanConfigError("host 不能为空")
    port = int(data.get("port", 8765))
    if not 1 <= port <= 65535:
        raise LanConfigError("port 必须在 1 到 65535 之间")
    app_server_port = int(data.get("app_server_port", 4500))
    if not 1 <= app_server_port <= 65535:
        raise LanConfigError("app_server_port 必须在 1 到 65535 之间")
    if app_server_port == port:
        raise LanConfigError("app_server_port 不能与 Web port 相同")
    timeout = float(data.get("turn_timeout_seconds", 1800))
    if timeout <= 0:
        raise LanConfigError("turn_timeout_seconds 必须大于 0")
    max_image_bytes = int(data.get("max_image_bytes", 10 * 1024 * 1024))
    if max_image_bytes <= 0:
        raise LanConfigError("max_image_bytes 必须大于 0")
    max_images = int(data.get("max_images", 4))
    if not 1 <= max_images <= 20:
        raise LanConfigError("max_images 必须在 1 到 20 之间")
    if "session_ids" in data and "session_id" in data:
        raise LanConfigError("session_ids 与旧版 session_id 不能同时配置")
    if "session_ids" in data:
        session_ids_raw = data["session_ids"]
        if not isinstance(session_ids_raw, list) or not all(isinstance(item, str) for item in session_ids_raw):
            raise LanConfigError("session_ids 必须是 Session ID 字符串数组")
        session_ids = tuple(item.strip() for item in session_ids_raw)
        if any(not item for item in session_ids):
            raise LanConfigError("session_ids 不能包含空字符串")
        if len(set(session_ids)) != len(session_ids):
            raise LanConfigError("session_ids 不能包含重复的 Session ID")
    else:
        if "session_id" not in data:
            session_ids = None
        else:
            session_id_raw = data["session_id"]
            if not isinstance(session_id_raw, str):
                raise LanConfigError("session_id 必须是字符串")
            session_id = session_id_raw.strip()
            session_ids = (session_id,) if session_id else None
    permission_mode_raw = data.get("permission_mode", "danger-full-access")
    if not isinstance(permission_mode_raw, str):
        raise LanConfigError("permission_mode 必须是字符串")
    permission_mode = permission_mode_raw.strip()
    if permission_mode not in PERMISSION_MODES:
        choices = "、".join(sorted(PERMISSION_MODES))
        raise LanConfigError(f"permission_mode 必须是以下值之一：{choices}")
    password = data.get("password", "")
    if not isinstance(password, str):
        raise LanConfigError("password 必须是字符串")
    preview_roots_raw = data.get("preview_roots", [])
    if not isinstance(preview_roots_raw, list) or not all(isinstance(item, str) for item in preview_roots_raw):
        raise LanConfigError("preview_roots 必须是路径字符串数组")
    preview_roots: list[Path] = []
    for raw_root in preview_roots_raw:
        root = Path(raw_root).expanduser()
        if not root.is_absolute():
            root = config_path.parent / root
        root = root.resolve()
        if not root.is_dir():
            raise LanConfigError(f"预览目录不存在：{root}")
        if root != workspace and root not in preview_roots:
            preview_roots.append(root)

    return LanConfig(
        workspace=workspace,
        host=host,
        port=port,
        app_server_port=app_server_port,
        turn_timeout_seconds=timeout,
        max_image_bytes=max_image_bytes,
        max_images=max_images,
        log_level=str(data.get("log_level", "INFO")).upper(),
        preview_roots=tuple(preview_roots),
        session_ids=session_ids,
        permission_mode=permission_mode,
        password=password,
    )
