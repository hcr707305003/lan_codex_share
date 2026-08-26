from pathlib import Path
import json
import sys

import pytest

from lan_codex_share.codex_client import CodexClient, CodexClientError
from lan_codex_share.jsonrpc import JsonRpcError
from lan_codex_share.state_store import StateStore


def fake_command():
    script = Path(__file__).parent / "fixtures" / "fake_app_server.py"
    return (sys.executable, str(script))


def test_full_turn_and_resume(tmp_path):
    state = StateStore(tmp_path / "state.json")
    client = CodexClient(tmp_path, state, turn_timeout_seconds=2, command=fake_command())
    try:
        assert client.run_turn("hello") == "fake answer"
        assert state.thread_id == "thread-fake"
        assert client.run_turn("again") == "fake answer"
    finally:
        client.close()


def test_archive_and_new_thread(tmp_path):
    state = StateStore(tmp_path / "state.json")
    state.set_thread_id("old-thread")
    client = CodexClient(tmp_path, state, turn_timeout_seconds=2, command=fake_command())
    try:
        assert client.archive_thread()
        assert state.thread_id is None
        assert client.new_thread() == "thread-fake"
    finally:
        client.close()


def test_permissions_are_explicit(tmp_path):
    client = CodexClient(tmp_path, StateStore(tmp_path / "state.json"), command=fake_command())
    assert client._thread_params() == {
        "cwd": str(tmp_path.resolve()),
        "approvalPolicy": "never",
        "sandbox": "danger-full-access",
    }


def test_sandbox_mode_is_configurable(tmp_path):
    client = CodexClient(
        tmp_path,
        StateStore(tmp_path / "state.json"),
        command=fake_command(),
        sandbox_mode="read-only",
    )

    assert client._thread_params() == {
        "cwd": str(tmp_path.resolve()),
        "approvalPolicy": "never",
        "sandbox": "read-only",
    }


def test_structured_input_and_custom_thread_name(tmp_path):
    state = StateStore(tmp_path / "state.json")
    client = CodexClient(
        tmp_path,
        state,
        turn_timeout_seconds=2,
        command=fake_command(),
        thread_name="局域网共享 Codex 会话",
    )
    items = [
        {"type": "text", "text": "__echo_input__"},
        {"type": "localImage", "path": str(tmp_path / "image.png")},
    ]
    try:
        assert json.loads(client.run_turn_items(items)) == items
        assert client.run_turn("__thread_name__") == "局域网共享 Codex 会话"
    finally:
        client.close()


def test_streaming_delta_callback_is_isolated(tmp_path):
    client = CodexClient(tmp_path, StateStore(tmp_path / "state.json"), turn_timeout_seconds=2, command=fake_command())
    deltas = []
    try:
        assert client.run_turn_items([{"type": "text", "text": "__stream__"}], on_delta=deltas.append) == "fake answer"
        assert deltas == ["fake ", "answer"]

        def broken_callback(_delta):
            raise RuntimeError("UI callback failed")

        assert client.run_turn_items([{"type": "text", "text": "__stream__"}], on_delta=broken_callback) == "fake answer"
    finally:
        client.close()


def test_external_turn_updates_busy_state_without_completing_own_turn(tmp_path):
    client = CodexClient(tmp_path, StateStore(tmp_path / "state.json"), command=fake_command())
    states = []
    client.add_thread_state_handler(states.append)

    client._on_notification("turn/started", {"turn": {"id": "external-turn"}})
    assert client.thread_busy
    assert states == [True]
    assert not client._turn_done.is_set()

    client._on_notification("turn/completed", {"turn": {"id": "external-turn", "status": "completed"}})
    assert not client.thread_busy
    assert states == [True, False]
    assert not client._turn_done.is_set()


def test_read_thread_and_public_notification_subscription(tmp_path):
    client = CodexClient(tmp_path, StateStore(tmp_path / "state.json"), turn_timeout_seconds=2, command=fake_command())
    events = []
    client.add_notification_handler(lambda method, params: events.append((method, params)))
    try:
        thread = client.read_thread()
        assert thread["turns"][0]["items"][0]["text"] == "history"
        assert client.run_turn("__stream__") == "fake answer"
        assert any(method == "item/reasoning/summaryTextDelta" for method, _ in events)
    finally:
        client.close()


def test_list_threads_over_app_server_transport(tmp_path):
    client = CodexClient(tmp_path, StateStore(tmp_path / "catalog.json"), command=fake_command())
    try:
        threads = client.list_threads()
        assert [thread["id"] for thread in threads] == ["thread-fake"]
        assert threads[0]["projectId"] == "project-fake"
    finally:
        client.close()


def test_turn_client_id_and_additional_context(tmp_path):
    client = CodexClient(tmp_path, StateStore(tmp_path / "state.json"), turn_timeout_seconds=2, command=fake_command())
    try:
        result = client.run_turn_items(
            [{"type": "text", "text": "__turn_params__"}],
            client_user_message_id="client-1",
            additional_context={"lan": {"kind": "application", "value": "source=127.0.0.1"}},
        )
        assert json.loads(result) == {
            "clientUserMessageId": "client-1",
            "additionalContext": {"lan": {"kind": "application", "value": "source=127.0.0.1"}},
        }
    finally:
        client.close()


def test_model_catalog_and_thread_settings_update(tmp_path):
    client = CodexClient(tmp_path, StateStore(tmp_path / "state.json"), command=fake_command())
    try:
        client.read_thread()
        assert client.model_settings == {
            "model": "gpt-5.6-sol", "reasoning_effort": "high", "service_tier": None,
        }
        models = client.list_models()
        assert models[0] == {
            "id": "gpt-5.6-sol",
            "model": "gpt-5.6-sol",
            "display_name": "GPT-5.6 Sol",
            "description": "Frontier coding model",
            "is_default": True,
            "default_reasoning_effort": "high",
            "default_service_tier": None,
            "service_tiers": [{"id": "fast", "name": "Fast", "description": "Lower latency"}],
            "supported_reasoning_efforts": [
                {"value": "medium", "description": "Balanced"},
                {"value": "high", "description": "Deeper"},
            ],
        }
        assert client.update_thread_settings("gpt-5.6-luna", "medium", "priority") == {
            "model": "gpt-5.6-luna",
            "reasoning_effort": "medium",
            "service_tier": "priority",
        }
        assert client.model_settings == {
            "model": "gpt-5.6-luna", "reasoning_effort": "medium", "service_tier": "priority",
        }
    finally:
        client.close()

def test_strict_resume_never_replaces_fixed_session(tmp_path):
    class FailingRpc:
        def request(self, method, _params, timeout=30):
            assert method == "thread/resume"
            raise JsonRpcError(-32600, "thread fixed-session already has an active writer")

    state = StateStore(tmp_path / "state.json")
    state.set_thread_id("fixed-session")
    client = CodexClient(tmp_path, state, strict_resume=True)
    client.start = lambda: None
    client.rpc = FailingRpc()

    with pytest.raises(CodexClientError, match="正被旧 Codex/VS Code 写入端占用"):
        client.ensure_thread()
    assert state.thread_id == "fixed-session"


def test_list_threads_reads_all_pages_filters_and_deduplicates(tmp_path):
    class PagedRpc:
        def __init__(self):
            self.calls = []

        def request(self, method, params, timeout=30):
            self.calls.append((method, params, timeout))
            assert method == "thread/list"
            if "cursor" not in params:
                return {
                    "data": [
                        {"id": "main-a", "cwd": str(tmp_path / "a"), "recencyAt": 20, "ephemeral": False},
                        {"id": "child", "cwd": str(tmp_path / "a"), "parentThreadId": "main-a", "ephemeral": False},
                        {"id": "temporary", "cwd": str(tmp_path), "recencyAt": 99, "ephemeral": True},
                    ],
                    "nextCursor": "page-2",
                }
            assert params["cursor"] == "page-2"
            return {
                "data": [
                    {"id": "main-b", "cwd": str(tmp_path / "b"), "updatedAt": 30, "ephemeral": False},
                    {"id": "main-a", "cwd": str(tmp_path / "old"), "recencyAt": 1, "ephemeral": False},
                ],
                "nextCursor": None,
            }

    rpc = PagedRpc()
    client = CodexClient(tmp_path, StateStore(tmp_path / "catalog.json"))
    client.start = lambda: None
    client.rpc = rpc

    threads = client.list_threads()

    assert [thread["id"] for thread in threads] == ["main-b", "main-a"]
    assert threads[1]["cwd"] == str(tmp_path / "a")
    assert rpc.calls[0][1] == {
        "archived": False,
        "limit": 100,
        "sortDirection": "desc",
        "sortKey": "recency_at",
    }


@pytest.mark.parametrize(
    "result",
    [None, [], {"data": None}, {"data": [{"cwd": "missing-id"}]}, {"data": [], "nextCursor": 42}],
)
def test_list_threads_rejects_invalid_responses(tmp_path, result):
    class InvalidRpc:
        def request(self, method, params, timeout=30):
            return result

    client = CodexClient(tmp_path, StateStore(tmp_path / "catalog.json"))
    client.start = lambda: None
    client.rpc = InvalidRpc()

    with pytest.raises(CodexClientError, match="thread/list"):
        client.list_threads()
