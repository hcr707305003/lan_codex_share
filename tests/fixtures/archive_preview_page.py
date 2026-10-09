"""Isolated real-web UI fixture; does not connect to Codex or user services."""
from pathlib import Path
import sys
import tempfile
import threading
import time
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.test_lan_web import FakeService
from tests.test_archive_preview import xlsx_bytes
from lan_codex_share.lan_web import LanWebApplication
from lan_codex_share.lan_store import ImageStore


def main():
    with tempfile.TemporaryDirectory(prefix='archive-ui-') as temporary:
        root = Path(temporary)
        package = root / '演示导出.zip'
        with zipfile.ZipFile(package, 'w') as z:
            z.writestr('示例企业/绩效方案.xlsx', xlsx_bytes())
            z.writestr('示例企业/README.md', '# 绩效方案\n\n这里是测试内容，不包含真实业务数据。')
            z.writestr('说明.txt', '演示压缩包中的纯文本')
            z.writestr('空目录/', '')
            z.writestr('这是一个很长的中文文件名称用于检查窄屏是否能够正确换行不撑开右侧预览面板.txt', 'long name')
            z.writestr('示例.pdf', b'%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Count 0/Kids[]>>endobj\ntrailer<</Root 1 0 R>>\n%%EOF')
        class Service(FakeService):
            def snapshot(self, *args, **kwargs):
                value = super().snapshot(*args, **kwargs)
                value['thread'] = {'id': 'thread-web', 'name': '压缩包预览测试（模拟会话）',
                    'turns': [{'id': 'turn', 'status': 'completed', 'items': [
                        {'id': 'answer', 'type': 'agentMessage',
                         'text': f'导出完成：[下载演示 ZIP]({package.as_posix()})'}]}]}
                return value
        app = LanWebApplication(Service(), ImageStore(root / 'images', 10485760, 4),
            {'127.0.0.1', 'localhost'}, max_request_bytes=2 * 1024 * 1024, workspace=root)
        server = app.create_server('127.0.0.1', 0)
        stop = root / 'stop'
        print(f'PREVIEW_URL=http://127.0.0.1:{server.server_port}\nSTOP_FILE={stop}', flush=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 900
            while time.monotonic() < deadline and not stop.exists():
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            server.shutdown()
            server.server_close()
            thread.join(2)


if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()
    main()
