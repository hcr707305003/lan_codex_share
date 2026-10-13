# PDF Preview Layout Implementation Plan

> **For agentic workers:** Use executing-plans inline in the current branch, as requested by the user.

**Goal:** Give ZIP PDF members the remaining preview height with compact navigation.

**Architecture:** Keep archive-preview.js responsible for DOM and lifecycle; use scoped CSS flex sizing for the archive shell and PDF content. Existing APIs and browser-native rendering remain unchanged.

**Tech Stack:** Vanilla JavaScript, CSS, Node test runner, pytest.

**Spec:** ../specs/2026-10-13-pdf-preview-layout-design.md

## Global Constraints

No new dependencies, service restart, commit, packaging or release in this task.
Preserve the existing CSP fix and drag-resize behavior. Native viewer internals are browser-owned.

## Task 1: Compact toolbar and full-height PDF

Files: lan_codex_share/web/archive-preview.js, lan_codex_share/web/style.css,
tests/javascript/archive-preview.test.cjs.

- [x] Add a PDF fixture test asserting one toolbar containing return/navigation/download controls, no constant warning, an accessible PDF object and retained fallback/download.
- [x] Run `node --test tests/javascript/archive-preview.test.cjs` to confirm the new assertions fail.
- [x] In shell(), place return and breadcrumbs in toolbar alongside downloads. Remove the redundant return button in member(). For PDF set `body.className = 'archive-content archive-content-pdf'`, set object title and retain fallback inside object only.
- [x] Use `.archive-panel { height: 100%; display: flex; flex-direction: column; }`, flexible scrollable content with min-height:0, and PDF-specific zero padding/min-height:0 to fill available space without affecting other preview types.
- [x] Add a return-to-list assertion and rerun Node tests; run `pytest -q -p no:cacheprovider tests/test_lan_web.py tests/test_archive_web.py`.
- [x] Open an isolated fixture using the actual JS/CSS. Check a wide panel, 360px panel, 375px viewport and a short viewport; verify PDF bounds fit available height, controls remain reachable and returning to list restores ordinary scrolling.
- [x] Review diff and report tests and limitations. Leave changes uncommitted for user testing.

Results: 72 Node tests and 27 targeted Python tests passed. Actual JS/CSS fixture in Chromium: 1440×900, 1200×720 with 360px panel, 375×667, and 900×480 all had zero PDF bottom gap, no outer preview scroll, and toolbar controls within panel bounds. The short viewport used the existing responsive 640px overlay width. Native PDF thumbnails remained browser-managed. Preview fixture used a synthetic PDF, not user business documents.
