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


def test_astra_fallback_is_selectable_through_shared_session(tmp_path):
    from lan_codex_share.lan_service import LanChatService
    from lan_codex_share.session_projection import SessionProjection

    client = CodexClient(tmp_path, StateStore(tmp_path / "state.json"), command=fake_command())
    service = LanChatService(client, SessionProjection(tmp_path / "uploads"))
    try:
        service.start()
        astra = next(item for item in service.snapshot()["model_catalog"] if item["model"] == "gpt-6-astra")
        assert astra["display_name"] == "GPT-6 Astra"
        assert astra["is_default"] is False
        assert astra["default_reasoning_effort"] == "low"
        assert [item["value"] for item in astra["supported_reasoning_efforts"]] == [
            "low", "medium", "high", "xhigh", "max", "ultra",
        ]
        for tier in (None, "priority"):
            settings = service.update_model_settings("gpt-6-astra", "high", tier, "127.0.0.1")
            assert settings == {
                "model": "gpt-6-astra", "reasoning_effort": "high", "service_tier": tier,
            }
            # Re-read the fake server's state, not only the client's local cache.
            resumed = client.rpc.request("thread/resume", {"threadId": service.thread_id})
            assert resumed["model"] == "gpt-6-astra"
            assert resumed["reasoningEffort"] == "high"
            assert resumed["serviceTier"] == tier
            assert service.snapshot()["model_settings"] == settings
        with pytest.raises(ValueError, match="不支持该速度档位"):
            service.update_model_settings("gpt-6-astra", "high", "ultrafast", "127.0.0.1")
    finally:
        service.close()


def test_server_astra_on_later_page_overrides_fallback(tmp_path):
    class PagedRpc:
        def request(self, method, params, timeout=30):
            assert method == "model/list"
            if "cursor" not in params:
                return {"data": [{"model": "gpt-5.6-sol"}], "nextCursor": "page-2"}
            assert params["cursor"] == "page-2"
            return {"data": [{
                "id": "astra-server-id", "model": "gpt-6-astra", "displayName": "Server Astra",
                "isDefault": True, "defaultReasoningEffort": "medium",
                "supportedReasoningEfforts": [{"reasoningEffort": "medium", "description": "Server effort"}],
                "defaultServiceTier": "priority", "serviceTiers": [],
            }]}

    client = CodexClient(tmp_path, StateStore(tmp_path / "state.json"), command=fake_command())
    client.start = lambda: None
    client.rpc = PagedRpc()
    models = client.list_models()
    astra = [item for item in models if item["model"] == "gpt-6-astra"]
    assert len(models) == 2
    assert len(astra) == 1
    assert astra[0] == {
        "id": "astra-server-id", "model": "gpt-6-astra", "display_name": "Server Astra",
        "description": "", "is_default": True, "default_reasoning_effort": "medium",
        "supported_reasoning_efforts": [{"value": "medium", "description": "Server effort"}],
        "default_service_tier": "priority", "service_tiers": [],
    }


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
