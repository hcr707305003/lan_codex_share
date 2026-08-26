import threading
import time

import pytest

from lan_codex_share.codex_client import CodexClientError
from lan_codex_share.lan_service import LanChatService
from lan_codex_share.session_projection import SessionProjection


class FakeCodex:
    def __init__(self):
        self.calls = []
        self.thread_id = "thread-lan"
        self.active = 0
        self.max_active = 0
        self.release = threading.Event()
        self.release.set()
        self.interrupted = False
        self.failure = None
        self.thread_busy = False
        self.state_handlers = []
        self.notification_handlers = []
        self.settings_updates = []
        self.closed = 0
        self.read_failure = None
        self.model_settings = {
            "model": "gpt-5.6-sol", "reasoning_effort": "high", "service_tier": None,
        }

    def ensure_thread(self):
        return self.thread_id

    def read_thread(self, include_turns=True):
        if self.read_failure:
            raise self.read_failure
        return {
            "id": self.thread_id,
            "name": "LAN Shared",
            "status": {"type": "idle"},
            "turns": [{"id": "history-turn", "status": "completed", "items": [{"id": "history-answer", "type": "agentMessage", "text": "history"}]}] if include_turns else [],
        }

    def _emit(self, method, params):
        for handler in self.notification_handlers:
            handler(method, params)

    def run_turn_items(self, items, on_delta=None, *, client_user_message_id=None, additional_context=None):
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        turn_id = f"turn-{len(self.calls) + 1}"
        self.calls.append({
            "items": items,
            "client_user_message_id": client_user_message_id,
            "additional_context": additional_context,
        })
        self._emit("turn/started", {"threadId": self.thread_id, "turn": {"id": turn_id, "status": "inProgress", "items": []}})
        user = {"id": f"user-{turn_id}", "type": "userMessage", "clientId": client_user_message_id, "content": items}
        self._emit("item/started", {"threadId": self.thread_id, "turnId": turn_id, "item": user})
        self._emit("item/reasoning/summaryTextDelta", {
            "threadId": self.thread_id,
            "turnId": turn_id,
            "itemId": f"reason-{turn_id}",
            "summaryIndex": 0,
            "delta": "checking",
        })
        self._emit("item/agentMessage/delta", {
            "threadId": self.thread_id,
            "turnId": turn_id,
            "itemId": f"answer-{turn_id}",
            "delta": "partial",
        })
        self.release.wait(2)
        self.active -= 1
        if self.failure:
            raise self.failure
        answer = f"answer-{len(self.calls)}"
        self._emit("item/completed", {
            "threadId": self.thread_id,
            "turnId": turn_id,
            "item": {"id": f"answer-{turn_id}", "type": "agentMessage", "text": answer},
        })
        self._emit("turn/completed", {"threadId": self.thread_id, "turn": {"id": turn_id, "status": "completed"}})
        return answer

    def interrupt_turn(self):
        self.interrupted = True
        return self.active > 0

    def close(self):
        self.closed += 1

    def wait_for_thread_idle(self, timeout=None):
        if not self.thread_busy:
            return True
        time.sleep(min(timeout or 0, 0.01))
        return False

    def add_thread_state_handler(self, handler):
        self.state_handlers.append(handler)

    def add_notification_handler(self, handler):
        self.notification_handlers.append(handler)

    def list_models(self):
        return [
            {
                "id": "gpt-5.6-sol", "model": "gpt-5.6-sol", "display_name": "GPT-5.6 Sol",
                "description": "Frontier coding model", "is_default": True,
                "default_reasoning_effort": "high",
                "default_service_tier": None,
                "service_tiers": [{"id": "fast", "name": "Fast", "description": "Lower latency"}],
                "supported_reasoning_efforts": [
                    {"value": "medium", "description": "Balanced"},
                    {"value": "high", "description": "Deeper"},
                ],
            },
            {
                "id": "gpt-5.6-luna", "model": "gpt-5.6-luna", "display_name": "GPT-5.6 Luna",
                "description": "Fast coding model", "is_default": False,
                "default_reasoning_effort": "medium",
                "default_service_tier": "priority",
                "service_tiers": [{"id": "priority", "name": "Priority", "description": "Priority processing"}],
                "supported_reasoning_efforts": [{"value": "medium", "description": "Balanced"}],
            },
        ]

    def update_thread_settings(self, model, reasoning_effort, service_tier):
        self.settings_updates.append((model, reasoning_effort, service_tier))
        self.model_settings = {
            "model": model, "reasoning_effort": reasoning_effort, "service_tier": service_tier,
        }
        self._emit("thread/settings/updated", {
            "threadId": self.thread_id,
            "threadSettings": {"model": model, "effort": reasoning_effort, "serviceTier": service_tier},
        })
        return dict(self.model_settings)


def wait_until(predicate, timeout=2):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def make_service(tmp_path, codex=None):
    codex = codex or FakeCodex()
    service = LanChatService(codex, SessionProjection(tmp_path / "uploads"))
    service.start()
    return service, codex


def test_fifo_shared_session_and_structured_inputs(tmp_path):
    service, codex = make_service(tmp_path)
    try:
        first_id = service.submit("first", [], "192.168.1.2")
        second_id = service.submit(
            "second",
            [{"id": "a" * 32, "name": "a.png", "mime": "image/png", "path": str(tmp_path / "uploads" / ("a" * 32 + ".png"))}],
            "192.168.1.3",
        )
        wait_until(lambda: len(codex.calls) == 2 and service.snapshot()["status"] == "idle")

        assert codex.max_active == 1
        assert codex.calls[0]["items"] == [{"type": "text", "text": "first"}]
        assert codex.calls[0]["client_user_message_id"] == first_id
        assert "192.168.1.2" in codex.calls[0]["additional_context"]["lan-web-source"]["value"]
        assert codex.calls[1]["items"][1] == {"type": "localImage", "path": str(tmp_path / "uploads" / ("a" * 32 + ".png"))}
        assert codex.calls[1]["client_user_message_id"] == second_id
        snapshot = service.snapshot()
        assert snapshot["thread_id"] == "thread-lan"
        assert snapshot["pending"] == []
        assert len(snapshot["thread"]["turns"]) == 3
        live_users = [item for turn in snapshot["thread"]["turns"] for item in turn["items"] if item["type"] == "userMessage"]
        assert live_users[1]["images"][0]["id"] == "a" * 32
    finally:
        service.close()


def test_start_reads_real_thread_and_cancel_reports_state(tmp_path):
    service, codex = make_service(tmp_path)
    try:
        snapshot = service.snapshot()
        assert snapshot["connection"] == "connected"
        assert snapshot["thread"]["turns"][0]["items"][0]["text"] == "history"
        assert not service.cancel("192.168.1.4")
        assert service.snapshot()["last_notice"] == "当前没有活动任务。"
    finally:
        service.close()


def test_idle_session_can_be_released_and_explicitly_reconnected(tmp_path):
    service, codex = make_service(tmp_path)
    try:
        assert service.release_session("192.168.1.4")
        released = service.snapshot()
        assert released["connection"] == "released"
        assert released["status"] == "released"
        assert codex.closed == 1
        assert not service.release_session("192.168.1.4")
        with pytest.raises(ValueError, match="已释放"):
            service.submit("blocked", [], "192.168.1.4")
        with pytest.raises(ValueError, match="已释放"):
            service.resync("192.168.1.4")

        assert service.reconnect_session("192.168.1.4")
        reconnected = service.snapshot()
        assert reconnected["connection"] == "connected"
        assert reconnected["status"] == "idle"
        assert not service.reconnect_session("192.168.1.4")
    finally:
        service.close()


def test_session_release_rejects_active_or_queued_work(tmp_path):
    codex = FakeCodex()
    codex.thread_busy = True
    service, _ = make_service(tmp_path, codex)
    try:
        service.submit("queued", [], "192.168.1.4")
        wait_until(lambda: service.snapshot()["queue_size"] == 1)
        with pytest.raises(ValueError, match="任务与队列结束后"):
            service.release_session("192.168.1.4")
        assert service.snapshot()["connection"] == "connected"
    finally:
        codex.thread_busy = False
        service.close()


def test_failed_reconnect_keeps_session_released(tmp_path):
    service, codex = make_service(tmp_path)
    try:
        assert service.release_session("192.168.1.4")
        codex.read_failure = CodexClientError("active writer")

        with pytest.raises(ValueError, match="active writer"):
            service.reconnect_session("192.168.1.4")

        snapshot = service.snapshot()
        assert snapshot["connection"] == "released"
        assert "active writer" in snapshot["last_error"]
        assert codex.closed == 2
    finally:
        service.close()


def test_reasoning_and_streaming_answer_come_from_notifications(tmp_path):
    service, codex = make_service(tmp_path)
    try:
        service.submit("stream", [], "192.168.1.2")
        wait_until(lambda: service.snapshot()["status"] == "idle" and len(codex.calls) == 1)
        turn = service.snapshot()["thread"]["turns"][-1]
        reasoning = next(item for item in turn["items"] if item["type"] == "reasoning")
        answer = next(item for item in turn["items"] if item["type"] == "agentMessage")
        assert reasoning["summary"] == ["checking"]
        assert answer["text"] == "answer-1"
    finally:
        service.close()


def test_partial_projection_is_retained_on_failure(tmp_path):
    codex = FakeCodex()
    codex.failure = CodexClientError("failed")
    service, _ = make_service(tmp_path, codex)
    try:
        service.submit("stream", [], "192.168.1.2")
        wait_until(lambda: service.snapshot()["status"] == "idle" and len(codex.calls) == 1)
        snapshot = service.snapshot()
        assert snapshot["pending"] == []
        assert "failed" in snapshot["last_error"]
        assert any(item.get("text") == "partial" for item in snapshot["thread"]["turns"][-1]["items"])
    finally:
        service.close()


def test_web_queue_waits_while_external_turn_is_active(tmp_path):
    codex = FakeCodex()
    codex.thread_busy = True
    service, _ = make_service(tmp_path, codex)
    try:
        service.submit("wait", [], "192.168.1.2")
        time.sleep(0.05)
        assert codex.calls == []
        codex.thread_busy = False
        wait_until(lambda: len(codex.calls) == 1)
    finally:
        service.close()


def test_cancel_queued_message_removes_upload_without_interrupting_active_turn(tmp_path):
    codex = FakeCodex()
    codex.release.clear()
    service, _ = make_service(tmp_path, codex)
    image = tmp_path / "cancel.png"
    image.write_bytes(b"queued")
    try:
        service.submit("active", [], "192.168.1.2")
        wait_until(lambda: len(codex.calls) == 1)
        queued_id = service.submit(
            "queued",
            [{"id": "a" * 32, "name": "cancel.png", "mime": "image/png", "path": str(image)}],
            "192.168.1.3",
        )
        wait_until(lambda: service.snapshot()["queue_size"] == 1)

        assert service.cancel_queued(queued_id, "192.168.1.4")
        assert not service.cancel_queued(queued_id, "192.168.1.4")
        assert service.snapshot()["queue_size"] == 0
        assert all(item["id"] != queued_id for item in service.snapshot()["pending"])
        assert not image.exists()
        assert not codex.interrupted

        codex.release.set()
        wait_until(lambda: service.snapshot()["status"] == "idle")
        assert [call["items"][0]["text"] for call in codex.calls] == ["active"]
    finally:
        codex.release.set()
        service.close()


def test_clear_queued_keeps_active_turn_and_remaining_fifo_order(tmp_path):
    codex = FakeCodex()
    codex.release.clear()
    service, _ = make_service(tmp_path, codex)
    first_image = tmp_path / "first.png"
    second_image = tmp_path / "second.png"
    first_image.write_bytes(b"first")
    second_image.write_bytes(b"second")
    try:
        service.submit("active", [], "192.168.1.2")
        wait_until(lambda: len(codex.calls) == 1)
        service.submit("queued-1", [{"path": str(first_image)}], "192.168.1.3")
        service.submit("queued-2", [{"path": str(second_image)}], "192.168.1.3")
        wait_until(lambda: service.snapshot()["queue_size"] == 2)

        assert service.clear_queued("192.168.1.4") == 2
        assert service.clear_queued("192.168.1.4") == 0
        assert service.snapshot()["queue_size"] == 0
        assert service.snapshot()["pending"] == []
        assert not first_image.exists()
        assert not second_image.exists()
        assert not codex.interrupted

        codex.release.set()
        wait_until(lambda: service.snapshot()["status"] == "idle")
        assert [call["items"][0]["text"] for call in codex.calls] == ["active"]
    finally:
        codex.release.set()
        service.close()


def test_cancel_middle_queued_message_preserves_fifo(tmp_path):
    codex = FakeCodex()
    codex.release.clear()
    service, _ = make_service(tmp_path, codex)
    try:
        service.submit("active", [], "192.168.1.2")
        wait_until(lambda: len(codex.calls) == 1)
        service.submit("second", [], "192.168.1.2")
        middle_id = service.submit("cancel-me", [], "192.168.1.2")
        service.submit("fourth", [], "192.168.1.2")
        assert service.cancel_queued(middle_id, "192.168.1.2")

        codex.release.set()
        wait_until(lambda: len(codex.calls) == 3 and service.snapshot()["status"] == "idle")
        assert [call["items"][0]["text"] for call in codex.calls] == ["active", "second", "fourth"]
    finally:
        codex.release.set()
        service.close()


def test_cancel_queued_survives_image_cleanup_failure(tmp_path):
    codex = FakeCodex()
    codex.release.clear()
    service, _ = make_service(tmp_path, codex)
    undeletable = tmp_path / "queued-image-directory"
    undeletable.mkdir()
    try:
        service.submit("active", [], "192.168.1.2")
        wait_until(lambda: len(codex.calls) == 1)
        queued_id = service.submit("queued", [{"path": str(undeletable)}], "192.168.1.3")

        assert service.cancel_queued(queued_id, "192.168.1.3")
        assert service.snapshot()["queue_size"] == 0
        assert all(item["id"] != queued_id for item in service.snapshot()["pending"])
        assert undeletable.is_dir()

        codex.release.set()
        wait_until(lambda: service.snapshot()["status"] == "idle")
        assert [call["items"][0]["text"] for call in codex.calls] == ["active"]
    finally:
        codex.release.set()
        service.close()


def test_snapshot_refresh_does_not_interrupt_active_turn(tmp_path):
    codex = FakeCodex()
    codex.release.clear()
    service, _ = make_service(tmp_path, codex)
    try:
        service.submit("active", [], "192.168.1.2")
        wait_until(lambda: len(codex.calls) == 1)
        assert all(service.snapshot()["status"] == "processing" for _ in range(3))
        assert not codex.interrupted
    finally:
        codex.release.set()
        service.close()


def test_model_settings_are_shared_and_only_change_when_idle(tmp_path):
    service, codex = make_service(tmp_path)
    try:
        snapshot = service.snapshot()
        assert snapshot["model_settings"] == {
            "model": "gpt-5.6-sol", "reasoning_effort": "high", "service_tier": None,
        }
        assert snapshot["model_catalog"][1]["display_name"] == "GPT-5.6 Luna"

        result = service.update_model_settings("gpt-5.6-luna", "medium", "priority", "192.168.1.3")
        assert result == {
            "model": "gpt-5.6-luna", "reasoning_effort": "medium", "service_tier": "priority",
        }
        assert codex.settings_updates == [("gpt-5.6-luna", "medium", "priority")]
        assert service.snapshot()["model_settings"] == result
        with pytest.raises(ValueError, match="不支持该速度档位"):
            service.update_model_settings("gpt-5.6-sol", "high", "turbo", "192.168.1.3")
        codex._emit("thread/settings/updated", {
            "threadId": codex.thread_id,
            "threadSettings": {"model": "gpt-5.6-sol"},
        })
        assert service.snapshot()["model_settings"] == {
            "model": "gpt-5.6-sol", "reasoning_effort": "medium", "service_tier": "priority",
        }

        codex.release.clear()
        service.submit("active", [], "192.168.1.2")
        wait_until(lambda: len(codex.calls) == 1)
        with pytest.raises(ValueError, match="任务与队列完成后"):
            service.update_model_settings("gpt-5.6-sol", "high", "fast", "192.168.1.3")
    finally:
        codex.release.set()
        service.close()


def test_external_cli_events_are_projected(tmp_path):
    service, codex = make_service(tmp_path)
    try:
        codex._emit("turn/started", {"threadId": codex.thread_id, "turn": {"id": "external", "status": "inProgress", "items": []}})
        codex._emit("item/started", {
            "threadId": codex.thread_id,
            "turnId": "external",
            "item": {"id": "external-user", "type": "userMessage", "content": [{"type": "text", "text": "from CLI"}]},
        })
        assert service.snapshot()["thread"]["turns"][-1]["items"][0]["content"][0]["text"] == "from CLI"
    finally:
        service.close()
