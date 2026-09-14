import json

import pytest

from lan_codex_share.session_projection import SessionProjection


def history(count=2000):
    return {"id": "history-session", "turns": [
        {"id": f"t-{i}", "status": "completed", "items": [
            {"id": f"u-{i}", "type": "userMessage", "content": [{"type": "text", "text": f"question {i}"}]},
            {"id": f"c-{i}", "type": "commandExecution", "aggregatedOutput": "tool-output" * 1000},
            {"id": f"a-{i}", "type": "agentMessage", "text": f"answer {i}"},
        ]} for i in range(count)
    ]}


def test_first_page_is_small_and_older_pages_keep_complete_pairs():
    projection = SessionProjection()
    projection.replace_thread(history())
    page = projection.history_page()
    assert len(page["thread"]["turns"]) == 20
    assert page["history"]["total"] == 2000
    assert "tool-output" not in json.dumps(page)
    assert len(json.dumps(page)) < 20000
    assert page["thread"]["turns"][0]["id"] == "t-1980"
    assert all(len(turn["items"]) == 2 and turn["activity_count"] == 1 for turn in page["thread"]["turns"])
    seen = [turn["id"] for turn in page["thread"]["turns"]]
    while page["history"]["before"]:
        page = projection.history_page(before=page["history"]["before"])
        seen = [turn["id"] for turn in page["thread"]["turns"]] + seen
    assert seen == [f"t-{i}" for i in range(2000)]
    assert len(projection.snapshot()["thread"]["turns"]) == 2000


def test_cursor_is_stable_on_append_and_invalid_after_resync():
    projection = SessionProjection()
    original = history(25)
    projection.replace_thread(original)
    first = projection.history_page()
    projection.apply_notification("turn/started", {"turn": {"id": "new", "status": "inProgress"}})
    older = projection.history_page(before=first["history"]["before"])
    assert [turn["id"] for turn in older["thread"]["turns"]] == [f"t-{i}" for i in range(5)]
    before_revision = projection.history_page()["thread"]["turns"][0]["history_revision"]
    projection.apply_notification("item/agentMessage/delta", {"turnId": "new", "itemId": "reply", "delta": "hello"})
    assert projection.history_page()["thread"]["turns"][0]["history_revision"] == before_revision
    projection.replace_thread(original)
    with pytest.raises(ValueError, match="历史已重新同步"):
        projection.history_page(before=first["history"]["before"])


def test_activity_pages_include_diff_without_raw_reasoning():
    projection = SessionProjection()
    projection.replace_thread({"id": "history-session", "turns": [{"id": "turn", "diff": "the diff", "items": [
        {"id": str(i), "type": "reasoning", "summary": [str(i)], "content": ["private raw"]} for i in range(45)
    ]}]})
    epoch = projection.history_page()["history"]["epoch"]
    page = projection.activities("turn", epoch)
    assert len(page["items"]) == 20
    assert page["items"][-1]["type"] == "turnDiff"
    assert "private raw" not in json.dumps(page)
    assert page["history"]["total"] == 46
    earlier = projection.activities("turn", epoch, before=page["history"]["before"])
    assert earlier["items"][-1]["id"] == "25"
    with pytest.raises(ValueError):
        projection.activities("missing", epoch)
    with pytest.raises(ValueError):
        projection.activities("turn", "old")


@pytest.mark.parametrize("limit", [0, -1, 51, "bad", True])
def test_invalid_limit_rejected(limit):
    with pytest.raises(ValueError):
        SessionProjection().history_page(limit=limit)


def test_empty_history_and_invalid_cursors():
    projection = SessionProjection()
    assert projection.history_page()["history"]["before"] is None
    for cursor in ["bad", "", "a:-1", "a:10000"]:
        with pytest.raises(ValueError):
            projection.history_page(before=cursor)


@pytest.fixture
def history_server(tmp_path):
    import threading
    from lan_codex_share.lan_service import LanChatService
    from lan_codex_share.lan_store import ImageStore
    from lan_codex_share.lan_web import LanWebApplication
    from lan_codex_share.session_hub import LanSessionHub
    from tests.test_lan_service import FakeCodex

    class HistoryCodex(FakeCodex):
        def read_thread(self, include_turns=True):
            return history(100)

    service = LanChatService(HistoryCodex(), SessionProjection())
    hub = LanSessionHub([service])
    hub.start()
    app = LanWebApplication(hub, ImageStore(tmp_path / 'images', max_bytes=1024 * 1024, max_images=4), {'127.0.0.1'},
                            max_request_bytes=1024 * 1024, password='test-password')
    server = app.create_server('127.0.0.1', 0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        yield app, hub, server
    finally:
        server.shutdown()
        server.server_close()
        hub.close()
        worker.join(2)


def test_http_pagination_uses_existing_auth_and_session_boundary(history_server):
    from tests.test_lan_web import request

    app, hub, server = history_server
    headers = {'Cookie': f'lan_codex_auth={app.auth_token}'}
    assert request(server, 'GET', '/api/snapshot')[0] == 401
    assert request(server, 'GET', '/api/history/activities?turn_id=t-99')[0] == 401
    assert request(server, 'GET', '/history.js')[0] == 200
    status, _, body = request(server, 'GET', '/api/snapshot', headers=headers)
    assert status == 200
    page = json.loads(body)
    assert len(page['thread']['turns']) == 20
    epoch = page['history']['epoch']
    query = f'/api/history/activities?session_id=history-session&turn_id=t-99&epoch={epoch}'
    status, _, body = request(server, 'GET', query, headers=headers)
    assert status == 200
    assert 'tool-output' in json.loads(body)['items'][0]['aggregatedOutput']
    assert request(server, 'GET', query.replace('history-session', 'not-shared'), headers=headers)[0] == 400
    for suffix in ['limit=0', 'limit=51', 'limit=bad', 'before=bad']:
        assert request(server, 'GET', f'/api/snapshot?{suffix}', headers=headers)[0] == 400


def test_page_does_not_copy_unselected_turns():
    class CannotCopy:
        def __deepcopy__(self, memo):
            raise AssertionError('unselected history was copied')
    projection = SessionProjection()
    projection.replace_thread(history(21))
    # An object in an unselected old turn must not be visited by deepcopy.
    projection._thread['turns'][0]['error'] = CannotCopy()
    assert len(projection.history_page()['thread']['turns']) == 20
