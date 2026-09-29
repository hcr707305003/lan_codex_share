import json
import queue
import threading
import time
import socket as sockets
import websocket

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

    def abort(self):
        self.incoming.put("")

    def shutdown(self):
        self.closed = True


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


def test_close_unblocks_idle_reader_without_peer_close_handshake():
    client, peer = sockets.socketpair()
    socket = websocket.WebSocket(enable_multithread=True)
    socket.sock = client
    socket.connected = True
    connection = WebSocketJsonRpcConnection('ws://test', websocket_socket=socket)
    reading = threading.Event()
    original_recv = socket.frame_buffer.recv

    def recv(size):
        reading.set()
        return original_recv(size)

    socket.frame_buffer.recv = recv
    connection.start()
    assert reading.wait(1)
    closer = threading.Thread(target=connection.close, daemon=True)
    try:
        closer.start()
        closer.join(1)
        assert not closer.is_alive(), 'close blocked behind the idle WebSocket reader'
        connection._reader_thread.join(1)
        assert not connection._reader_thread.is_alive()
        assert socket.sock is None
    finally:
        peer.close()  # Unblock the regression on the old implementation too.
        closer.join(4)
        connection._reader_thread.join(4)


def test_remove_shared_idle_socket_completes_and_snapshot_stays_available(tmp_path):
    from tests.test_shared_config import setup
    from tests.test_lan_service import FakeCodex
    from lan_codex_share.lan_service import LanChatService
    from lan_codex_share.session_projection import SessionProjection

    path, store, tasks, hub, metadata_client = setup(tmp_path)
    sid = metadata_client.threads[0]['id']
    client, peer = sockets.socketpair()
    socket = websocket.WebSocket(enable_multithread=True)
    socket.sock = client
    socket.connected = True
    rpc = WebSocketJsonRpcConnection('ws://test', websocket_socket=socket)
    reading = threading.Event()
    original_recv = socket.frame_buffer.recv

    def recv(size):
        reading.set()
        return original_recv(size)

    socket.frame_buffer.recv = recv
    codex = FakeCodex()
    codex.thread_id = sid
    codex.close = rpc.close
    service = LanChatService(codex, SessionProjection(tmp_path / 'uploads'))
    hub._added_factory = lambda entry: service
    tasks.add(sid)
    hub.snapshot(sid)
    rpc.start()
    assert reading.wait(1)
    errors = []

    def remove():
        try:
            tasks.remove(sid, 'test')
        except Exception as exc:
            errors.append(exc)

    worker = threading.Thread(target=remove, daemon=True)
    try:
        worker.start()
        worker.join(2)
        assert not worker.is_alive(), 'removal held the shared-session lock'
        assert not errors
        assert store.read() == ('selected', [])
        assert hub.snapshot(sid)['sessions'] == []
        assert not hub.thread_ids
    finally:
        peer.close()
        worker.join(4)
        rpc.close()
        hub.close()
