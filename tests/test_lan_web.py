import http.client
import json
import threading

import pytest

from lan_codex_share.lan_store import ImageStore
from lan_codex_share.lan_web import LanWebApplication


class FakeService:
    def __init__(self):
        self.submitted = []
        self.cancelled = []
        self.cancelled_queued = []
        self.cleared_queued = []
        self.resynced = []
        self.model_updates = []
        self.subscribers = set()

    def resolve_session_id(self, session_id=None):
        selected = session_id or "thread-web"
        if selected != "thread-web":
            raise ValueError("指定的 Session 不在共享列表中")
        return selected

    def snapshot(self, session_id=None):
        selected = self.resolve_session_id(session_id)
        return {
            "thread_id": "thread-web",
            "selected_session_id": selected,
            "sessions": [{
                "thread_id": "thread-web", "name": "Web Session", "status": "idle",
                "connection": "connected", "queue_size": 0,
            }],
            "status": "idle",
            "connection": "connected",
            "queue_size": 0,
            "version": 1,
            "thread": {"id": "thread-web", "turns": []},
            "pending": [],
            "model_catalog": [{
                "id": "gpt-5.6-sol", "model": "gpt-5.6-sol", "display_name": "GPT-5.6 Sol",
                "description": "Frontier coding model", "is_default": True,
                "default_reasoning_effort": "high",
                "default_service_tier": None,
                "service_tiers": [{"id": "fast", "name": "Fast", "description": "Lower latency"}],
                "supported_reasoning_efforts": [{"value": "high", "description": "Deeper"}],
            }],
            "model_settings": {
                "model": "gpt-5.6-sol", "reasoning_effort": "high", "service_tier": None,
            },
        }

    def submit(self, session_id, text, images, source_ip):
        self.submitted.append((session_id, text, images, source_ip))
        return "message-1"

    def cancel(self, session_id, source_ip):
        self.cancelled.append((session_id, source_ip))
        return True

    def cancel_queued(self, session_id, message_id, source_ip):
        self.cancelled_queued.append((session_id, message_id, source_ip))
        return True

    def clear_queued(self, session_id, source_ip):
        self.cleared_queued.append((session_id, source_ip))
        return 2

    def resync(self, session_id, source_ip):
        self.resynced.append((session_id, source_ip))
        return True

    def update_model_settings(self, session_id, model, reasoning_effort, service_tier, source_ip):
        self.model_updates.append((session_id, model, reasoning_effort, service_tier, source_ip))
        return {"model": model, "reasoning_effort": reasoning_effort, "service_tier": service_tier}

    def subscribe(self):
        import queue

        value = queue.Queue()
        self.subscribers.add(value)
        return value

    def unsubscribe(self, subscriber):
        self.subscribers.discard(subscriber)


def start_app(tmp_path):
    service = FakeService()
    images = ImageStore(tmp_path / "uploads", max_bytes=1024 * 1024, max_images=4)
    app = LanWebApplication(
        service,
        images,
        {"127.0.0.1", "localhost"},
        max_request_bytes=2 * 1024 * 1024,
        workspace=tmp_path,
    )
    server = app.create_server("127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return app, service, server, thread


def request(server, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    base_headers = {"Host": f"127.0.0.1:{server.server_port}"}
    base_headers.update(headers or {})
    connection.request(method, path, body=body, headers=base_headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, response.getheaders(), data


def mutation_headers(server, csrf):
    host = f"127.0.0.1:{server.server_port}"
    return {
        "Host": host,
        "Origin": f"http://{host}",
        "Content-Type": "application/json",
        "X-CSRF-Token": csrf,
    }


def test_web_application_rejects_missing_frozen_assets(tmp_path, monkeypatch):
    monkeypatch.setattr("lan_codex_share.lan_web.__file__", str(tmp_path / "lan_web.py"))
    images = ImageStore(tmp_path / "uploads", max_bytes=1024, max_images=1)

    with pytest.raises(FileNotFoundError, match="Web 静态资源不完整"):
        LanWebApplication(FakeService(), images, {"127.0.0.1"}, max_request_bytes=2048, workspace=tmp_path)


def test_page_snapshot_and_message_post(tmp_path):
    app, service, server, thread = start_app(tmp_path)
    try:
        status, headers, page = request(server, "GET", "/")
        assert status == 200
        assert app.csrf_token.encode() in page
        assert b'id="timeline"' in page
        assert b'id="resync"' in page
        assert b'id="file-preview"' in page
        assert b'id="clear-queue"' in page
        assert b'id="queue-panel"' in page
        assert b'id="queue-count"' in page
        assert b'id="queue-list"' in page
        assert b'id="processing-banner"' in page
        assert b'id="model-toggle"' in page
        assert b'id="project-list"' in page
        assert b'id="session-control"' in page
        assert b'id="session-select"' in page
        assert b'id="speed-select"' in page
        assert b'id="scroll-to-bottom"' in page
        assert b'aria-label="\xe5\x9b\x9e\xe5\x88\xb0\xe6\x9c\x80\xe6\x96\xb0\xe6\xb6\x88\xe6\x81\xaf"' in page
        assert b'id="image-lightbox"' in page
        assert b'aria-label="\xe5\x85\xb3\xe9\x97\xad\xe5\x9b\xbe\xe7\x89\x87\xe9\xa2\x84\xe8\xa7\x88"' in page
        assert b'aria-atomic="true"' in page
        assert b'id="clear"' not in page
        assert dict(headers)["X-Content-Type-Options"] == "nosniff"
        assert "img-src 'self' data: blob:" in dict(headers)["Content-Security-Policy"]

        status, _, stylesheet = request(server, "GET", "/style.css")
        assert status == 200
        assert b"container-type: inline-size" in stylesheet
        assert b".topbar-title-group > div" in stylesheet
        assert b"@container (max-width: 640px)" in stylesheet
        assert b"@media (min-width: 821px) and (max-width: 1199px)" in stylesheet
        assert b"width: min(640px, calc(100vw - var(--sidebar-width)))" in stylesheet
        assert b".main-panel { width: 100%; max-width: 100vw; height: 100dvh; }" in stylesheet
        assert b"env(safe-area-inset-bottom)" in stylesheet
        assert b".answer table, .file-markdown table" in stylesheet
        assert b".answer img, .file-markdown img" in stylesheet
        assert b"@media (max-width: 360px)" in stylesheet
        assert b"grid-template-columns: minmax(0, 1fr)" in stylesheet
        assert b".project-group" in stylesheet
        assert b".session-control[hidden]" in stylesheet
        assert b".queue-panel[hidden]" in stylesheet
        assert b".queue-list" in stylesheet
        status, _, script = request(server, "GET", "/app.js")
        assert status == 200
        assert b"reasoning" in script
        assert b"commandExecution" in script
        assert b"parseLocalFileTarget" in script
        assert b"/api/queue/cancel" in script
        assert b"/api/queue/clear" in script
        assert b"renderQueue(pending)" in script
        assert b"fragment.append(renderUserMessage(pending, true))" not in script
        assert b"processingBanner.hidden = !processing" in script
        assert b"Codex \xe5\xa4\x84\xe7\x90\x86\xe4\xb8\xad" in script
        assert b"renderProjectNavigation" in script
        assert b"collapsedProjects" in script
        assert b"/api/settings/model" in script
        assert b"selectedSessionId" in script
        assert b"previewReturnFocus" in script
        assert b"resetOuterLayoutScroll" in script
        assert b"element.scrollTop = 0" in script
        assert b"filePreviewBody.scrollTop = Math.max(0, centeredTop)" in script
        assert b"scrollIntoView" not in script
        assert b"syncScrollToBottomButton" in script
        assert b"behavior: reduceMotion ? 'auto' : 'smooth'" in script
        assert b"timeline.addEventListener('scroll'" in script
        assert b"openImageLightbox" in script
        assert b"closeImageLightbox" in script
        assert b"if (imageLightbox.open)" in script
        assert b"event.preventDefault()" in script
        assert b"imageLightbox.addEventListener('cancel'" in script
        assert b"button.setAttribute('aria-label', `\xe6\x94\xbe\xe5\xa4\xa7\xe6\x9f\xa5\xe7\x9c\x8b ${label}`)" in script

        status, _, snapshot = request(server, "GET", "/api/snapshot")
        assert status == 200
        assert json.loads(snapshot)["thread_id"] == "thread-web"
        status, _, snapshot = request(server, "GET", "/api/snapshot?session_id=thread-web")
        assert status == 200
        assert json.loads(snapshot)["selected_session_id"] == "thread-web"
        assert request(server, "GET", "/api/snapshot?session_id=not-shared")[0] == 400

        payload = json.dumps({"session_id": "thread-web", "text": "hello", "images": []}).encode()
        status, _, result = request(server, "POST", "/api/messages", payload, mutation_headers(server, app.csrf_token))
        assert status == 202
        assert json.loads(result)["message_id"] == "message-1"
        assert service.submitted == [("thread-web", "hello", [], "127.0.0.1")]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_security_and_control_routes(tmp_path):
    app, service, server, thread = start_app(tmp_path)
    try:
        payload = json.dumps({"text": "hello", "images": []}).encode()
        bad_headers = mutation_headers(server, app.csrf_token)
        bad_headers["Origin"] = "http://evil.example"
        assert request(server, "POST", "/api/messages", payload, bad_headers)[0] == 403
        assert request(server, "GET", "/", headers={"Host": "evil.example"})[0] == 403

        headers = mutation_headers(server, app.csrf_token)
        assert request(server, "POST", "/api/cancel", b"{}", headers)[0] == 200
        status, _, cancelled = request(
            server,
            "POST",
            "/api/queue/cancel",
            json.dumps({"message_id": "queued-1"}).encode(),
            headers,
        )
        assert status == 200
        assert json.loads(cancelled) == {"cancelled": True}
        status, _, cleared = request(server, "POST", "/api/queue/clear", b"{}", headers)
        assert status == 200
        assert json.loads(cleared) == {"cleared": 2}
        assert request(server, "POST", "/api/queue/cancel", b"{}", headers)[0] == 400
        assert request(server, "POST", "/api/resync", b"{}", headers)[0] == 200
        status, _, updated = request(
            server,
            "POST",
            "/api/settings/model",
            json.dumps({"model": "gpt-5.6-sol", "reasoning_effort": "high", "service_tier": "fast"}).encode(),
            headers,
        )
        assert status == 200
        assert json.loads(updated) == {
            "model": "gpt-5.6-sol", "reasoning_effort": "high", "service_tier": "fast",
        }
        status, _, default_speed = request(
            server,
            "POST",
            "/api/settings/model",
            json.dumps({"model": "gpt-5.6-sol", "reasoning_effort": "high", "service_tier": None}).encode(),
            headers,
        )
        assert status == 200
        assert json.loads(default_speed)["service_tier"] is None
        assert request(server, "POST", "/api/settings/model", b"{}", headers)[0] == 400
        assert request(server, "POST", "/api/history/clear", b"{}", headers)[0] == 410
        assert service.cancelled == [("thread-web", "127.0.0.1")]
        assert service.cancelled_queued == [("thread-web", "queued-1", "127.0.0.1")]
        assert service.cleared_queued == [("thread-web", "127.0.0.1")]
        assert service.resynced == [("thread-web", "127.0.0.1")]
        assert service.model_updates == [
            ("thread-web", "gpt-5.6-sol", "high", "fast", "127.0.0.1"),
            ("thread-web", "gpt-5.6-sol", "high", None, "127.0.0.1"),
        ]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_workspace_file_preview_route_and_boundary(tmp_path):
    markdown = tmp_path / "design.md"
    markdown.write_text("# Design", encoding="utf-8")
    image = tmp_path / "diagram.png"
    image.write_bytes(b"png-data")
    outside = tmp_path.parent / "outside-lan-preview.txt"
    outside.write_text("secret", encoding="utf-8")
    app, service, server, thread = start_app(tmp_path)
    try:
        from urllib.parse import quote

        status, _, body = request(server, "GET", f"/api/files/view?path={quote(str(markdown))}")
        assert status == 200
        preview = json.loads(body)
        assert preview["kind"] == "markdown"
        assert preview["content"] == "# Design"

        status, headers, body = request(server, "GET", f"/api/files/view?path={quote(str(image))}")
        assert status == 200
        assert dict(headers)["Content-Type"] == "image/png"
        assert body == b"png-data"

        status, _, body = request(server, "GET", f"/api/files/view?path={quote(str(outside))}")
        assert status == 403
        assert "工作区" in json.loads(body)["error"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
        outside.unlink(missing_ok=True)


def test_sse_sends_initial_event(tmp_path):
    app, service, server, thread = start_app(tmp_path)
    connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=2)
    try:
        connection.request("GET", "/api/events", headers={"Host": f"127.0.0.1:{server.server_port}"})
        response = connection.getresponse()
        assert response.status == 200
        assert response.readline().startswith(b"event: update")
        assert response.readline().startswith(b"data:")
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(2)
