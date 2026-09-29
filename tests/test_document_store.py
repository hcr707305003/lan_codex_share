import base64
import json
from io import BytesIO
from pathlib import Path
import zipfile

import pytest

from lan_codex_share.document_store import DocumentStore
from lan_codex_share.document_extract import extract_document


def payload(name, raw):
    return {'name': name, 'mime': '', 'data': base64.b64encode(raw).decode()}


def test_preview_cache_restart_and_missing_original(tmp_path, monkeypatch):
    store = DocumentStore(tmp_path)
    docs = store.save_many([payload('notes.md', b'# Content')])
    store.bind('s', 'm', 'question', docs)
    monkeypatch.setattr('lan_codex_share.document_store.extract_isolated', lambda _: pytest.fail('should use persisted extraction'))
    store = DocumentStore(tmp_path)
    result = store.preview(docs[0]['id'], 's')
    assert result == {'name': 'notes.md', 'size': 9, 'kind': 'markdown', 'content': '# Content', 'warning': ''}
    assert 'Content' not in json.dumps(store.metadata('s', 'm'))
    with pytest.raises(FileNotFoundError):
        store.preview(docs[0]['id'], 'wrong')
    store.resolve(docs[0]['id'], 's')[0].unlink()
    with pytest.raises(FileNotFoundError):
        store.preview(docs[0]['id'], 's')


@pytest.mark.parametrize('extension', ['.txt', '.docx'])
def test_legacy_preview_cached_without_resurrecting_cancelled_files(tmp_path, monkeypatch, extension):
    store = DocumentStore(tmp_path)
    docs = store.save_many([payload('a.txt', b'legacy')])
    store.bind('s', 'm', '', docs)
    path, record = store.resolve(docs[0]['id'], 's')
    record.pop('text', None)
    record['extension'] = extension
    path.rename(store._path(record))
    with store._connect() as db:
        db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(record), record['id']))
    calls = []
    def extract(path):
        calls.append(path)
        return {'text': 'paragraph\ncell1\tcell2', 'warning': 'preview note'}
    monkeypatch.setattr('lan_codex_share.document_store.extract_isolated', extract)
    result = store.preview(record['id'], 's')
    assert result['kind'] == 'text' and result['content'] == 'paragraph\ncell1\tcell2'
    assert 'preview note' in result['warning']
    if extension == '.docx':
        assert '原始版式' in result['warning']
    assert store.preview(record['id'], 's') == result
    assert len(calls) == 1
    with store._connect() as db:
        db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(record), record['id']))
    def cancel_during_parse(path):
        store.delete_many([record])
        return extract(path)
    monkeypatch.setattr('lan_codex_share.document_store.extract_isolated', cancel_during_parse)
    with pytest.raises(FileNotFoundError):
        store.preview(record['id'], 's')
    assert store.metadata('s', 'm') is None


@pytest.mark.parametrize('message', ['解析繁忙', '解析超时', '文档损坏'])
def test_legacy_preview_failure_not_cached(tmp_path, monkeypatch, message):
    store = DocumentStore(tmp_path)
    docs = store.save_many([payload('a.txt', b'legacy')])
    store.bind('s', 'm', '', docs)
    _, record = store.resolve(docs[0]['id'], 's')
    record.pop('text', None)
    with store._connect() as db:
        db.execute('UPDATE documents SET record=? WHERE id=?', (json.dumps(record), record['id']))
    def fail(path):
        raise ValueError(message)
    monkeypatch.setattr('lan_codex_share.document_store.extract_isolated', fail)
    with pytest.raises(ValueError, match=message):
        store.preview(record['id'], 's')
    assert 'text' not in store.resolve(record['id'], 's')[1]


def test_text_storage_binding_and_restart(tmp_path):
    store = DocumentStore(tmp_path)
    docs = store.save_many([payload('笔记.MD', '# 内容'.encode())])
    assert docs[0]['text'] == '# 内容'
    store.bind('session-a', 'message-a', '看看这个', docs)
    metadata = store.metadata('session-a', 'message-a', 'item-a')
    assert metadata['text'] == '看看这个'
    assert 'path' not in metadata['documents'][0]
    restarted = DocumentStore(tmp_path)
    assert restarted.metadata('session-a', None, 'item-a') == metadata
    path, record = restarted.resolve(docs[0]['id'], 'session-a')
    assert path.read_bytes() == '# 内容'.encode()
    with pytest.raises(FileNotFoundError):
        restarted.resolve(docs[0]['id'], 'session-b')


@pytest.mark.parametrize('name,raw', [('old.doc', b'data'), ('bad.pdf', b'fake'), ('empty.txt', b''), ('../a.md', b'a'), ('a.txt', b'\x00\x01')])
def test_reject_invalid_and_rollback(tmp_path, name, raw):
    store = DocumentStore(tmp_path)
    with pytest.raises(ValueError):
        store.save_many([payload('valid.md', b'hello'), payload(name, raw)])
    assert list(tmp_path.glob('*.md')) == []


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'utf-16', 'gb18030'])
def test_text_encodings(tmp_path, encoding):
    path = tmp_path / 'a.txt'
    path.write_bytes('中文内容'.encode(encoding))
    assert extract_document(path)['text'] == '中文内容'


def docx_bytes(xml):
    output = BytesIO()
    with zipfile.ZipFile(output, 'w') as archive:
        archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('word/document.xml', xml)
    return output.getvalue()


def test_docx_paragraph_table_order(tmp_path):
    path = tmp_path / 'a.docx'
    path.write_bytes(docx_bytes('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>before</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>cell</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>after</w:t></w:r></w:p></w:body></w:document>'))
    assert extract_document(path)['text'] == 'before\ncell\nafter'


def test_docx_entities_rejected(tmp_path):
    path = tmp_path / 'a.docx'
    path.write_bytes(docx_bytes('<!DOCTYPE x [<!ENTITY x "bad">]><x>&x;</x>'))
    with pytest.raises(ValueError):
        extract_document(path)


def test_pdf_text_and_encryption(tmp_path):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 10 100 Td (Hello document) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    path = tmp_path / 'a.pdf'
    writer.write(path)
    assert 'Hello document' in extract_document(path)['text']
    writer.add_blank_page(width=200, height=200)
    writer.write(path)
    assert '页面无可提取文字：2' in extract_document(path)['warning']
    writer.encrypt('secret')
    writer.write(path)
    with pytest.raises(ValueError, match='加密'):
        extract_document(path)


def test_limits_and_cancel_cleanup(tmp_path):
    store = DocumentStore(tmp_path, max_bytes=4, max_documents=1)
    with pytest.raises(ValueError):
        store.save_many([payload('a.md', b'12345')])
    docs = store.save_many([payload('a.md', b'1234')])
    store.bind('s', 'm', '', docs)
    store.delete_many(docs)
    assert store.metadata('s', 'm') is None
    with pytest.raises(FileNotFoundError):
        store.resolve(docs[0]['id'], 's')


def test_extraction_timeout_and_busy(tmp_path):
    from lan_codex_share.document_extract import extract_isolated, _EXTRACTION_LOCK
    path = tmp_path / 'a.md'
    path.write_text('hello', encoding='utf-8')
    with pytest.raises(ValueError, match='超时'):
        extract_isolated(path, timeout=0)
    with _EXTRACTION_LOCK:
        with pytest.raises(ValueError, match='繁忙'):
            extract_isolated(path)
    assert extract_isolated(path)['text'] == 'hello'


def test_text_count_total_and_rollback(tmp_path):
    store = DocumentStore(tmp_path)
    with pytest.raises(ValueError):
        store.save_many([payload('a.md', b'a' * 100001)])
    with pytest.raises(ValueError, match='200,000'):
        store.save_many([payload(f'{i}.txt', b'b' * 80000) for i in range(3)])
    with pytest.raises(ValueError):
        store.save_many([payload('a.md', b'a')] * 6)
    assert not list(tmp_path.glob('*.txt'))


def test_zip_bomb_and_duplicates(tmp_path):
    path = tmp_path / 'a.docx'
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('large.xml', 'x' * 1_000_000)
    with pytest.raises(ValueError, match='解压'):
        extract_document(path)


def test_pdf_scanned_page_limit_and_empty_warning(tmp_path):
    from pypdf import PdfWriter
    path = tmp_path / 'a.pdf'
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(path)
    with pytest.raises(ValueError, match='OCR'):
        extract_document(path)
    for _ in range(500):
        writer.add_blank_page(width=100, height=100)
    writer.write(path)
    with pytest.raises(ValueError, match='500'):
        extract_document(path)


def test_missing_original_preserves_card(tmp_path):
    store = DocumentStore(tmp_path)
    docs = store.save_many([payload('a.md', b'hello')])
    store.bind('s', 'm', 'text', docs)
    (tmp_path / (docs[0]['id'] + '.md')).unlink()
    assert store.metadata('s', 'm')['documents'][0]['missing'] is True


def test_same_filename_sessions_and_targeted_cleanup(tmp_path):
    store = DocumentStore(tmp_path)
    first = store.save_many([payload('same.md', b'first')])
    second = store.save_many([payload('same.md', b'second')])
    assert first[0]['id'] != second[0]['id']
    store.bind('session-a', 'm1', '', first)
    store.bind('session-b', 'm2', '', second)
    store.delete_many(first)
    assert store.resolve(second[0]['id'], 'session-b')[0].read_bytes() == b'second'
    assert store.metadata('session-b', 'm2')['documents'][0]['name'] == 'same.md'


@pytest.mark.parametrize('extra', ['max_documents = 0', 'max_documents = 21', 'max_documents = true', 'max_document_bytes = 20971521', 'max_document_bytes = "20"'])
def test_document_config_validation(tmp_path, extra):
    from lan_codex_share.lan_config import load_lan_config, LanConfigError
    config = tmp_path / 'lan_config.toml'
    config.write_text('workspace = "."\n' + extra, encoding='utf-8')
    with pytest.raises(LanConfigError):
        load_lan_config(config)
