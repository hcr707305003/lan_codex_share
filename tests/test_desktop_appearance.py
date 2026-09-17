import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop.theme import THEMES, normalize_theme, apply_theme


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('value', ['', 'missing', 42, [], None])
def test_theme_fallback(value):
    assert normalize_theme(value) == 'graphite'


@pytest.mark.parametrize('theme_id', ['graphite', 'forest', 'midnight', 'lavender'])
def test_theme_palette(app, theme_id):
    from PySide6.QtGui import QPalette
    assert apply_theme(app, theme_id) == theme_id
    assert app.property('theme_id') == theme_id
    assert app.palette().color(QPalette.Window).name().lower() == THEMES[theme_id].colors['bg'].lower()


def test_same_theme_does_not_repolish_application(app, monkeypatch):
    apply_theme(app, 'graphite')
    monkeypatch.setattr(app, 'setStyleSheet', lambda *_: pytest.fail('unchanged theme must not repolish'))
    assert apply_theme(app, 'graphite') == 'graphite'


@pytest.mark.parametrize('raw', ['theme=42', 'theme=[]', 'theme="unknown"'])
def test_invalid_persisted_theme_does_not_block_settings(tmp_path, raw):
    settings = DesktopSettings(tmp_path / 'lan_config.toml')
    settings.path.write_text(raw + '\nfrpc_config="my-frpc.toml"\n', encoding='utf-8')
    assert settings.load()['theme'] == 'graphite'
    assert settings.load()['frpc_config'] == 'my-frpc.toml'


def test_theme_write_preserves_other_settings(tmp_path):
    settings = DesktopSettings(tmp_path / 'lan_config.toml')
    settings.path.write_text('# keep this comment\nfrpc_executable="bin/frpc"\nfuture=true\n', encoding='utf-8')
    settings.save({'theme': 'forest'})
    assert settings.load()['theme'] == 'forest'
    assert settings.load()['frpc_executable'] == 'bin/frpc'
    assert '# keep this comment' in settings.path.read_text()
    assert 'future=true' in settings.path.read_text()


def luminance(hex_color):
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
    return sum(a * b for a, b in zip(linear, [.2126, .7152, .0722]))


@pytest.mark.parametrize('theme_id', ['graphite', 'forest', 'midnight', 'lavender'])
def test_text_contrast(theme_id):
    colors = THEMES[theme_id].colors
    pairs = [('text', 'bg'), ('muted', 'bg'), ('text', 'card'), ('muted', 'card'),
             ('on_accent', 'accent'), ('danger', 'danger_bg'), ('success', 'card'), ('warning', 'card')]
    for fg, bg in pairs:
        light, dark = sorted([luminance(colors[fg]), luminance(colors[bg])], reverse=True)
        assert (light + .05) / (dark + .05) >= 4.5, (theme_id, fg, bg)


def test_appearance_saves_before_apply(app, tmp_path, monkeypatch):
    from lan_codex_share.desktop.appearance import AppearanceDialog
    settings = DesktopSettings(tmp_path / 'lan_config.toml')
    apply_theme(app, 'graphite')
    dialog = AppearanceDialog(settings)
    assert dialog.select_theme('midnight')
    assert settings.load()['theme'] == 'midnight'
    assert app.property('theme_id') == 'midnight'
    before = settings.path.read_bytes()
    def deny(*args):
        raise PermissionError('test only')
    monkeypatch.setattr(settings, 'save', deny)
    assert not dialog.select_theme('forest')
    assert app.property('theme_id') == 'midnight'
    assert dialog.theme_buttons['midnight'].isChecked()
    assert not dialog.theme_buttons['forest'].isChecked()
    assert settings.path.read_bytes() == before
    assert '失败' in dialog.message.text()
    dialog.close()


@pytest.mark.parametrize('key', ['return', 'escape'])
def test_common_question_defaults_to_cancel(app, key):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QDialog
    from lan_codex_share.desktop.messages import MessageDialog
    dialog = MessageDialog(None, '未保存修改', '<b>plain text</b>', question=True)
    dialog.show()
    app.processEvents()
    assert dialog.body.textFormat() == Qt.PlainText
    assert dialog.cancel.isDefault()
    assert not dialog.confirm.isDefault()
    QTest.keyClick(dialog, Qt.Key_Return if key == 'return' else Qt.Key_Escape)
    assert dialog.result() == QDialog.Rejected
    assert not dialog.isVisible()


def test_window_theme_switch_preserves_drafts_and_services(app, tmp_path, monkeypatch):
    from lan_codex_share.desktop.window import DesktopWindow
    from lan_codex_share.desktop.appearance import AppearanceDialog
    from lan_codex_share.desktop.external_monitor import ExternalShareMonitor
    from lan_codex_share.desktop.tunnel_monitor import ExternalTunnelMonitor
    from lan_codex_share.desktop.components_page import ComponentsPage
    from lan_codex_share.desktop.process import ServiceProcess
    monkeypatch.setattr(ExternalShareMonitor, 'start', lambda self: None)
    monkeypatch.setattr(ExternalTunnelMonitor, 'start', lambda self: None)
    monkeypatch.setattr(ComponentsPage, 'rescan', lambda self: None)
    monkeypatch.setattr(ServiceProcess, 'start', lambda *args, **kwargs: pytest.fail('theme must not start service'))
    config = tmp_path / 'lan_config.toml'
    config.write_text('workspace="."\nport=9000\n', encoding='utf-8')
    settings = DesktopSettings(config)
    settings.save({'theme': 'forest'})
    window = DesktopWindow(config)
    assert app.property('theme_id') == 'forest'
    window.timer.stop()
    window.config_page.raw.setPlainText('workspace="."\nport=9002\n')
    draft = window.config_page.raw.toPlainText()
    window.logs.add('Client', 'test-only-log')
    log_rows = window.logs.filtered()
    changed = set(window.changed_services)
    dialog = AppearanceDialog(settings, window)
    for theme in THEMES:
        assert dialog.select_theme(theme)
        assert window.config_page.raw.toPlainText() == draft
        assert window.logs.filtered() == log_rows
        assert window.changed_services == changed
        assert all(not service.snapshot()['running'] for service in window.services.values())
    dialog.close()
    window.resize(900, 640)
    window.show()
    for index in range(4):
        window.navigate(index)
        app.processEvents()
        assert window.width() == 900
        assert window.stack.currentIndex() == index
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QPushButton
    window.navigate(1)
    if not window.config_page.form_mode:
        window.config_page.toggle_mode()
    app.processEvents()
    save = next(b for b in window.config_page.findChildren(QPushButton) if b.text() == '校验并保存')
    assert save.mapTo(window, QPoint(0, save.height())).y() <= window.height() - window.statusBar().height()
    assert window.config_page.form_area.verticalScrollBar().maximum() > 0
    window.config_page.raw.setPlainText(window.config_page.baseline)
    window.close()
    again = DesktopWindow(config)
    assert app.property('theme_id') == 'lavender'
    again.close()
