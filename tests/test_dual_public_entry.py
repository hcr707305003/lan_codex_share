import http.client
import json
from urllib.parse import quote

import pytest

from lan_codex_share.lan_access import AccessDenied, normalize_entry_origins, request_origin
from lan_codex_share.lan_config import LanConfigError, load_lan_config
from tests.test_lan_web import request, start_app
from tests.test_dynamic_proxy import origin_server


CF = 'https://codex.example.com'
FRP = 'http://192.0.2.10:20000'


@pytest.mark.parametrize('extra, expected', [
    ('', ()), ('cloudflare_origin = ""\nfrp_origin = ""', ()),
    (f'cloudflare_origin = "{CF}"', (CF,)), (f'frp_origin = "{FRP}"', (FRP,)),
    (f'cloudflare_origin = "{CF}"\nfrp_origin = "{FRP}"', (CF, FRP)),
    (f'public_origin = "{CF}"', (CF,)),
])
def test_config_independent_entries(tmp_path, extra, expected):
    path = tmp_path / 'config.toml'
    path.write_text('workspace = "."\npassword = "test-only"\n' + extra, encoding='utf-8')
    assert load_lan_config(path).public_origins == expected


@pytest.mark.parametrize('extra', [
    f'public_origin = "{CF}"\nfrp_origin = "{FRP}"',
    'public_origin = ""\ncloudflare_origin = ""',
    'cloudflare_origin = 12', 'frp_origin = []',
    f'cloudflare_origin = "{FRP}"',
    'cloudflare_origin = "https://192.0.2.10:20000"\nfrp_origin = "http://192.0.2.10:20000"',
])
def test_invalid_or_mixed_entry_config_rejected(tmp_path, extra):
    path = tmp_path / 'config.toml'
    path.write_text('workspace = "."\npassword = "test-only"\n' + extra, encoding='utf-8')
    with pytest.raises(LanConfigError):
        load_lan_config(path)


def test_host_selection_checks_all_entries_before_rejecting_port():
    entries = normalize_entry_origins('', 'https://codex.example.com', 'https://codex.example.com:8443')
    assert request_origin('codex.example.com:8443', set(), entries) == entries[1]
    assert request_origin('codex.example.com:443', set(), entries) == entries[0]
    with pytest.raises(AccessDenied):
        request_origin('codex.example.com:9000', {'codex.example.com'}, entries)


@pytest.mark.parametrize('cloudflare, frp', [('', ''), (CF, ''), ('', FRP), (CF, FRP)])
def test_only_configured_entries_are_accepted(tmp_path, cloudflare, frp):
    app, _, server, worker = start_app(tmp_path, password='test-only', cloudflare_origin=cloudflare, frp_origin=frp)
    try:
        assert request(server, 'GET', '/api/auth/status')[0] == 200
        for host, enabled in [('codex.example.com', cloudflare), ('192.0.2.10:20000', frp)]:
            assert request(server, 'GET', '/api/auth/status', headers={'Host': host})[0] == (200 if enabled else 403)
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        worker.join(2)


def test_dual_entries_cannot_enable_http_without_password(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text(f'workspace = "."\ncloudflare_origin = "{CF}"\nfrp_origin = "{FRP}"', encoding='utf-8')
    with pytest.raises(LanConfigError, match='password'):
        load_lan_config(path)
    with pytest.raises(ValueError, match='password'):
        start_app(tmp_path, cloudflare_origin=CF, frp_origin=FRP)


def test_both_entries_use_one_server_and_their_own_security_context(tmp_path):
    app, service, server, worker = start_app(tmp_path, password='test-only', cloudflare_origin=CF, frp_origin=FRP)
    document = tmp_path / 'shared.txt'
    document.write_text('shared file', encoding='utf-8')
    try:
        assert request(server, 'GET', '/')[0] == 200  # LAN remains usable
        with origin_server() as upstream:
            for entry, host, secure in [(CF, 'codex.example.com', True), (FRP, '192.0.2.10:20000', False)]:
                headers = {'Host': host, 'Origin': entry, 'Content-Type': 'application/json', 'X-CSRF-Token': app.csrf_token}
                assert request(server, 'GET', '/api/snapshot', headers=headers)[0] == 401
                status, response_headers, _ = request(server, 'POST', '/api/auth/login', b'{"password":"test-only"}', headers)
                assert status == 200
                cookie = dict(response_headers)['Set-Cookie']
                assert ('; Secure' in cookie) is secure
                headers['Cookie'] = cookie.split(';', 1)[0]
                assert request(server, 'GET', '/api/files/download?path=' + quote(str(document)), headers=headers)[2] == b'shared file'
                assert request(server, 'POST', '/api/messages', b'{"text":"entry test"}', headers)[0] == 202
                other = FRP if secure else CF
                assert request(server, 'POST', '/api/messages', b'{"text":"cross origin"}', {**headers, 'Origin': other})[0] == 403
                route = f'/proxy/localhost:{upstream.server_port}/data'
                assert request(server, 'POST', route, b'proxy', headers)[0] == 200
                assert upstream.seen[-1][2]['X-Forwarded-Proto'] == ('https' if secure else 'http')
                assert request(server, 'POST', route, b'cross origin', {**headers, 'Origin': other})[0] == 403
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
                try:
                    connection.request('GET', '/api/events?mode=delta', headers=headers)
                    response = connection.getresponse()
                    assert response.status == 200
                    assert response.fp.readline() == b'event: snapshot\n'
                    assert json.loads(response.fp.readline()[6:])['snapshot']['thread_id'] == 'thread-web'
                finally:
                    connection.close()
        assert len(service.submitted) == 2
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        worker.join(2)
