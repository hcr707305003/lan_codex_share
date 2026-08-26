from io import StringIO

import pytest

from lan_codex_share.jsonrpc import JsonRpcConnection, JsonRpcError


def test_dispatch_response_and_error():
    connection = JsonRpcConnection(StringIO(), StringIO())
    from concurrent.futures import Future

    ok = Future()
    bad = Future()
    connection._pending[1] = ok
    connection._pending[2] = bad
    connection._dispatch({"id": 1, "result": {"ok": True}})
    connection._dispatch({"id": 2, "error": {"code": 7, "message": "bad"}})
    assert ok.result() == {"ok": True}
    with pytest.raises(JsonRpcError, match="bad"):
        bad.result()


def test_dispatch_notification():
    connection = JsonRpcConnection(StringIO(), StringIO())
    received = []
    connection.add_notification_handler(lambda method, params: received.append((method, params)))
    connection._dispatch({"method": "turn/completed", "params": {"x": 1}})
    assert received == [("turn/completed", {"x": 1})]
