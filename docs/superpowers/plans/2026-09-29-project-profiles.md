# Project Profiles Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan task-by-task in the current branch, as requested by the user.

**Goal:** Shared project aliases and Markdown notices without changing business repositories or AI context.
**Architecture:** A locked atomic JSON store, Hub identity/summary integration, authenticated HTTP endpoints and an isolated browser panel controller using the existing preview shell and safe Markdown renderer.
**Tech Stack:** Python standard library, vanilla JavaScript, existing CSS tokens and pytest/Node/Playwright verification.
**Spec:** ../specs/2026-09-29-project-profile-design.md

## Global Constraints

- Current main branch; no service restarts, publishing, or business repository edits.
- alias ≤100 characters, no control characters; notice_markdown ≤64 KiB UTF-8.
- Project identity comes from canonical cwd; known shared projects only; empty cwd cannot edit.
- Auth, Origin/CSRF, revision conflicts, atomic persistence and safe Markdown are mandatory.

## 1. Store and integration

Files: new `lan_codex_share/project_profiles.py`, `tests/test_project_profiles.py`; modify `session_hub.py`, `lan_main.py`, `lan_web.py`.

Interfaces: `project_key(cwd) -> str`; `ProjectProfiles.get(key) -> dict`; `save(key, alias, notice_markdown, revision) -> dict`; `ProfileConflict(ValueError)`; Hub `project_profile(project_id, changes=None)` validates membership, reads/saves and broadcasts.

- [x] Write store tests before implementation, including:
  ```python
  saved = store.save(key, '后端', '# 公告', 0)
  assert saved['revision'] == 1
  with pytest.raises(ProfileConflict):
      store.save(key, '旧编辑', '', 0)
  assert ProjectProfiles(path).get(key) == saved
  ```
- [x] Run focused tests with `.venv-desktop/Scripts/python.exe -m pytest tests/test_project_profiles.py -q`; observe missing module, then implement validation, load errors and temp-file/fsync/replace under RLock.
- [x] Enrich project summaries with alias/revision/has_notice only; preserve original name and cwd. Instantiate store in `_build_session_hub` under runtime. Do not read any Codex thread through profile endpoints.
- [x] Add GET/POST `/api/projects/profile`; POST receives project_id, alias, notice_markdown, revision, returns full profile; conflict is HTTP 409. GET receives project_id query. Enrich `/api/sessions/projects` display names using the same key.
- [x] Add Hub/HTTP tests for unknown IDs, no workspace expansion, and write security. Run focused suite.

## 2. Browser interaction

Files: new `web/profiles.js`; modify `web/app.js`, `web/index.html`, `web/style.css`, `static_assets.py`, `lan_web.py`, static asset tests; new Node tests.

Interface: `LanProfiles.mount(options)` returns `{open(project), leave(), sync(projects)}`. Options supply request/mutate/renderMarkdown and preview host open/close hooks. No separate CSS theme or dependencies.

- [x] Implement testable `isDirty(profile, alias, notice)` and UTF-8 validation helpers; Node tests cover empty, unchanged, changed and multibyte limits.
- [x] Add controller with view/edit/preview, inline saving/errors, revision tracking and request-generation guards. `leave()` rejects while saving and confirms dirty discard, then invalidates pending reads. `sync` reloads clean views but preserves edits on remote revisions.
- [x] Wire separate project-info button, alias display, existing side panel handoff and current workspace label; integrate static asset hashing and required asset list.
- [x] Use existing file preview dimensions/scroll containment; clear file download/refresh controls when showing profile. Restore them for files. Add labeled inputs, live status, Escape/close behavior, visible focus and mobile button sizing.

## 3. Verification and docs

Files: `README.md`, existing `tests/fixtures/session_tasks_preview.py`, isolated ignored Playwright scripts/screenshots.

- [x] Configure a temporary profile store in the fake service fixture; never connect real sessions.
- [x] Browser check: alias, Markdown links/table/escaped HTML, save/reload, two-client sync/conflict, dirty cancel, file-preview handoff and 375px layout.
- [x] Run full Python suite and `node --test tests/javascript/*.test.cjs` with bundled Node runtime; run `git diff --check`.
- [x] Document public edit permissions, runtime backup and no AI injection; record actual results here. Local commit only after verification, no push/release.

## Results (2026-09-29)

- Python: 803 passed in 72.45s with PYTHONUTF8=1; no warnings in final run.
- Node: 49 tests passed. Existing preview harness updated for the new profile handoff dependency.
- Isolated browser checks passed: rendered Markdown table and HTTP link, inert HTML/dangerous URL, alias persistence, two-context revision conflict, dirty-close cancellation, file-preview handoff, new-task project alias and 375×812 mobile layout.
- Desktop and mobile screenshots inspected under ignored output/playwright/project-profile-*.png.
- Browser check initially required matching the existing file-link arrow suffix in its accessible name; product behavior was correct. A CSS hidden-state override was added for profile-only mode so file controls do not remain visible.
- No real Codex sessions or deployed services were changed. No release or push.
