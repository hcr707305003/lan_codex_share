# frpc Download Location Implementation Plan

> **For agentic workers:** Use executing-plans inline. Work on current main as explicitly requested; preserve all previous changes.

**Goal:** Install the official latest stable frpc under the desktop distribution directory independently of config and terminal locations.

**Architecture:** Reuse distribution_directory() in ComponentsPage's confirmed release handler. Keep installer validation and program-selection persistence unchanged; distinguish permission errors in the installation job.

**Tech Stack:** Python, existing PySide6, pytest.

**Spec:** docs/superpowers/specs/2026-09-16-frpc-download-location-design.md

## Constraints

No service start/stop, real download, commit, package or release. No migration/deletion of existing programs. Confirm target before download; do not fallback silently or elevate privileges.

## Task 1: Directory regression tests and implementation

Files: `tests/test_desktop_gui.py`, `tests/test_desktop_installer.py`, `lan_codex_share/desktop/components_page.py`.

- [x] Mock latest_release, install_frpc, distribution_directory and the confirmation dialog. Use distinct program/config/current directories; assert install destination equals `program / 'bin' / 'frp'`, confirmation includes it, successful result is selected and external paths remain absolute.
- [x] Test colocated config relative storage, rejected confirmation and PermissionError preserving old selection. Verify latest_release requests the official latest endpoint.
- [x] Run new tests to demonstrate the current config-relative destination fails.
- [x] Change the confirmed install handler:

```python
destination = distribution_directory() / 'bin' / 'frp'
# Display destination in the existing confirmation dialog, then:
self.run_job('installed', lambda: installer.install_frpc(result, destination, self.cancel, self.progress.emit))
```

- [x] Catch installation PermissionError in run_job with a directory-permission hint; no raw credential-bearing exception output, fallback path or elevation.
- [x] Run `python -m pytest tests/test_desktop_gui.py tests/test_desktop_installer.py -q`.

## Task 2: Documentation and verification

Files: `DESKTOP.md`, spec and this plan.

- [x] Document program-relative `bin/frp/<version>` and `.app` outside-directory convention, preserving per-config selection storage semantics.
- [x] Run `python -m pytest -q` and `git diff --check`.
- [x] Record exact results and leave source changes in place without packaging.

## Results

Windows `.venv-desktop`: targeted tests 23 passed; full regression 391 passed in 42.52s. `git diff --check` passed. Downloads and confirmation choices were mocked; no actual GitHub asset download, tunnel connection, package build or release performed.
