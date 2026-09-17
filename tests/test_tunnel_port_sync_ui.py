import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import tomllib

import pytest
pytest.importorskip('PySide6')
import yaml
from PySide6.QtWidgets import QApplication

from lan_codex_share.desktop import config_page as page_module
from lan_codex_share.desktop.config import DesktopSettings
from tests.test_tunnel_port_sync import FRP, CF


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app, tmp_path):
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\nport=9000\n', encoding='utf-8')
    (tmp_path / 'frpc.toml').write_text(FRP, encoding='utf-8')
    (tmp_path / 'cloudflared.yml').write_text(CF, encoding='utf-8')
    widget = page_module.ConfigPage(lan, DesktopSettings(lan))
    yield widget
    widget.close()


def change_port(page, port=9100):
    if page.form_mode:
        page.toggle_mode()
    page.raw.setPlainText(page.raw.toPlainText().replace('port=9000', f'port={port}'))


@pytest.mark.parametrize('form', [True, False])
def test_save_syncs_both_tunnels(page, form):
    signals = []
    page.tunnel_port_synced.connect(signals.append)
    if form:
        page.field_changed('port', 'int', '9100')
    else:
        change_port(page)
    assert page.save()
    root = page.lan_path.parent
    assert tomllib.loads((root / 'frpc.toml').read_text())['proxies'][0]['localPort'] == 9100
    assert yaml.safe_load((root / 'cloudflared.yml').read_text())['ingress'][0]['service'] == 'http://localhost:9100/'
    assert signals == ['frp', 'cf']
    assert '手动重启' in page.message.text()
    assert page.save()
    assert signals == ['frp', 'cf']  # unchanged port must not rewrite either file


@pytest.mark.parametrize('failure', ['missing', 'invalid', 'unrelated', 'conflict', 'denied'])
def test_frp_failure_does_not_block_share_or_cf(page, monkeypatch, failure):
    frp = page.lan_path.parent / 'frpc.toml'
    if failure == 'missing':
        frp.unlink()
    elif failure == 'invalid':
        frp.write_text('auth.token = "private-incomplete', encoding='utf-8')
    elif failure == 'unrelated':
        frp.write_text(FRP.replace('9000', '9001'), encoding='utf-8')
    elif failure == 'conflict':
        original = page.document.save
        def save(text):
            original(text)
            frp.write_text(FRP + '# external edit\n', encoding='utf-8')
        monkeypatch.setattr(page.document, 'save', save)
    elif failure == 'denied':
        original = page_module.prepare_port_sync
        def prepare(path, kind, *ports):
            proposal = original(path, kind, *ports)
            if kind == 'frp':
                def denied(_):
                    raise PermissionError('private-path-must-not-leak')
                proposal.document.save = denied
            return proposal
        monkeypatch.setattr(page_module, 'prepare_port_sync', prepare)
    change_port(page)
    assert page.save()
    assert tomllib.loads(page.lan_path.read_text())['port'] == 9100
    assert 'FRP 未同步' in page.message.text()
    assert 'Cloudflare 已同步' in page.message.text()
    assert 'private' not in page.message.text()
    if failure == 'conflict':
        assert frp.read_text(encoding='utf-8') == FRP + '# external edit\n'


def test_invalid_share_writes_neither_tunnel(page):
    change_port(page, 4500)  # collision with App Server
    assert not page.save()
    assert (page.lan_path.parent / 'frpc.toml').read_text(encoding='utf-8') == FRP
    assert (page.lan_path.parent / 'cloudflared.yml').read_text(encoding='utf-8') == CF


def test_token_mode_does_not_write_yaml(page):
    page.settings.save({'cloudflared_mode': 'token-file'})
    change_port(page)
    assert page.save()
    assert (page.lan_path.parent / 'cloudflared.yml').read_text(encoding='utf-8') == CF
    assert 'Cloudflare 控制台' in page.message.text()


@pytest.mark.parametrize('same_path', [True, False])
def test_save_copy_never_syncs(page, monkeypatch, same_path):
    target = page.lan_path if same_path else page.lan_path.with_name('copy.toml')
    monkeypatch.setattr(page_module.QFileDialog, 'getSaveFileName', lambda *a: (str(target), ''))
    change_port(page)
    page.save_copy()
    assert tomllib.loads(target.read_text())['port'] == 9100
    assert (page.lan_path.parent / 'frpc.toml').read_text(encoding='utf-8') == FRP
    assert (page.lan_path.parent / 'cloudflared.yml').read_text(encoding='utf-8') == CF


def test_custom_paths(page):
    root = page.lan_path.parent
    (root / 'another.toml').write_text(FRP, encoding='utf-8')
    (root / 'another.yml').write_text(CF, encoding='utf-8')
    page.settings.save({'frpc_config': 'another.toml', 'cloudflared_config': 'another.yml'})
    change_port(page)
    assert page.save()
    assert '9100' in (root / 'another.toml').read_text()
    assert '9100' in (root / 'another.yml').read_text()
    assert (root / 'frpc.toml').read_text(encoding='utf-8') == FRP
    assert (root / 'cloudflared.yml').read_text(encoding='utf-8') == CF


def test_default_port_matches_runtime(page):
    root = page.lan_path.parent
    page.lan_path.write_text('workspace="."\n', encoding='utf-8')
    (root / 'frpc.toml').write_text(FRP.replace('9000', '8765'), encoding='utf-8')
    page.load_path(page.lan_path)
    page.toggle_mode()
    page.raw.setPlainText('workspace="."\nport=9100\n')
    assert page.save()
    assert '9100' in (root / 'frpc.toml').read_text()


def test_cf_missing_does_not_block_frp(page):
    (page.lan_path.parent / 'cloudflared.yml').unlink()
    change_port(page)
    assert page.save()
    assert 'FRP 已同步' in page.message.text()
    assert 'Cloudflare 未同步' in page.message.text()


@pytest.mark.parametrize('change', ['path', 'mode', 'share'])
def test_changed_configuration_during_save_is_not_overwritten(page, monkeypatch, change):
    original = page.document.save
    root = page.lan_path.parent
    def save(text):
        original(text)
        if change == 'path':
            page.settings.save({'cloudflared_config': 'other.yml'})
        elif change == 'mode':
            page.settings.save({'cloudflared_mode': 'token-file'})
        else:
            page.lan_path.write_text(text + '# changed externally\n', encoding='utf-8')
    monkeypatch.setattr(page.document, 'save', save)
    change_port(page)
    assert page.save()
    assert 'Cloudflare 未同步' in page.message.text()
    assert (root / 'cloudflared.yml').read_text(encoding='utf-8') == CF
    if change == 'share':
        assert (root / 'frpc.toml').read_text(encoding='utf-8') == FRP


def test_new_configuration_does_not_guess_old_port(app, tmp_path):
    lan = tmp_path / 'new.toml'
    (tmp_path / 'frpc.toml').write_text(FRP, encoding='utf-8')
    widget = page_module.ConfigPage(lan, DesktopSettings(lan))
    widget.raw.setPlainText('workspace="."\nport=9100\n')
    assert widget.save()
    assert (tmp_path / 'frpc.toml').read_text(encoding='utf-8') == FRP
    widget.close()
