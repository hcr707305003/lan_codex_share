# Component Discovery Implementation Plan

> **For agentic workers:** Use executing-plans to implement the following tasks inline. Current main is explicitly authorized; preserve existing work. No commit, package, release or service operation in this task.

**Goal:** Discover frpc/cloudflared in the approved default locations without hard-coded installation paths.

**Architecture:** A Qt-independent discovery module returns candidates and scan warnings. ComponentsPage performs scans through its existing background job mechanism and caches results; explicit selections remain authoritative. DesktopSettings stores in-directory selections relatively.

**Tech Stack:** Python standard library, existing PySide6, pytest.

**Spec:** docs/superpowers/specs/2026-09-16-component-discovery-design.md

## Global Constraints

- Search only distribution/config roots, their bin subdirectories (three levels), and PATH.
- Never execute candidates during scanning or follow directory links/junctions.
- Do not silently replace invalid explicit selections or choose between multiple local candidates.
- Do not start or restart any service. Keep original CLI behavior and existing dirty files.

## Task 1: Discovery and portable storage

Files: create `lan_codex_share/desktop/discovery.py`, `tests/test_desktop_discovery.py`; modify `lan_codex_share/desktop/config.py`.

Interfaces: `discover(name, roots, *, system=None, machine=None, cancel=None, max_entries=4000) -> Discovery`; `Discovery.candidates: tuple[Path, ...]`, `Discovery.incomplete: bool`; `usable(path, system=None) -> bool`; `DesktopSettings.program_value(path) -> str`.

- [x] Write tests for fixed roots, depth and entry limits, platform names, explicit/executable validation, duplicate roots, PATH fallback, link exclusion and relative relocation.
- [x] Run `python -m pytest tests/test_desktop_discovery.py -q`, observe missing module failure.
- [x] Implement bounded `os.scandir` traversal and deterministic candidate ordering; use no subprocesses. An incomplete scan must not auto-select a seemingly unique candidate.
- [x] Implement storage as `path.resolve().relative_to(settings.path.parent).as_posix()` with absolute fallback outside config directory.
- [x] Rerun focused tests and inspect path boundaries.

## Task 2: Component page integration

Files: modify `lan_codex_share/desktop/components_page.py`, `tests/test_desktop_gui.py`.

- [x] Add offscreen tests with temporary fake binaries and patched `distribution_directory`; assert `page.executable('frpc')` after scan, stale explicit path blocking, and selection persistence.
- [x] Add background rescan using existing `run_job`, cache `Discovery` results, and candidate selector with placeholder and explicit confirmation button. Reuse manual selection saving after download.
- [x] Keep `executable()` free of directory traversal; validate the cached or explicit file before returning it. Refresh version detection from the cached selection.
- [x] Run desktop discovery/config/GUI tests; verify no service started and rescan does not change running processes.

## Task 3: Documentation and regression

Files: modify `DESKTOP.md`, `desktop_config.example.toml`, this plan and spec status.

- [x] Document default search locations, platform filtering, ambiguity, stale selection, relative storage, scan bounds and restart requirements for running services.
- [x] Run `python -m pytest -q` and `git diff --check`.
- [x] Inspect the offscreen component page at the minimum window size; report test results and leave all changes local without packaging.

## Verification record

- Full regression: 386 passed in 42.95s using `.venv-desktop` on Windows.
- New discovery tests cover Windows/Linux/macOS naming via injected platform values; no native macOS/Linux run claimed.
- Offscreen captures: `output/playwright/desktop/component-discovery-900.png` and `component-discovery-1280.png`; minimum-width layout inspected.
- `git diff --check` passed. No real services started/stopped, no downloads, no commit/push/release.
