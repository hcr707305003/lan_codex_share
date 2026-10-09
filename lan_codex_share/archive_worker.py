"""Two bounded spawn workers; only tiny status messages cross the control pipe."""
import base64
import json
import multiprocessing
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import time

import psutil

from .archive_reader import ArchiveError, inspect_archive, read_member
from .archive_preview import preview_member

_SLOTS = threading.BoundedSemaphore(2)
_RESULT_LIMIT = 40 * 1024 * 1024


def _child(path, action, options, output, sender):
    try:
        if action == 'list':
            result = inspect_archive(path, options['version'], options['directory'], options['page'])
        elif action == 'download':
            result = read_member(path, options['version'], options['member'])
        elif action == 'preview':
            result = preview_member(path, options['version'], options['member'], options['sheet'],
                                    workdir=str(Path(output).parent))
        else:
            raise ArchiveError('压缩包操作无效')
        if 'data' in result:
            result['base64'] = base64.b64encode(result.pop('data')).decode('ascii')
        encoded = json.dumps(result, ensure_ascii=False).encode('utf-8')
        if len(encoded) > _RESULT_LIMIT:
            raise ArchiveError('压缩包预览结果过大', 413)
        Path(output).write_bytes(encoded)
        sender.send({'ok': True})
    except ArchiveError as exc:
        sender.send({'error': str(exc), 'status': exc.status})
    except Exception:
        sender.send({'error': '压缩包解析失败或格式不受支持', 'status': 400})
    finally:
        sender.close()


def run_archive(path: str, action: str, *, version: str = '', member: int = -1,
                directory: str = '', page: int = 0, sheet: int = 0, timeout: float = 30) -> dict:
    if not _SLOTS.acquire(blocking=False):
        raise ArchiveError('压缩包解析繁忙，请稍后重试', 429)
    process = receiver = sender = None
    try:
        with TemporaryDirectory(prefix='lan-archive-result-') as tmp:
            output = Path(tmp) / 'result.json'
            try:
                context = multiprocessing.get_context('spawn')
                receiver, sender = context.Pipe(duplex=False)
                process = context.Process(target=_child, args=(path, action,
                    dict(version=version, member=member, directory=directory, page=page, sheet=sheet),
                    str(output), sender), daemon=True)
                process.start()
                sender.close()
                deadline = time.monotonic() + timeout
                child = psutil.Process(process.pid)
                while True:
                    if time.monotonic() >= deadline:
                        raise ArchiveError('压缩包解析超时，请下载整包查看', 408)
                    try:
                        if child.memory_info().rss > 512 * 1024 * 1024:
                            raise ArchiveError('压缩包解析内存超限', 413)
                    except psutil.NoSuchProcess:
                        pass
                    if receiver.poll(0.05):
                        break
                    if not process.is_alive():
                        raise ArchiveError('压缩包解析进程异常退出')
                try:
                    message = receiver.recv()
                except EOFError as exc:
                    raise ArchiveError('压缩包解析进程异常退出') from exc
                if 'error' in message:
                    raise ArchiveError(message['error'], message['status'])
                if not output.is_file() or output.stat().st_size > _RESULT_LIMIT:
                    raise ArchiveError('压缩包解析结果异常')
                result = json.loads(output.read_text(encoding='utf-8'))
                if 'base64' in result:
                    result['data'] = base64.b64decode(result.pop('base64'), validate=True)
                return result
            finally:
                if process is not None and process.pid is not None:
                    process.join(timeout=0.2)
                    if process.is_alive():
                        process.terminate()
                        process.join(timeout=2)
                    if process.is_alive():
                        process.kill()
                        process.join(timeout=2)
                    process.close()
    finally:
        if receiver is not None:
            receiver.close()
        if sender is not None:
            sender.close()
        _SLOTS.release()
