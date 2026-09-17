import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop.directory_list import DirectoryListEditor
from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop.config_page import ConfigPage
from lan_codex_share.lan_config import load_lan_config


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_directory_selection_remove_and_cancel(app, tmp_path, monkeypatch):
    folder = tmp_path / '中文 project'
    folder.mkdir()
    editor = DirectoryListEditor([], tmp_path)
    changes = []
    editor.changed.connect(lambda values: changes.append(values))
    editor.add_path(str(folder))
    assert editor.values() == ['中文 project']
    editor.add_path(str(folder / '.'))
    assert len(changes) == 1
    from lan_codex_share.desktop import directory_list
    monkeypatch.setattr(directory_list.QFileDialog, 'getExistingDirectory', lambda *args: '')
    editor.add_directory()
    assert len(changes) == 1
    editor.list.setCurrentRow(0)
    editor.remove_selected()
    assert editor.values() == []
    assert folder.is_dir()
    assert changes[-1] == []


def test_existing_strings_preserved_absolute_fallback(app, tmp_path, monkeypatch):
    editor = DirectoryListEditor(['../unchanged', './other'], tmp_path)
    assert editor.values() == ['../unchanged', './other']
    folder = tmp_path / 'cross-drive'
    folder.mkdir()
    from lan_codex_share.desktop import directory_list
    monkeypatch.setattr(directory_list.os.path, 'relpath', lambda *args: (_ for _ in ()).throw(ValueError()))
    editor.add_path(folder)
    assert editor.values()[-1] == folder.as_posix()


@pytest.mark.parametrize('value', ['bad', [42], None])
def test_invalid_list_rejected(app, tmp_path, value):
    with pytest.raises(ValueError):
        DirectoryListEditor(value, tmp_path)


def test_form_roundtrip(app, tmp_path):
    folder = tmp_path / 'frontend'
    folder.mkdir()
    path = tmp_path / 'lan_config.toml'
    text = 'workspace="."\n# keep\npreview_roots = []\n'
    path.write_text(text, encoding='utf-8')
    page = ConfigPage(path, DesktopSettings(path))
    page.editors['preview_roots'].add_path(folder)
    assert path.read_text(encoding='utf-8') == text
    page.save()
    assert load_lan_config(path).preview_roots == (folder.resolve(),)
    page.reload()
    assert page.editors['preview_roots'].values() == ['frontend']
    page.editors['preview_roots'].list.setCurrentRow(0)
    page.editors['preview_roots'].remove_selected()
    page.save()
    assert load_lan_config(path).preview_roots == ()
    assert folder.is_dir()
    assert '# keep' in path.read_text(encoding='utf-8')
    page.close()
