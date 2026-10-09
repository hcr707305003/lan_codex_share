import json
from urllib.parse import urlencode

import pytest

from tests.test_lan_web import start_app, request
from tests.test_archive_reader import make_zip


@pytest.fixture
def archive_server(tmp_path):
    app, service, server, thread = start_app(tmp_path)
    yield app, service, server
    server.shutdown()
    server.server_close()
    thread.join(2)


def endpoint(path, action='list', **kwargs):
    return '/api/archives/' + action + '?' + urlencode({'path': str(path), **kwargs})


def test_archive_routes_and_version(tmp_path, archive_server):
    app, _, server = archive_server
    path = make_zip(tmp_path, [('企业/说明.md', '# hello')])
    status, _, data = request(server, 'GET', endpoint(path))
    assert status == 200
    listing = json.loads(data)
    assert listing['entries'][0]['directory']
    args = {'version': listing['version'], 'member': 0}
    status, _, data = request(server, 'GET', endpoint(path, 'preview', **args))
    assert status == 200 and json.loads(data)['content'] == '# hello'
    status, headers, data = request(server, 'GET', endpoint(path, 'download', **args))
    assert status == 200 and data == b'# hello'
    assert dict(headers)['Content-Disposition'].startswith('attachment;')
    assert dict(headers)['X-Content-Type-Options'] == 'nosniff'
    make_zip(tmp_path, [('b', 'changed')])
    assert request(server, 'GET', endpoint(path, 'preview', **args))[0] == 409
    assert request(server, 'GET', endpoint(path, 'preview', member=-1))[0] == 400
    assert request(server, 'GET', '/api/files/view?' + urlencode({'path': str(path)}))[0] == 200


def test_boundaries_and_broken_archive_download(tmp_path, archive_server):
    app, service, server = archive_server
    path = make_zip(tmp_path, [('a.txt', 'hi')])
    outside = tmp_path.parent / (tmp_path.name + '-other')
    outside.mkdir()
    denied = make_zip(outside, [('secret', 'no')])
    try:
        for action in ('list', 'preview', 'download'):
            assert request(server, 'GET', endpoint(denied, action, member=0, version='x'))[0] == 403
        service.preview_roots = [str(outside)]
        assert request(server, 'GET', endpoint(denied))[0] == 200
        service.preview_roots = []
        assert request(server, 'GET', endpoint(denied))[0] == 403
        path.write_bytes(b'broken')
        assert request(server, 'GET', endpoint(path))[0] == 400
        status, _, body = request(server, 'GET', '/api/files/download?' + urlencode({'path': str(path)}))
        assert status == 200 and body == b'broken'
    finally:
        denied.unlink()
        outside.rmdir()


def test_archive_requires_login(tmp_path):
    app, _, server, thread = start_app(tmp_path, password='test-only')
    try:
        for action in ('list', 'preview', 'download'):
            assert request(server, 'GET', endpoint(tmp_path / 'x.zip', action))[0] == 401
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)
