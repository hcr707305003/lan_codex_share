import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop.config import ConfigDocument, DesktopSettings
from lan_codex_share.desktop.config_page import ConfigPage


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def make_page(tmp_path, session='session_id = "a"\n'):
    path = tmp_path / 'lan_config.toml'
    path.write_text('workspace="."\n# keep\ncustom="keep"\n' + session, encoding='utf-8')
    return ConfigPage(path, DesktopSettings(path)), path


@pytest.mark.parametrize('session', ['', 'session_ids=[]\n', 'session_ids=["a"]\n', 'session_id="a"\n'])
def test_unrelated_save_preserves_session(app, tmp_path, session):
    page, path = make_page(tmp_path, session)
    original = page.document.parse(path.read_text(encoding='utf-8'))
    page.field_changed('port', 'int', '9876')
    assert page.save()
    result = page.document.parse(path.read_text(encoding='utf-8'))
    for key in ('session_id', 'session_ids'):
        assert (key in result, result.get(key)) == (key in original, original.get(key))
    assert '# keep' in path.read_text(encoding='utf-8')
    assert result['custom'] == 'keep'
    assert not page.dirty()
    page.close()


def test_mode_roundtrips_and_legacy_migration(app, tmp_path):
    page, path = make_page(tmp_path)
    editor = page.editors['session_ids']
    original = path.read_text(encoding='utf-8')
    editor.input.setPlainText('b')
    editor.add_input()
    assert page.dirty()
    assert path.read_text(encoding='utf-8') == original
    assert page.save()
    assert page.document.parse(path.read_text(encoding='utf-8'))['session_ids'] == ['a', 'b']
    for mode, expected in [('all', []), ('auto', None), ('selected', ['a', 'b'])]:
        editor.mode.setCurrentIndex(editor.mode.findData(mode))
        assert page.save()
        data = page.document.parse(path.read_text(encoding='utf-8'))
        assert 'session_id' not in data
        assert data.get('session_ids') == expected
    page.toggle_mode()
    page.toggle_mode()
    assert page.editors['session_ids'].values() == ['a', 'b']
    assert not page.dirty()
    page.close()


def test_pending_draft_blocks_save_raw_and_reload_cancel(app, tmp_path, monkeypatch):
    page, path = make_page(tmp_path)
    original = path.read_text(encoding='utf-8')
    editor = page.editors['session_ids']
    editor.input.setPlainText('b')
    assert page.dirty()
    assert not page.save()
    page.toggle_mode()
    assert page.form_mode
    monkeypatch.setattr(page, 'discard', lambda: False)
    page.reload()
    assert editor.input.toPlainText() == 'b'
    assert path.read_text(encoding='utf-8') == original
    editor.input.clear()
    editor.list.setCurrentRow(0)
    editor.remove_selected()
    assert not page.save()
    assert path.read_text(encoding='utf-8') == original
    page.close()


def test_external_save_failure_preserves_list_and_dirty(app, tmp_path):
    page, path = make_page(tmp_path)
    editor = page.editors['session_ids']
    editor.input.setPlainText('b')
    editor.add_input()
    path.write_text('workspace="."\nport=9999\n', encoding='utf-8')
    assert not page.save()
    assert editor.values() == ['a', 'b']
    assert page.dirty()
    assert 'port=9999' in path.read_text(encoding='utf-8')
    page.close()


def test_explicit_top_level_removal(tmp_path):
    doc = ConfigDocument(tmp_path / 'lan.toml', 'lan')
    text = '# keep\nsession_id="a"\ncustom="yes"\n'
    result = doc.update_fields(text, {'session_ids': []}, remove_fields=('session_id',))
    data = doc.parse(result)
    assert 'session_id' not in data
    assert data['session_ids'] == []
    assert data['custom'] == 'yes'
    assert '# keep' in result
