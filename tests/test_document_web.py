import base64
from io import BytesIO
import json
import threading

from PIL import Image
import pytest

from lan_codex_share.document_store import DocumentStore
from lan_codex_share.lan_store import ImageStore
from lan_codex_share.lan_web import LanWebApplication
from lan_codex_share.lan_service import LanChatService
from lan_codex_share.session_projection import SessionProjection
from lan_codex_share.session_hub import LanSessionHub
from tests.test_document_store import payload
from tests.test_lan_service import FakeCodex
from tests.test_lan_web import request, mutation_headers


@pytest.fixture
def document_web(tmp_path):
    store = DocumentStore(tmp_path / 'documents')
    codex = FakeCodex()
    codex.thread_busy = True
    service = LanChatService(codex, SessionProjection(document_store=store), document_store=store)
    hub = LanSessionHub([service])
    hub.start()
    app = LanWebApplication(hub, ImageStore(tmp_path / 'images', 1024 * 1024, 4), {'127.0.0.1'}, max_request_bytes=2 * 1024 * 1024, document_store=store, workspace=tmp_path)
    server = app.create_server('127.0.0.1', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield app, server, service, codex
    server.shutdown()
    server.server_close()
    thread.join(3)
    hub.close()


def test_document_post_download_and_queue_cancel(document_web):
    app, server, service, codex = document_web
    raw = '# 中文文档'.encode()
    body = json.dumps({'documents': [payload('中文.md', raw)]})
    status, _, response = request(server, 'POST', '/api/messages', body, mutation_headers(server, app.csrf_token))
    assert status == 202, response
    pending = service.snapshot()['pending'][0]
    document_id = pending['documents'][0]['id']
    endpoint = '/api/documents/' + document_id + '?session_id=thread-lan'
    status, headers, contents = request(server, 'GET', endpoint)
    assert status == 200 and contents == raw
    assert dict(headers)['Content-Disposition'].startswith("attachment; filename*=UTF-8''")
    assert dict(headers)['X-Content-Type-Options'] == 'nosniff'
    assert request(server, 'GET', endpoint.replace('thread-lan', 'not-shared'))[0] == 400
    assert request(server, 'GET', '/api/documents/' + 'a' * 32 + '?session_id=thread-lan')[0] == 404
    assert request(server, 'GET', '/api/documents/..')[0] == 404
    app.password = 'private'
    assert request(server, 'GET', endpoint)[0] == 401
    app.password = ''
    assert service.cancel_queued(json.loads(response)['message_id'], 'local')
    assert request(server, 'GET', endpoint)[0] == 404
    assert not codex.calls


def test_mixed_invalid_upload_rolls_back(document_web):
    app, server, service, _ = document_web
    stream = BytesIO()
    Image.new('RGB', (2, 2)).save(stream, format='PNG')
    image = {'name': 'valid.png', 'mime': 'image/png', 'data': base64.b64encode(stream.getvalue()).decode()}
    body = json.dumps({'images': [image], 'documents': [payload('valid.md', b'fine'), payload('invalid.pdf', b'broken')]})
    status, _, _ = request(server, 'POST', '/api/messages', body, mutation_headers(server, app.csrf_token))
    assert status == 400
    assert not service.snapshot()['pending']
    assert list(app.image_store.directory.glob('*.png')) == []
    assert list(app.document_store.directory.glob('*.md')) == []


def test_limits_and_unauthenticated_upload(document_web):
    app, server, service, _ = document_web
    status, _, body = request(server, 'GET', '/api/auth/status')
    limits = json.loads(body)['upload_limits']
    assert limits['max_document_bytes'] == 20 * 1024 * 1024
    assert limits['max_documents'] == 5
    app.password = 'private'
    assert request(server, 'POST', '/api/messages', json.dumps({'documents': [payload('a.md', b'hello')]}), mutation_headers(server, app.csrf_token))[0] == 401
    assert not service.snapshot()['pending']


def test_document_preview_json_authorization_and_cleanup(document_web):
    app, server, service, codex = document_web
    body = json.dumps({'documents': [payload('notes.md', b'# Preview')]})
    assert request(server, 'POST', '/api/messages', body, mutation_headers(server, app.csrf_token))[0] == 202
    pending = service.snapshot()['pending'][0]
    document_id = pending['documents'][0]['id']
    endpoint = f'/api/documents/{document_id}/preview?session_id=thread-lan'
    status, headers, contents = request(server, 'GET', endpoint)
    assert status == 200, contents
    assert json.loads(contents)['content'] == '# Preview'
    assert json.loads(contents)['kind'] == 'markdown'
    assert dict(headers)['Cache-Control'] == 'no-store'
    assert dict(headers)['X-Content-Type-Options'] == 'nosniff'
    assert 'path' not in json.loads(contents)
    assert request(server, 'GET', endpoint.replace('thread-lan', 'wrong'))[0] == 400
    assert request(server, 'GET', endpoint.replace(document_id, 'a' * 32))[0] == 404
    assert request(server, 'GET', '/api/documents/../preview?session_id=thread-lan')[0] == 404
    app.password = 'private'
    assert request(server, 'GET', endpoint)[0] == 401
    app.password = ''
    service.cancel_queued(pending['id'], 'local')
    assert request(server, 'GET', endpoint)[0] == 404
    assert not codex.calls


def test_document_pdf_preview_inline_download_unchanged(document_web, monkeypatch):
    app, server, service, _ = document_web
    # Extraction is tested with real PDFs in test_document_store; here exercise HTTP bytes/headers.
    monkeypatch.setattr('lan_codex_share.document_store.extract_isolated', lambda _: {'text': 'pdf', 'warning': ''})
    raw = b'%PDF-1.4\nfixture'
    docs = app.document_store.save_many([payload('file.pdf', raw)])
    app.document_store.bind('thread-lan', 'pdf-message', '', docs)
    endpoint = f"/api/documents/{docs[0]['id']}"
    status, headers, contents = request(server, 'GET', endpoint + '/preview?session_id=thread-lan')
    assert status == 200 and contents == raw
    assert dict(headers)['Content-Type'] == 'application/pdf'
    assert dict(headers)['Content-Disposition'].startswith('inline;')
    assert dict(headers)['X-Frame-Options'] == 'SAMEORIGIN'
    status, headers, contents = request(server, 'GET', endpoint + '?session_id=thread-lan')
    assert status == 200 and contents == raw
    assert dict(headers)['Content-Disposition'].startswith('attachment;')
    assert dict(headers)['X-Frame-Options'] == 'DENY'
