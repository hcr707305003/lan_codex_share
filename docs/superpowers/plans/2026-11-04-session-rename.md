# Session Rename Implementation Plan

> Use executing-plans inline on the user-approved current branch.

**Goal:** Rename the current shared session in Codex and synchronize its displayed name.
**Architecture:** Add a validated client RPC, route through the hub, and update metadata only after success. A metadata-operation lock serializes catalog refresh and rename without holding the hub global lock during network I/O. Reuse the existing dialog styles and authenticated mutation helper.
**Tech Stack:** Python, vanilla JavaScript, native dialog, pytest and Node tests.
**Spec:** ../specs/2026-11-04-session-rename-design.md

## Constraints

No service restarts, real-session mutations during tests, automatic commits or releases. Keep IDs, history and queues unchanged.

## Tasks

Completed 2026-11-04: all implementation tasks below are complete. Validation: 901 Python tests and 74 JavaScript tests passed; git diff --check passed. Tests use fake Codex RPC/services and exercise target capture, retry, CSRF/membership validation, history preservation and stale catalog ordering. No real Codex session was renamed during verification; no services were restarted. Browser visual verification was not performed. Changes remain uncommitted.

- [ ] Add client `rename_thread(thread_id, name)` using `thread/name/set`; normalize and validate name (1–100 Unicode characters, no control/format characters or line separators). Test valid payload and unsupported RPC errors.
- [ ] Add `LanChatService.rename_session(name)` and projection metadata setter without replacing history. Add hub `rename_session(session_id, name)` under metadata lock shared with `refresh_catalog()`; validate membership, publish authoritative name only on success. Test failures and stale refresh ordering.
- [ ] Add POST `/api/session/rename` after existing authentication, CSRF and session resolution. Return `{name}` on success and sanitized gateway errors on RPC failure. Test validation and unauthorized requests.
- [ ] Add menu button and dialog in index.html, reusing task-dialog styling. Capture target ID at open, prevent duplicate submit, preserve input on failure, disable closing while saving, and refresh only after successful mutation. Test JavaScript behavior with fake DOM and mutation callbacks.
- [ ] Run targeted then complete Python and JavaScript suites, inspect diff; leave uncommitted and report manual restart requirement.
