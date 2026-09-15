import re

from tests.test_lan_web import request, start_app


def test_fingerprint_content_change_and_cache_boundaries(tmp_path):
    app, service, server, worker = start_app(tmp_path, password='test')
    try:
        status, headers, body = request(server, 'GET', '/')
        assert status == 200
        assert dict(headers)['Cache-Control'] == 'no-store'
        paths = re.findall(rb'(?:src|href)="(/assets/[^"]+)"', body)
        assert len(paths) == 4
        for path in paths:
            status, headers, asset = request(server, 'GET', path.decode())
            assert status == 200
            assert len([key for key, _ in headers if key.lower() == 'cache-control']) == 1
            headers = dict(headers)
            assert headers['Cache-Control'] == 'public, max-age=31536000, immutable'
            assert 'Set-Cookie' not in headers
            etag = headers['ETag']
            assert request(server, 'GET', path.decode(), headers={'If-None-Match': etag})[0] == 304
            assert request(server, 'HEAD', path.decode())[2] == b''
        for path in ['/app.js', '/style.css', '/history.js', '/api/auth/status', '/api/snapshot', '/proxy-client.js']:
            assert dict(request(server, 'GET', path)[1])['Cache-Control'] == 'no-store'
        assert request(server, 'GET', '/assets/app.invalid.js')[0] == 404
    finally:
        server.shutdown(); server.server_close(); worker.join(2)


def test_modified_files_get_new_urls_and_old_url_never_serves_new_content(tmp_path):
    from lan_codex_share.static_assets import StaticAssets
    (tmp_path / 'app.js').write_text('original', encoding='utf-8')
    assets = StaticAssets(tmp_path, names=('app.js',))
    old = assets.url('app.js')
    (tmp_path / 'app.js').write_text('changed content', encoding='utf-8')
    new = assets.url('app.js')
    assert new != old
    assert assets.get(old).body == b'original'
    assert assets.get(new).body == b'changed content'
    assert assets.get('/assets/../app.js') is None
    assert assets.url('app.js') == new
