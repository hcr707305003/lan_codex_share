import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop.config_page import ConfigPage, TEMPLATES


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize('kind', ['lan', 'frp'])
def test_advanced_edit_roundtrip(app, tmp_path, kind):
    path = tmp_path / 'lan_config.toml'
    path.write_text('workspace="."\n# keep\ncustom="original"\n', encoding='utf-8')
    settings = DesktopSettings(path)
    frp_path = settings.resolve(settings.load()['frpc_config'])
    frp_path.write_text(TEMPLATES['frp'] + '\n# keep\ncustom="original"\n', encoding='utf-8')
    page = ConfigPage(path, settings)
    if kind == 'frp':
        page.choose_kind('frp')
    target = path if kind == 'lan' else frp_path
    original = target.read_text(encoding='utf-8')
    assert page.mode.text() == '高级文件编辑'
    page.mode.click()
    assert not page.form_mode
    assert page.mode.text() == '返回表单编辑'
    assert not page.raw.isReadOnly()
    page.raw.setPlainText(original.replace('original', 'advanced'))
    assert target.read_text(encoding='utf-8') == original
    assert page.dirty()
    page.mode.click()
    assert page.form_mode
    assert page.save(sync_entries=False)
    assert 'custom="advanced"' in target.read_text(encoding='utf-8')
    assert '# keep' in target.read_text(encoding='utf-8')
    page.close()


def test_invalid_raw_is_retained_and_not_saved(app, tmp_path):
    path = tmp_path / 'lan_config.toml'
    original = 'workspace="."\n'
    path.write_text(original, encoding='utf-8')
    page = ConfigPage(path, DesktopSettings(path))
    page.mode.click()
    page.raw.setPlainText('workspace = [')
    page.mode.click()
    assert not page.form_mode
    assert not page.save()
    assert page.raw.toPlainText() == 'workspace = ['
    assert path.read_text(encoding='utf-8') == original
    page.close()
