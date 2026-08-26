from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import queue
import secrets
import threading
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from .lan_access import AccessDenied, is_lan_client, validate_host, validate_mutating_request
from .lan_store import ImageStore, ImageValidationError
from .workspace_files import WorkspaceFileError, WorkspaceFileViewer


class LanWebApplication:
    def __init__(
        self,
        service,
        image_store: ImageStore,
        allowed_hosts: set[str],
        *,
        max_request_bytes: int,
        workspace: str | Path | None = None,
        preview_roots: tuple[Path, ...] = (),
        logger: logging.Logger | None = None,
    ):
        self.service = service
        self.image_store = image_store
        self.allowed_hosts = allowed_hosts
        self.max_request_bytes = max_request_bytes
        self.csrf_token = secrets.token_urlsafe(32)
        self.logger = logger or logging.getLogger(__name__)
        self.web_root = Path(__file__).with_name("web")
        missing_assets = [name for name in ("index.html", "app.js", "style.css") if not (self.web_root / name).is_file()]
        if missing_assets:
            raise FileNotFoundError(f"Web 静态资源不完整：{', '.join(missing_assets)}")
        self.file_viewer = WorkspaceFileViewer(workspace or Path.cwd(), preview_roots=preview_roots)

    def create_server(self, host: str, port: int) -> ThreadingHTTPServer:
        server = ThreadingHTTPServer((host, port), LanRequestHandler)
        server.daemon_threads = True
        server.app = self  # type: ignore[attr-defined]
        server.stopping = threading.Event()  # type: ignore[attr-defined]
        return server


class LanRequestHandler(BaseHTTPRequestHandler):
    server_version = "LanCodexShare/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def app(self) -> LanWebApplication:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format_string: str, *args: Any) -> None:
        self.app.logger.info("HTTP %s %s", self.client_address[0], format_string % args)

    def _security_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-store")

    def _send_bytes(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, value: Any) -> None:
        self._send_bytes(status, json.dumps(value, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _guard(self, *, mutation: bool = False) -> None:
        if not is_lan_client(str(self.client_address[0])):
            raise AccessDenied("只允许局域网访问")
        host = self.headers.get("Host", "")
        validate_host(host, self.app.allowed_hosts)
        if mutation:
            validate_mutating_request(
                host=host,
                origin=self.headers.get("Origin", ""),
                content_type=self.headers.get("Content-Type", ""),
                csrf=self.headers.get("X-CSRF-Token", ""),
                expected_csrf=self.app.csrf_token,
                allowed_hosts=self.app.allowed_hosts,
            )

    def do_GET(self) -> None:
        try:
            self._guard()
            request_url = urlsplit(self.path)
            path = request_url.path
            if path == "/":
                page = (self.app.web_root / "index.html").read_text(encoding="utf-8")
                page = page.replace("__CSRF_TOKEN__", self.app.csrf_token)
                body = page.encode("utf-8")
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header(
                    "Content-Security-Policy",
                    "default-src 'self'; img-src 'self' data: blob:; connect-src 'self'; script-src 'self'; style-src 'self'; base-uri 'none'; frame-ancestors 'none'",
                )
                self._security_headers()
                self.end_headers()
                self.wfile.write(body)
                return
            if path == "/app.js":
                self._serve_asset("app.js", "text/javascript; charset=utf-8")
                return
            if path == "/style.css":
                self._serve_asset("style.css", "text/css; charset=utf-8")
                return
            if path == "/api/snapshot":
                session_id = parse_qs(request_url.query, keep_blank_values=True).get("session_id", [None])[0]
                self._json(HTTPStatus.OK, self.app.service.snapshot(session_id))
                return
            if path == "/api/events":
                self._serve_events()
                return
            if path.startswith("/api/images/"):
                self._serve_image(path.rsplit("/", 1)[-1])
                return
            if path == "/api/files/view":
                raw_path = parse_qs(request_url.query, keep_blank_values=True).get("path", [""])[0]
                self._serve_workspace_file(raw_path)
                return
            self._error(HTTPStatus.NOT_FOUND, "页面不存在")
        except AccessDenied as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except (BrokenPipeError, ConnectionResetError):
            return
        except FileNotFoundError:
            self._error(HTTPStatus.NOT_FOUND, "文件不存在")
        except Exception:
            self.app.logger.exception("LAN GET failed")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "服务内部错误")

    def _serve_asset(self, name: str, content_type: str) -> None:
        self._send_bytes(HTTPStatus.OK, (self.app.web_root / name).read_bytes(), content_type)

    def _serve_image(self, image_id: str) -> None:
        path, mime = self.app.image_store.resolve(image_id)
        self._send_bytes(HTTPStatus.OK, path.read_bytes(), mime)

    def _serve_workspace_file(self, raw_path: str) -> None:
        try:
            if hasattr(self.app.service, "preview_roots"):
                self.app.file_viewer.set_dynamic_roots(self.app.service.preview_roots)
            preview = self.app.file_viewer.open(raw_path)
        except WorkspaceFileError as exc:
            self._error(exc.status, str(exc))
            return
        if preview.kind in {"markdown", "code"}:
            self._json(HTTPStatus.OK, preview.json_value())
            return
        filename = quote(preview.name, safe="")
        self._send_bytes(
            HTTPStatus.OK,
            preview.path.read_bytes(),
            preview.mime,
            {"Content-Disposition": f"inline; filename*=UTF-8''{filename}"},
        )

    def _serve_events(self) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        self._security_headers()
        self.end_headers()
        self.wfile.write(b"event: update\ndata: connected\n\n")
        self.wfile.flush()
        subscriber = self.app.service.subscribe()
        try:
            while not self.server.stopping.is_set():  # type: ignore[attr-defined]
                try:
                    version = subscriber.get(timeout=15)
                    payload = f"event: update\ndata: {version}\n\n".encode("utf-8")
                except queue.Empty:
                    payload = b": heartbeat\n\n"
                self.wfile.write(payload)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.app.service.unsubscribe(subscriber)

    def do_POST(self) -> None:
        try:
            self._guard(mutation=True)
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0:
                raise ValueError("请求正文为空")
            if length > self.app.max_request_bytes:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "请求内容过大")
                return
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError("JSON 格式无效") from exc
            if not isinstance(payload, dict):
                raise ValueError("JSON 必须是对象")
            path = urlsplit(self.path).path
            source_ip = str(self.client_address[0])
            session_id = self.app.service.resolve_session_id(payload.get("session_id"))
            if path == "/api/messages":
                raw_images = payload.get("images", [])
                if not isinstance(raw_images, list):
                    raise ValueError("images 必须是数组")
                images = self.app.image_store.save_many(raw_images)
                message_id = self.app.service.submit(session_id, str(payload.get("text", "")), images, source_ip)
                self._json(HTTPStatus.ACCEPTED, {"message_id": message_id})
                return
            if path == "/api/queue/cancel":
                raw_message_id = payload.get("message_id")
                if not isinstance(raw_message_id, str) or not raw_message_id.strip():
                    raise ValueError("message_id 不能为空")
                cancelled = self.app.service.cancel_queued(session_id, raw_message_id.strip(), source_ip)
                self._json(HTTPStatus.OK, {"cancelled": cancelled})
                return
            if path == "/api/queue/clear":
                cleared = self.app.service.clear_queued(session_id, source_ip)
                self._json(HTTPStatus.OK, {"cleared": cleared})
                return
            if path == "/api/cancel":
                self._json(HTTPStatus.OK, {"cancelled": self.app.service.cancel(session_id, source_ip)})
                return
            if path == "/api/resync":
                self._json(HTTPStatus.OK, {"resynced": self.app.service.resync(session_id, source_ip)})
                return
            if path == "/api/settings/model":
                raw_model = payload.get("model")
                raw_effort = payload.get("reasoning_effort")
                raw_service_tier = payload.get("service_tier")
                if not isinstance(raw_model, str) or not raw_model.strip():
                    raise ValueError("model 不能为空")
                if not isinstance(raw_effort, str) or not raw_effort.strip():
                    raise ValueError("reasoning_effort 不能为空")
                if raw_service_tier is not None and not isinstance(raw_service_tier, str):
                    raise ValueError("service_tier 必须是字符串或 null")
                service_tier = raw_service_tier.strip() if isinstance(raw_service_tier, str) else None
                service_tier = service_tier or None
                settings = self.app.service.update_model_settings(
                    session_id, raw_model.strip(), raw_effort.strip(), service_tier, source_ip
                )
                self._json(HTTPStatus.OK, settings)
                return
            if path == "/api/history/clear":
                self._error(HTTPStatus.GONE, "页面现在以真实 Codex Session 为准，不能单独清空网页历史")
                return
            self._error(HTTPStatus.NOT_FOUND, "接口不存在")
        except AccessDenied as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except (ValueError, ImageValidationError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except Exception:
            self.app.logger.exception("LAN POST failed")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "服务内部错误")
