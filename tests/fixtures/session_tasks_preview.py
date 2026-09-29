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
from lan_codex_share.config_write import SessionConfigStore
import json
from tests.test_session_tasks import Client
from tests.test_session_hub import FakeSessionService


class Service(FakeSessionService):
    def __init__(self, entry):
        super().__init__(entry['id'], entry['name'])
        self.cwd = entry['cwd']
        self.demo_turns = entry.get('demo_turns', [])

    def summary(self):
        return dict(super().summary(), cwd=self.cwd)

    def snapshot(self, **kwargs):
        result = super().snapshot()
        result['thread'].update(name=self.name, cwd=self.cwd)
        result['thread']['turns'] = self.demo_turns
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
        entries = [client.threads[0]]
        if '--notice' in sys.argv:
            entries.extend([dict(client.threads[0], id=str(uuid4()), name='同项目第二会话'),
                            dict(client.threads[1], name='其他项目会话', cwd=str(other))])
            for entry in entries:
                entry['demo_turns'] = [{'id': f'turn-{i}', 'status': 'completed', 'items': [
                    {'id': f'user-{i}', 'type': 'userMessage', 'content': [{'type': 'text', 'text': f'示例问题 {i}'}]},
                    {'id': f'answer-{i}', 'type': 'agentMessage', 'text': f'示例回答 {i}。用于验证公告折叠时的历史阅读位置。'},
                ]} for i in range(25)]
        hub = LanSessionHub([Service(entry) for entry in entries])
        hub.profiles = ProjectProfiles(root / 'project_profiles.json')
        store = None
        if '--config-shared' in sys.argv:
            config_path = root / 'lan_config.toml'
            config_path.write_text('workspace = "."\nsession_mode = "selected"\nsession_ids = ' + json.dumps([entry['id'] for entry in entries]) + '\n', encoding='utf-8')
            store = SessionConfigStore(config_path)
        tasks = SessionTasks(root / 'shared_sessions.json', client, root, hub.register_session, lambda: hub.thread_ids,
                             config_store=store, hub=hub)
        hub.configure_tasks(tasks, Service)
        hub.start()
        if '--notice' in sys.argv:
            project = hub.project_summaries()[0]
            hub.project_profile(project['id'], {'alias': '演示项目', 'revision': 0,
                'notice_markdown': '# 项目公告\n\n[相关网站](https://example.com)\n\n| 环境 | 用途 |\n| --- | --- |\n| 测试 | 联调 |\n\n' + '\n\n'.join(f'说明 {i}：演示项目的操作注意事项。' for i in range(20))})
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
