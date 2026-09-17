# Public Origin Sync Implementation Plan

> Execute inline with executing-plans on current main, per user preference. Preserve dirty work; no commit/build/release or real service/config mutations.

**Goal:** Saving the selected tunnel config synchronizes an unambiguous Share entry; conflicts require confirmation.

**Architecture:** Qt-free proposal module derives only Share-targeted candidates and retains a ConfigDocument snapshot for conflict-safe LAN writes. ConfigPage saves the tunnel first, then coordinates an optional dark selection dialog and emits a dedicated LAN-change signal. Partial success is explicit.

**Tech Stack:** Existing Python/tomlkit/ConfigDocument/PySide6/pytest.

**Spec:** docs/superpowers/specs/2026-09-16-public-origin-sync-design.md

## Constraints

No token reads/network calls/service operations. Retain HTTP password enforcement and existing IPv4-only public HTTP origin policy (IPv6 loopback upstream is allowed; public IPv6 is not). Preserve legacy entry/comments/unrelated settings and reject concurrent file changes. No sync on Save Copy.

## Task 1 — candidates and write safety

Files: create `desktop/origin_sync.py`, `tests/test_origin_sync.py`.

Interface: `prepare_sync(lan_path, kind, data, mode='yaml') -> SyncProposal`; proposal exposes `field`, `current`, `candidates` (origin strings), `reason`, `needs_choice`, and `apply(origin) -> bool` (whether LAN changed).

- [x] Add tests for exact loopback/Share-port mapping; invalid, wildcard, path-specific and token-mode exclusions; deduplication; legacy migration, unchanged writes, cancellation boundary, missing password, file conflict and permissions.
- [x] Run focused pytest to establish failing missing-module tests.
- [x] Implement candidate extraction using urlsplit/ipaddress and normalize_public_origin; cap candidate count and use only validated origins in UI. Snapshot and fully validate LAN before proposals; call ConfigDocument.save for atomic replacement, with legacy migration performed on parsed TOML.
- [x] Verify tests: `proposal = prepare_sync(lan, 'frp', data); assert proposal.candidates == ('http://203.0.113.10:20000',); assert proposal.apply(proposal.candidates[0])`. Repeat apply preparation must not rewrite unchanged entries. All files are temporary.

## Task 2 — save coordinator and dialog

Files: create `desktop/origin_dialog.py`, `tests/test_origin_sync_ui.py`; modify `desktop/config_page.py`, `desktop/window.py`, `DESKTOP.md`.

- [x] Write GUI tests for auto-sync, user accept/cancel conflict, partial failure message, Save Copy exclusion, changed-signal refresh, and default cancellation.
- [x] Add `choose_origin(parent, proposal) -> str | None` dark QDialog with old entry, candidate selection, apply/cancel buttons; Cancel is default and no option is silently confirmed.
- [x] After tunnel save only, prepare proposal from saved snapshot. Empty/identical single candidate auto-applies; conflict/multiple opens selector. Catch sync errors separately and keep tunnel save successful, with explicit partial-result text. Emit `origin_synced(str)` only after a real LAN write; window marks Share changed and refreshes entries.
- [x] Verify focused and full pytest, diff check, and an offscreen conflict-dialog screenshot. Update spec/plan results and DESKTOP.md. Do not touch real configs, restart services or publish.

## Verification (2026-09-16)

- Baseline: 507 passed. Final combined suite: **554 passed in 47.29s**. Dedicated sync tests: 47 passed.
- Equivalent existing URLs keep their quote style and comments without unnecessary rewrites. Legacy scheme/case is normalized before migration.
- GUI tests cover actual Save-button activation, auto-sync, conflict acceptance/cancellation, concurrent edits, password/permission failure, and Save Copy without sync (including selecting the original path).
- Visually inspected the offscreen conflict dialog in ignored output/playwright/desktop/origin-sync-dialog.png. Only temporary/example configs and simulated UI actions were used; no real config or service was modified.
- git diff --check passed. Existing changes retained on main; no commit/build/release.
