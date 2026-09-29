# Session release blocking regression

## Scope

Release/removal must finish without depending on the App Server acknowledging a WebSocket close handshake. Keep the existing busy-task checks, config persistence, history retention and CSP unchanged.

## Verified cause

`WebSocketJsonRpcConnection.close()` called the websocket-client graceful `close()` while a JSON-RPC reader was blocked in receive with no timeout. Graceful close also reads frames; it can wait for the frame-buffer lock held by that reader. Its handshake timeout does not bound waiting for that lock. Shared removal holds the service creation/operation lock while closing, so snapshots waiting for that lock also stall.

A real local socket pair with a silent peer reproduces the failure: the previous implementation does not finish close within one second. Test cleanup closes the peer so the old implementation leaves no hanging non-daemon process.

## Fix and checks

- [x] Wake the receiver using websocket-client `abort()`, then `shutdown()` to close the transport without a close handshake.
- [x] Retain JSON-RPC pending-request failure and idempotent socket-close locking.
- [x] Add a real-socket regression for the idle receiver.
- [x] Exercise removal through SessionTasks, a real LanChatService and the real WebSocket adapter; assert config membership and the snapshot become empty.
- [x] Full Python regression suite: 822 passed in 79.14 seconds.

Only temporary config, fake Codex data and local socket pairs are used. No user service or actual session is stopped or modified.
