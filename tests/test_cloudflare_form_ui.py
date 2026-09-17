import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
import yaml
from PySide6.QtWidgets import QApplication

from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop.config_page import ConfigPage
from lan_codex_share.desktop import cloudflare_form as cf_module
from tests.test_cloudflare_form_data import YAML


@pytest.fixture(scope='module')
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def page(app, tmp_path):
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\nport=9100\n', encoding='utf-8')
    (tmp_path / 'cloudflared.yml').write_text(YAML, encoding='utf-8')
    widget = ConfigPage(lan, DesktopSettings(lan))
    widget.choose_kind('cf')
    yield widget
    widget.close()


def edit(form, key, value):
    form.fields[key].setText(value)
    form.fields[key].textEdited.emit(value)


def test_load_defaults_to_form_without_modifying_file(page):
    assert page.form_mode
    assert page.mode.isEnabled()
    assert page.mode.text() == '高级文件编辑'
    assert page.cf_form.fields['hostname'].text() == 'share.example.com'
    assert page.cf_form.fields['service'].text() == 'http://localhost:9000'
    assert not page.dirty()
    assert page.document.path.read_text(encoding='utf-8') == YAML


def test_switch_rule_keeps_edits_and_only_save_writes(page):
    form = page.cf_form
    edit(form, 'hostname', 'edited.example.com')
    form.rules.setCurrentIndex(1)
    assert form.fields['hostname'].text() == 'other.example.com'
    edit(form, 'service', 'http://localhost:14444')
    assert page.document.path.read_text(encoding='utf-8') == YAML
    assert page.dirty()
    assert page.save(sync_entries=False)
    data = yaml.safe_load(page.document.path.read_text(encoding='utf-8'))
    assert data['ingress'][0]['hostname'] == 'edited.example.com'
    assert data['ingress'][1]['service'] == 'http://localhost:14444'
    assert data['ingress'][1]['path'] == '/api/*'
    assert not page.dirty()


def test_form_and_advanced_roundtrip(page):
    edit(page.cf_form, 'tunnel', 'new-name')
    page.toggle_mode()
    assert not page.form_mode
    assert 'new-name' in page.raw.toPlainText()
    page.raw.setPlainText(page.raw.toPlainText().replace('localhost:20241', 'localhost:20242'))
    page.toggle_mode()
    assert page.form_mode
    assert page.cf_form.fields['tunnel'].text() == 'new-name'
    assert page.save(sync_entries=False)
    text = page.document.path.read_text(encoding='utf-8')
    assert 'localhost:20242' in text and '# domain comment' in text


def test_invalid_form_preserves_input_and_selection(page):
    form = page.cf_form
    edit(form, 'hostname', 'https://bad.example.com')
    form.rules.setCurrentIndex(1)
    assert form.rules.currentIndex() == 0
    assert not page.save(sync_entries=False)
    assert form.fields['hostname'].text() == 'https://bad.example.com'
    assert form.fields['hostname'].property('invalid')
    assert page.document.path.read_text(encoding='utf-8') == YAML


def test_share_address_is_explicit_draft_change(page):
    page.cf_form.use_share.click()
    assert page.cf_form.fields['service'].text() == 'http://localhost:9100'
    assert page.document.path.read_text(encoding='utf-8') == YAML
    assert page.save(sync_entries=False)
    assert 'http://localhost:9100' in page.document.path.read_text(encoding='utf-8')


def test_credential_picker_cancel_and_choose(page, monkeypatch, tmp_path):
    form = page.cf_form
    monkeypatch.setattr(cf_module.QFileDialog, 'getOpenFileName', lambda *a: ('', ''))
    form.browse.click()
    assert form.fields['credentials-file'].text() == './old.json'
    assert not page.dirty()
    credential = tmp_path / 'my credentials.json'
    credential.write_text('contents never read', encoding='utf-8')
    monkeypatch.setattr(cf_module.QFileDialog, 'getOpenFileName', lambda *a: (str(credential), ''))
    form.browse.click()
    assert form.fields['credentials-file'].text() == credential.as_posix()
    assert page.dirty()
    assert page.document.path.read_text(encoding='utf-8') == YAML


def test_example_uses_share_port(page):
    page.document.path.unlink()
    page.load_path(page.document.path)
    page.create_example()
    assert page.form_mode
    assert page.cf_form.fields['service'].text() == 'http://localhost:9100'
    assert not page.document.path.exists()


def test_complex_yaml_retains_advanced_editor(page):
    text = YAML.replace('existing-name', '&name existing-name')
    page.document.path.write_text(text, encoding='utf-8')
    page.load_path(page.document.path)
    assert not page.form_mode
    assert page.mode.isEnabled()
    assert '锚点' in page.message.text()
    assert page.raw.toPlainText() == text


def test_token_mode_explains_local_only(page):
    page.settings.save({'cloudflared_mode': 'token-file'})
    page.load_path(page.document.path)
    assert page.form_mode
    assert 'Token' in page.cf_form.info.text()
    assert '远程' in page.cf_form.info.text()


def test_external_edit_does_not_get_overwritten(page):
    edit(page.cf_form, 'tunnel', 'new-name')
    page.document.path.write_text(YAML + '# external\n', encoding='utf-8')
    assert not page.save(sync_entries=False)
    assert '# external' in page.document.path.read_text(encoding='utf-8')
    assert page.dirty()


def test_save_copy_keeps_original_and_origin(page, monkeypatch, tmp_path):
    from lan_codex_share.desktop import config_page
    target = tmp_path / 'copy.yml'
    lan_before = page.lan_path.read_bytes()
    monkeypatch.setattr(config_page.QFileDialog, 'getSaveFileName', lambda *a: (str(target), ''))
    edit(page.cf_form, 'hostname', 'copy.example.com')
    page.save_copy()
    assert yaml.safe_load(target.read_text(encoding='utf-8'))['ingress'][0]['hostname'] == 'copy.example.com'
    assert page.document.path.read_text(encoding='utf-8') == YAML
    assert page.lan_path.read_bytes() == lan_before
    assert page.dirty()


def test_bad_raw_yaml_cannot_replace_form_or_file(page):
    page.toggle_mode()
    page.raw.setPlainText('tunnel: [')
    page.toggle_mode()
    assert not page.form_mode
    assert page.raw.toPlainText() == 'tunnel: ['
    assert not page.save(sync_entries=False)
    assert page.document.path.read_text(encoding='utf-8') == YAML
