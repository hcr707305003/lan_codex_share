from lan_codex_share.session_projection import SessionProjection


def test_replace_thread_normalizes_history_and_hides_raw_reasoning(tmp_path):
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    image = uploads / ("a" * 32 + ".png")
    projection = SessionProjection(uploads)
    projection.replace_thread(
        {
            "id": "thread-1",
            "name": "Shared",
            "path": "secret-rollout-path",
            "status": {"type": "idle"},
            "turns": [
                {
                    "id": "turn-1",
                    "status": "completed",
                    "items": [
                        {"id": "u1", "type": "userMessage", "content": [{"type": "localImage", "path": str(image)}]},
                        {"id": "r1", "type": "reasoning", "summary": ["Readable"], "content": ["hidden raw chain"]},
                    ],
                }
            ],
        }
    )

    thread = projection.snapshot()["thread"]
    assert "path" not in thread
    assert thread["turns"][0]["items"][0]["content"][0]["imageId"] == "a" * 32
    assert thread["turns"][0]["items"][1] == {"id": "r1", "type": "reasoning", "summary": ["Readable"]}


def test_live_deltas_merge_in_order_and_completed_item_is_authoritative():
    projection = SessionProjection(max_text_chars=100)
    projection.replace_thread({"id": "thread-1", "turns": [], "status": {"type": "idle"}})
    projection.apply_notification("turn/started", {"threadId": "thread-1", "turn": {"id": "turn-1", "status": "inProgress", "items": []}})
    projection.apply_notification("item/reasoning/summaryPartAdded", {"threadId": "thread-1", "turnId": "turn-1", "itemId": "r1", "summaryIndex": 0})
    projection.apply_notification("item/reasoning/summaryTextDelta", {"threadId": "thread-1", "turnId": "turn-1", "itemId": "r1", "summaryIndex": 0, "delta": "先检查"})
    projection.apply_notification("item/reasoning/textDelta", {"threadId": "thread-1", "turnId": "turn-1", "itemId": "r1", "delta": "hidden"})
    projection.apply_notification("item/commandExecution/outputDelta", {"threadId": "thread-1", "turnId": "turn-1", "itemId": "c1", "delta": "one"})
    projection.apply_notification("item/commandExecution/outputDelta", {"threadId": "thread-1", "turnId": "turn-1", "itemId": "c1", "delta": "two"})
    projection.apply_notification("item/agentMessage/delta", {"threadId": "thread-1", "turnId": "turn-1", "itemId": "a1", "delta": "partial"})
    projection.apply_notification("item/completed", {"threadId": "thread-1", "turnId": "turn-1", "item": {"id": "a1", "type": "agentMessage", "text": "final"}})

    items = projection.snapshot()["thread"]["turns"][0]["items"]
    assert next(item for item in items if item["id"] == "r1")["summary"] == ["先检查"]
    assert "hidden" not in str(items)
    assert next(item for item in items if item["id"] == "c1")["aggregatedOutput"] == "onetwo"
    assert next(item for item in items if item["id"] == "a1")["text"] == "final"


def test_pending_message_deduplicates_by_client_id():
    projection = SessionProjection()
    projection.replace_thread({"id": "thread-1", "turns": [], "status": {"type": "idle"}})
    projection.add_pending("hello", [{"id": "img1", "name": "x.png", "mime": "image/png"}], "192.168.1.2", "client-1")
    projection.apply_notification("item/started", {
        "threadId": "thread-1",
        "turnId": "turn-1",
        "item": {"id": "u1", "type": "userMessage", "clientId": "client-1", "content": [{"type": "text", "text": "hello"}]},
    })

    snapshot = projection.snapshot()
    assert snapshot["pending"] == []
    item = snapshot["thread"]["turns"][0]["items"][0]
    assert item["sourceIp"] == "192.168.1.2"
    assert item["images"][0]["id"] == "img1"


def test_remove_pending_messages_in_one_update():
    projection = SessionProjection()
    projection.add_pending("one", [], "192.168.1.2", "client-1")
    projection.add_pending("two", [], "192.168.1.2", "client-2")
    projection.add_pending("three", [], "192.168.1.2", "client-3")
    before = projection.snapshot()["version"]

    assert projection.remove_pending({"client-1", "client-3"}) == 2

    snapshot = projection.snapshot()
    assert snapshot["version"] == before + 1
    assert [item["id"] for item in snapshot["pending"]] == ["client-2"]


def test_turn_completed_merges_partial_items_without_dropping_user_message():
    projection = SessionProjection()
    projection.replace_thread({"id": "thread-1", "turns": [], "status": {"type": "idle"}})
    projection.add_pending("question", [], "192.168.1.2", "client-1")
    projection.apply_notification("turn/started", {
        "threadId": "thread-1",
        "turn": {"id": "turn-1", "status": "inProgress", "items": []},
    })
    projection.apply_notification("item/started", {
        "threadId": "thread-1",
        "turnId": "turn-1",
        "item": {
            "id": "user-1",
            "type": "userMessage",
            "clientId": "client-1",
            "content": [{"type": "text", "text": "question"}],
        },
    })
    projection.apply_notification("turn/completed", {
        "threadId": "thread-1",
        "turn": {
            "id": "turn-1",
            "status": "completed",
            "items": [{"id": "answer-1", "type": "agentMessage", "text": "answer"}],
        },
    })

    snapshot = projection.snapshot()
    assert snapshot["pending"] == []
    assert [(item["type"], item.get("text") or item.get("content", [{}])[0].get("text"))
            for item in snapshot["thread"]["turns"][0]["items"]] == [
        ("userMessage", "question"),
        ("agentMessage", "answer"),
    ]


def test_unknown_items_and_large_output_degrade_safely():
    projection = SessionProjection(max_text_chars=10)
    projection.replace_thread({"id": "thread-1", "turns": [{"id": "turn-1", "status": "completed", "items": [{"id": "x", "type": "futureTool", "payload": "x" * 20}]}]})
    item = projection.snapshot()["thread"]["turns"][0]["items"][0]
    assert item["type"] == "futureTool"
    assert item["payload"].endswith("[输出已截断]")


def test_notifications_for_other_threads_are_ignored():
    projection = SessionProjection()
    projection.replace_thread({"id": "thread-1", "turns": []})
    assert not projection.apply_notification("turn/started", {"threadId": "thread-2", "turn": {"id": "turn-x"}})
    assert projection.snapshot()["thread"]["turns"] == []
