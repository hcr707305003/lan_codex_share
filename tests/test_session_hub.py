import queue

import pytest

from lan_codex_share.session_hub import LanSessionHub


class FakeSessionService:
    def __init__(self, thread_id, name):
        self.thread_id = thread_id
        self.name = name
        self.handlers = []
        self.calls = []
        self.closed = False

    def add_change_handler(self, handler):
        self.handlers.append(handler)

    def start(self):
        return None

    def summary(self):
        return {
            "thread_id": self.thread_id, "name": self.name, "status": "idle",
            "connection": "connected", "queue_size": 0,
        }

    def snapshot(self):
        return {
            "thread_id": self.thread_id, "status": "idle", "connection": "connected",
            "queue_size": 0, "version": 1, "thread": {"id": self.thread_id, "turns": []},
            "pending": [],
        }

    def submit(self, text, images, source_ip):
        self.calls.append((text, images, source_ip))
        return f"message-{self.thread_id}"

    def close(self):
        self.closed = True


def test_hub_selects_and_routes_independent_sessions():
    first = FakeSessionService("session-a", "Alpha")
    second = FakeSessionService("session-b", "Beta")
    hub = LanSessionHub([first, second])
    hub.start()
    try:
        snapshot = hub.snapshot("session-b")

        assert snapshot["selected_session_id"] == "session-b"
        assert [item["thread_id"] for item in snapshot["sessions"]] == ["session-a", "session-b"]
        assert hub.submit("session-b", "hello", [], "192.168.1.2") == "message-session-b"
        assert first.calls == []
        assert second.calls == [("hello", [], "192.168.1.2")]
        with pytest.raises(ValueError, match="共享列表"):
            hub.snapshot("not-shared")
    finally:
        hub.close()
    assert first.closed and second.closed


def test_hub_fans_out_session_updates():
    service = FakeSessionService("session-a", "Alpha")
    hub = LanSessionHub([service])
    hub.start()
    subscriber = hub.subscribe()
    try:
        for handler in service.handlers:
            handler()
        assert isinstance(subscriber.get(timeout=0.2), int)
    except queue.Empty as exc:
        raise AssertionError("hub did not broadcast the session update") from exc
    finally:
        hub.unsubscribe(subscriber)
        hub.close()
