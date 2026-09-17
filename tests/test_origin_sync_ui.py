import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import time
import tomllib

import pytest
pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QPushButton
from lan_codex_share.desktop import config_page as page_module
from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop.origin_sync import prepare_sync
from lan_codex_share.desktop.origin_dialog import OriginDialog

FRP = 'serverAddr="203.0.113.10"\nserverPort=7000\n[[proxies]]\ntype="tcp"\nlocalIP="127.0.0.1"\nlocalPort=9000\nremotePort=20000\n'
CF = 'tunnel: example\ningress:\n  - hostname: share.example.invalid\n    service: http://localhost:9000\n  - service: http_status:404\n'


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app, tmp_path, monkeypatch):
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\nport=9000\npassword="example-only"\n', encoding='utf-8')
    (tmp_path / 'frpc.toml').write_text(FRP, encoding='utf-8')
    (tmp_path / 'cloudflared.yml').write_text(CF, encoding='utf-8')
    monkeypatch.setattr(page_module, 'choose_origin', lambda *a: pytest.fail('unexpected conflict dialog'))
    widget = page_module.ConfigPage(lan, DesktopSettings(lan))
    widget.choose_kind('frp')
    yield widget
    widget.close()


@pytest.mark.parametrize('kind,field,expected', [('frp', 'frp_origin', 'http://203.0.113.10:20000'),
                                               ('cf', 'cloudflare_origin', 'https://share.example.invalid')])
def test_save_auto_syncs_entry(page, kind, field, expected):
    page.choose_kind(kind)
    signals = []
    page.origin_synced.connect(signals.append)
    assert page.save()
    assert tomllib.loads(page.lan_path.read_text(encoding='utf-8'))[field] == expected
    assert signals == [str(page.lan_path)]
    assert '已同步' in page.message.text()
    assert page.save()
    assert len(signals) == 1


@pytest.mark.parametrize('accept', [True, False])
def test_conflict_accept_or_skip_preserves_tunnel_save(page, monkeypatch, accept):
    with page.lan_path.open('a', encoding='utf-8') as stream:
        stream.write('frp_origin="http://203.0.113.20:20000"\n')
    def choose(parent, proposal):
        assert proposal.current == 'http://203.0.113.20:20000'
        return proposal.candidates[0] if accept else None
    monkeypatch.setattr(page_module, 'choose_origin', choose)
    assert page.save()
    result = tomllib.loads(page.lan_path.read_text(encoding='utf-8'))
    assert result['frp_origin'] == ('http://203.0.113.10:20000' if accept else 'http://203.0.113.20:20000')
    assert ('已同步' if accept else '未同步') in page.message.text()


def test_password_failure_reports_partial_success(page):
    page.lan_path.write_text('workspace="."\nport=9000\npassword=""\n', encoding='utf-8')
    assert page.save()  # The tunnel itself was saved successfully.
    assert '配置已保存' in page.message.text() and '入口未同步' in page.message.text()
    assert '密码' in page.message.text()
    assert 'frp_origin' not in tomllib.loads(page.lan_path.read_text(encoding='utf-8'))


def test_concurrent_lan_edit_during_choice_is_not_overwritten(page, monkeypatch):
    with page.lan_path.open('a', encoding='utf-8') as stream:
        stream.write('frp_origin="http://203.0.113.20:20000"\n')
    def choose(parent, proposal):
        with page.lan_path.open('a', encoding='utf-8') as stream:
            stream.write('# external edit\n')
        return proposal.candidates[0]
    monkeypatch.setattr(page_module, 'choose_origin', choose)
    assert page.save()
    assert '入口未同步' in page.message.text()
    assert '# external edit' in page.lan_path.read_text(encoding='utf-8')


def test_save_copy_does_not_sync(page, tmp_path, monkeypatch):
    before = page.lan_path.read_bytes()
    monkeypatch.setattr(page_module.QFileDialog, 'getSaveFileName', lambda *a: (str(tmp_path / 'copy.toml'), ''))
    page.save_copy()
    assert (tmp_path / 'copy.toml').exists()
    assert page.lan_path.read_bytes() == before


def test_save_copy_same_path_still_does_not_sync(page, monkeypatch):
    before = page.lan_path.read_bytes()
    monkeypatch.setattr(page_module.QFileDialog, 'getSaveFileName', lambda *a: (str(page.document.path), ''))
    page.save_copy()
    assert page.lan_path.read_bytes() == before


def test_actual_save_button_triggers_sync(page):
    button = next(b for b in page.findChildren(QPushButton) if b.text() == '校验并保存')
    button.click()
    assert 'frp_origin' in tomllib.loads(page.lan_path.read_text(encoding='utf-8'))


def test_source_changes_during_confirmation_skip_sync(page, monkeypatch):
    with page.lan_path.open('a', encoding='utf-8') as stream:
        stream.write('frp_origin="http://203.0.113.20:20000"\n')
    before = page.lan_path.read_bytes()
    def choose(parent, proposal):
        with page.document.path.open('a', encoding='utf-8') as stream:
            stream.write('# external tunnel edit\n')
        return proposal.candidates[0]
    monkeypatch.setattr(page_module, 'choose_origin', choose)
    assert page.save()
    assert '入口未同步' in page.message.text()
    assert page.lan_path.read_bytes() == before


def test_write_permission_failure_is_partial_success(page, monkeypatch):
    original = page_module.prepare_sync
    def prepare(*args, **kwargs):
        proposal = original(*args, **kwargs)
        def denied(_):
            raise PermissionError('must not leak private path')
        proposal.document.save = denied
        return proposal
    monkeypatch.setattr(page_module, 'prepare_sync', prepare)
    assert page.save()
    assert '入口未同步' in page.message.text() and '权限' in page.message.text()
    assert 'must not leak' not in page.message.text()


def test_no_candidates_and_token_mode_keep_existing_origin(page):
    page.choose_kind('cf')
    page.settings.save({'cloudflared_mode': 'token-file'})
    assert page.save()
    assert 'Token' in page.message.text() and '未同步' in page.message.text()
    assert 'cloudflare_origin' not in tomllib.loads(page.lan_path.read_text(encoding='utf-8'))


def test_dialog_cancel_default_and_explicit_selection(page, app):
    data = tomllib.loads(FRP)
    data['proxies'].append({**data['proxies'][0], 'remotePort': 20001})
    proposal = prepare_sync(page.lan_path, 'frp', data)
    dialog = OriginDialog(None, proposal)
    dialog.show()
    app.processEvents()
    assert dialog.cancel.isDefault()
    assert not dialog.confirm.isDefault()
    QTest.keyClick(dialog, Qt.Key_Return)
    assert dialog.result() == QDialog.Rejected
    dialog.show()
    dialog.candidates.setCurrentIndex(1)
    dialog.confirm.click()
    assert dialog.result() == QDialog.Accepted
    assert dialog.selected_origin() == proposal.candidates[1]


def test_success_refreshes_window_entry_and_marks_share_changed(app, tmp_path, monkeypatch):
    from lan_codex_share.desktop import window as window_module, external_monitor, tunnel_monitor
    from lan_codex_share.desktop.external_share import ExternalState
    from lan_codex_share.desktop.external_tunnels import TunnelState
    monkeypatch.setattr(external_monitor, 'inspect_share', lambda _: ExternalState('stopped', '已停止'))
    monkeypatch.setattr(tunnel_monitor, 'inspect_tunnels', lambda _: {n: TunnelState('stopped', '未发现外部运行实例') for n in ('frpc', 'Tunnel')})
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\nport=9000\npassword="example-only"\n', encoding='utf-8')
    (tmp_path / 'frpc.toml').write_text(FRP, encoding='utf-8')
    window = window_module.DesktopWindow(lan)
    window.config_page.choose_kind('frp')
    assert window.config_page.save()
    assert window.entries['frpc'].url == 'http://203.0.113.10:20000'
    assert 'Share' in window.changed_services
    (tmp_path / 'cloudflared.yml').write_text(CF, encoding='utf-8')
    window.config_page.choose_kind('lan')
    window.changed_services.clear()
    window.config_page.field_changed('port', 'int', '9100')
    assert window.config_page.save()
    assert {'Share', 'frpc', 'Tunnel'} <= window.changed_services
    assert window.entries['Share'].url == 'http://localhost:9100'
    deadline = time.monotonic() + 5
    while (window.components.busy or window.external.scanning or window.tunnels.scanning) and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.005)
    window.close()
