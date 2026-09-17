import pytest

from lan_codex_share.desktop.config import DesktopSettings
from lan_codex_share.desktop.entries import service_entries, safe_web_url


@pytest.mark.parametrize('url', ['file:///private.txt', 'javascript:alert(1)', 'ftp://example.invalid',
                               'https://user:secret@example.invalid', '//example.invalid', 'http://',
                               'https://example.invalid:bad', 'https://example.invalid/\nsecret'])
def test_unsafe_links_rejected(url):
    assert not safe_web_url(url)


def test_entries_use_configured_public_origins_and_not_control_port(tmp_path):
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\nport=9000\npassword="example-only"\n'
                   'cloudflare_origin="https://share.example.invalid"\nfrp_origin="http://203.0.113.10:20000"\n', encoding='utf-8')
    (tmp_path / 'frpc.toml').write_text('serverAddr="example.invalid"\nserverPort=7000\n'
                                      '[[proxies]]\ntype="tcp"\nlocalPort=9000\nremotePort=20000\n', encoding='utf-8')
    result = service_entries(lan, DesktopSettings(lan))
    assert result['Share'].url == 'http://localhost:9000'
    assert result['Tunnel'].url == 'https://share.example.invalid'
    assert result['frpc'].url == 'http://203.0.113.10:20000'
    assert '7000' in result['frpc'].text and '9000 → 20000' in result['frpc'].text
    assert 'example-only' not in repr(result)


def test_missing_configs_and_unconfigured_frp_do_not_invent_links(tmp_path):
    lan = tmp_path / 'lan_config.toml'
    result = service_entries(lan, DesktopSettings(lan))
    assert all(not e.url for e in result.values())
    lan.write_text('workspace="."\nport=9000\n', encoding='utf-8')
    (tmp_path / 'frpc.toml').write_text('serverAddr="example.invalid"\nserverPort=7000\n', encoding='utf-8')
    result = service_entries(lan, DesktopSettings(lan))
    assert result['Share'].url
    assert not result['frpc'].url
    assert not result['Tunnel'].url


def test_invalid_lan_rejects_links_and_frp_errors_hide_parser_secrets(tmp_path):
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\nport=9000\ncloudflare_origin="file:///secret"\n', encoding='utf-8')
    (tmp_path / 'frpc.toml').write_text('test-secret invalid config', encoding='utf-8')
    result = service_entries(lan, DesktopSettings(lan))
    assert not result['Tunnel'].url
    assert 'test-secret' not in repr(result)


def test_many_mappings_are_bounded(tmp_path):
    lan = tmp_path / 'lan_config.toml'
    (tmp_path / 'frpc.toml').write_text('serverAddr="example.invalid"\n' + ''.join(
        f'[[proxies]]\ntype="tcp"\nlocalPort={9000+i}\nremotePort={20000+i}\n' for i in range(30)), encoding='utf-8')
    entry = service_entries(lan, DesktopSettings(lan))['frpc']
    assert len(entry.text.splitlines()) <= 4
    assert '30' in entry.text
    assert '9000 → 20000' in entry.detail


def test_legacy_public_origin(tmp_path):
    lan = tmp_path / 'lan_config.toml'
    lan.write_text('workspace="."\npassword="example-only"\npublic_origin="https://share.example.invalid"\n', encoding='utf-8')
    entry = service_entries(lan, DesktopSettings(lan))['Tunnel']
    assert entry.url == 'https://share.example.invalid'
    assert '旧配置' in entry.detail
