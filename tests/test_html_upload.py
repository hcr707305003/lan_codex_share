import json

import pytest

from lan_codex_share.document_extract import extract_document
from lan_codex_share.document_store import DocumentStore, document_input
from tests.test_document_store import payload
from tests.test_document_web import document_web
from tests.test_lan_web import request, mutation_headers


SOURCE = '<!DOCTYPE html><html><h1>中文内容</h1><script>throw new Error("inert")</script><img src="https://example.invalid/a.png"></html>'


@pytest.mark.parametrize('extension', ['.html', '.HTM'])
@pytest.mark.parametrize('encoding', ['utf-8-sig', 'utf-16', 'gb18030'])
def test_html_keeps_source_and_uses_existing_text_decoding(tmp_path, extension, encoding):
    path = tmp_path / ('页面' + extension)
    path.write_bytes(SOURCE.encode(encoding))
    result = extract_document(path)
    assert result['text'] == SOURCE
    assert '源码' in result['warning']


def test_html_persistent_model_material_and_preview(tmp_path):
    store = DocumentStore(tmp_path)
    docs = store.save_many([payload('页面.html', SOURCE.encode())])
    material = json.loads(document_input(docs[0])['text'].split('\n', 1)[1])
    assert material['document_text'] == SOURCE
    store.bind('s', 'm', '', docs)
    restarted = DocumentStore(tmp_path)
    preview = restarted.preview(docs[0]['id'], 's')
    assert preview['kind'] == 'text' and preview['content'] == SOURCE
    assert restarted.resolve(docs[0]['id'], 's')[0].read_bytes() == SOURCE.encode()
    with pytest.raises(FileNotFoundError):
        restarted.preview(docs[0]['id'], 'other')


def test_html_invalid_text_rolls_back(tmp_path):
    store = DocumentStore(tmp_path)
    with pytest.raises(ValueError):
        store.save_many([payload('page.html', b'\x00binary')])
    assert not list(tmp_path.glob('*.html'))


@pytest.mark.parametrize('extension', ['html', 'htm'])
def test_large_html_switches_to_file_and_keeps_complete_preview_after_restart(tmp_path, extension):
    raw = ('<html>' + '页面设计' * 50000 + '</html>').encode()
    store = DocumentStore(tmp_path)
    docs = store.save_many([payload(f'page{i}.{extension}', raw) for i in range(5)])
    store.bind('s', 'm', '', docs)
    store = DocumentStore(tmp_path)
    path, record = store.resolve(docs[0]['id'], 's')
    assert path.read_bytes() == raw
    assert record['input_mode'] == 'file'
    assert '页面设计' not in record['text']
    material = json.loads(document_input(record)['text'].split('\n', 1)[1])
    assert material['local_file'] == str(path) and material['input_mode'] == 'file'
    assert '完整' in material['reading_note']
    preview = store.preview(record['id'], 's')
    assert preview['content'] == raw.decode() and '完整' in preview['warning']
    assert 'local_file' not in json.dumps(store.metadata('s', 'm'))


@pytest.mark.parametrize('size,mode', [(100000, 'text'), (100001, 'file')])
def test_html_switch_boundary_preserves_all_source(tmp_path, size, mode):
    path = tmp_path / 'page.html'
    path.write_bytes(b'a' * size)
    record = extract_document(path)
    assert record['input_mode'] == mode
    if mode == 'text':
        assert record['text'] == 'a' * size
    else:
        assert 'local_file' in record['text']
    assert path.read_bytes() == b'a' * size


@pytest.mark.parametrize('extension', ['html', 'htm'])
def test_html_http_upload_text_preview_original_download_and_auth(document_web, extension):
    app, server, service, _ = document_web
    body = json.dumps({'documents': [payload('页面.' + extension, SOURCE.encode())]})
    status, _, response = request(server, 'POST', '/api/messages', body, mutation_headers(server, app.csrf_token))
    assert status == 202, response
    pending = service.snapshot()['pending'][0]
    endpoint = '/api/documents/' + pending['documents'][0]['id']
    status, headers, contents = request(server, 'GET', endpoint + '/preview?session_id=thread-lan')
    assert status == 200
    assert dict(headers)['Content-Type'].startswith('application/json')
    assert json.loads(contents)['kind'] == 'text'
    assert json.loads(contents)['content'] == SOURCE
    status, headers, contents = request(server, 'GET', endpoint + '?session_id=thread-lan')
    assert status == 200 and contents == SOURCE.encode()
    assert dict(headers)['Content-Type'] == 'application/octet-stream'
    assert dict(headers)['Content-Disposition'].startswith('attachment;')
    assert dict(headers)['X-Content-Type-Options'] == 'nosniff'
    assert request(server, 'GET', endpoint + '/preview?session_id=wrong')[0] == 400
    app.password = 'private'
    assert request(server, 'GET', endpoint + '/preview?session_id=thread-lan')[0] == 401
