import tomllib

import pytest

from lan_codex_share.desktop import origin_sync as sync


def frp(**proxy):
    return {'serverAddr': '203.0.113.10', 'serverPort': 7000,
            'proxies': [{'type': 'tcp', 'localIP': '127.0.0.1', 'localPort': 9000, 'remotePort': 20000, **proxy}]}


def cf(**rule):
    return {'tunnel': 'example', 'ingress': [{'hostname': 'share.example.invalid',
             'service': 'http://localhost:9000', **rule}, {'service': 'http_status:404'}]}


@pytest.fixture
def lan(tmp_path):
    path = tmp_path / 'lan_config.toml'
    path.write_text('# Keep comment\nworkspace="."\nport=9000\npassword="example-only"\n'
                    'session_ids=[]\npermission_mode="workspace-write"\ncustom="keep"\n', encoding='utf-8')
    return path


def test_frp_save_derives_business_port_and_preserves_other_fields(lan):
    proposal = sync.prepare_sync(lan, 'frp', frp())
    assert proposal.candidates == ('http://203.0.113.10:20000',)
    assert not proposal.needs_choice
    assert proposal.apply(proposal.candidates[0])
    text = lan.read_text(encoding='utf-8')
    data = tomllib.loads(text)
    assert data['frp_origin'] == proposal.candidates[0]
    assert data['session_ids'] == [] and data['custom'] == 'keep'
    assert data['permission_mode'] == 'workspace-write'
    assert '# Keep comment' in text


@pytest.mark.parametrize('proxy', [dict(type='udp'), dict(localIP='192.168.1.240'), dict(localPort=9001),
                                 dict(remotePort=0), dict(remotePort=True), dict(plugin={'type': 'http_proxy'}),
                                 dict(localIP='localhost.evil.invalid')])
def test_unrelated_frp_mappings_excluded(lan, proxy):
    assert not sync.prepare_sync(lan, 'frp', frp(**proxy)).candidates


@pytest.mark.parametrize('address', ['2001:db8::1', 'frps.example.invalid', 'not-an-ip'])
def test_unsupported_public_host_not_guessed(lan, address):
    data = frp()
    data['serverAddr'] = address
    proposal = sync.prepare_sync(lan, 'frp', data)
    assert not proposal.candidates and 'IPv4' in proposal.reason


def test_loopback_ipv6_upstream_and_multiple_candidates(lan):
    data = frp(localIP='::1')
    data['proxies'] += [dict(data['proxies'][0]), {**data['proxies'][0], 'remotePort': 20001}]
    proposal = sync.prepare_sync(lan, 'frp', data)
    assert len(proposal.candidates) == 2 and proposal.needs_choice
    with pytest.raises(ValueError):
        proposal.apply('http://203.0.113.10:7000')


def test_cloudflare_exact_rule_and_token_mode(lan):
    proposal = sync.prepare_sync(lan, 'cf', cf(service='http://[::1]:9000'))
    assert proposal.candidates == ('https://share.example.invalid',)
    assert proposal.apply(proposal.candidates[0])
    token = sync.prepare_sync(lan, 'cf', cf(), mode='token-file')
    assert not token.candidates and 'Token' in token.reason


@pytest.mark.parametrize('rule', [dict(hostname='*.example.invalid'), dict(path='/api'),
                                dict(service='http_status:404'), dict(service='http://localhost:9001'),
                                dict(service='http://192.168.1.240:9000'), dict(service='https://localhost:9000'),
                                dict(service='http://user:test-secret@localhost:9000'),
                                dict(service='http://localhost:9000/path'), dict(hostname='127.0.0.1'),
                                dict(hostname='example.invalid:8443'), dict(hostname='example.invalid/')])
def test_cloudflare_unreliable_rule_excluded(lan, rule):
    proposal = sync.prepare_sync(lan, 'cf', cf(**rule))
    assert not proposal.candidates
    assert 'test-secret' not in repr(proposal)


def test_conflicting_entry_requires_choice_but_preparation_never_writes(lan):
    with lan.open('a', encoding='utf-8') as stream:
        stream.write('frp_origin="http://203.0.113.20:20000"\n')
    before = lan.read_bytes()
    proposal = sync.prepare_sync(lan, 'frp', frp())
    assert proposal.needs_choice
    assert proposal.current == 'http://203.0.113.20:20000'
    assert lan.read_bytes() == before


def test_same_entry_never_rewrites(lan, monkeypatch):
    proposal = sync.prepare_sync(lan, 'frp', frp())
    proposal.apply(proposal.candidates[0])
    proposal = sync.prepare_sync(lan, 'frp', frp())
    monkeypatch.setattr(proposal.document, 'save', lambda _: pytest.fail('unnecessary write'))
    assert not proposal.apply(proposal.candidates[0])


def test_equivalent_existing_url_keeps_original_quotes_and_comment(lan, monkeypatch):
    with lan.open('a', encoding='utf-8') as stream:
        stream.write("frp_origin='http://203.0.113.10:20000/' # Keep style\n")
    before = lan.read_bytes()
    proposal = sync.prepare_sync(lan, 'frp', frp())
    monkeypatch.setattr(proposal.document, 'save', lambda _: pytest.fail('equivalent URL rewritten'))
    assert not proposal.apply(proposal.candidates[0])
    assert lan.read_bytes() == before


@pytest.mark.parametrize('legacy,kind', [('https://old.example.invalid', 'frp'), ('http://203.0.113.20:20000', 'cf')])
def test_legacy_other_entry_is_preserved(lan, legacy, kind):
    with lan.open('a', encoding='utf-8') as stream:
        stream.write(f'public_origin="{legacy}"\n')
    proposal = sync.prepare_sync(lan, kind, frp() if kind == 'frp' else cf())
    assert not proposal.needs_choice
    proposal.apply(proposal.candidates[0])
    data = tomllib.loads(lan.read_text(encoding='utf-8'))
    assert 'public_origin' not in data
    assert data['cloudflare_origin' if kind == 'frp' else 'frp_origin'] == legacy


def test_legacy_same_entry_conflict_needs_confirmation(lan):
    with lan.open('a', encoding='utf-8') as stream:
        stream.write('public_origin="https://old.example.invalid"\n')
    proposal = sync.prepare_sync(lan, 'cf', cf())
    assert proposal.needs_choice and proposal.current == 'https://old.example.invalid'


def test_legacy_scheme_is_normalized_before_migration(lan):
    with lan.open('a', encoding='utf-8') as stream:
        stream.write('public_origin=" HTTPS://OLD.EXAMPLE.INVALID:443/ "\n')
    proposal = sync.prepare_sync(lan, 'frp', frp())
    proposal.apply(proposal.candidates[0])
    data = tomllib.loads(lan.read_text(encoding='utf-8'))
    assert data['cloudflare_origin'] == 'https://old.example.invalid'
    assert data['frp_origin'] == 'http://203.0.113.10:20000'


def test_password_validation_preserves_original(lan):
    lan.write_text('workspace="."\nport=9000\npassword=""\n', encoding='utf-8')
    before = lan.read_bytes()
    proposal = sync.prepare_sync(lan, 'frp', frp())
    with pytest.raises(ValueError, match='密码'):
        proposal.apply(proposal.candidates[0])
    assert lan.read_bytes() == before


def test_concurrent_edit_and_write_denied_preserve_original(lan, monkeypatch):
    proposal = sync.prepare_sync(lan, 'frp', frp())
    with lan.open('a', encoding='utf-8') as stream:
        stream.write('# other editor\n')
    before = lan.read_bytes()
    with pytest.raises(ValueError, match='修改'):
        proposal.apply(proposal.candidates[0])
    assert lan.read_bytes() == before
    proposal = sync.prepare_sync(lan, 'frp', frp())
    def denied(_):
        raise PermissionError('test-only')
    monkeypatch.setattr(proposal.document, 'save', denied)
    with pytest.raises(PermissionError):
        proposal.apply(proposal.candidates[0])
    assert lan.read_bytes() == before
