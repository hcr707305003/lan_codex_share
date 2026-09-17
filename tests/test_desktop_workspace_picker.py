import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop import workspace_picker
from lan_codex_share.desktop.workspace_picker import WorkspacePicker
from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop.config_page import ConfigPage
from lan_codex_share.lan_config import load_lan_config


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_select_cancel_and_same_directory(app, tmp_path, monkeypatch):
    picker = WorkspacePicker('./', tmp_path)
    changes = []
    picker.changed.connect(changes.append)
    assert picker.path.isReadOnly()
    starts = []
    choice = ''
    def choose(*args):
        starts.append(args[2])
        return choice
    monkeypatch.setattr(workspace_picker.QFileDialog, 'getExistingDirectory', choose)
    picker.choose_directory()
    choice = str(tmp_path)
    picker.choose_directory()
    assert changes == []
    assert picker.text() == './'
    folder = tmp_path / '中文 project'
    folder.mkdir()
    choice = str(folder)
    picker.choose_directory()
    assert picker.text() == '中文 project'
    assert changes == ['中文 project']
    picker.choose_directory()
    assert starts[-1] == str(folder)
    assert changes == ['中文 project']


def test_invalid_directory_and_start_fallback(app, tmp_path, monkeypatch):
    picker = WorkspacePicker('missing', tmp_path)
    starts = []
    def choose(*args):
        starts.append(args[2])
        return str(tmp_path / 'still-missing')
    monkeypatch.setattr(workspace_picker.QFileDialog, 'getExistingDirectory', choose)
    picker.choose_directory()
    assert starts == [str(tmp_path)]
    assert picker.text() == 'missing'
    assert picker.feedback.text()


def test_cross_drive_and_cwd_independence(app, tmp_path, monkeypatch):
    folder = tmp_path / 'other-drive'
    folder.mkdir()
    monkeypatch.chdir(folder)
    picker = WorkspacePicker('.', tmp_path)
    monkeypatch.setattr(workspace_picker.QFileDialog, 'getExistingDirectory', lambda *args: str(folder))
    def cross_drive(*args):
        raise ValueError()
    monkeypatch.setattr(workspace_picker.os.path, 'relpath', cross_drive)
    picker.choose_directory()
    assert picker.text() == folder.as_posix()


def test_form_saves_only_on_request_and_raw_roundtrip(app, tmp_path, monkeypatch):
    folder = tmp_path / 'selected'
    folder.mkdir()
    path = tmp_path / 'lan_config.toml'
    original = 'workspace="."\n# keep\n'
    path.write_text(original, encoding='utf-8')
    page = ConfigPage(path, DesktopSettings(path))
    picker = page.editors['workspace']
    monkeypatch.setattr(workspace_picker.QFileDialog, 'getExistingDirectory', lambda *args: str(folder))
    picker.browse.click()
    assert page.dirty()
    assert path.read_text(encoding='utf-8') == original
    assert page.save()
    assert load_lan_config(path).workspace == folder
    assert '# keep' in path.read_text(encoding='utf-8')
    assert not page.dirty()
    page.toggle_mode()
    page.raw.setPlainText('workspace="."\n')
    page.toggle_mode()
    assert page.editors['workspace'].text() == '.'
    assert page.save()
    assert load_lan_config(path).workspace == tmp_path
    page.close()


def test_external_edit_preserves_draft(app, tmp_path, monkeypatch):
    folder = tmp_path / 'chosen'
    folder.mkdir()
    path = tmp_path / 'lan_config.toml'
    path.write_text('workspace="."\n', encoding='utf-8')
    page = ConfigPage(path, DesktopSettings(path))
    monkeypatch.setattr(workspace_picker.QFileDialog, 'getExistingDirectory', lambda *args: str(folder))
    page.editors['workspace'].choose_directory()
    path.write_text('workspace="."\nport=9999\n', encoding='utf-8')
    assert not page.save()
    assert page.editors['workspace'].text() == 'chosen'
    assert page.dirty()
    assert 'port=9999' in path.read_text(encoding='utf-8')
    page.close()
