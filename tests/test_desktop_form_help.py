import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QLabel
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop.config_page import ConfigPage, FIELDS, TEMPLATES
from lan_codex_share.desktop.theme import apply_theme


def settle(app):
    for _ in range(8):
        app.processEvents()


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('kind', ['lan', 'frp', 'cf'])
def test_all_fields_have_visible_static_help_without_changing_data(app, tmp_path, kind):
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\nport=9000\npassword="sample-private-value"\n', encoding='utf-8')
    (tmp_path / 'frpc.toml').write_text(TEMPLATES['frp'], encoding='utf-8')
    (tmp_path / 'cloudflared.yml').write_text(TEMPLATES['cf'], encoding='utf-8')
    page = ConfigPage(lan, DesktopSettings(lan))
    page.choose_kind(kind)
    page.show()
    app.processEvents()
    editors = page.cf_form.fields if kind == 'cf' else page.editors
    keys = set(editors) if kind == 'cf' else {key for key, _, _ in FIELDS[kind]}
    notes = {label.property('help_key'): label for label in page.findChildren(QLabel)
             if label.property('help_key')}
    assert keys <= notes.keys()
    for key in keys:
        assert notes[key].isVisible()
        assert notes[key].wordWrap()
        assert editors[key].accessibleDescription()
        assert len(notes[key].text()) > len(key) + 8
        assert 'sample-private-value' not in notes[key].text()
    assert not page.dirty()
    page.toggle_mode()
    assert not page.form_mode
    assert all(not notes[key].isVisible() for key in keys)
    page.close()


@pytest.mark.parametrize('kind', ['lan', 'frp', 'cf'])
def test_help_uses_full_field_width_and_wraps_without_clipping(app, tmp_path, kind):
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\nport=9000\n', encoding='utf-8')
    (tmp_path / 'frpc.toml').write_text(TEMPLATES['frp'], encoding='utf-8')
    (tmp_path / 'cloudflared.yml').write_text(TEMPLATES['cf'], encoding='utf-8')
    page = ConfigPage(lan, DesktopSettings(lan))
    page.choose_kind(kind)
    original_style = app.styleSheet()
    try:
        apply_theme(app, 'graphite')
        page.show()
        for width in (1050, 650, 900, 1050):
            page.resize(width, 720)
            for _ in range(5):
                app.processEvents()
            notes = [label for label in page.findChildren(QLabel) if label.property('help_key')]
            widest = max(label.width() for label in notes)
            for note in notes:
                key = note.property('help_key')
                assert note.width() >= widest - 2, (width, key, note.width(), widest)
                assert note.height() >= note.heightForWidth(note.width()), (
                    width, key, note.height(), note.heightForWidth(note.width()))
                assert note.parentWidget().rect().contains(note.geometry()), (width, key)
        assert not page.dirty()
    finally:
        page.close()
        app.setStyleSheet(original_style)


@pytest.mark.parametrize('width', [650, 1050])
def test_changing_session_scope_does_not_collapse_directory_editor(app, tmp_path, monkeypatch, width):
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\nsession_ids=["demo-one", "demo-two"]\n'
                   'preview_roots=["../frontend", "../backend", "../website", "../miniapp"]\n',
                   encoding='utf-8')
    original_style = app.styleSheet()
    apply_theme(app, 'graphite')
    page = ConfigPage(lan, DesktopSettings(lan))
    try:
        page.resize(width, 720)
        page.show()
        settle(app)
        scope = page.editors['session_ids']
        directories = page.editors['preview_roots']
        for mode in ('all', 'auto', 'selected', 'all'):
            scope.mode.setCurrentIndex(scope.mode.findData(mode))
            settle(app)
            page.form_area.verticalScrollBar().setValue(page.form_area.verticalScrollBar().maximum())
            settle(app)
            assert directories.height() >= directories.minimumSizeHint().height()
            assert directories.add.y() > directories.list.geometry().bottom()
            assert directories.add.height() >= directories.add.minimumSizeHint().height()
            for child in (directories.list, directories.add, directories.remove):
                assert directories.rect().contains(child.geometry())
            for note in page.findChildren(QLabel):
                if note.property('help_key') or note.parentWidget() is directories:
                    assert note.height() >= note.heightForWidth(note.width())
                    assert note.parentWidget().rect().contains(note.geometry())
            field = directories.parentWidget()
            following = page.editors['cloudflare_origin'].parentWidget()
            assert field.geometry().bottom() < following.y()

        # Exercise the actual buttons without opening a native picker or touching real config.
        folder = tmp_path / 'extra-preview'
        folder.mkdir()
        from lan_codex_share.desktop.directory_list import QFileDialog
        monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *args: str(folder))
        page.form_area.ensureWidgetVisible(directories.add)
        QTest.mouseClick(directories.add, Qt.LeftButton)
        settle(app)
        assert directories.values()[-1] == 'extra-preview'
        assert directories.remove.isEnabled()
        QTest.mouseClick(directories.remove, Qt.LeftButton)
        settle(app)
        assert directories.values() == ['../frontend', '../backend', '../website', '../miniapp']
        assert folder.is_dir()
        assert 'extra-preview' not in lan.read_text(encoding='utf-8')
        # Rebuild the form through advanced mode, then revisit the same scroll position.
        page.mode.click()
        page.mode.click()
        settle(app)
        directories = page.editors['preview_roots']
        page.form_area.ensureWidgetVisible(directories.remove)
        settle(app)
        assert directories.add.y() > directories.list.geometry().bottom()
        assert directories.rect().contains(directories.remove.geometry())
    finally:
        page.close()
        app.setStyleSheet(original_style)
