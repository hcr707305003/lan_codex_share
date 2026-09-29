# Session Notice Banner Implementation Plan

> **For agentic workers:** Use executing-plans in this session, on the user-requested current branch.

**Goal:** Show a default-collapsed project Markdown notice above the active conversation.
**Architecture:** Isolated banner controller consumes project summary and session ID, fetches the existing profile endpoint on expansion and renders with the existing safe Markdown renderer. A bounded cache and request generation prevent stale responses; the existing profile editor handles editing.
**Tech Stack:** Vanilla JavaScript/CSS, Python, Node tests, isolated Playwright fixture.
**Spec:** ../specs/2026-09-29-session-notice-banner-design.md

## Global Constraints

- No new permissions, AI context, configuration or dependencies.
- Default collapsed on reload and every Session change; no notice means no occupied row.
- Body max-height min(280px, 35dvh); preserve timeline nodes and reading position.
- No publishing or deployed service restart.

## Tasks

### 1. Banner controller and tests

Create `web/notice.js` and `tests/javascript/notice.test.cjs`; modify `session_hub.py` and `tests/test_project_profiles.py`.
Interface: `LanNotice.mount({root, toggle, body, retry, status, edit, request, markdown, editProject, layout})` returns `{update(sessionId, project)}`. `layout(fn)` preserves timeline scroll while fn updates the banner DOM.

- [x] Write fake-DOM tests: `update('a', project)` leaves root visible/body hidden/no requests; click toggle fetches once, repeated update does not; cache survives collapse; Session change collapses; delayed response ignored after switching; failure retries only on explicit action; revision invalidates cache; deletion hides and aborts.
- [x] Run `node --test tests/javascript/notice.test.cjs` to observe missing module, then implement controller. Cache only current project/revision to remain bounded; abort and generation-check in-flight fetches.
- [x] Set `has_notice=bool(profile['notice_markdown'].strip())`; test whitespace produces false without modifying stored Markdown.

### 2. Integration

Modify `web/index.html`, `web/style.css`, `web/app.js`, `web/profiles.js`, `static_assets.py`, `lan_web.py`, `tests/test_static_assets.py`.

- [x] Add banner between header and timeline, explicitly assign grid rows so hidden banner does not shift the flexible timeline row. Include aria-expanded/controls and retry/edit controls.
- [x] `render` calls `notice.update(threadId,currentProject)`; `selectSession` resets immediately with `(next,null)`. Layout callback captures bottom distance/scrollTop, mutates synchronously, restores bottom only if already following; otherwise preserve scrollTop.
- [x] Extend profile `open(project, edit=false)` to enter edit after successful read, retaining existing dirty/saving guards. Add notice.js to hashed static asset list and test count.
- [x] Add responsive CSS with hidden overrides, bounded scroll, inherited Markdown style and 44px mobile actions; use semantic colors and no animation.

### 3. Verification and docs

- [x] Use isolated fixture and fake project metadata to check default collapse, long Markdown, editor handoff, same-project Session switch, two-client updates/deletion, desktop/mobile/landscape, and timeline reading position.
- [x] Run full Python suite with PYTHONUTF8=1 and Node tests using bundled Node; `git diff --check`.
- [x] Update README and spec/plan results; local commit only, close test browser and fixture.

## Verification results

- Python: 803 passed. Node: 55 passed, including six new banner-controller tests.
- Browser: default collapse, cache reuse, 800px history position preserved on both toggle directions, bottom-follow preserved, same-project switch reset, other-project absence, guarded direct editing, two-client updates/whitespace deletion/recreation and refresh reset passed.
- Screenshots inspected at 1440×960, 375×812 and 812×375. Short landscape needed an additional body cap to keep the timeline from collapsing; corrected and visually rechecked. Screenshot capture disables resize transitions for stable results.
- Existing Markdown renderer reused unchanged; static hash tests verify the new asset participates in cache invalidation.
- Testing used temporary fake projects only; no real sessions, deployed services, or private configuration were changed.
