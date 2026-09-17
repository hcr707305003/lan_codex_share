import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop.session_list import SessionListEditor, parse_session_input


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('text,expected', [
    (' a, b\na ', ['a', 'b']), ('[" a ", "b", "a"]', ['a', 'b']),
    ('', []), ('\n , ', []), ('session-custom-id', ['session-custom-id']),
])
def test_batch_parse(text, expected):
    assert parse_session_input(text) == expected


@pytest.mark.parametrize('text', ['["a", 1]', '["a",]', '["a", ""]', 'a b', '"a"', '{"id":"a"}'])
def test_invalid_batch(text):
    with pytest.raises(ValueError):
        parse_session_input(text)


@pytest.mark.parametrize('data,mode,values', [({}, 'auto', []), ({'session_ids': []}, 'all', []),
    ({'session_ids': ['a', 'b']}, 'selected', ['a', 'b']), ({'session_id': ' a '}, 'selected', ['a']),
    ({'session_id': ''}, 'auto', [])])
def test_load_preserves_original(app, data, mode, values):
    editor = SessionListEditor(data)
    assert editor.mode.currentData() == mode
    assert editor.values() == values
    assert not editor.dirty()
    assert editor.changes() == ({}, ())


@pytest.mark.parametrize('data', [{'session_ids': 'a'}, {'session_ids': [1]}, {'session_ids': ['']},
    {'session_id': 1}, {'session_id': 'a', 'session_ids': []}])
def test_bad_config(app, data):
    with pytest.raises(ValueError):
        SessionListEditor(data)


def test_add_atomic_dedup_and_copy(app, monkeypatch):
    editor = SessionListEditor({'session_id': 'a'})
    editor.input.setPlainText('["b", 1]')
    editor.add_input()
    assert editor.values() == ['a']
    assert editor.input.toPlainText() == '["b", 1]'
    with pytest.raises(ValueError):
        editor.changes()
    editor.input.setPlainText('a,b\nb,c')
    editor.add_input()
    assert editor.values() == ['a', 'b', 'c']
    assert editor.changes() == ({'session_ids': ['a', 'b', 'c']}, ('session_id',))
    copied = []
    class Clipboard:
        def setText(self, text):
            copied.append(text)
    monkeypatch.setattr(QApplication, 'clipboard', lambda: Clipboard())
    editor.list.setCurrentRow(1)
    editor.copy_selected()
    assert copied == ['b']


def test_modes_empty_guard_and_pending_input(app):
    editor = SessionListEditor({'session_ids': ['a']})
    editor.input.setPlainText('b')
    editor.mode.setCurrentIndex(editor.mode.findData('all'))
    assert editor.mode.currentData() == 'selected'
    assert editor.dirty()
    editor.input.clear()
    editor.list.setCurrentRow(0)
    editor.remove_selected()
    assert editor.mode.currentData() == 'selected'
    with pytest.raises(ValueError):
        editor.changes()
    editor.mode.setCurrentIndex(editor.mode.findData('all'))
    assert editor.changes() == ({'session_ids': []}, ('session_id',))
    editor.mode.setCurrentIndex(editor.mode.findData('auto'))
    assert editor.changes() == ({}, ('session_ids', 'session_id'))


def test_mode_switch_preserves_list_and_duplicate_does_not_migrate(app):
    editor = SessionListEditor({'session_id': 'a'})
    editor.input.setPlainText('a')
    editor.add_input()
    assert not editor.dirty()
    editor.mode.setCurrentIndex(editor.mode.findData('all'))
    editor.mode.setCurrentIndex(editor.mode.findData('selected'))
    assert editor.values() == ['a']
    editor.mark_applied()
    assert not editor.dirty()
