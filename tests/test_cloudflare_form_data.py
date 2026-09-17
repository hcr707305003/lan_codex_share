import pytest
import yaml

from lan_codex_share.desktop.cloudflare_form_data import form_data, update_fields


YAML = '''# local tunnel
tunnel: existing-name # tunnel comment
credentials-file: './old.json'
metrics: localhost:20241
ingress:
  - hostname: share.example.com # domain comment
    service: http://localhost:9000 # origin comment
    originRequest:
      connectTimeout: 30s
  - hostname: other.example.com
    path: /api/*
    service: http://localhost:13333
  - service: http_status:404
'''


def test_edit_preserves_other_fields_and_comments():
    changed = update_fields(YAML, {'tunnel': 'new-name', 'hostname': 'new.example.com',
                                  'credentials-file': r'C:\Tunnel files\credentials.json'}, 0)
    before, after = yaml.safe_load(YAML), yaml.safe_load(changed)
    before['tunnel'] = 'new-name'
    before['credentials-file'] = r'C:\Tunnel files\credentials.json'
    before['ingress'][0]['hostname'] = 'new.example.com'
    assert after == before
    for comment in ('# local tunnel', '# tunnel comment', '# domain comment', '# origin comment'):
        assert comment in changed


def test_noop_and_selected_rule_only():
    assert update_fields(YAML, {}, 0) == YAML
    assert [index for index, _ in form_data(YAML)[1]] == [0, 1]
    changed = update_fields(YAML, {'service': 'http://127.0.0.1:9100'}, 1)
    data = yaml.safe_load(changed)
    assert data['ingress'][0]['service'] == 'http://localhost:9000'
    assert data['ingress'][1]['service'] == 'http://127.0.0.1:9100'
    assert data['ingress'][1]['path'] == '/api/*'


def test_missing_top_field_inserted_before_document_end():
    text = YAML.replace("credentials-file: './old.json'\n", '') + '...\n'
    changed = update_fields(text, {'credentials-file': './new.json'}, 0)
    assert yaml.safe_load(changed)['credentials-file'] == './new.json'
    assert changed.endswith('...\n')


@pytest.mark.parametrize('key,value', [('tunnel', ''), ('hostname', 'https://example.com'),
                                      ('hostname', 'example.com/path'), ('hostname', 'bad name'),
                                      ('credentials-file', ''), ('service', 'file:///tmp/data'),
                                      ('service', 'http://user:secret@localhost:9000'),
                                      ('service', 'http://localhost:99999'), ('service', 'http://localhost:0'),
                                      ('service', 'http://localhost:9000/?secret=value')])
def test_invalid_value_rejected_without_echoing_secret(key, value):
    with pytest.raises(ValueError) as exc:
        update_fields(YAML, {key: value}, 0)
    assert value not in str(exc.value) if value else True


@pytest.mark.parametrize('text', ['tunnel: [', YAML + 'tunnel: duplicate\n',
                                 YAML.replace('existing-name', '&tunnel existing-name'),
                                 'tunnel: name\ningress:\n  - service: http_status:404\n'])
def test_complex_or_invalid_yaml_uses_advanced_mode(text):
    with pytest.raises(ValueError):
        form_data(text)


def test_unicode_crlf_and_quoted_hostname():
    text = YAML.replace('share.example.com', '"旧域名.example.com"').replace('\n', '\r\n')
    changed = update_fields(text, {'hostname': '新域名.example.com'}, 0)
    assert yaml.safe_load(changed)['ingress'][0]['hostname'] == '新域名.example.com'
    assert changed.count('\r\n') == text.count('\r\n')


def test_wrong_rule_or_key_rejected():
    with pytest.raises(ValueError):
        update_fields(YAML, {'service': 'http://localhost:9000'}, 2)
    with pytest.raises(ValueError):
        update_fields(YAML, {'token': 'secret'}, 0)
