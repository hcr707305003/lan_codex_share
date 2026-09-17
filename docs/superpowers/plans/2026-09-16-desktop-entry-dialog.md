# Desktop Entries and Stop Dialog Implementation Plan

> Execute inline with executing-plans on the user-approved current branch. Preserve dirty changes; no commit, packaging or real service operations.

**Goal:** Add per-card ports and safe browser links, and replace service-stop confirmation boxes with a consistent dark dialog.

**Architecture:** Pure entry metadata helper reads existing configs on explicit refresh, not each UI tick. Small QDialog encapsulates presentation only; DesktopWindow retains all existing process ownership and confirmation logic.

**Tech Stack:** Existing Python/PySide6/pytest.

**Spec:** docs/superpowers/specs/2026-09-16-desktop-entry-dialog-design.md

## Task 1: Entry metadata and card integration

Files: create `desktop/entries.py`, `tests/test_desktop_entries.py`; modify `desktop/window.py`.

Interface: frozen `EntryInfo(text, url='', detail='')`; `service_entries(config_path, settings) -> dict[str, EntryInfo]`; `safe_web_url(value) -> str`.

- [x] Tests first: valid/invalid HTTP(S) scheme, username/password rejection, missing config, LAN/FRP/CF mapping, bounded multi-proxy display, old public_origin compatibility. Run focused pytest and confirm missing-module failure.
- [x] Implement parsed metadata without credential display. Local URL uses Share port; public URLs only use allowed LAN origins. FRP control port is descriptive, never the browser link. Parse a bounded FRP file through existing ConfigDocument.
- [x] Add card labels and open buttons using QDesktopServices.openUrl only on explicit click. Refresh on configuration/component changes, keep a compact generic note beneath cards. Validate click target again before opening.

```python
url = safe_web_url(self.entries[name].url)
if url:
    QDesktopServices.openUrl(QUrl(url))
```

## Task 2: Consistent confirmation UI

Files: create `desktop/dialogs.py`, `tests/test_desktop_dialogs.py`; modify `desktop/window.py`, `desktop/theme.py`, existing external-Share UI tests.

Interface: `StopDialog(parent, service, *, force=False, details='', exiting=False)`; `confirm_stop(...) -> bool`.

- [x] Write tests verifying default Cancel/focus, Enter and Escape reject, explicit confirm accepts, service/impact text, and long details wrap.
- [x] Implement dark native QDialog, selectable plain-text details, distinct destructive action text and muted red action styling. Replace only stop/force-stop/exit-confirmation calls; preserve process checks and default rejection.
- [x] Update affected tests to mock confirm_stop rather than unrelated QMessageBox questions. Cover no browser launch on construction and no external process stops from exit.
- [x] Run full suite and diff check; capture mocked offscreen 900/1280-width cards and dialog, inspect screenshots, update DESKTOP.md and record results. No publication.

## Verification (2026-09-16)

- Final combined tree: **507 passed in 48.05s**; `git diff --check` passed.
- Tests cover URL schemes/credential rejection, LAN and public-origin mapping, legacy origin, separate control/business ports, bounded mappings, explicit browser clicks, entry refresh and unchanged stop ownership.
- Enter/Escape cancel by default; explicit confirmation accepts. Long wrapped details were initially clipped in visual QA, fixed with height-for-width minimum sizing and protected by a layout assertion.
- Visually checked ignored screenshots: `output/playwright/desktop/tunnel-entries-900.png`, `tunnel-entries-1280.png`, `stop-service-dialog.png`, `force-service-dialog.png`. All use simulated service states and example configuration; no real process control or browser navigation.
- Changes retained on current main, no commit/build/release. DESKTOP.md documents configured links, unknown external states and cancellation behavior.
