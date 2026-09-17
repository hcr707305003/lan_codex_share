import tomllib

import pytest
import yaml

from lan_codex_share.desktop.tunnel_port_sync import prepare_port_sync


FRP = '''# keep configuration
serverAddr = "203.0.113.10"
serverPort = 7000
auth.token = "example-only"
[[proxies]]
name = "stable-name"
type = "tcp"
localIP = "127.0.0.1"
localPort = 9000 # keep port comment
remotePort = 20000
'''
CF = '''# keep configuration
tunnel: sample
credentials-file: ./sample.json
ingress:
  - hostname: example.invalid
    service: http://localhost:9000/ # keep port comment
  - service: http_status:404
'''


@pytest.mark.parametrize('kind,text', [('frp', FRP), ('cf', CF)])
def test_sync_preserves_other_fields_and_comments(tmp_path, kind, text):
    path = tmp_path / 'config'
    path.write_text(text, encoding='utf-8')
    proposal = prepare_port_sync(path, kind, 9000, 9100)
    assert path.read_text(encoding='utf-8') == text  # preparation is read-only
    assert proposal.apply() == 1
    result = path.read_text(encoding='utf-8')
    assert '# keep configuration' in result and '# keep port comment' in result
    parse = tomllib.loads if kind == 'frp' else yaml.safe_load
    before, after = parse(text), parse(result)
    if kind == 'frp':
        before['proxies'][0]['localPort'] = 9100
    else:
        before['ingress'][0]['service'] = 'http://localhost:9100/'
    assert after == before


@pytest.mark.parametrize('change', [
    ('type = "tcp"', 'type = "udp"'),
    ('127.0.0.1', '192.0.2.5'),
    ('localPort = 9000', 'localPort = 9001'),
    ('remotePort = 20000', 'remotePort = 20000\nplugin.type = "http_proxy"'),
])
def test_frp_unrelated_proxies_untouched(tmp_path, change):
    path = tmp_path / 'frpc.toml'
    text = FRP.replace(*change)
    path.write_text(text, encoding='utf-8')
    with pytest.raises(ValueError, match='未找到'):
        prepare_port_sync(path, 'frp', 9000, 9100)
    assert path.read_text(encoding='utf-8') == text


@pytest.mark.parametrize('url', ['https://localhost:9000/', 'http://example.invalid:9000/',
                                  'http://localhost:9001/', 'http://user@localhost:9000/',
                                  'http://localhost:9000/?a=1', 'http://localhost:9000/#x'])
def test_cf_unrelated_services_untouched(tmp_path, url):
    path = tmp_path / 'cloudflared.yml'
    path.write_text(CF.replace('http://localhost:9000/', url), encoding='utf-8')
    with pytest.raises(ValueError, match='未找到'):
        prepare_port_sync(path, 'cf', 9000, 9100)


@pytest.mark.parametrize('url,old,expected', [('http://[::1]:9000/path', 9000, 'http://[::1]:9100/path'),
                                           ('http://localhost:', 80, 'http://localhost:9100'),
                                           ('http://127.0.0.1', 80, 'http://127.0.0.1:9100')])
def test_cf_ipv6_and_implicit_http_port(tmp_path, url, old, expected):
    path = tmp_path / 'cloudflared.yml'
    path.write_text(CF.replace('http://localhost:9000/', '"' + url + '"'), encoding='utf-8')
    prepare_port_sync(path, 'cf', old, 9100).apply()
    assert yaml.safe_load(path.read_text())['ingress'][0]['service'] == expected


@pytest.mark.parametrize('kind,text', [('frp', FRP), ('cf', CF)])
def test_external_edit_is_not_overwritten(tmp_path, kind, text):
    path = tmp_path / 'config'
    path.write_text(text, encoding='utf-8')
    proposal = prepare_port_sync(path, kind, 9000, 9100)
    path.write_text(text + '# external edit\n', encoding='utf-8')
    with pytest.raises(ValueError, match='外部修改'):
        proposal.apply()
    assert path.read_text(encoding='utf-8') == text + '# external edit\n'


def test_multiple_matching_rules_only(tmp_path):
    path = tmp_path / 'frpc.toml'
    proxy = FRP[FRP.index('[[proxies]]'):]
    path.write_text(FRP + proxy.replace('stable-name', 'second') + proxy.replace('9000', '9001'), encoding='utf-8')
    assert prepare_port_sync(path, 'frp', 9000, 9100).apply() == 2
    assert [p['localPort'] for p in tomllib.loads(path.read_text())['proxies']] == [9100, 9100, 9001]


def test_yaml_alias_is_not_rewritten(tmp_path):
    path = tmp_path / 'cloudflared.yml'
    path.write_text(CF.replace('service: http://', 'service: &origin http://') + 'other: *origin\n', encoding='utf-8')
    with pytest.raises(ValueError, match='锚点'):
        prepare_port_sync(path, 'cf', 9000, 9100)


def test_yaml_multiple_rules_and_crlf_comments(tmp_path):
    path = tmp_path / 'cloudflared.yml'
    text = CF.replace('  - service: http_status:404',
                      '  - path: /second/*\n    service: "http://127.0.0.1:9000" # second\n'
                      '  - service: http://localhost:9101\n  - service: http_status:404').replace('\n', '\r\n')
    path.write_bytes(text.encode('utf-8'))
    assert prepare_port_sync(path, 'cf', 9000, 9100).apply() == 2
    result = path.read_bytes().decode('utf-8')
    assert '# second\r\n' in result
    assert result.count('\r\n') == text.count('\r\n')
    rules = yaml.safe_load(result)['ingress']
    assert [r['service'] for r in rules] == ['http://localhost:9100/', 'http://127.0.0.1:9100',
                                           'http://localhost:9101', 'http_status:404']
