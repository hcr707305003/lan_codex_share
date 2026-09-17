# Desktop Client Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking. Execute inline; do not delegate or commit/publish without user direction.

**Goal:** Build a native desktop controller for Share, frpc and cloudflared, with safe configuration editing, bounded logs and verified frpc downloads.

**Architecture:** Qt Widgets is a separate optional GUI entry. Pure-Python configuration, installation and logging modules are independently tested. Owned subprocesses communicate over inherited pipes; no management HTTP endpoints are added.

**Tech Stack:** Python 3.11, PySide6 6.11.2, tomlkit, PyYAML, existing psutil and PyInstaller. Pin package versions after querying official package metadata.

**Spec:** `docs/superpowers/specs/2026-09-16-desktop-client-design.md`

## Global Constraints

- Preserve existing default/share/cli entry points and `--config` semantics; Qt is optional.
- Only modify this repository. Never start, stop or restart PHP/Webman or real tunnels during development.
- No real credentials, user paths or private configs in fixtures, documentation or release archives.
- Desktop controls only processes it creates. No port/name-based killing or remote management API.
- GUI minimum 900 × 640. Log limit 10,000 records; line limit 16 KiB; file rotation 5 MiB × 3.
- Download archive limit 200 MiB; extracted frpc limit 100 MiB. Require official SHA-256 and safe extraction.
- Defaults refer to executable distribution directory, outside macOS `.app`. Explicit relative config path uses caller cwd.
- Saving configuration never restarts a service. Closing with running services requires confirmation.
- Stop waits 15 seconds before offering continued wait or explicit force stop. No silent forced shutdown.
- One release archive includes GUI and existing Share/CLI; no version bump or release in this task.

## Progress / workspace

- [x] User approved UI and written design.
- [x] User explicitly chose current branch main; previous FRP changes preserved.
- [x] Baseline: `.venv/Scripts/python.exe -m pytest -q`: 337 passed.

## Task 1: Configuration documents and desktop settings

**Files:** create `lan_codex_share/desktop/{__init__,config,logs}.py`, `requirements-desktop.txt`, `tests/test_desktop_config.py`, `tests/test_desktop_logs.py`; extend `.gitignore`.

**Interfaces:**

```python
class ConfigDocument:
    def __init__(self, path: Path, kind: str): ...
    def load(self) -> str: ...
    def parse(self, text: str) -> dict: ...
    def update_fields(self, text: str, updates: dict, proxy_index: int = 0) -> str: ...
    def save(self, text: str) -> None: ...

class DesktopSettings:
    def __init__(self, lan_path: Path): ...
    def load(self) -> dict: ...
    def save(self, values: dict) -> None: ...

class LogBuffer:
    def add(self, source: str, text: str) -> None: ...
    def filtered(self, source: str = "", query: str = "") -> list[str]: ...
    def set_secrets(self, secrets: list[str]) -> None: ...
```

- [ ] Write failing tests for comment/unknown-key preservation, multi-proxy editing, conflict detection, invalid save, missing/empty Session semantics, YAML duplicate keys/object tags, redaction and bounds.

```python
def test_external_edit_is_not_overwritten(tmp_path):
    p = tmp_path / "frpc.toml"
    p.write_text('serverAddr = "192.0.2.10"\n', encoding="utf-8")
    doc = ConfigDocument(p, "frp")
    text = doc.load()
    p.write_text('# external edit\n' + text, encoding="utf-8")
    with pytest.raises(ValueError, match="外部"):
        doc.save(text)
```

- [ ] Run focused tests; expect missing-module failure initially.
- [ ] Implement TOML round-trip via tomlkit, YAML safe loader with duplicate-key rejection, domain-specific validation and same-directory atomic replacement after digest check. Existing Share loader validates a temporary config beside the original so relative paths retain semantics. Avoid emitting parser excerpts that may include secrets.
- [ ] Implement desktop settings for selected executable/config paths and cloudflared mode/token-file; do not store secret contents. Add private config/binary ignores.
- [ ] Add redaction before bounded memory/file logging, UTF-8 safe line handling and dropped-record count. Run focused tests to PASS.

## Task 2: Owned processes and Share worker

**Files:** create `lan_codex_share/desktop/{process,worker}.py`; modify `lan_codex_share/lan_main.py`; create `tests/test_desktop_process.py`, `tests/test_desktop_worker.py`.

**Interfaces:**

```python
class ServiceProcess:
    def start(self, argv: list[str], cwd: Path, *, controlled: bool = False) -> None: ...
    def stop(self) -> None: ...
    def force_stop(self) -> None: ...
    def snapshot(self) -> dict: ...

# Extend run without changing existing positional call sites:
def run(config_path, *, stop_event=None, on_ready=None) -> int: ...
```

- [ ] Tests spawn only test Python children in temp directories: start/duplicate start, stdout/stderr, failure code, normal pipe stop, already-exited stop, readiness and timeout. Test no unrelated process termination.
- [ ] Run focused tests and confirm initial failures.
- [ ] Implement background pipe readers with incremental UTF-8 decoder and bounded lines; only stored Popen handles may terminate. Snapshot is lock-protected; GUI polls it, never receives UI callbacks from workers.
- [ ] Controlled Share uses fixed JSON stop command on stdin and a reserved readiness event. Add stop-event watcher before entering `serve_forever`, call HTTP shutdown from watcher, retain finally cleanup.
- [ ] For external tunnel processes, graceful POSIX SIGTERM / Windows supported termination, accurately report its semantics. After 15 seconds expose waiting state; force is separate explicit action.
- [ ] Run focused and existing `test_lan_main`/service/instance-lock tests to PASS.

## Task 3: Official frpc installer

**Files:** create `lan_codex_share/desktop/installer.py`, `tests/test_desktop_installer.py`.

**Interfaces:**

```python
def platform_key(system: str | None = None, machine: str | None = None) -> str: ...
def latest_release() -> dict: ...
def install_frpc(release: dict, destination: Path, cancel: Event,
                 progress: Callable[[str], None]) -> Path: ...
```

- [ ] Write fixtures containing a tiny fake executable; mock network. Cover exact platform selection, missing/bad checksum, cancellation, size limit, traversal/symlink rejection and unchanged old binary.

```python
def test_platform_mapping():
    assert platform_key("Windows", "AMD64") == "windows_amd64"
    assert platform_key("Darwin", "arm64") == "darwin_arm64"
```

- [ ] Confirm failures, then implement official API/asset origin allowlist with redirect validation, timeouts and bounded retry. Obtain SHA-256 from official metadata or same-release checksum asset; reject missing digest.
- [ ] Stream downloads with byte caps into unique temp directory; safely extract only expected regular frpc file; atomically place at versioned destination, preserving active versions. Always cleanup own temp artifacts.
- [ ] Verify tests PASS. Never contact user's frps or run downloaded frpc during tests.

## Task 4: Native GUI and launcher

**Files:** create `lan_codex_share/desktop/{app,window,config_page,components_page,theme}.py`, `run_lan_codex_desktop.py`, `start_lan_codex_desktop.cmd`, `start_lan_codex_desktop.sh`, `desktop_config.example.toml`, `cloudflared.example.yml`, `tests/test_desktop_gui.py`, `tests/test_desktop_launcher.py`.

**Interfaces:**

```python
def main(argv: list[str] | None = None) -> int: ...
class DesktopWindow(QMainWindow):
    def __init__(self, config_path: Path): ...
```

- [ ] Add offscreen tests that construct window without real services, inspect four pages, edit/save temp config, test navigation, invalid validation, masked secret retention, download failure UI and close confirmation.
- [ ] Implement Qt Widgets layout from approved prototype; use native accessible controls, focus rings and scroll areas. GUI state is real (not prototype demo state).
- [ ] Wire independent service cards, status and config indicators; no auto-start. Share command uses companion executable or source worker; configured missing dependencies show installation guidance.
- [ ] Implement form/raw modes over Task 1 documents, selected proxy index, open/create/save/refresh conflict behavior, and unsaved-change confirmation on file/tab/exit changes.
- [ ] Run installer on cancellable background thread; component path validation and version probing occur off GUI thread. cloudflared supports local YAML or token-file mode without token command-line arguments.
- [ ] Poll process status and log buffer at bounded intervals; support source/search/pause/clear/export, no full-view refresh for each incoming line. Polling does not imply tunnel connected.
- [ ] Verify offscreen tests and render screenshots using Qt to a test artifact directory; inspect 900×640 and 1280×800. CLI command tests prove Qt is not imported by existing launcher.

## Task 5: Distribution and regression

**Files:** create `lan_codex_desktop.spec`; modify `scripts/package_release.py`, `.github/workflows/release.yml`, `README.md`, `RELEASE_README.md`, `PIPELINE_RELEASE.md`, related packaging tests.

- [ ] Write archive tests for GUI directory/.app + CLI, config examples, licenses, executable mode bits and forbidden files. Existing CLI-only packaging behavior remains available for tests/legacy use.
- [ ] Add directory-style GUI build, Qt plugin/license collection and no WebEngine. Native package default root must resolve outside macOS bundle.
- [ ] Add GUI dependency/build jobs and GUI smoke without opening real services on each platform; keep original CLI smoke checks. Release remains tag-triggered.
- [ ] Document GUI/source startup, dependency installation, token placement, secure configuration, limitations and unsigned distribution. Use examples only.
- [ ] Run full tests, `git diff --check`, source launcher help, GUI offscreen smoke, local Windows build and built CLI/GUI startup test. Do not publish artifacts or push code.

## Plan self-review

Configuration, lifecycle, installation, GUI, packaging and security acceptance criteria map to Tasks 1–5. All public interfaces are specified above. Cross-platform validation beyond local Windows is performed by CI; report unexecuted platforms honestly. Previous FRP changes stay intact. No commit step is executed until the user requests submission.

## Execution record — 2026-09-16

- [x] Task 1 implemented: comment-preserving TOML, strict YAML, conflict detection, atomic save, bounded/redacted logs.
- [x] Task 2 implemented: owned process handles, inherited-pipe worker, graceful Share shutdown, verified App Server identity handling and hidden Windows children.
- [x] Task 3 implemented: official platform assets, digest verification, bounded extraction, cancellation and official-page fallback. Tests use synthetic archives; real frps was never contacted.
- [x] Task 4 implemented: four native pages, form/raw config editing, independent controls, component selection/download/version detection and logs. CRLF false-dirty and narrow-form regressions fixed.
- [x] Task 5 local Windows build and assembled-archive smoke passed; existing CLI and GUI share one archive, both default and explicit config locations tested.
- [x] GUI render checks performed at 900×640 and 1280×800. Offscreen Windows rendering uses a system font explicitly in the test fixture; production uses the native font backend.
- [ ] Execute remote macOS/Linux builds after a future user-authorized push/release. No remote workflow has been triggered in this task.

Implementation adjustments: the existing Anaconda environment could not load Qt. An ignored `.venv-desktop` based on standalone CPython was created without changing Anaconda. PyInstaller also discovered incompatible Conda ICU DLLs on PATH; the Windows GUI spec excludes those copies so Qt uses Windows ICU. The built executable and extracted archive now pass smoke tests. GUI import failures produce a local startup diagnostic instead of silently exiting.

The per-task steps above retain the original intended test sequence; the completed task summaries here record the delivered local result. No code was committed, pushed or released, and no real tunnel or PHP service was started/stopped.

Final verification: standalone CPython full suite **371 passed in 44.09s**; `git diff --check`, shell syntax and workflow YAML checks passed. The locally assembled Windows archive passed extracted GUI startup (default and explicit config paths) and companion CLI checks. Preview archive size: 64,658,945 bytes. SHA-256: `C25DB20658DDCE2931F54520341069030FA4485C21F887A2C0B05202369728A3`. It retains the existing version number solely as a local test build, not a new published release.
