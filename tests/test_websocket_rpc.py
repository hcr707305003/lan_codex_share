import json
import queue
import threading
import time

from lan_codex_share.websocket_rpc import WebSocketJsonRpcConnection


class FakeWebSocket:
    def __init__(self):
        self.incoming = queue.Queue()
        self.sent = []
        self.closed = False

    def send(self, value):
        self.sent.append(value)

    def recv(self):
        value = self.incoming.get(timeout=2)
        if isinstance(value, Exception):
            raise value
        return value

    def close(self):
        self.closed = True
        self.incoming.put("")


def wait_until(predicate, timeout=1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


def test_websocket_rpc_request_and_notification():
    socket = FakeWebSocket()
    connection = WebSocketJsonRpcConnection("ws://127.0.0.1:4500", websocket_socket=socket)
    notifications = []
    connection.add_notification_handler(lambda method, params: notifications.append((method, params)))
    connection.start()
    result = {}

    requester = threading.Thread(target=lambda: result.setdefault("value", connection.request("ping", {"x": 1}, timeout=1)))
    requester.start()
    wait_until(lambda: len(socket.sent) == 1)
    request = json.loads(socket.sent[0])
    socket.incoming.put(json.dumps({"id": request["id"], "result": {"ok": True}}))
    requester.join(1)

    assert result["value"] == {"ok": True}
    socket.incoming.put(json.dumps({"method": "turn/started", "params": {"turn": {"id": "t1"}}}))
    wait_until(lambda: notifications)
    assert notifications == [("turn/started", {"turn": {"id": "t1"}})]
    connection.close()
    assert socket.closed


def test_websocket_writer_removes_jsonl_newline():
    socket = FakeWebSocket()
    connection = WebSocketJsonRpcConnection("ws://127.0.0.1:4500", websocket_socket=socket)
    connection.notify("initialized", {})
    assert socket.sent == ['{"method":"initialized","params":{}}']
    connection.close()
