from pathlib import Path

import pytest

pytest.importorskip("tomlkit")
from lan_codex_share.desktop.config import ConfigDocument, DesktopSettings


def test_external_edit_is_not_overwritten(tmp_path):
    p = tmp_path / "frpc.toml"
    p.write_text('serverAddr = "192.0.2.10"\n', encoding="utf-8")
    doc = ConfigDocument(p, "frp")
    text = doc.load()
    p.write_text('# external edit\n' + text, encoding="utf-8")
    with pytest.raises(ValueError, match="外部"):
        doc.save(text)


def test_preserves_comments_unknown_fields_and_other_proxies(tmp_path):
    doc = ConfigDocument(tmp_path / "frpc.toml", "frp")
    original = '# keep\nserverAddr = "192.0.2.10"\nextra = 42\n[[proxies]]\nname="one"\ntype="tcp"\nlocalPort=9000\nremotePort=20000\n[[proxies]]\nname="two"\ntype="tcp"\nlocalPort=9001\nremotePort=20001\n'
    result = doc.update_fields(original, {"proxies.localPort": 9999}, 1)
    assert '# keep' in result
    data = doc.parse(result)
    assert data['extra'] == 42
    assert data['proxies'][0]['localPort'] == 9000
    assert data['proxies'][1]['localPort'] == 9999


def test_invalid_save_preserves_file(tmp_path):
    p = tmp_path / 'frpc.toml'
    p.write_text('serverAddr="192.0.2.10"\n', encoding='utf-8')
    doc = ConfigDocument(p, 'frp')
    before = doc.load()
    with pytest.raises(ValueError):
        doc.save('serverAddr = "secret\n')
    assert p.read_bytes().decode('utf-8') == before


@pytest.mark.parametrize('text', ['a: 1\na: 2', '!!python/object:os.system {}'])
def test_yaml_rejects_duplicate_and_unsafe_tags(tmp_path, text):
    with pytest.raises(ValueError):
        ConfigDocument(tmp_path / 'config.yml', 'cf').parse(text)


def test_missing_session_key_stays_missing(tmp_path):
    doc = ConfigDocument(tmp_path / 'lan.toml', 'lan')
    text = doc.update_fields('workspace="."\n', {'port': 9000})
    assert 'session_ids' not in doc.parse(text)


def test_settings_resolve_relative_paths(tmp_path):
    settings = DesktopSettings(tmp_path / 'lan.toml')
    settings.save({'frpc_config': 'config/frpc.toml'})
    assert settings.resolve(settings.load()['frpc_config']) == tmp_path / 'config/frpc.toml'
