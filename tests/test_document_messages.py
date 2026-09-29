import time

from lan_codex_share.document_store import DocumentStore
from lan_codex_share.lan_service import LanChatService
from lan_codex_share.session_projection import SessionProjection
from tests.test_document_store import payload
from tests.test_lan_service import FakeCodex


def test_document_only_input_and_persistent_history(tmp_path):
    store = DocumentStore(tmp_path / 'docs')
    codex = FakeCodex()
    projection = SessionProjection(document_store=store)
    service = LanChatService(codex, projection, document_store=store)
    service.start()
    try:
        docs = store.save_many([payload('hello.md', b'# document content')])
        message_id = service.submit('', [], '127.0.0.1', documents=docs)
        for _ in range(100):
            if codex.calls:
                break
            time.sleep(0.02)
        assert '# document content' in codex.calls[0]['items'][0]['text']
        for _ in range(100):
            if not service.snapshot()['pending']:
                break
            time.sleep(0.02)
        user = next(item for turn in service.snapshot()['thread']['turns'] for item in turn['items'] if item['type'] == 'userMessage')
        assert user['text'] == ''
        assert user['content'] == []
        assert user['documents'][0]['name'] == 'hello.md'
        restored = SessionProjection(document_store=DocumentStore(tmp_path / 'docs'))
        restored.replace_thread({'id': service.thread_id, 'turns': [{'id': 't', 'items': [{'id': user['id'], 'type': 'userMessage', 'content': codex.calls[0]['items']}]}]})
        assert restored.snapshot()['thread']['turns'][0]['items'][0]['documents'] == user['documents']
    finally:
        service.close()


def test_cancel_document_queue_only(tmp_path):
    store = DocumentStore(tmp_path)
    codex = FakeCodex()
    codex.thread_busy = True
    service = LanChatService(codex, SessionProjection(document_store=store), document_store=store)
    service.start()
    try:
        docs = store.save_many([payload('a.md', b'data')])
        message_id = service.submit('question', [], 'local', documents=docs)
        assert service.cancel_queued(message_id, 'local')
        assert not (tmp_path / (docs[0]['id'] + '.md')).exists()
        assert not codex.calls
    finally:
        service.close()
