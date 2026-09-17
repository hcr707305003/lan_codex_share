import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

from lan_codex_share.lan_config import LanConfigError, load_lan_config


@pytest.mark.parametrize('raw, expected', [('', False), ('false', False), ('true', True)])
def test_notification_config(tmp_path, raw, expected):
    path = tmp_path / 'lan_config.toml'
    path.write_text('workspace = "."\n' + (f'notify_on_task_complete = {raw}\n' if raw else ''), encoding='utf-8')
    assert load_lan_config(path).notify_on_task_complete is expected


@pytest.mark.parametrize('raw', ['"false"', '0', '1', '[]'])
def test_invalid_notification_config(tmp_path, raw):
    path = tmp_path / 'lan_config.toml'
    path.write_text(f'workspace = "."\nnotify_on_task_complete = {raw}\n', encoding='utf-8')
    with pytest.raises(LanConfigError, match='notify_on_task_complete'):
        load_lan_config(path)


def test_desktop_notification_checkbox_roundtrip(tmp_path):
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication, QCheckBox
    from lan_codex_share.desktop.config import DesktopSettings
    from lan_codex_share.desktop.config_page import ConfigPage
    app = QApplication.instance() or QApplication([])
    path = tmp_path / 'lan_config.toml'
    original = 'workspace = "."\n# preserve me\nport = 9000\n'
    path.write_text(original, encoding='utf-8')
    page = ConfigPage(path, DesktopSettings(path))
    editor = page.editors['notify_on_task_complete']
    assert isinstance(editor, QCheckBox)
    assert not editor.isChecked()
    editor.setChecked(True)
    assert path.read_text(encoding='utf-8') == original
    page.save()
    assert load_lan_config(path).notify_on_task_complete
    assert '# preserve me' in path.read_text(encoding='utf-8')
    page.reload()
    assert page.editors['notify_on_task_complete'].isChecked()
    page.editors['notify_on_task_complete'].setChecked(False)
    page.save()
    assert not load_lan_config(path).notify_on_task_complete
    page.toggle_mode()
    page.raw.setPlainText(page.raw.toPlainText().replace('notify_on_task_complete = false', 'notify_on_task_complete = true'))
    page.toggle_mode()
    assert page.editors['notify_on_task_complete'].isChecked()
    page.close()


def test_failed_save_retains_notification_draft(tmp_path, monkeypatch):
    pytest.importorskip('PySide6')
    from PySide6.QtWidgets import QApplication
    from lan_codex_share.desktop.config import DesktopSettings
    from lan_codex_share.desktop.config_page import ConfigPage
    app = QApplication.instance() or QApplication([])
    path = tmp_path / 'lan_config.toml'
    path.write_text('workspace="."\n', encoding='utf-8')
    page = ConfigPage(path, DesktopSettings(path))
    page.editors['notify_on_task_complete'].setChecked(True)
    def fail(text):
        raise OSError('read only')
    monkeypatch.setattr(page.document, 'save', fail)
    saved=[]
    page.saved.connect(saved.append)
    page.save()
    assert not saved
    assert not load_lan_config(path).notify_on_task_complete
    assert page.editors['notify_on_task_complete'].isChecked()
    assert page.dirty()
    page.raw.setPlainText(page.baseline)
    page.updates.clear()
    page.close()
