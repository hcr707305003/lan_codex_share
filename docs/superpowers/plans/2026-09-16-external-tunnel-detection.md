# External Tunnel Detection Implementation Plan

> Execute inline with executing-plans in the current branch, as requested. Preserve existing dirty work. No real service starts/stops, commits or packaging.

**Goal:** Detect external frpc and Cloudflare processes/services and block duplicate desktop starts.

**Architecture:** Qt-free inspection produces immutable status snapshots. A separate asynchronous monitor polls every 3 seconds. Owned ServiceProcess stays authoritative for owned processes, and external detection never takes ownership.

**Tech Stack:** Existing Python, psutil, PySide6, pytest.

**Spec:** docs/superpowers/specs/2026-09-16-external-tunnel-detection-design.md

## Constraints

No token contents in output or config matching. No network readiness claims. No external service control. No PHP operations. Current branch and existing work are retained.

## Task 1: Read-only inspection

Files: new `desktop/external_tunnels.py`, `tests/test_external_tunnels.py`.

Interface: `inspect_tunnels(settings) -> dict[str, TunnelState]`, keyed by `frpc` and `Tunnel`; frozen `TunnelState(status, message, pids=())`.

- [x] Write fake-process/service tests for matching config paths, defaults/token mode, multiple candidates, permission failure, PID changes, command exclusion and Windows service transitions.
- [x] Run `.venv-desktop/Scripts/python.exe -m pytest tests/test_external_tunnels.py -q` and confirm missing-module failure.
- [x] Implement executable/name checks and argument parsing. Compare only config/token-file paths to settings; classify uncertain matches conservatively. Resolve relative paths from process cwd, and recheck process identity before reporting. Use Windows service PID/status only with live-process verification; ambiguous/permission failure blocks starts.
- [x] Run focused tests until passing; read-only inspect actual host and print only sanitized states.

Test pattern:
```python
result = inspect_tunnels(settings)
assert result['Tunnel'].status == 'unverified'
assert 'Windows' in result['Tunnel'].message
assert 'test-secret' not in repr(result)
```

## Task 2: Async UI integration and regression

Files: new `desktop/tunnel_monitor.py`, `tests/test_desktop_tunnel_ui.py`; modify `desktop/window.py`, old GUI fixtures, `DESKTOP.md`.

Interface: `ExternalTunnelMonitor(settings)` with `states`, `scanning`, `closed`, `start()`, `scan()`, `close()`, `changed` signal. Background jobs perform file/process reads; Qt callbacks render cached results only.

- [x] Write tests that external/unknown states disable launches, cached stopped is freshly checked before start, owned state wins, exit never touches external services, and late worker results are ignored after close.
- [x] Implement 3-second nonoverlapping background scans. Hook window startup, configuration changes, completion and close. Guard direct toggle calls as well as buttons. Recheck immediately before ServiceProcess.start:
```python
external = inspect_tunnels(self.settings)[name]
if external.status != 'stopped':
    raise ValueError('未启动新隧道：' + external.message)
```
- [x] Render matching, unverified, multiple, transitional, unknown and stopped states consistently in cards/footer. Use a short footer label and full card/tooltip detail; external operations stay disabled. Keep owned controls unchanged.
- [x] Run focused tests, full pytest, `git diff --check`, and mocked offscreen 900/1280-width visual check. Update DESKTOP.md and mark completion with exact results. No real service operations or release.

## Verification (2026-09-16)

- Baseline: 437 tests passed. Final combined tree: **507 passed in 48.05s**; `git diff --check` passed.
- Read-only host check recognized Cloudflared as a running Windows service, PID 45796, with configuration unverified. No credential or full command line was printed; no live service was started/stopped.
- Fake process/service tests cover config matching, defaults, token-file paths without content reads, multiple instances, denied access, changed identity, Windows transition states and non-Windows adapter behavior.
- Qt tests verify duplicate-start blocking, fresh prelaunch checks, owned-state precedence, disposal of late scan results and exit ownership. Fixed a close-time scan flag discovered by teardown tests.
- Mocked offscreen 900/1280-width screenshots were visually inspected. Source and docs retained on current main; no commit, packaging or release.
