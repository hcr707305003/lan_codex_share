"""HTTP/WebSocket proxy to explicit loopback/private-IP targets, without DNS lookup."""

import base64
from dataclasses import dataclass
import hashlib
import http.client
from ipaddress import ip_address
import re
import socket
import tempfile
import threading
from urllib.parse import urljoin, urlsplit

from .lan_access import PRIVATE_V4, request_origin
from .proxy_rewrite import rewrite_cookie, rewrite_document, rewrite_url, rewrite_json


MAX_BODY_BYTES = 128 * 1024 * 1024
MAX_REWRITE_BYTES = 2 * 1024 * 1024
IO_TIMEOUT = 30
CHUNK = 64 * 1024
HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailer", "transfer-encoding", "upgrade"}


class ProxyError(ValueError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ProxyTarget:
    host: str
    port: int
    authority: str
    prefix: str
    path: str
    needs_slash: bool


def parse_target(raw_path: str, blocked_ports: set[int]) -> ProxyTarget:
    parsed = urlsplit(raw_path)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/proxy/"):
        raise ProxyError("反代地址应为 /proxy/localhost:端口/ 或 /proxy/内网IP:端口/")
    authority, slash, path = parsed.path[len("/proxy/"):].partition("/")
    match = re.fullmatch(r"(localhost|\d+\.\d+\.\d+\.\d+|\[::1\]):([1-9]\d{0,4})", authority, re.I)
    if not match:
        raise ProxyError("目标只支持 localhost、内网 IPv4 或 [::1]，必须指定端口")
    name, port = match[1].lower(), int(match[2])
    host = "127.0.0.1" if name == "localhost" else name.strip("[]")
    try:
        address = ip_address(host)
    except ValueError as exc:
        raise ProxyError("目标 IP 无效") from exc
    if not address.is_loopback and not (
        address.version == 4 and any(address in network for network in PRIVATE_V4)
    ):
        raise ProxyError("只允许代理本机和 RFC1918 局域网地址", 403)
    if port > 65535:
        raise ProxyError("端口必须在 1 到 65535 之间")
    if port in blocked_ports:
        raise ProxyError("禁止代理共享服务端口或 Codex App Server 端口", 403)
    upstream = "/" + path
    if parsed.query:
        upstream += "?" + parsed.query
    return ProxyTarget(host, port, authority, f"/proxy/{authority}/", upstream, not slash)


def check_browser_origin(handler) -> str:
    expected = request_origin(handler.headers.get("Host", ""), handler.app.allowed_hosts, handler.app.public_origins)
    origin = handler.headers.get("Origin", "")
    site = handler.headers.get("Sec-Fetch-Site", "")
    if origin and origin != expected:
        raise ProxyError("反代请求 Origin 不允许", 403)
    if site and site not in {"same-origin", "none"}:
        raise ProxyError("不允许跨站反代请求", 403)
    if handler.command not in {"GET", "HEAD", "OPTIONS"} or handler.headers.get("Upgrade"):
        if origin != expected:
            raise ProxyError("反代写入和 WebSocket 请求必须携带本站 Origin", 403)
    return expected


def read_body(handler):
    """Spool bounded uploads before forwarding; reject ambiguous HTTP framing."""
    lengths = handler.headers.get_all("Content-Length", [])
    transfers = handler.headers.get_all("Transfer-Encoding", [])
    if len(lengths) > 1 or len(transfers) > 1 or (lengths and transfers):
        raise ProxyError("不允许重复或冲突的请求长度")
    if transfers and transfers[0].lower().strip() != "chunked":
        raise ProxyError("不支持该 Transfer-Encoding", 501)
    if lengths and not re.fullmatch(r"\d+", lengths[0]):
        raise ProxyError("Content-Length 无效")
    size = int(lengths[0]) if lengths else 0
    if size > MAX_BODY_BYTES:
        raise ProxyError("反代上传不能超过 128 MiB", 413)
    body = tempfile.SpooledTemporaryFile(max_size=1024 * 1024)
    total = 0
    try:
        while True:
            if transfers:
                line = handler.rfile.readline(8193)
                if len(line) > 8192 or not line.endswith(b"\r\n"):
                    raise ProxyError("chunked 长度行无效")
                token = line[:-2].split(b";", 1)[0]
                if not re.fullmatch(b"[0-9A-Fa-f]{1,16}", token):
                    raise ProxyError("chunked 长度无效")
                size = int(token, 16)
                if size == 0:
                    # Trailers are deliberately not forwarded.
                    trailer_bytes = 0
                    while True:
                        trailer = handler.rfile.readline(8193)
                        trailer_bytes += len(trailer)
                        if not trailer.endswith(b"\r\n") or trailer_bytes > 65536:
                            raise ProxyError("chunked trailers 无效")
                        if trailer == b"\r\n":
                            break
                    break
            if total + size > MAX_BODY_BYTES:
                raise ProxyError("反代上传不能超过 128 MiB", 413)
            total += size
            remaining = size
            while remaining:
                chunk = handler.rfile.read(min(CHUNK, remaining))
                if not chunk:
                    raise ProxyError("请求正文提前结束")
                body.write(chunk)
                remaining -= len(chunk)
            if not transfers:
                break
            if handler.rfile.read(2) != b"\r\n":
                raise ProxyError("chunked 分隔符无效")
        body.seek(0)
        return body, total
    except Exception:
        body.close()
        raise


def hop_headers(headers) -> set[str]:
    return HOP_HEADERS | {
        item.strip().lower()
        for value in headers.get_all("Connection", []) for item in value.split(",")
    }


def upstream_headers(handler, target, origin, websocket, auth_cookie):
    excluded = hop_headers(handler.headers) | {"host", "content-length", "accept-encoding", "expect", "forwarded"}
    result = []
    for name, value in handler.headers.items():
        lower = name.lower()
        if lower in excluded or lower.startswith(("x-forwarded-", "cf-")):
            continue
        if lower == "cookie":
            value = "; ".join(
                item.strip() for item in value.split(";")
                if item.strip().partition("=")[0] != auth_cookie
                and not item.strip().partition("=")[0].lower().startswith(("cf_", "__cf"))
            )
            if not value:
                continue
        if lower == "x-csrf-token" and value == handler.app.csrf_token:
            continue
        if lower == "origin":
            value = "http://" + target.authority
        if lower == "referer":
            base = origin + target.prefix
            if not value.startswith(base):
                continue
            value = "http://" + target.authority + "/" + value[len(base):]
        result.append((name, value))
    result.extend([
        ("Host", target.authority), ("Accept-Encoding", "identity"),
        ("X-Forwarded-Host", handler.headers.get("Host", "")),
        ("X-Forwarded-Proto", urlsplit(origin).scheme),
        ("X-Forwarded-Prefix", target.prefix.rstrip("/")),
        ("Connection", "Upgrade" if websocket else "close"),
    ])
    if websocket:
        result.append(("Upgrade", "websocket"))
    return result


class WebSocketResponse(http.client.HTTPResponse):
    def __init__(self, sock, *args, **kwargs):
        super().__init__(sock, *args, **kwargs)
        self.fp.close()
        self.fp = sock.makefile("rb", buffering=0)

    def begin(self):
        super().begin()
        if self.status == 101:
            self.will_close = False


def relay_websocket(handler, upstream):
    finished = threading.Event()
    handler.connection.settimeout(1800)
    upstream.settimeout(1800)

    def pump(read, destination):
        try:
            while not finished.is_set():
                data = read(CHUNK)
                if not data:
                    break
                destination.sendall(data)
        except OSError:
            pass
        finally:
            finished.set()

    # Use rfile for the client direction: HTTP parsing may have already buffered
    # the first frame sent alongside the upgrade request.
    readers = [
        threading.Thread(target=pump, args=(handler.rfile.read1, upstream), daemon=True),
        threading.Thread(target=pump, args=(upstream.recv, handler.connection), daemon=True),
    ]
    for reader in readers:
        reader.start()
    try:
        while not finished.wait(1) and not handler.server.stopping.is_set():
            pass
    finally:
        finished.set()
        for peer in (upstream, handler.connection):
            try:
                peer.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        for reader in readers:
            reader.join(2)


def forward(handler, target: ProxyTarget, origin: str, auth_cookie: str):
    websocket = handler.headers.get("Upgrade", "").lower() == "websocket"
    if handler.headers.get("Upgrade") and not websocket:
        raise ProxyError("只支持 WebSocket 协议升级", 400)
    if websocket:
        key = handler.headers.get("Sec-WebSocket-Key", "")
        try:
            valid_key = len(base64.b64decode(key, validate=True)) == 16
        except ValueError:
            valid_key = False
        if handler.command != "GET" or not valid_key or handler.headers.get("Sec-WebSocket-Version") != "13":
            raise ProxyError("WebSocket 握手无效")
        if "upgrade" not in {part.strip().lower() for part in handler.headers.get("Connection", "").split(",")}:
            raise ProxyError("WebSocket 缺少 Connection: Upgrade")
    handler.close_connection = True
    handler.connection.settimeout(IO_TIMEOUT)
    body, size = read_body(handler)
    connection = http.client.HTTPConnection(target.host, target.port, timeout=IO_TIMEOUT)
    response = None
    started = False
    try:
        if websocket and size:
            raise ProxyError("WebSocket 握手不能包含正文")
        if websocket:
            connection.response_class = WebSocketResponse
        connection.putrequest(handler.command, target.path, skip_host=True, skip_accept_encoding=True)
        for name, value in upstream_headers(handler, target, origin, websocket, auth_cookie):
            connection.putheader(name, value)
        if not websocket:
            connection.putheader("Content-Length", str(size))
        connection.endheaders(body if size else None)
        response = connection.getresponse()
        if response.status == 101:
            expected = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode() if websocket else ""
            if not websocket or response.getheader("Sec-WebSocket-Accept") != expected or response.getheader("Upgrade", "").lower() != "websocket":
                raise ProxyError("目标 WebSocket 握手无效", 502)
            handler.send_response(101)
            handler.send_header("Upgrade", "websocket")
            handler.send_header("Connection", "Upgrade")
            handler.send_header("Sec-WebSocket-Accept", expected)
            for name in ("Sec-WebSocket-Protocol", "Sec-WebSocket-Extensions"):
                if response.getheader(name):
                    handler.send_header(name, response.getheader(name))
            for value in response.headers.get_all("Set-Cookie", []):
                for cookie in rewrite_cookie(value, target.prefix, urlsplit(target.path).path, auth_cookie):
                    handler.send_header("Set-Cookie", cookie)
            handler.end_headers()
            handler.wfile.flush()
            started = True
            relay_websocket(handler, connection.sock)
            return

        # Only small, uncompressed HTML/CSS/JSON is buffered for adaptation. SSE and
        # binary downloads are streamed immediately, including chunked origins.
        content_type = response.getheader("Content-Type", "")
        media_type = content_type.lower().split(";", 1)[0].strip()
        is_json = media_type == "application/json" or (media_type.startswith("application/") and media_type.endswith("+json"))
        prefix_data = b""
        rewritten = None
        no_body = handler.command == "HEAD" or response.status in {204, 304} or response.status < 200
        transformable = (
            not no_body and response.status != 206
            and (media_type in {"text/html", "text/css"} or is_json)
            and response.getheader("Content-Encoding", "identity").lower() == "identity"
            and (response.length is None or response.length <= MAX_REWRITE_BYTES)
        )
        if transformable:
            prefix_data = response.read(MAX_REWRITE_BYTES + 1)
            if len(prefix_data) <= MAX_REWRITE_BYTES:
                if is_json:
                    rewritten = rewrite_json(prefix_data, content_type, target.prefix, target.authority, origin)
                else:
                    rewritten = rewrite_document(prefix_data, content_type, target.prefix, target.authority)
        excluded = hop_headers(response.headers) | {"content-length", "set-cookie", "cache-control", "alt-svc", "strict-transport-security", "clear-site-data", "service-worker-allowed"}
        lengths = response.headers.get_all("Content-Length", [])
        if not response.chunked and (len(lengths) > 1 or (lengths and not re.fullmatch(r"\d+", lengths[0]))):
            raise ProxyError("目标服务返回的 Content-Length 无效", 502)
        if rewritten is not None:
            excluded |= {"etag", "content-md5", "digest", "accept-ranges"}
        handler.send_response(response.status)
        for name, value in response.getheaders():
            if name.lower() in excluded:
                continue
            if name.lower() == "location":
                if not value.startswith("/proxy/"):
                    value = urljoin("http://" + target.authority + target.path, value)
                value = rewrite_url(value, target.prefix, target.authority)
            handler.send_header(name, value)
        for value in response.headers.get_all("Set-Cookie", []):
            for cookie in rewrite_cookie(value, target.prefix, urlsplit(target.path).path, auth_cookie):
                handler.send_header("Set-Cookie", cookie)
        if rewritten is not None:
            handler.send_header("Content-Length", str(len(rewritten)))
        elif response.getheader("Content-Length") is not None and not response.chunked:
            handler.send_header("Content-Length", response.getheader("Content-Length"))
        handler.send_header("Connection", "close")
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()
        handler.wfile.flush()
        started = True
        if no_body:
            return
        if rewritten is not None:
            handler.wfile.write(rewritten)
            return
        if prefix_data:
            handler.wfile.write(prefix_data)
        while chunk := response.read1(CHUNK):
            handler.wfile.write(chunk)
            handler.wfile.flush()
    except (OSError, http.client.HTTPException) as exc:
        if not started:
            raise ProxyError("目标服务连接失败或响应超时，请确认服务已启动且为 HTTP 服务", 502) from exc
        handler.app.logger.info("反代连接结束：%s", type(exc).__name__)
    finally:
        body.close()
        if response is not None:
            response.close()
        connection.close()
