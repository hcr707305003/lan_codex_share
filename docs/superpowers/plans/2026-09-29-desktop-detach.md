# Independent service lifetime

**Goal:** Add explicit exit-console/keep-services alongside tray background and stop-and-exit.

**Approved design:** Qt exits completely. A headless per-service runner retains the child pipes and rotating redacted logs. External services remain untouched. No live process is restarted or silently migrated. Unsupported legacy owned processes prevent detach with an explanation.

**Architecture:** A private supervisor starts the existing ServiceProcess, forwards status/logs while attached and acknowledges explicit detachment. Parent EOF without detachment retains existing stop semantics. Separate POSIX session / Windows no-console process prevents terminal lifecycle coupling. Secrets travel only in a pipe, never command arguments or startup files. Frozen launcher dispatches the same supervisor without Qt.

**Files:** desktop/supervisor.py (runner), desktop/process.py (handshake), desktop/logs.py (secret snapshot), desktop/window.py and close_dialog.py (exit choice), launcher.py (frozen entry), tests/test_desktop_detach.py, README.md.

- [x] Add subprocess regressions: explicit detach + parent EOF retains a live child and disk logging; EOF without detach stops child; legacy detach refuses.
- [x] Implement supervisor with serialized command/ack/log output, bounded rotating redacted logs, owned identity updates, normal/forced stop compatibility.
- [x] Wire desktop launches and async detach with timeout; refuse during downloads/start/stop operations; keep window on any failure.
- [x] Run Python suite and inspect diff; leave local changes unpushed and do not touch live services.

Verification: 848 full-suite tests passed, plus the subsequently added Qt console subprocess exit integration test passed. It exercises DesktopWindow close/handshake/app event-loop exit while an isolated service keeps writing redacted logs. git diff --check clean. No live services changed. Packaged binaries and non-Windows native tray behavior were not tested in this change.
