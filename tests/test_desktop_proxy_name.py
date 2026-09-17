import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import re
from types import SimpleNamespace
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from lan_codex_share.desktop import proxy_name
from lan_codex_share.desktop.proxy_name import new_proxy_name
from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop.config_page import ConfigPage, TEMPLATES


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


def test_random_name_and_local_collision(monkeypatch):
    names = {new_proxy_name() for _ in range(100)}
    assert len(names) == 100
    assert all(re.fullmatch(r'codex-share-[0-9a-f]{32}', n) for n in names)
    candidates = iter(['old', 'new'])
    monkeypatch.setattr(proxy_name, 'uuid4', lambda: SimpleNamespace(hex=next(candidates)))
    assert new_proxy_name(['codex-share-old']) == 'codex-share-new'


def make_page(tmp_path, existing=None):
    path = tmp_path / 'lan_config.toml'
    path.write_text('workspace="."\n', encoding='utf-8')
    settings = DesktopSettings(path)
    frp_path = settings.resolve(settings.load()['frpc_config'])
    if existing is not None:
        frp_path.write_text(existing, encoding='utf-8')
    page = ConfigPage(path, settings)
    page.choose_kind('frp')
    return page, frp_path


def test_new_templates_different_and_save_stable(app, tmp_path, monkeypatch):
    page, path = make_page(tmp_path)
    page.create_example()
    first = page.editors['proxies.name'].text()
    assert first != 'codex-share'
    assert not path.exists()
    monkeypatch.setattr(page, 'discard', lambda: True)
    page.create_example()
    second = page.editors['proxies.name'].text()
    assert first != second
    assert page.save(sync_entries=False)
    page.reload()
    assert page.editors['proxies.name'].text() == second
    assert not page.dirty()
    page.close()


def test_only_selected_proxy_changes(app, tmp_path):
    original = TEMPLATES['frp'] + '\n[[proxies]]\nname="other"\ntype="tcp"\nlocalPort=9001\nremotePort=20001\n'
    page, path = make_page(tmp_path, original)
    assert page.editors['proxies.name'].text() == 'codex-share'
    assert not page.dirty()
    page.proxy.setCurrentIndex(1)
    editor = page.editors['proxies.name']
    editor.regenerate()
    name = editor.text()
    assert name != 'other'
    assert page.proxy.currentText() == name
    assert path.read_text(encoding='utf-8') == original
    page.proxy.setCurrentIndex(0)
    assert page.editors['proxies.name'].text() == 'codex-share'
    assert page.save(sync_entries=False)
    data = page.document.parse(path.read_text(encoding='utf-8'))
    assert [p['name'] for p in data['proxies']] == ['codex-share', name]
    page.close()


def test_cancel_reload_retains_generated_draft(app, tmp_path, monkeypatch):
    page, path = make_page(tmp_path, TEMPLATES['frp'])
    page.editors['proxies.name'].regenerate()
    name = page.editors['proxies.name'].text()
    monkeypatch.setattr(page, 'discard', lambda: False)
    page.reload()
    assert page.editors['proxies.name'].text() == name
    assert page.dirty()
    assert page.document.parse(path.read_text(encoding='utf-8'))['proxies'][0]['name'] == 'codex-share'
    page.close()
