# Project Notice Popover Implementation Plan

> **For agentic workers:** Use executing-plans to implement this plan task-by-task in the current branch, as requested by the user.

**Goal:** Replace the full-width notice row with a title-side button and bounded floating panel.
**Architecture:** Keep notice.js request/cache state; add explicit dismiss and positioning behavior. Render the panel at document body level to avoid main-panel containment clipping.
**Tech Stack:** Vanilla JavaScript, CSS, Node test runner, isolated browser fixture.
**Spec:** docs/superpowers/specs/2026-09-29-project-notice-popover-design.md

## Global Constraints

No backend/config changes, no real sessions, no running service restart, no publishing. Preserve Markdown safety and draft protection. Default collapsed; outside click must not steal focus.

## Task 1: Popover behavior

- [x] Extend tests/javascript/notice.test.cjs mocks with panel/close/document and focus tracking. Assert `c.close.click(); assert.equal(c.panel.hidden,true)`; assert Esc restores focus and outside click does not. Assert panel click stays open and failed edit handoff stays open.
- [x] Run `node --test tests/javascript/notice.test.cjs`, confirm new tests fail.
- [x] Modify web/notice.js mount options: panel, close, document, beforeOpen, position. Paint synchronizes panel.hidden and calls position while expanded. Add `dismiss(restoreFocus=false)` and public close. Outside pointerdown checks root and panel containment; Esc prevents downstream global close behavior. Use synchronous editProject boolean result, dismiss only unless false returned.
- [x] Run targeted tests and preserve all cache/revision/abort regression cases.

## Task 2: Layout integration

- [x] Move session-notice into topbar-title-group; panel contains header/close, status/retry, scrollable body, footer/edit. Keep original element IDs.
- [x] Restore main-panel three grid rows. Style compact button and fixed 420px max-width panel using theme tokens. Body flexes with min-height:0 and overflow:auto.
- [x] In app.js pass panel/close/document, close other menus before open, append panel to body. Position with 12px main-panel gutters and viewport bounds; cap height to viewport space below anchor. Reposition via resize/ResizeObserver of main panel. Close on other menu buttons, including stopped-propagation handlers.
- [x] Use isolated notice fixture to verify desktop, mobile and landscape, no timeline size/scroll changes, outer click/Esc/close, Markdown and edit handoff.

## Task 3: Verification and docs

- [x] Update README to title-side popover wording.
- [x] Run full JavaScript tests and related Python static resource/page tests; run git diff --check.
- [x] Record validation results, commit only this feature locally. No push/package/release.

## Results

- 803 Python tests passed; 57 JavaScript tests passed.
- Browser fixture: 1440×960, 375×812, 812×375; screenshots inspected. Bounds, independent scrolling, stable timeline size/offset, three dismiss methods and focus return passed.
- Keyboard open focuses close control; menu/notice exclusion passed; rejected dirty-edit handoff preserves draft and notice. Escape does not close the underlying file preview.
- Tests used temporary profiles and fake sessions only. No running user service changed.
