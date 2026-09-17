import http.client
import json
from urllib.parse import quote

import pytest

from lan_codex_share.lan_access import AccessDenied, normalize_public_origin, request_origin
from lan_codex_share.lan_config import LanConfigError, load_lan_config
from lan_codex_share.lan_web import LanRequestHandler
from tests.test_lan_web import request, start_app
from tests.test_dynamic_proxy import origin_server


ORIGIN = 'http://192.0.2.10:20000'


def test_http_ipv4_origin_and_default_port():
    assert normalize_public_origin(ORIGIN + '/') == ORIGIN
    assert normalize_public_origin('http://192.0.2.10:80') == 'http://192.0.2.10'
    assert request_origin('192.0.2.10:80', set(), 'http://192.0.2.10') == 'http://192.0.2.10'
    assert request_origin('192.0.2.10:20000', set(), ORIGIN) == ORIGIN
    for host in ['192.0.2.10', '192.0.2.10:20001', 'user@192.0.2.10:20000', '192.0.2.10:020000']:
        with pytest.raises(AccessDenied):
            request_origin(host, set(), ORIGIN)


@pytest.mark.parametrize('value', [
    'http://example.com:20000', 'http://192.000.2.10:20000', 'http://999.2.3.4:20000',
    'http://[::1]:20000', 'ftp://192.0.2.10:20000', 'http://192.0.2.10:0',
    'http://192.0.2.10:65536', ORIGIN + '/path', ORIGIN + '?a=1', ORIGIN + '#x',
    'http://user@192.0.2.10:20000',
])
def test_invalid_http_entry_rejected(value):
    with pytest.raises(ValueError):
        normalize_public_origin(value)


@pytest.mark.parametrize('password', ['', '   '])
def test_http_requires_password_in_config_and_application(tmp_path, password):
    path = tmp_path / 'config.toml'
    path.write_text(f'workspace = "."\npublic_origin = "{ORIGIN}"\npassword = "{password}"\n', encoding='utf-8')
    with pytest.raises(LanConfigError, match='password'):
        load_lan_config(path)
    with pytest.raises(ValueError, match='password'):
        start_app(tmp_path, password=password, public_origin=ORIGIN)


def test_http_config_can_load(tmp_path):
    path = tmp_path / 'config.toml'
    path.write_text(f'workspace = "."\npublic_origin = "{ORIGIN}"\npassword = "test-only"\n', encoding='utf-8')
    assert load_lan_config(path).public_origin == ORIGIN


def test_frp_entry_auth_csrf_files_and_sse(tmp_path):
    app, service, server, worker = start_app(tmp_path, password='test-only', public_origin=ORIGIN)
    headers = {'Host': '192.0.2.10:20000', 'Origin': ORIGIN, 'Content-Type': 'application/json',
               'X-CSRF-Token': app.csrf_token}
    connection = None
    try:
        assert request(server, 'GET', '/', headers=headers)[0] == 200
        assert request(server, 'GET', '/api/snapshot', headers=headers)[0] == 401
        for changes in [{'Host': '192.0.2.10:20001'}, {'Origin': 'https://192.0.2.10:20000'}, {'X-CSRF-Token': 'wrong'}]:
            assert request(server, 'POST', '/api/auth/login', b'{"password":"test-only"}', {**headers, **changes})[0] == 403
        status, response_headers, _ = request(server, 'POST', '/api/auth/login', b'{"password":"test-only"}', headers)
        assert status == 200
        cookie = dict(response_headers)['Set-Cookie']
        assert '; Secure' not in cookie
        assert 'HttpOnly' in cookie and 'SameSite=Strict' in cookie and 'Max-Age=2592000' in cookie
        headers['Cookie'] = cookie.split(';', 1)[0]
        assert request(server, 'POST', '/api/messages', b'{"text":"via frp"}', headers)[0] == 202
        document = tmp_path / 'test.txt'
        document.write_text('file contents', encoding='utf-8')
        assert request(server, 'GET', '/api/files/download?path=' + quote(str(document)), headers=headers)[2] == b'file contents'
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=2)
        connection.request('GET', '/api/events?mode=delta', headers=headers)
        response = connection.getresponse()
        assert response.status == 200
        assert response.fp.readline() == b'event: snapshot\n'
        assert json.loads(response.fp.readline()[6:])['snapshot']['thread_id'] == 'thread-web'
        handler = object.__new__(LanRequestHandler)
        handler.server = server
        handler.headers = {**headers, 'X-Forwarded-For': '127.0.0.1', 'X-Forwarded-Proto': 'https'}
        for peer in ['192.168.1.20', '192.0.2.10']:
            handler.client_address = (peer, 12345)
            with pytest.raises(AccessDenied):
                handler._guard()
    finally:
        if connection:
            connection.close()
        server.stopping.set()
        server.shutdown()
        server.server_close()
        worker.join(2)


def test_frp_single_entry_proxies_multiple_services(tmp_path):
    app, _, server, worker = start_app(tmp_path, password='test-only', public_origin=ORIGIN)
    headers = {'Host': '192.0.2.10:20000', 'Origin': ORIGIN}
    try:
        with origin_server() as front, origin_server() as back:
            for upstream in (front, back):
                route = f'/proxy/localhost:{upstream.server_port}'
                assert request(server, 'GET', route + '/page', headers=headers)[0] == 401
                authorized = {**headers, 'Cookie': 'lan_codex_auth=' + app.authenticate('test-only', 'test')}
                status, _, body = request(server, 'GET', route + '/page', headers=authorized)
                assert status == 200 and (route + '/style.css').encode() in body
                assert request(server, 'POST', route + '/data', b'payload', authorized)[0] == 200
                assert upstream.seen[-1][3] == b'payload'
                assert upstream.seen[-1][2]['X-Forwarded-Proto'] == 'http'
                assert 'Cookie' not in upstream.seen[-1][2]
                assert request(server, 'POST', route + '/data', b'blocked', {**authorized, 'Origin': 'https://evil.example'})[0] == 403
    finally:
        server.stopping.set()
        server.shutdown()
        server.server_close()
        worker.join(2)
