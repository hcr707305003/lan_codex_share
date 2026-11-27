from io import BytesIO
import json
import tarfile
import zipfile

import pytest

from lan_codex_share.attachment_formats import TEXT_EXTENSIONS
from lan_codex_share.document_store import DocumentStore, document_input
from tests.test_document_store import payload


@pytest.mark.parametrize('extension', sorted(TEXT_EXTENSIONS))
def test_source_formats_are_inert_originals(tmp_path, extension):
    raw = '<script>not executed</script>\n中文'.encode()
    store = DocumentStore(tmp_path)
    docs = store.save_many([payload('source' + extension.upper(), raw)])
    store.bind('s', 'm', '', docs)
    path, record = store.resolve(docs[0]['id'], 's')
    assert path.read_bytes() == raw
    assert record['text'] == raw.decode()
    assert store.preview(record['id'], 's')['content'] == raw.decode()
    assert json.loads(document_input(record)['text'].split('\n', 1)[1])['local_file'] == str(path)


@pytest.mark.parametrize('extension', ['zip', 'tar.gz'])
def test_archive_upload_only_lists_headers_and_preserves_paths(tmp_path, extension):
    output = BytesIO()
    if extension == 'zip':
        with zipfile.ZipFile(output, 'w') as archive:
            archive.writestr('src/app.js', 'alert(1)')
            archive.writestr('../outside.txt', 'not extracted')
    else:
        with tarfile.open(fileobj=output, mode='w:gz') as archive:
            for name in ['src/app.js', '../outside.txt']:
                info = tarfile.TarInfo(name); info.size = 4
                archive.addfile(info, BytesIO(b'text'))
    raw = output.getvalue()
    store = DocumentStore(tmp_path / 'uploads')
    docs = store.save_many([payload('project.' + extension, raw)])
    store.bind('s', 'm', '', docs)
    restarted = DocumentStore(store.directory)
    path, record = restarted.resolve(docs[0]['id'], 's')
    assert record['input_mode'] == 'file' and path.read_bytes() == raw
    assert 'src/app.js' in restarted.preview(record['id'], 's')['content']
    assert not (tmp_path / 'outside.txt').exists()
    with pytest.raises(FileNotFoundError):
        restarted.preview(record['id'], 'other')


@pytest.mark.parametrize('extension', ['zip', 'tar.gz'])
def test_invalid_archive_is_rolled_back(tmp_path, extension):
    store = DocumentStore(tmp_path)
    with pytest.raises(ValueError):
        store.save_many([payload('broken.' + extension, b'broken')])
    assert not list(tmp_path.glob('*.' + extension))
