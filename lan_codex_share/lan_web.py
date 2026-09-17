from __future__ import annotations

from http.cookies import CookieError, SimpleCookie
from http import HTTPStatus
from ipaddress import ip_address
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import logging
from pathlib import Path
import queue
import secrets
import sys
import threading
import time
from typing import Any
from urllib.parse import parse_qs, quote, urlsplit

from .lan_access import AccessDenied, is_lan_client, normalize_public_origin, normalize_entry_origins, request_origin, validate_mutating_request
from .lan_store import ImageStore, ImageValidationError
from .workspace_files import WorkspaceFileError, WorkspaceFilePreview, WorkspaceFileViewer
from .dynamic_proxy import ProxyError, check_browser_origin, forward, parse_target
from .static_assets import StaticAssets
from .stream_delta import SnapshotDelta
from .auth_tokens import AuthTokens, LOGIN_MAX_AGE


AUTH_COOKIE_NAME = "lan_codex_auth"
LOGIN_FAILURE_LIMIT = 5
LOGIN_FAILURE_WINDOW_SECONDS = 60


class AuthenticationRequired(Exception):
    pass


class LoginRateLimited(Exception):
    pass


class LanThreadingHTTPServer(ThreadingHTTPServer):
    logger = logging.getLogger(__name__)
    # Tunnel HTTP/2 fan-out and Vite imports exceed Python 3.11's default of 5.
    request_queue_size = 128

    def handle_error(self, request: Any, client_address: Any) -> None:
        error = sys.exception()
        if isinstance(error, (ConnectionAbortedError, ConnectionResetError, BrokenPipeError)):
            suffix = f"（WinError {error.winerror}）" if getattr(error, "winerror", None) is not None else ""
            self.logger.info("客户端 %s:%s 已断开连接%s", client_address[0], client_address[1], suffix)
            return
        super().handle_error(request, client_address)


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
        password: str = "",
        auth_state_path: Path | None = None,
        public_origin: str = "",
        cloudflare_origin: str = "",
        frp_origin: str = "",
        app_server_port: int = 4500,
        notify_on_task_complete: bool = False,
        logger: logging.Logger | None = None,
    ):
        self.service = service
        self.image_store = image_store
        self.allowed_hosts = allowed_hosts
        self.max_request_bytes = max_request_bytes
        self.csrf_token = secrets.token_urlsafe(32)
        self.password = password
        self.public_origin = normalize_public_origin(public_origin)
        self.cloudflare_origin = normalize_public_origin(cloudflare_origin)
        self.frp_origin = normalize_public_origin(frp_origin)
        if any(entry.startswith("http://") for entry in self.public_origins) and not password.strip():
            raise ValueError("HTTP 公网入口必须设置非空 password；HTTP 不加密密码或会话内容")
        self.app_server_port = app_server_port
        self.notify_on_task_complete = notify_on_task_complete
        self.auth_tokens = AuthTokens(password, auth_state_path)
        self.login_failures: dict[str, list[float]] = {}
        self.auth_lock = threading.Lock()
        self.logger = logger or logging.getLogger(__name__)
        self.web_root = Path(__file__).with_name("web")
        missing_assets = [name for name in ("index.html", "app.js", "history.js", "realtime.js", "notifications.js", "style.css", "proxy-client.js") if not (self.web_root / name).is_file()]
        if missing_assets:
            raise FileNotFoundError(f"Web 静态资源不完整：{', '.join(missing_assets)}")
        self.static_assets = StaticAssets(self.web_root)
        self.file_viewer = WorkspaceFileViewer(workspace or Path.cwd(), preview_roots=preview_roots)

    @property
    def public_origins(self) -> tuple[str, ...]:
        return normalize_entry_origins(self.public_origin, self.cloudflare_origin, self.frp_origin)

    @property
    def password_required(self) -> bool:
        return bool(self.password)

    def is_authenticated(self, cookie_header: str) -> bool:
        if not self.password_required:
            return True
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header)
        except CookieError:
            return False
        morsel = cookie.get(AUTH_COOKIE_NAME)
        return morsel is not None and self.auth_tokens.verify(morsel.value)

    def authenticate(self, password: str, source_ip: str) -> str:
        if not self.password_required:
            return ""
        now = time.monotonic()
        with self.auth_lock:
            failures = [
                recorded
                for recorded in self.login_failures.get(source_ip, [])
                if now - recorded < LOGIN_FAILURE_WINDOW_SECONDS
            ]
            if len(failures) >= LOGIN_FAILURE_LIMIT:
                self.login_failures[source_ip] = failures
                raise LoginRateLimited("密码尝试过多，请稍后再试")
            if hmac.compare_digest(password.encode("utf-8"), self.password.encode("utf-8")):
                self.login_failures.pop(source_ip, None)
                return self.auth_tokens.issue()
            failures.append(now)
            self.login_failures[source_ip] = failures
        raise AuthenticationRequired("密码错误")

    def create_server(self, host: str, port: int) -> ThreadingHTTPServer:
        server = LanThreadingHTTPServer((host, port), LanRequestHandler)
        server.daemon_threads = True
        server.logger = self.logger
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

    def _security_headers(self, cache_control: str = "no-store") -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", cache_control)

    def _send_bytes(self, status: int, body: bytes, content_type: str, headers: dict[str, str] | None = None, *, cache_control: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self._security_headers(cache_control)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, value: Any, headers: dict[str, str] | None = None) -> None:
        self._send_bytes(
            status,
            json.dumps(value, ensure_ascii=False).encode("utf-8"),
            "application/json; charset=utf-8",
            headers,
        )

    def _error(self, status: int, message: str) -> None:
        self._json(status, {"error": message})

    def _guard(self, *, mutation: bool = False) -> None:
        if not is_lan_client(str(self.client_address[0])):
            raise AccessDenied("只允许局域网访问")
        host = self.headers.get("Host", "")
        expected_origin = request_origin(host, self.app.allowed_hosts, self.app.public_origins)
        if expected_origin in self.app.public_origins:
            # cloudflared/frpc must run on this host. Forwarding headers cannot grant trust.
            if not ip_address(self.client_address[0]).is_loopback:
                raise AccessDenied("公网入口只接受本机反向代理连接")
        if mutation:
            validate_mutating_request(
                host=host,
                origin=self.headers.get("Origin", ""),
                content_type=self.headers.get("Content-Type", ""),
                csrf=self.headers.get("X-CSRF-Token", ""),
                expected_csrf=self.app.csrf_token,
                allowed_hosts=self.app.allowed_hosts,
                public_origin=self.app.public_origins,
            )

    def _require_authentication(self) -> None:
        if not self.app.is_authenticated(self.headers.get("Cookie", "")):
            raise AuthenticationRequired("需要密码登录")

    def do_GET(self) -> None:
        if self._try_proxy():
            return
        try:
            self._guard()
            request_url = urlsplit(self.path)
            path = request_url.path
            if path == "/":
                page = (self.app.web_root / "index.html").read_text(encoding="utf-8")
                page = page.replace("__CSRF_TOKEN__", self.app.csrf_token)
                for name in self.app.static_assets.names:
                    page = page.replace(f'"/{name}"', f'"{self.app.static_assets.url(name)}"')
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
            if path.startswith("/assets/"):
                asset = self.app.static_assets.get(path)
                if asset is None:
                    self._error(404, "静态资源版本不存在，请刷新页面")
                    return
                cache = "public, max-age=31536000, immutable"
                etags = [part.strip().removeprefix("W/") for part in self.headers.get("If-None-Match", "").split(",")]
                if asset.etag in etags or "*" in etags:
                    self.send_response(304)
                    self.send_header("ETag", asset.etag)
                    self._security_headers(cache)
                    self.end_headers()
                else:
                    self._send_bytes(200, asset.body, asset.mime, {"ETag": asset.etag}, cache_control=cache)
                return
            if path in {"/app.js", "/history.js", "/realtime.js", "/notifications.js"}:
                self._serve_asset(path[1:], "text/javascript; charset=utf-8")
                return
            if path == "/style.css":
                self._serve_asset("style.css", "text/css; charset=utf-8")
                return
            if path == "/api/auth/status":
                self._json(
                    HTTPStatus.OK,
                    {
                        "required": self.app.password_required,
                        "authenticated": self.app.is_authenticated(self.headers.get("Cookie", "")),
                        "notify_on_task_complete": self.app.notify_on_task_complete,
                    },
                    {"X-CSRF-Token": self.app.csrf_token},
                )
                return
            self._require_authentication()
            if path == "/proxy-client.js":
                self._serve_asset("proxy-client.js", "text/javascript; charset=utf-8")
                return
            if path == "/api/snapshot":
                query = parse_qs(request_url.query, keep_blank_values=True)
                session_id = query.get("session_id", [None])[0]
                limit = int(query.get("limit", ["20"])[0])
                if not 1 <= limit <= 50:
                    raise ValueError("每页数量必须为 1 到 50")
                self._json(HTTPStatus.OK, self.app.service.snapshot(
                    session_id, history_limit=limit, before=query.get("before", [None])[0],
                ))
                return
            if path == "/api/history/activities":
                query = parse_qs(request_url.query, keep_blank_values=True)
                self._json(HTTPStatus.OK, self.app.service.activities(
                    query.get("session_id", [None])[0], query.get("turn_id", [""])[0],
                    query.get("epoch", [""])[0], query.get("before", [None])[0],
                ))
                return
            if path == "/api/events":
                query = parse_qs(request_url.query, keep_blank_values=True)
                if query.get("mode", [""])[0] == "delta":
                    self._serve_delta_events(query.get("session_id", [None])[0])
                else:
                    self._serve_events()
                return
            if path.startswith("/api/images/"):
                self._serve_image(path.rsplit("/", 1)[-1])
                return
            if path == "/api/files/view":
                raw_path = parse_qs(request_url.query, keep_blank_values=True).get("path", [""])[0]
                self._serve_workspace_file(raw_path)
                return
            if path == "/api/files/download":
                raw_path = parse_qs(request_url.query, keep_blank_values=True).get("path", [""])[0]
                self._serve_workspace_download(raw_path)
                return
            self._error(HTTPStatus.NOT_FOUND, "页面不存在")
        except AuthenticationRequired as exc:
            self._error(HTTPStatus.UNAUTHORIZED, str(exc))
        except AccessDenied as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except ValueError as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
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
            preview = self._open_workspace_file(raw_path)
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

    def _serve_workspace_download(self, raw_path: str) -> None:
        try:
            preview = self._open_workspace_file(raw_path)
        except WorkspaceFileError as exc:
            self._error(exc.status, str(exc))
            return
        filename = quote(preview.name, safe="")
        self._send_bytes(
            HTTPStatus.OK,
            preview.path.read_bytes(),
            preview.mime,
            {"Content-Disposition": f"attachment; filename*=UTF-8''{filename}"},
        )

    def _open_workspace_file(self, raw_path: str) -> WorkspaceFilePreview:
        if hasattr(self.app.service, "preview_roots"):
            self.app.file_viewer.set_dynamic_roots(self.app.service.preview_roots)
        return self.app.file_viewer.open(raw_path)

    def _serve_delta_events(self, session_id: str | None) -> None:
        subscriber = self.app.service.subscribe()
        started = False
        try:
            # Validate selection and prepare a bounded baseline before sending
            # streaming headers. Subscribe first so no changes are lost here.
            first = self.app.service.snapshot(session_id, history_limit=20)
            selected = first.get("selected_session_id") or first.get("thread_id") or session_id
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Connection", "keep-alive")
            self.send_header("X-Accel-Buffering", "no")
            self._security_headers("no-store, no-transform")
            self.end_headers()
            started = True
            self.connection.settimeout(30)
            stream = SnapshotDelta()

            def send(frame):
                if frame is not None:
                    data = json.dumps(frame['data'], ensure_ascii=False, separators=(',', ':'))
                    self.wfile.write(f"event: {frame['event']}\ndata: {data}\n\n".encode('utf-8'))
                    self.wfile.flush()

            send(stream.next(first))
            last_sent = time.monotonic()
            while not self.server.stopping.is_set():
                try:
                    subscriber.get(timeout=15)
                except queue.Empty:
                    if not self.app.is_authenticated(self.headers.get("Cookie", "")):
                        break
                    self.wfile.write(b": heartbeat\n\n")
                    self.wfile.flush()
                    continue
                if self.server.stopping.wait(max(0, 0.15 - (time.monotonic() - last_sent))):
                    break
                while True:
                    try:
                        subscriber.get_nowait()
                    except queue.Empty:
                        break
                if not self.app.is_authenticated(self.headers.get("Cookie", "")):
                    break
                send(stream.next(self.app.service.snapshot(selected, history_limit=20)))
                last_sent = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        except Exception:
            if not started:
                raise
            self.app.logger.exception("实时增量流中断")
            # Do not append an HTTP error response inside an SSE body.
        finally:
            self.close_connection = True
            self.app.service.unsubscribe(subscriber)

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
                if not self.app.is_authenticated(self.headers.get("Cookie", "")):
                    break
                self.wfile.write(payload)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.close_connection = True
            self.app.service.unsubscribe(subscriber)

    def do_POST(self) -> None:
        if self._try_proxy():
            return
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
            if path == "/api/auth/login":
                raw_password = payload.get("password")
                if not isinstance(raw_password, str):
                    raise ValueError("password 必须是字符串")
                token = self.app.authenticate(raw_password, source_ip)
                headers = None
                if token:
                    origin = request_origin(self.headers.get("Host", ""), self.app.allowed_hosts, self.app.public_origins)
                    secure = "; Secure" if origin.startswith("https://") else ""
                    headers = {
                        "Set-Cookie": f"{AUTH_COOKIE_NAME}={token}; Path=/; Max-Age={LOGIN_MAX_AGE}; HttpOnly; SameSite=Strict{secure}"
                    }
                self._json(HTTPStatus.OK, {"authenticated": True}, headers)
                return
            self._require_authentication()
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
            if path == "/api/session/release":
                released = self.app.service.release_session(session_id, source_ip)
                self._json(HTTPStatus.OK, {"released": released})
                return
            if path == "/api/session/reconnect":
                reconnected = self.app.service.reconnect_session(session_id, source_ip)
                self._json(HTTPStatus.OK, {"reconnected": reconnected})
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
        except LoginRateLimited as exc:
            self._error(HTTPStatus.TOO_MANY_REQUESTS, str(exc))
        except AuthenticationRequired as exc:
            self._error(HTTPStatus.UNAUTHORIZED, str(exc))
        except AccessDenied as exc:
            self._error(HTTPStatus.FORBIDDEN, str(exc))
        except (ValueError, ImageValidationError) as exc:
            self._error(HTTPStatus.BAD_REQUEST, str(exc))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return
        except Exception:
            self.app.logger.exception("LAN POST failed")
            self._error(HTTPStatus.INTERNAL_SERVER_ERROR, "服务内部错误")

    def _try_proxy(self) -> bool:
        direct = self.path.startswith("/proxy/")
        # Canonicalize root-relative resources from a proxied page (including ES
        # module imports) without a global "current target" cookie across tabs.
        try:
            referer = urlsplit(self.headers.get("Referer", ""))
        except ValueError:
            referer = urlsplit("")
        fallback = (
            not direct and self.path.startswith("/") and not self.path.startswith("//")
            and urlsplit(self.path).path != "/proxy-client.js"
            and referer.path.startswith("/proxy/")
        )
        if not direct and not fallback:
            return False
        # Every proxy response closes this HTTP connection, including rejection
        # paths, so unread upload bytes cannot become a second HTTP request.
        self.close_connection = True
        try:
            self._guard()
            self._require_authentication()
            origin = check_browser_origin(self)
            if fallback:
                if f"{referer.scheme}://{referer.netloc}" != origin:
                    raise ProxyError("资源请求 Referer 不允许", 403)
                target = parse_target(referer.path, {int(self.server.server_port), self.app.app_server_port})
                self._send_bytes(307, b"", "text/plain", {"Location": target.prefix.rstrip("/") + self.path})
                return True
            target = parse_target(self.path, {int(self.server.server_port), self.app.app_server_port})
            if target.needs_slash:
                query = urlsplit(self.path).query
                self._send_bytes(307, b"", "text/plain", {"Location": target.prefix + ("?" + query if query else "")})
            else:
                forward(self, target, origin, AUTH_COOKIE_NAME)
        except AuthenticationRequired:
            # Keep login on the existing trusted Share page, never the upstream.
            body = '<!doctype html><meta charset="utf-8"><title>需要项目密码</title><p>请先<a href="/" target="_blank" rel="noopener">打开共享首页登录</a>，登录后刷新此页。</p>'
            self._send_bytes(401, body.encode("utf-8"), "text/html; charset=utf-8")
        except AccessDenied as exc:
            self._error(403, str(exc))
        except ProxyError as exc:
            self._error(exc.status, str(exc))
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass
        except (OSError, ValueError) as exc:
            self.app.logger.info("反代请求结束：%s", type(exc).__name__)
            self._error(502, "反代连接失败或超时")
        return True

    def _proxy_method(self) -> None:
        if self.command == "HEAD" and urlsplit(self.path).path.startswith("/assets/"):
            self.do_GET()
            return
        if not self._try_proxy():
            self.close_connection = True
            self._error(405, "该路径不支持此方法")

    do_HEAD = _proxy_method
    do_PUT = _proxy_method
    do_PATCH = _proxy_method
    do_DELETE = _proxy_method
    do_OPTIONS = _proxy_method
