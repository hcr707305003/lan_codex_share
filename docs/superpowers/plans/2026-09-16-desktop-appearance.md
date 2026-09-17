# Desktop Appearance Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in this session. Steps use checkbox syntax for tracking. User explicitly selected the current branch; do not create a worktree or commit.

**Goal:** Deliver four persistent desktop themes, a cohesive console/dialog layout and one application icon wired to future platform packaging.

**Architecture:** Theme definitions and Qt presentation helpers are independent of service lifecycle logic. DesktopSettings persists a stable theme ID. All GUI pages inherit one QApplication palette/QSS; appearance selection saves before applying. SVG source and an offline exporter provide runtime and distribution icons.

**Tech Stack:** Python 3.12 development environment, existing PySide6 6.11.2, tomlkit, pytest; stdlib icon containers plus Qt SVG rendering.

**Spec:** `docs/superpowers/specs/2026-09-16-desktop-appearance-design.md`

## Global Constraints

- Work in current branch; preserve all dirty changes and real configurations.
- No commit, push, release or application package build in this task.
- No real service start/stop/restart, including PHP and user-managed tunnels.
- Four themes: graphite (default), forest, midnight, lavender; all retained.
- Save only `theme` in existing desktop_config.toml; no service restart flag.
- Keep 900×640 minimum, 1280×800 default, native file pickers and window chrome.
- Keep all lifecycle authority, configuration validation and external identity checks unchanged.
- Test with fake states, temporary configuration and offscreen Qt.

## Task 1 — Theme tokens and settings

**Files:** `desktop/theme.py`, `desktop/config.py`, `tests/test_desktop_appearance.py` under the existing package/tests roots.

**Interfaces:** `THEMES: dict[str, Theme]`, `normalize_theme(value) -> str`, `apply_theme(app, theme_id) -> str`; `Theme.colors: dict[str, str]`. DesktopSettings.load returns normalized `theme` in addition to existing keys.

- [x] Add parameterized tests for all theme IDs and invalid persisted theme values:

```python
@pytest.mark.parametrize('value', ['', 'missing', 42, []])
def test_theme_fallback(value):
    assert normalize_theme(value) == 'graphite'
```

- [x] Run `.venv-desktop/Scripts/python.exe -m pytest tests/test_desktop_appearance.py -q` and observe missing interface failure.
- [x] Implement immutable theme records, common QSS with semantic colors, palette roles for disabled/selection/tooltips; use existing system font families. Preserve `STYLE` as default QSS compatibility export. Apply theme only on initialization/user selection.

```python
def normalize_theme(value):
    return value if isinstance(value, str) and value in THEMES else 'graphite'
```

- [x] Extend DesktopSettings defaults and normalize just theme; invalid unrelated fields still raise. Test comment/unknown-field preservation and all ordinary foreground/background contrast pairs.
- [x] Re-run focused tests plus `tests/test_desktop_config.py`; inspect diff, no commit.

## Task 2 — Appearance selector and unified dialogs

**Files:** create `desktop/appearance.py`, `desktop/messages.py`; modify `desktop/dialogs.py`, `desktop/origin_dialog.py`, config/components/window/app message call sites; extend appearance/dialog tests.

**Interfaces:** `AppearanceDialog(settings, parent=None)` exposes `theme_buttons`, `message`, `select_theme(theme_id)`; `MessageBox` preserves required QMessageBox constants and question/information/warning/critical signatures while rendering custom themed dialogs. `MessageDialog` exposes cancel/confirm for keyboard testing.

- [x] Add failing UI tests: theme persistence, save failure retains old theme, other settings preserved; prompt default cancel and pure text.

```python
dialog.select_theme('midnight')
assert settings.load()['theme'] == 'midnight'
assert app.property('theme_id') == 'midnight'
```

- [x] Implement thumbnail theme buttons and explicit inline write failure; call settings.save before apply_theme, never emit service-config signals. Theme ID/property maps and thumbnails share Theme data.
- [x] Create reusable custom message dialog with bounded scrollable text, action labels, default cancel for questions, plain-text messages, native parent modality. Use compatibility facade only for current call signatures; do not monkeypatch Qt globally.
- [x] Style StopDialog/OriginDialog consistently, constrain long content to scroll areas while retaining current confirmation members/signals and identity details. Replace all current application QMessageBox call sites with facade imports; tests patch each module's facade as before.
- [x] Run appearance, dialogs, origin-sync UI, GUI and interrupt tests; review no lifecycle operations added.

## Task 3 — All four pages and application integration

**Files:** `desktop/window.py`, `desktop/config_page.py`, `desktop/components_page.py`, `desktop/app.py`, `tests/test_desktop_appearance.py`.

**Interfaces:** `DesktopWindow.open_appearance()` opens AppearanceDialog; shared `icons.ui_icon(name, color)` used after Task 4 (temporarily absent imports must not be introduced until available). Page widget references and signal signatures remain stable.

- [x] Write tests that switching themes preserves config draft/logs/changed_services and never starts processes; all four pages remain reachable at minimum width.
- [x] Redesign sidebar and service cards to confirmed hierarchy; place primary lifecycle action and secondary configure control on same row. Label helpers use Qt.PlainText and wrap safely. Use semantic tone properties based on actual state; refresh only repolishes controls when tone changes.
- [x] Group config toolbar/editor/save sections with consistent padding and alignments. Group component cards and Tunnel settings; prevent long candidate paths from expanding layout. Refine log toolbar and monospace font via theme integration.
- [x] Load saved theme before showing the window; set application font/palette before constructing forms, preserve Ctrl+C and smoke-test setup.
- [x] Run desktop GUI/external/tunnel/origin/interrupt tests and appearance tests. Compare temporary Qt screenshots with confirmed preview; no commit.

## Task 4 — App icon and build resources

**Files:** create `desktop/icons.py`, `desktop/assets/app-icon.svg`, derived PNG/ICO/ICNS, `scripts/export_desktop_icons.py`, `tests/test_desktop_icons.py`; modify desktop app/window, both PyInstaller specs, desktop documentation/example.

**Interfaces:** `asset_path(name) -> Path` resolves adjacent package assets; `app_icon() -> QIcon`; `ui_icon(name, color) -> QIcon`. Offline exporter `main()` writes fixed derived assets under package assets from the SVG using QSvgRenderer; stdlib ICO directory and PNG-based ICNS chunks.

- [x] Write tests for icon resolution from unrelated CWD, required sizes/container magic, Qt parsing, spec resource references and consistent source path.

```python
assert asset_path('app-icon.svg').is_file()
assert not app_icon().isNull()
assert asset_path('app-icon.ico').read_bytes()[:4] == b'\x00\x00\x01\x00'
```

- [x] Add approved SVG with title, no embedded fonts/network assets. Render PNGs with Qt; serialize ICO images at 16/24/32/48/64/128/256 and ICNS at 16/32/64/128/256/512/1024. Generate assets only, not application bundles.
- [x] Use same asset icon for app/window, Windows app ID, desktop executable and macOS BUNDLE; CLI EXE icon on Windows. Add package assets to desktop Analysis datas, avoiding resource paths based on CWD.
- [x] Add offline generation and theme settings documentation, no private config data. Run icons/package tests and static spec syntax checks, not PyInstaller.

## Task 5 — Regression and visual handoff

**Files:** tests and ignored `.superpowers/` visual-check script; update this plan and `DESKTOP.md`.

- [x] Run full `.venv-desktop/Scripts/python.exe -m pytest -q` with offscreen Qt.
- [x] Render each theme at 900×640 and 1280×800 with fake service states and sanitized temporary configs; inspect overview, config, components, logs, appearance, stop and origin dialogs. Use Qt grab, no real service operations.
- [x] Run a separate high-DPI offscreen check with `QT_SCALE_FACTOR=1.5`; inspect long-path and wrapped dialog text. Verify readable focus/disabled states and no clipped actions.
- [x] Verify generated resource signatures, inspect changed-file scope and whitespace, remove no unrelated files. Mark completed steps, record actual test totals and platform limitations.
- [x] Handoff source changes for user's local test, state no packaging/publication performed.

## Plan self-review

All spec sections mapped: tokens/settings (1/2), pages (3), dialogs (2), icon/build resources (4), lifecycle/security and platform verification (5). Existing DesktopSettings remains sole persistence source. Icon task can precede layout integration to satisfy imports; no lifecycle side effects are required.

## Execution outcome — 2026-09-16

- Completed on main in the existing directory; all previous dirty work preserved.
- Baseline: 554 tests passed. Final regression after layout refinements: **579 passed in 49.19s**.
- Four themes persist through DesktopSettings; save failure keeps previous theme; repeated unchanged theme application skips global repolish.
- All four pages, theme dialog, service stop/force, public-origin selection and general prompts use the common theme. Configuration form scrolls internally with its save footer visible at minimum window size.
- Qt screenshots generated using fake process states/temporary configs at 900×640 and 1280×800, both 100% and 150% scale. Inspected representative screenshots across all themes/pages/dialog types; long force-close details and errors scroll without hiding actions.
- SVG master plus PNG/ICO/ICNS generated offline; desktop and Windows CLI build specs reference shared icon assets. Added per-theme combo-box arrow assets, included with package resources.
- Updated desktop docs/example and future CI test coverage. No service operations, real config writes, application package build, commit, push or release performed.
- Windows Qt runtime verified locally; macOS/Linux resource/build wiring checked statically, no native platform execution claimed.
