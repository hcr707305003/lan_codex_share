"""Isolated new-task UI fixture. No real Codex or user services."""
import sys
from pathlib import Path
import tempfile
import threading
import time
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from lan_codex_share.lan_web import LanWebApplication
from lan_codex_share.lan_store import ImageStore
from lan_codex_share.session_hub import LanSessionHub
from lan_codex_share.session_tasks import SessionTasks
from lan_codex_share.project_profiles import ProjectProfiles
from tests.test_session_tasks import Client
from tests.test_session_hub import FakeSessionService


class Service(FakeSessionService):
    def __init__(self, entry):
        super().__init__(entry['id'], entry['name'])
        self.cwd = entry['cwd']

    def summary(self):
        return dict(super().summary(), cwd=self.cwd)

    def snapshot(self, **kwargs):
        result = super().snapshot()
        result['thread'].update(name=self.name, cwd=self.cwd)
        return result


def main():
    with tempfile.TemporaryDirectory(prefix='task-ui-') as temp:
        root = Path(temp)
        client = Client(root)
        client.threads[0]['name'] = '当前项目 · 原始会话'
        other = root / 'Other Project'; other.mkdir()
        for i in range(65):
            client.threads.append({'id': str(uuid4()), 'name': f'示例任务 {i + 1}', 'cwd': str(other if i % 2 else root), 'updatedAt': 1790000000 + i})
        client.threads.append({'id': str(uuid4()), 'name': '<img src=x onerror=alert(1)> 安全标题', 'cwd': str(root)})
        hub = LanSessionHub([Service(client.threads[0])])
        hub.profiles = ProjectProfiles(root / 'project_profiles.json')
        tasks = SessionTasks(root / 'shared_sessions.json', client, root, hub.register_session, lambda: hub.thread_ids)
        hub.configure_tasks(tasks, Service)
        hub.start()
        app = LanWebApplication(hub, ImageStore(root / 'images', 10485760, 4), {'127.0.0.1', 'localhost'}, max_request_bytes=64 * 1048576, workspace=root)
        server = app.create_server('127.0.0.1', 0)
        print(f'PREVIEW_URL=http://127.0.0.1:{server.server_port}', flush=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            time.sleep(1800)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown(); server.server_close(); hub.close()


if __name__ == '__main__':
    main()
