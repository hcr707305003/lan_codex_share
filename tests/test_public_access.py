import http.client
import json
from urllib.parse import quote

import pytest

from lan_codex_share.lan_access import AccessDenied
from lan_codex_share.lan_web import LanRequestHandler
from tests.test_lan_web import login, mutation_headers, request, start_app


@pytest.fixture
def public_app(tmp_path):
    app, service, server, thread = start_app(
        tmp_path, password="test-only password", public_origin="https://codex.example.com",
    )
    try:
        yield app, service, server
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        thread.join(2)


def public_headers(app):
    return {
        "Host": "codex.example.com", "Origin": app.public_origin,
        "Content-Type": "application/json", "X-CSRF-Token": app.csrf_token,
    }


def test_public_login_and_protected_routes(public_app, tmp_path):
    app, service, server = public_app
    headers = public_headers(app)
    document = tmp_path / "test.md"
    document.write_text("# private", encoding="utf-8")
    paths = [
        "/api/snapshot", "/api/events", "/api/images/" + "a" * 32,
        f"/api/files/view?path={quote(str(document))}",
        f"/api/files/download?path={quote(str(document))}",
    ]
    for path in ("/", "/app.js", "/style.css"):
        assert request(server, "GET", path, headers=headers)[0] == 200
    status, _, body = request(server, "GET", "/api/auth/status", headers=headers)
    assert status == 200
    assert json.loads(body) == {"required": True, "authenticated": False, "notify_on_task_complete": False}
    for path in paths:
        assert request(server, "GET", path, headers=headers)[0] == 401
    assert request(server, "POST", "/api/messages", b'{"text":"blocked"}', headers)[0] == 401
    assert service.submitted == []
    assert request(server, "POST", "/api/auth/login", b'{"password":"wrong"}', headers)[0] == 401
    status, response_headers, _ = request(
        server, "POST", "/api/auth/login", b'{"password":"test-only password"}', headers,
    )
    assert status == 200
    cookie = dict(response_headers)["Set-Cookie"]
    assert "; Secure" in cookie and "; HttpOnly" in cookie and "; SameSite=Strict" in cookie
    assert "Domain=" not in cookie
    headers["Cookie"] = cookie.split(";", 1)[0]
    assert request(server, "GET", "/api/snapshot", headers=headers)[0] == 200
    status, _, body = request(server, "GET", paths[-1], headers=headers)
    assert status == 200 and body == b"# private"
    assert request(server, "POST", "/api/messages", b'{"text":"hello","images":[]}', headers)[0] == 202
    assert service.submitted == [("thread-web", "hello", [], "127.0.0.1")]

    # Read the first event without waiting for a long-lived stream to finish.
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request("GET", "/api/events", headers=headers)
        response = connection.getresponse()
        assert response.status == 200
        assert response.getheader("Content-Type").startswith("text/event-stream")
        assert response.fp.readline() == b"event: update\n"
        assert response.fp.readline() == b"data: connected\n"
    finally:
        connection.close()


def test_forwarding_headers_do_not_bypass_origin_or_host(public_app):
    app, _, server = public_app
    headers = {**public_headers(app), "X-Forwarded-Proto": "https", "X-Forwarded-Host": "codex.example.com"}
    for changes in ({"Host": "evil.example"}, {"Origin": "http://codex.example.com"},
                    {"Origin": "https://evil.example"}, {"X-CSRF-Token": "wrong"}):
        assert request(server, "POST", "/api/auth/login", b'{"password":"test-only password"}', {**headers, **changes})[0] == 403
    assert request(server, "GET", "/", headers={**headers, "Host": "evil.example"})[0] == 403
    handler = object.__new__(LanRequestHandler)
    handler.server = server
    handler.headers = {**headers, "CF-Connecting-IP": "127.0.0.1", "X-Forwarded-For": "127.0.0.1"}
    for peer in ("192.168.1.20", "8.8.8.8"):
        handler.client_address = (peer, 12345)
        with pytest.raises(AccessDenied):
            handler._guard()


def test_lan_login_still_uses_http_and_non_secure_cookie(public_app):
    app, _, server = public_app
    status, response_headers, _ = login(server, app.csrf_token, "test-only password")
    assert status == 200
    cookie = dict(response_headers)["Set-Cookie"]
    assert "; Secure" not in cookie
    headers = mutation_headers(server, app.csrf_token)
    headers["Cookie"] = cookie.split(";", 1)[0]
    assert request(server, "POST", "/api/messages", b'{"text":"local"}', headers)[0] == 202


def test_public_login_rate_limit_cannot_be_reset_by_forwarded_ip(public_app):
    app, _, server = public_app
    for attempt in range(5):
        headers = {**public_headers(app), "CF-Connecting-IP": f"192.0.2.{attempt}", "X-Forwarded-For": f"192.0.2.{attempt}"}
        assert request(server, "POST", "/api/auth/login", b'{"password":"wrong"}', headers)[0] == 401
    assert request(server, "POST", "/api/auth/login", b'{"password":"test-only password"}', public_headers(app))[0] == 429


def test_passwordless_public_mode_is_explicitly_supported(tmp_path):
    app, service, server, thread = start_app(tmp_path, public_origin="https://codex.example.com")
    try:
        headers = public_headers(app)
        assert request(server, "GET", "/api/snapshot", headers=headers)[0] == 200
        status, _, body = request(server, "GET", "/api/auth/status", headers=headers)
        assert json.loads(body) == {"required": False, "authenticated": True, "notify_on_task_complete": False}
        assert request(server, "POST", "/api/messages", b'{"text":"hello"}', headers)[0] == 202
        assert len(service.submitted) == 1
        assert request(server, "POST", "/api/messages", b'{"text":"blocked"}', {**headers, "X-CSRF-Token": "wrong"})[0] == 403
        assert len(service.submitted) == 1
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
