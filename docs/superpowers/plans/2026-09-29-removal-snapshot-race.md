# Removal / snapshot race

The reported SSE failure occurs after a successful removal: snapshot validates membership before obtaining the service operation lock. Removal can finish between that check and service lookup, so lookup rejects the stale ID instead of falling back.

Fix: hold the same reentrant operation lock across membership fallback, service lookup, snapshot and shared-list assembly. Do not swallow ValueError or weaken validation of write requests.

Regression: hold the operation lock, start a snapshot waiter, remove its session, then release the lock. The original implementation fails with the reported ValueError. Verify both remaining-session and last-session removal cases; the corrected implementation returns the remaining session or an empty snapshot.

- Focused shared-config / session-hub / WebSocket suite: 28 passed.
- Full regression: 824 passed in 77.93 seconds.
- Temporary configuration and fake sessions only; no running user service changes.
