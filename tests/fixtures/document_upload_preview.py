"""Temporary UI fixture: real HTTP/upload code, fake Codex, no user services."""
import sys
from pathlib import Path
import tempfile
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lan_codex_share.document_store import DocumentStore
from lan_codex_share.lan_store import ImageStore
from lan_codex_share.lan_web import LanWebApplication
from lan_codex_share.lan_service import LanChatService
from lan_codex_share.session_projection import SessionProjection
from lan_codex_share.session_hub import LanSessionHub
from tests.test_lan_service import FakeCodex


class PreviewCodex(FakeCodex):
    def __init__(self):
        super().__init__()
        self.history = {'id': self.thread_id, 'name': '文档上传测试（模拟会话）', 'cwd': 'demo', 'status': {'type': 'idle'}, 'turns': []}

    def read_thread(self, include_turns=True):
        return self.history

    def run_turn_items(self, items, **kwargs):
        result = super().run_turn_items(items, **kwargs)
        turn_id = f'turn-{len(self.calls)}'
        self.history['turns'].append({'id': turn_id, 'status': 'completed', 'items': [
            {'id': f'user-{turn_id}', 'type': 'userMessage', 'clientId': kwargs['client_user_message_id'], 'content': items},
            {'id': f'answer-{turn_id}', 'type': 'agentMessage', 'text': '模拟回复：已收到文档文字。此检查不会连接真实模型。'},
        ]})
        return result


def main():
    with tempfile.TemporaryDirectory(prefix='document-ui-') as temporary:
        root = Path(temporary)
        store = DocumentStore(root / 'documents')
        codex = PreviewCodex()
        hub = LanSessionHub([LanChatService(codex, SessionProjection(document_store=store), document_store=store)])
        hub.start()
        app = LanWebApplication(hub, ImageStore(root / 'images', 10485760, 4), {'127.0.0.1', 'localhost'}, max_request_bytes=200 * 1024 * 1024, document_store=store, workspace=root)
        server = app.create_server('127.0.0.1', 0)
        print(f'PREVIEW_URL=http://127.0.0.1:{server.server_port}', flush=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            # Exit automatically so an interrupted smoke session cannot linger.
            time.sleep(900)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
            server.server_close()
            hub.close()


if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()
    main()
