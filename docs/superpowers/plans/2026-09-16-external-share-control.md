# External Share Control Implementation Plan

> **For agentic workers:** Use executing-plans inline on current main (user approved), preserving existing dirty work. No real user-process termination, commit, build or release.

**Goal:** Discover an externally started Share for the current config and provide explicitly confirmed, identity-checked force close.

**Architecture:** Separate Qt-free discovery/termination from owned ServiceProcess. A minimal runtime identity record proves newly launched App Server ownership in combination with live process checks. Qt polls asynchronously and keeps external shutdown separate from normal desktop exit.

**Tech Stack:** Existing Python/psutil/PySide6/pytest, no new dependencies.

**Spec:** docs/superpowers/specs/2026-09-16-external-share-control-design.md

## Constraints

No PHP/business process control; no name/port-only kill, recursive tree kill, automatic restart, or external shutdown on GUI close. Missing identity or permission must fail closed. Existing older scripts remain discoverable; uncertain App Servers remain untouched.

## Task 1: Qt-independent identity discovery

Files: create `lan_codex_share/desktop/external_share.py`, `tests/test_external_share.py`.

Interfaces: `ShareIdentity(pid, created, config_path, executable, argv)`; `ExternalState(status, message, identity=None)`; `inspect_share(config_path) -> ExternalState`; `force_close_share(identity) -> str`.

- [x] Test module/script/frozen/worker command parsing, CLI exclusion, relative/default config, PID reuse, listening identity, port-only conflict, permission failure and ambiguity.
- [x] Implement narrow command parser and process checks; collapse a same-command Python launcher parent only when the actual child can be proven. Probe listener ownership, not just open ports.
- [x] Test and implement force close with a second discovery and immediate live identity check, explicit timeout and failure reporting. Never terminate a test's real process; mocks record attempted kills.

```python
state = inspect_share(identity.config_path)
if state.identity != identity:
    raise ValueError('进程身份已改变，已取消强制关闭，请重新检测')
```

## Task 2: App Server ownership record

Files: create `lan_codex_share/share_instance.py`, tests; modify `lan_codex_share/lan_main.py`.

Interfaces: `write_instance(config_path, app_server, port)`; `remove_instance(config_path)`; `verified_app_servers(identity) -> (list[(process, executable_and_argv)], str)`.

- [x] Atomically write runtime/lan/instance.json after App Server startup, holding existing server lock. Record only config/PID/create time/listen endpoint and owned App Server identities, no secrets.
- [x] Revalidate record parent identity, live exact App Server command/listen endpoint, ancestry and timestamps before accepting cleanup targets. Refuse reused/unverified children and unrelated business descendants.
- [x] Remove only own matching record on normal exit. Stale files never authorize killing anything. Test new/old/reused/forged/mismatching identities.

## Task 3: Qt integration and regression

Files: modify `lan_codex_share/desktop/window.py`, GUI tests, `DESKTOP.md`.

- [x] Background detection every 3 seconds; callbacks update cached status. Cancel observation on window close; never let observation trigger termination.
- [x] Show external running/starting PID, occupied/unknown/ambiguous states; block duplicate launch and recheck before own launch. External terminate dialog defaults to No and warns about interrupted work.
- [x] On confirmation, retain immutable selected identity, block repeat clicks, perform shutdown in worker, surface failures and refresh state. Normal GUI close never calls external shutdown.
- [x] Test cancel/confirm, PID-changing result, duplicate clicks, external disappearance, normal exit ownership boundary; run full suite and git diff --check.
- [x] Read-only check real local detection (never force close). Record outcomes; no publication.

## Verification outcomes (2026-09-16)

- Full suite: `.venv-desktop/Scripts/python.exe -m pytest -q` — **437 passed in 45.96s**.
- `git diff --check` passed.
- Read-only discovery recognized the existing script-started Share as running, PID 49196, and excluded its virtual-environment launcher. No live user Share or PHP/business process was terminated.
- Termination and ownership failure paths use fake process objects; they cover PID reuse, command/executable changes, access denial, timeouts, reused App Servers, and unrelated descendants.
- Offscreen Qt screenshots generated at 900 and 1280 widths under ignored `output/playwright/desktop/`; the 900-width view was visually checked for status, PID, force-close action and layout. GUI interactions are covered by automated tests, not a destructive live-service test.
- Existing dirty work retained on main. No commit, packaging or release performed.
