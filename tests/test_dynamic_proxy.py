import base64
import gzip
from contextlib import contextmanager
import hashlib
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import threading

import pytest
import websocket

from lan_codex_share.dynamic_proxy import MAX_BODY_BYTES, ProxyError, parse_target
from lan_codex_share.proxy_rewrite import rewrite_cookie, rewrite_document, rewrite_url, rewrite_json
from tests.test_lan_web import login, request, start_app


class Origin(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_args):
        pass

    def do_GET(self):
        if self.headers.get("Upgrade", "").lower() == "websocket":
            key = self.headers["Sec-WebSocket-Key"]
            accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
            self.send_response(101)
            self.send_header("Upgrade", "websocket")
            self.send_header("Connection", "Upgrade")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()
            self.wfile.write(b"\x81\x05ready")
            self.wfile.flush()
            while True:
                head = self.rfile.read(2)
                if not head or head[0] & 15 == 8:
                    return
                size = head[1] & 127
                mask = self.rfile.read(4)
                data = self.rfile.read(size)
                decoded = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
                self.wfile.write(bytes([head[0], size]) + decoded)
                self.wfile.flush()
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            payload = b"data: first\n\n"
            self.wfile.write(f"{len(payload):X}\r\n".encode() + payload + b"\r\n")
            self.wfile.flush()
            self.server.release_stream.wait(5)
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        else:
            self.respond()

    def respond(self):
        data = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.server.seen.append((self.command, self.path, dict(self.headers), data))
        status, mime, body = 200, "application/json", json.dumps({"path": self.path, "method": self.command}).encode()
        if self.path.startswith("/page"):
            mime = "text/html; charset=utf-8"
            body = b'<!doctype html><html><head><link rel="stylesheet" href="/style.css"></head><body><a href="/next">go</a><img src="/image.png"><script>fetch("/data")</script></body></html>'
        elif self.path == "/resource-json":
            mime = getattr(self.server, 'resource_mime', 'application/json')
            body = json.dumps({"qrcode": f"{self.headers.get('X-Forwarded-Proto', 'http')}://{self.headers['Host']}/download?scene=test%2F1"}).encode()
            status = getattr(self.server, 'resource_status', 200)
            if getattr(self.server, 'resource_compressed', False):
                body = gzip.compress(body)
        elif self.path == "/style.css":
            mime, body = "text/css", b'@import "/base.css"; a { background: url("/image.png") }'
        elif self.path == "/download":
            mime, body = "application/octet-stream", bytes(range(256)) * 300
        elif self.path in {"/redirect", "/cross-redirect"}:
            status, body = 302, b""
        elif self.path == "/missing":
            status = 404
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        if self.path == "/resource-json" and getattr(self.server, 'resource_compressed', False):
            self.send_header('Content-Encoding', 'gzip')
        if self.path == "/download":
            self.send_header("Content-Disposition", 'attachment; filename="test.bin"')
        if self.path == "/redirect":
            self.send_header("Location", "/page?x=1")
        if self.path == "/cross-redirect":
            self.send_header("Location", self.server.cross_redirect)
        if self.path == "/cookies":
            self.send_header("Set-Cookie", "sid=test; Path=/; Domain=localhost; HttpOnly")
            self.send_header("Set-Cookie", "prefs=dark; Path=/prefs; SameSite=Lax")
            self.send_header("Set-Cookie", "lan_codex_auth=poison; Path=/")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    do_HEAD = respond
    do_POST = respond
    do_PUT = respond
    do_PATCH = respond
    do_DELETE = respond
    do_OPTIONS = respond


@contextmanager
def origin_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Origin)
    server.daemon_threads = True
    server.seen = []
    server.release_stream = threading.Event()
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server
    finally:
        server.release_stream.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


@pytest.fixture
def proxy(tmp_path):
    app, _, server, thread = start_app(tmp_path)
    with origin_server() as upstream:
        try:
            yield app, server, upstream, f"/proxy/localhost:{upstream.server_port}"
        finally:
            upstream.release_stream.set()
            server.stopping.set()
            server.shutdown()
            server.server_close()
            thread.join(2)


@pytest.mark.parametrize("target", ["localhost:1122", "127.0.0.1:13333", "192.168.1.20:3301", "10.0.0.1:80", "172.16.0.1:8000", "[::1]:8080"])
def test_target_without_registration(target):
    parsed = parse_target(f"/proxy/{target}/api?q=a%2Fb", {9000, 4500})
    assert parsed.path == "/api?q=a%2Fb"
    assert parsed.prefix == f"/proxy/{target}/"


@pytest.mark.parametrize("target", [
    "example.com:80", "8.8.8.8:80", "169.254.169.254:80", "0.0.0.0:80", "172.32.0.1:80",
    "127.1:80", "2130706433:80", "127.0.0.01:80", "localhost:0", "localhost:65536", "localhost:0443",
    "localhost:4500", "192.168.1.20:9000", "user@localhost:80", "%6cocalhost:80", "localhost", "[::ffff:127.0.0.1]:80",
])
def test_rejects_unapproved_targets(target):
    with pytest.raises(ProxyError):
        parse_target(f"/proxy/{target}/", {9000, 4500})


def test_html_css_redirect_and_binary_download(proxy):
    app, server, upstream, prefix = proxy
    status, headers, body = request(server, "GET", prefix + "/page?q=1")
    assert status == 200
    assert prefix.encode() + b'/style.css' in body
    assert b'/proxy-client.js' in body
    assert b'fetch("/data")' in body  # runtime wrapper, not blind JS string replacement
    assert int(dict(headers)["Content-Length"]) == len(body)
    assert upstream.seen[-1][1] == "/page?q=1"
    status, _, css = request(server, "GET", prefix + "/style.css")
    assert prefix.encode() + b'/image.png' in css and prefix.encode() + b'/base.css' in css
    status, headers, _ = request(server, "GET", prefix + "/redirect")
    assert status == 302 and dict(headers)["Location"] == prefix + "/page?x=1"
    status, headers, data = request(server, "GET", prefix + "/download")
    assert status == 200 and data == bytes(range(256)) * 300
    assert "attachment" in dict(headers)["Content-Disposition"]
    assert request(server, "GET", prefix + "/missing")[0] == 404
    status, headers, _ = request(server, "GET", prefix + "?q=1")
    assert status == 307 and dict(headers)["Location"] == prefix + "/?q=1"


@pytest.mark.parametrize("method", ["HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def test_methods_and_upload(proxy, method):
    _, server, upstream, prefix = proxy
    payload = b"binary\x00\xff" * 300 if method != "HEAD" else None
    headers = {"Origin": f"http://127.0.0.1:{server.server_port}", "Content-Type": "multipart/form-data; boundary=test"}
    status, _, body = request(server, method, prefix + "/upload?x=1", payload, headers)
    assert status == 200
    assert upstream.seen[-1][0] == method
    assert upstream.seen[-1][3] == (payload or b"")
    if method == "HEAD":
        assert body == b""


def test_chunked_upload_and_request_limits(proxy):
    _, server, upstream, prefix = proxy
    origin = f"http://127.0.0.1:{server.server_port}"
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    connection.request("POST", prefix + "/upload", iter([b"abc", b"123"]), {"Origin": origin}, encode_chunked=True)
    response = connection.getresponse()
    assert response.status == 200
    response.read()
    connection.close()
    assert upstream.seen[-1][3] == b"abc123"
    for headers, status in [
        ({"Content-Length": str(MAX_BODY_BYTES + 1)}, 413),
        ({"Transfer-Encoding": "gzip"}, 501),
        ({"Content-Length": "3", "Transfer-Encoding": "chunked"}, 400),
    ]:
        assert request(server, "POST", prefix + "/upload", b"", {"Origin": origin, **headers})[0] == status


def test_cookie_scoping_and_share_credentials_are_not_forwarded(proxy):
    app, server, upstream, prefix = proxy
    headers = {"Cookie": f"lan_codex_auth={app.auth_token}; sid=upstream; cf_clearance=private", "X-CSRF-Token": app.csrf_token}
    status, response_headers, _ = request(server, "GET", prefix + "/cookies", headers=headers)
    assert status == 200
    sent_headers = upstream.seen[-1][2]
    assert sent_headers["Cookie"] == "sid=upstream"
    assert "X-CSRF-Token" not in sent_headers
    cookies = [value for name, value in response_headers if name == "Set-Cookie"]
    assert len(cookies) == 2
    assert all("Domain=" not in value and "lan_codex_auth" not in value for value in cookies)
    assert any(f"Path={prefix}/prefs" in value for value in cookies)


def test_password_covers_proxy_and_client_script(proxy):
    app, server, upstream, prefix = proxy
    app.password = "test secret"
    app.auth_token = "test-token"
    assert request(server, "GET", prefix + "/page")[0] == 401
    assert request(server, "GET", "/proxy-client.js")[0] == 401
    assert not upstream.seen
    status, headers, _ = login(server, app.csrf_token, "test secret")
    assert status == 200
    cookie = dict(headers)["Set-Cookie"].split(";", 1)[0]
    assert request(server, "GET", prefix + "/page", headers={"Cookie": cookie})[0] == 200
    assert "Cookie" not in upstream.seen[-1][2]


def test_cross_site_and_loop_requests_never_reach_upstream(proxy):
    _, server, upstream, prefix = proxy
    assert request(server, "POST", prefix + "/write", b"data")[0] == 403
    assert request(server, "POST", prefix + "/write", b"data", {"Origin": "https://evil.example"})[0] == 403
    assert request(server, "GET", prefix + "/page", headers={"Sec-Fetch-Site": "cross-site"})[0] == 403
    assert request(server, "GET", f"/proxy/localhost:{server.server_port}/")[0] == 403
    assert request(server, "GET", "/proxy/localhost:4500/")[0] == 403
    assert not upstream.seen


def test_public_https_proxy_and_configured_app_server_port(proxy):
    app, server, upstream, prefix = proxy
    app.public_origin = "https://codex.example.com"
    headers = {"Host": "codex.example.com", "Origin": app.public_origin}
    assert request(server, "POST", prefix + "/upload", b"https", headers)[0] == 200
    assert upstream.seen[-1][2]["X-Forwarded-Proto"] == "https"
    assert upstream.seen[-1][2]["Origin"] == f"http://localhost:{upstream.server_port}"
    app.app_server_port = upstream.server_port
    count = len(upstream.seen)
    assert request(server, "GET", prefix + "/page", headers=headers)[0] == 403
    assert len(upstream.seen) == count


def test_root_resource_redirect_uses_per_request_referer(proxy):
    _, server, upstream, prefix = proxy
    origin = f"http://127.0.0.1:{server.server_port}"
    for target in (prefix, "/proxy/localhost:1122"):
        status, headers, _ = request(server, "GET", "/module.js?x=1", headers={"Referer": origin + target + "/page"})
        assert status == 307 and dict(headers)["Location"] == target + "/module.js?x=1"
    assert request(server, "GET", "/module.js")[0] == 404
    assert request(server, "GET", "/module.js", headers={"Referer": "https://evil.example" + prefix + "/"})[0] == 403
    assert request(server, "GET", "/proxy-client.js", headers={"Referer": origin + prefix + "/"})[0] == 200


def test_event_stream_is_forwarded_before_origin_finishes(proxy):
    _, server, upstream, prefix = proxy
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request("GET", prefix + "/events")
        response = connection.getresponse()
        assert response.status == 200
        assert response.fp.readline() == b"data: first\n"
        assert not upstream.release_stream.is_set()
    finally:
        upstream.release_stream.set()
        connection.close()


def test_websocket_forwards_early_frame_text_and_binary(proxy):
    _, server, _, prefix = proxy
    client = websocket.create_connection(
        f"ws://127.0.0.1:{server.server_port}{prefix}/ws", timeout=3,
        origin=f"http://127.0.0.1:{server.server_port}", http_no_proxy=["127.0.0.1"],
    )
    try:
        assert client.recv() == "ready"
        client.send("hello")
        assert client.recv() == "hello"
        client.send_binary(b"\x00\xff")
        assert client.recv() == b"\x00\xff"
    finally:
        client.close(timeout=1)


def test_upstream_unavailable_returns_bad_gateway(proxy, monkeypatch):
    monkeypatch.setattr("lan_codex_share.dynamic_proxy.IO_TIMEOUT", 0.2)
    _, server, _, _ = proxy
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
        assert request(server, "GET", f"/proxy/127.0.0.1:{port}/")[0] == 502


def test_rewrite_preserves_external_urls_code_and_encoding():
    prefix, host = "/proxy/localhost:1122/", "localhost:1122"
    assert rewrite_url("https://example.com/a", prefix, host) == "https://example.com/a"
    assert rewrite_url("http://localhost:1122/a?b=1#x", prefix, host) == prefix + "a?b=1#x"
    data = '<html><head></head><body>中文 &amp; <script>const x="/not-rewritten";</script></body></html>'.encode()
    result = rewrite_document(data, "text/html; charset=utf-8", prefix, host)
    assert '中文 &amp;'.encode() in result and b'const x="/not-rewritten"' in result
    assert rewrite_document(b"\xff", "text/html; charset=utf-8", prefix, host) is None
    assert rewrite_cookie("bad cookie", prefix, "/", "lan_codex_auth") == []


@pytest.mark.parametrize("url, expected", [
    ("http://localhost:13333/api?q=a%2Fb#row", "/proxy/localhost:13333/api?q=a%2Fb#row"),
    ("http://127.0.0.1:13333/api", "/proxy/127.0.0.1:13333/api"),
    ("//192.168.1.20:8080/image.png", "/proxy/192.168.1.20:8080/image.png"),
    ("http://10.0.0.1/image.png", "/proxy/10.0.0.1:80/image.png"),
    ("http://[::1]:8080/a", "/proxy/[::1]:8080/a"),
    ("http://172.31.255.1:8080/", "/proxy/172.31.255.1:8080/"),
    ("/proxy/localhost:13333/api?q=1", "/proxy/localhost:13333/api?q=1"),
])
def test_cross_port_url_rewrite(url, expected):
    assert rewrite_url(url, "/proxy/localhost:3301/", "localhost:3301") == expected


@pytest.mark.parametrize("url", [
    "https://localhost:13333/api", "wss://localhost:13333/ws",
    "http://example.com:13333/api", "http://8.8.8.8:80/", "http://169.254.169.254/",
    "http://172.32.0.1/", "http://user:pass@localhost:13333/", "http://localhost:0/",
    "http://localhost:65536/", "http://127.1:80/", "http://localhost.evil.example:80/",
])
def test_cross_port_rewrite_leaves_unsupported_urls_unchanged(url):
    assert rewrite_url(url, "/proxy/localhost:3301/", "localhost:3301") == url


def test_cross_port_html_and_css_resources():
    prefix, host = "/proxy/localhost:3301/", "localhost:3301"
    html = b'<html><head></head><body><img src="http://localhost:13333/image.png"><a href="/proxy/localhost:13333/file">file</a><img srcset="http://localhost:13333/1.png 1x, http://localhost:13333/2.png 2x"></body></html>'
    result = rewrite_document(html, "text/html", prefix, host)
    assert b'src="/proxy/localhost:13333/image.png"' in result
    assert b'href="/proxy/localhost:13333/file"' in result
    assert b'/proxy/localhost:13333/2.png 2x' in result
    css = b'@import "http://localhost:13333/base.css"; a{background:url(//localhost:13333/image.png)}'
    result = rewrite_document(css, "text/css", prefix, host)
    assert b'"/proxy/localhost:13333/base.css"' in result
    assert b'url(/proxy/localhost:13333/image.png)' in result


def test_cross_port_redirects_and_authentication(proxy):
    app, server, frontend, prefix = proxy
    with origin_server() as backend:
        other = f"/proxy/localhost:{backend.server_port}/"
        for location in (f"http://localhost:{backend.server_port}/data?q=1", other + "data?q=1"):
            frontend.cross_redirect = location
            status, headers, _ = request(server, "GET", prefix + "/cross-redirect")
            assert status == 302
            assert dict(headers)["Location"] == other + "data?q=1"
            assert request(server, "GET", dict(headers)["Location"])[0] == 200
            assert backend.seen[-1][1] == "/data?q=1"
        app.password = "test secret"
        app.auth_token = "test-token"
        previous = len(backend.seen)
        assert request(server, "GET", other + "data?q=1")[0] == 401
        assert len(backend.seen) == previous


def test_json_resource_urls_preserve_business_bytes():
    source = br'{"data": ["https:\/\/localhost:13333\/image?scene=a%2Fb#x"], "amount": 1.234567890123456789, "id": 12345678901234567890123, "https://localhost:13333/key": "unchanged", "text":"see https://localhost:13333/image", "other":"https://localhost:14444/image", "public":"https://example.org/a"}'
    result = rewrite_json(source, "application/json", "/proxy/localhost:13333/", "localhost:13333", "https://share.example.com")
    expected = source.replace(br'"https:\/\/localhost:13333\/image?scene=a%2Fb#x"', b'"https://share.example.com/proxy/localhost:13333/image?scene=a%2Fb#x"')
    assert result == expected


@pytest.mark.parametrize("value", [
    "https://localhost:13333/a?x=1#row", "http://localhost:13333/a",
    "https://localhost:13333?x=1", "https://localhost:13333/a?",
])
def test_json_current_backend_urls(value):
    data = json.dumps({"url": value}).encode()
    result = rewrite_json(data, "application/json; charset=utf-8", "/proxy/localhost:13333/", "localhost:13333", "https://share.example.com")
    tail = value.split('localhost:13333', 1)[1]
    assert json.loads(result)["url"] == "https://share.example.com/proxy/localhost:13333" + (tail if tail.startswith('/') else '/' + tail)


@pytest.mark.parametrize("data", [
    b'{"url":"https://public.example/a"}', b'{"url":"https://user@localhost:13333/a"}',
    b'{"url":"https://localhost:13334/a"}', b'{"url":"//localhost:13333/a"}',
    b'{"url":"https://localhost:13333/a"', b'\xff',
])
def test_json_resource_rewrite_bypasses_unrelated_or_invalid_data(data):
    assert rewrite_json(data, "application/json", "/proxy/localhost:13333/", "localhost:13333", "https://share.example.com") is None


def test_public_proxy_json_generated_resource_url(proxy):
    app, server, upstream, prefix = proxy
    app.public_origin = "https://share.example.com"
    status, headers, body = request(server, "GET", prefix + "/resource-json", headers={"Host": "share.example.com"})
    assert status == 200
    assert json.loads(body)["qrcode"] == app.public_origin + prefix + "/download?scene=test%2F1"
    assert int(dict(headers)["Content-Length"]) == len(body)


@pytest.mark.parametrize("mode", ["large", "compressed", "partial", "vendor"])
def test_json_resource_rewrite_response_boundaries(proxy, monkeypatch, mode):
    app, server, upstream, prefix = proxy
    app.public_origin = "https://share.example.com"
    if mode == "large":
        monkeypatch.setattr("lan_codex_share.dynamic_proxy.MAX_REWRITE_BYTES", 10)
    elif mode == "compressed":
        upstream.resource_compressed = True
    elif mode == "partial":
        upstream.resource_status = 206
    else:
        upstream.resource_mime = "application/vnd.example+json"
    status, headers, body = request(server, "GET", prefix + "/resource-json", headers={"Host": "share.example.com"})
    assert status == (206 if mode == "partial" else 200)
    assert int(dict(headers)["Content-Length"]) == len(body)
    if mode == "compressed":
        assert dict(headers)["Content-Encoding"] == "gzip"
        body = gzip.decompress(body)
    expected = app.public_origin + prefix if mode == "vendor" else f"https://localhost:{upstream.server_port}"
    assert json.loads(body)["qrcode"] == expected + "/download?scene=test%2F1"
