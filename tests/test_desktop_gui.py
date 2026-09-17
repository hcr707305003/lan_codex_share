import os
import time
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
pytest.importorskip('PySide6')
pytest.importorskip('tomlkit')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop.window import DesktopWindow


def wait_components(app, page):
    deadline = time.monotonic() + 5
    while page.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.005)
    app.processEvents()
    assert not page.busy


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def no_real_external_discovery(monkeypatch):
    from lan_codex_share.desktop import external_monitor, tunnel_monitor
    from lan_codex_share.desktop.external_share import ExternalState
    from lan_codex_share.desktop.external_tunnels import TunnelState
    monkeypatch.setattr(external_monitor, 'inspect_share', lambda _: ExternalState('stopped', '已停止'))
    monkeypatch.setattr(tunnel_monitor, 'inspect_tunnels', lambda _: {n: TunnelState('stopped', '未发现外部运行实例') for n in ('frpc', 'Tunnel')})


def test_window_starts_nothing_and_has_pages(app, tmp_path):
    window = DesktopWindow(tmp_path / 'lan_config.toml')
    assert window.stack.count() == 4
    assert all(not p.snapshot()['running'] for p in window.services.values())
    window.resize(900, 640)
    window.show()
    app.processEvents()
    assert window.width() == 900
    wait_components(app, window.components)
    window.close()


def test_config_page_saves_without_starting_service(app, tmp_path):
    path = tmp_path / 'lan_config.toml'
    path.write_text('workspace="."\nport=9000\npassword="example-only"\n', encoding='utf-8')
    window = DesktopWindow(path)
    page = window.config_page
    assert not page.dirty(), 'CRLF must not appear as an unsaved edit'
    page.raw.setPlainText('workspace="."\nport=9001\npassword="example-only"\n')
    assert page.save()
    assert '9001' in path.read_text()
    assert not window.services['Share'].snapshot()['running']
    wait_components(app, window.components)
    window.close()


def test_invalid_form_keeps_text_and_blocks_save(app, tmp_path):
    path = tmp_path / 'lan_config.toml'
    path.write_text('workspace="."\nport=9000\n', encoding='utf-8')
    window = DesktopWindow(path)
    page = window.config_page
    editor = page.editors['port']
    editor.setText('bad-port')
    editor.textEdited.emit('bad-port')
    assert not page.save()
    page.toggle_mode()
    assert page.form_mode
    assert editor.text() == 'bad-port'
    # Restore test-only input so close does not prompt.
    editor.setText('9000')
    editor.textEdited.emit('9000')
    page.updates.clear()
    wait_components(app, window.components)
    window.close()


def test_rescan_discovers_new_binary_without_starting(app, tmp_path, monkeypatch):
    from lan_codex_share.desktop import components_page, discovery
    monkeypatch.setattr(components_page, 'distribution_directory', lambda: tmp_path)
    monkeypatch.setattr(discovery.shutil, 'which', lambda _: None)
    window = DesktopWindow(tmp_path / 'lan_config.toml')
    page = window.components
    wait_components(app, page)
    assert page.executable('frpc') is None
    name = 'frpc.exe' if os.name == 'nt' else 'frpc'
    path = tmp_path / 'bin/frp/v1' / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b'not executed')
    path.chmod(0o755)
    page.rescan()
    wait_components(app, page)
    assert page.executable('frpc') == str(path.resolve())
    assert window.available['frpc']
    # executable() must not rescan during normal status or start checks.
    monkeypatch.setattr(components_page, 'discover', lambda *a, **kw: pytest.fail('unexpected scan'))
    assert page.executable('frpc') == str(path.resolve())
    assert all(not p.snapshot()['running'] for p in window.services.values())
    window.close()


def test_stale_manual_path_requires_selection_and_saves_relative(app, tmp_path, monkeypatch):
    from lan_codex_share.desktop import components_page, discovery
    from lan_codex_share.desktop.config import DesktopSettings
    monkeypatch.setattr(components_page, 'distribution_directory', lambda: tmp_path)
    monkeypatch.setattr(discovery.shutil, 'which', lambda _: None)
    settings = DesktopSettings(tmp_path / 'lan_config.toml')
    settings.save({'frpc_executable': 'missing/frpc.exe'})
    name = 'frpc.exe' if os.name == 'nt' else 'frpc'
    for version in ('v1', 'v2'):
        path = tmp_path / 'bin/frp' / version / name
        path.parent.mkdir(parents=True)
        path.write_bytes(b'not executed')
        path.chmod(0o755)
    window = DesktopWindow(tmp_path / 'lan_config.toml')
    page = window.components
    wait_components(app, page)
    assert page.executable('frpc') is None
    assert '失效' in page.labels['frpc'].text()
    assert settings.load()['frpc_executable'] == 'missing/frpc.exe'
    page.candidates['frpc'].setCurrentIndex(1)
    page.use_candidate('frpc')
    assert settings.load()['frpc_executable'].startswith('bin/frp/')
    selected = page.executable('frpc')
    page.rescan()
    wait_components(app, page)
    assert page.executable('frpc') == selected
    assert all(not p.snapshot()['running'] for p in window.services.values())
    window.close()


def test_ambiguous_or_incomplete_scan_requires_choice(app, tmp_path, monkeypatch):
    from lan_codex_share.desktop import components_page
    from lan_codex_share.desktop.discovery import Discovery
    name = 'frpc.exe' if os.name == 'nt' else 'frpc'
    files = []
    for sub in ('one', 'two'):
        path = tmp_path / sub / name
        path.parent.mkdir()
        path.write_bytes(b'not executed')
        path.chmod(0o755)
        files.append(path)
    monkeypatch.setattr(components_page, 'discover', lambda *a, **kw: Discovery(tuple(files)))
    window = DesktopWindow(tmp_path / 'lan_config.toml')
    page = window.components
    wait_components(app, page)
    assert page.executable('frpc') is None
    assert page.candidates['frpc'].count() == 3
    assert not page.candidate_buttons['frpc'].isEnabled()
    page.discoveries['frpc'] = Discovery((files[0],), incomplete=True)
    page.refresh()
    assert page.executable('frpc') is None
    assert '未完成' in page.labels['frpc'].text()
    page.candidates['frpc'].setCurrentIndex(1)
    page.use_candidate('frpc')
    assert page.executable('frpc') == str(files[0])
    window.close()


@pytest.mark.parametrize('outcome', ['installed', 'colocated', 'declined', 'denied'])
def test_frpc_download_uses_program_directory(app, tmp_path, monkeypatch, outcome):
    from lan_codex_share.desktop import components_page
    from lan_codex_share.desktop.config import DesktopSettings
    from lan_codex_share.desktop.discovery import Discovery
    from PySide6.QtWidgets import QMessageBox
    program = tmp_path / 'program'
    program.mkdir()
    config_dir = program if outcome == 'colocated' else tmp_path / 'config'
    cwd = tmp_path / 'unrelated-working-directory'
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    monkeypatch.setattr(components_page, 'distribution_directory', lambda: program)
    monkeypatch.setattr(components_page, 'discover', lambda *a, **kw: Discovery())
    release = {'tag_name': 'v1.2.3', 'assets': []}
    monkeypatch.setattr(components_page.installer, 'latest_release', lambda cancel: release)
    calls, dialogs = [], []

    def confirm(parent, title, text, *args):
        dialogs.append(text)
        return QMessageBox.No if outcome == 'declined' else QMessageBox.Yes

    def install(data, destination, cancel, progress):
        calls.append((data, destination))
        if outcome == 'denied':
            raise PermissionError('test-only')
        path = destination / '1.2.3' / ('frpc.exe' if os.name == 'nt' else 'frpc')
        path.parent.mkdir(parents=True)
        path.write_bytes(b'fake-never-executed')
        path.chmod(0o755)
        return path

    monkeypatch.setattr(components_page.QMessageBox, 'question', confirm)
    monkeypatch.setattr(components_page.installer, 'install_frpc', install)
    settings = DesktopSettings(config_dir / 'lan_config.toml')
    settings.save({'frpc_executable': 'old-frpc'})
    page = components_page.ComponentsPage(settings)
    wait_components(app, page)
    page.fetch_release()
    wait_components(app, page)
    destination = program / 'bin' / 'frp'
    assert len(dialogs) == 1
    assert str(destination) in dialogs[0]
    assert 'v1.2.3' in dialogs[0]
    if outcome == 'declined':
        assert not calls
    else:
        assert calls == [(release, destination)]
    saved = settings.load()['frpc_executable']
    if outcome in ('declined', 'denied'):
        assert saved == 'old-frpc'
        if outcome == 'denied':
            assert '目录' in page.message.text() and '权限' in page.message.text()
    else:
        assert settings.resolve(saved).parent == destination / '1.2.3'
        assert saved.startswith('bin/frp/') if outcome == 'colocated' else os.path.isabs(saved)
        assert '已安装并通过校验' in page.message.text()
    page.close()
