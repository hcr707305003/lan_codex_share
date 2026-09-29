# Desktop background mode implementation plan

**Goal:** Close the window without stopping Share or tunnels, using a recoverable tray entry.

**Approved design:** Offer background, stop owned services and exit, or cancel. Background keeps the Qt loop, control pipes, log readers, drafts and downloads alive. External services are never stopped by exit. Disable background when no system tray is available. Explicit tray exit uses the existing graceful-stop confirmation and timeout handling.

**Architecture:** Keep process ownership unchanged; add a close-choice dialog and a QSystemTrayIcon to DesktopWindow. No detached processes, startup tasks or configuration changes.

**Tech Stack:** Python / PySide6.

## Tasks
- [x] Add themed three-choice dialog with cancel default and unavailable-tray explanation.
- [x] Add tray restore / exit actions; handle background before unsaved-edit prompts; preserve existing cleanup and stop flow.
- [x] Test hide/restore without stop, cancellation, unavailable tray, explicit exit and cleanup with fake services.
- [x] Document background lifetime and terminal caveat; run desktop regression tests. Do not publish or manipulate live services.

Verification: full Python suite 834 passed; git diff --check passed. Qt event-loop subprocess verifies hide does not quit. No live services were changed. Native tray interaction on other desktop platforms remains a manual check.
