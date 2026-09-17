import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tomllib

import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication, QPushButton
from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop.config_page import ConfigPage, TEMPLATES


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app, tmp_path):
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\nport=9100\n', encoding='utf-8')
    (tmp_path / 'frpc.toml').write_text(TEMPLATES['frp'] + '\n[[proxies]]\nname="other"\ntype="tcp"\n'
                                     'localIP="127.0.0.2"\nlocalPort=9200\nremotePort=20001\n', encoding='utf-8')
    widget = ConfigPage(lan, DesktopSettings(lan))
    widget.choose_kind('frp')
    yield widget
    widget.close()


def click_apply(page):
    buttons = [b for b in page.findChildren(QPushButton) if b.text() == '应用 Share 端口']
    assert len(buttons) == 1
    buttons[0].click()


def test_selected_proxy_draft_only_until_save(page):
    before = page.document.path.read_bytes()
    page.proxy.setCurrentIndex(1)
    click_apply(page)
    assert page.editors['proxies.localPort'].text() == '9100'
    assert page.document.path.read_bytes() == before
    assert page.dirty()
    page.proxy.setCurrentIndex(0)
    assert page.editors['proxies.localPort'].text() == '9000'
    assert page.save(sync_entries=False)
    data = tomllib.loads(before.decode('utf-8'))
    data['proxies'][1]['localPort'] = 9100
    assert tomllib.loads(page.document.path.read_text(encoding='utf-8')) == data


def test_reads_latest_saved_share_port_and_advanced_roundtrip(page):
    page.lan_path.write_text('workspace="."\nport=9300\n', encoding='utf-8')
    click_apply(page)
    assert page.editors['proxies.localPort'].text() == '9300'
    page.toggle_mode()
    assert 'localPort = 9300' in page.raw.toPlainText()
    page.toggle_mode()
    assert page.editors['proxies.localPort'].text() == '9300'


def test_same_port_is_not_a_new_edit(page):
    page.lan_path.write_text('workspace="."\nport=9000\n', encoding='utf-8')
    click_apply(page)
    assert not page.dirty()
    assert '一致' in page.message.text()


@pytest.mark.parametrize('content', [None, 'workspace="."\nport=0\n', 'password="private-incomplete',
                                    'workspace="missing-directory"\nport=9100\n'])
def test_bad_share_keeps_input_and_files(page, content):
    before = page.document.path.read_bytes()
    if content is None:
        page.lan_path.unlink()
    else:
        page.lan_path.write_text(content, encoding='utf-8')
    click_apply(page)
    assert page.editors['proxies.localPort'].text() == '9000'
    assert page.document.path.read_bytes() == before
    assert not page.dirty()
    assert 'Share 配置' in page.message.text()
    assert 'private' not in page.message.text()


def test_default_share_port_and_invalid_draft_replaced(page):
    page.lan_path.write_text('workspace="."\n', encoding='utf-8')
    editor = page.editors['proxies.localPort']
    editor.setText('invalid')
    page.field_changed('proxies.localPort', 'int', 'invalid')
    click_apply(page)
    assert editor.text() == '8765'
    assert not editor.property('invalid')
    assert page.save(sync_entries=False)
