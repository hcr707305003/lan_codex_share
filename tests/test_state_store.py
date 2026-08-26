import json

from lan_codex_share.state_store import StateStore


def test_thread_id_persists(tmp_path):
    path = tmp_path / "state.json"
    state = StateStore(path)
    state.set_thread_id("thread-1")

    assert StateStore(path).thread_id == "thread-1"


def test_legacy_extra_fields_are_ignored(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(
        json.dumps({"thread_id": "thread-1", "pending_replies": ["old"], "recent_messages": {"x": 1}}),
        encoding="utf-8",
    )

    state = StateStore(path)
    state.set_thread_id("thread-2")

    assert json.loads(path.read_text(encoding="utf-8")) == {"thread_id": "thread-2"}


def test_corrupt_state_is_preserved_as_backup(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{bad", encoding="utf-8")
    state = StateStore(path)
    assert state.thread_id is None
    assert list(tmp_path.glob("state.corrupt-*.json"))
