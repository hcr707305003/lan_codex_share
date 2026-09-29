"""Bounded text extraction. Never renders documents or resolves external resources."""
from __future__ import annotations

from pathlib import Path
import multiprocessing
import threading
import time
import zipfile
import psutil

from defusedxml.ElementTree import fromstring


MAX_TEXT = 100_000
_EXTRACTION_LOCK = threading.Lock()
_WORD = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'


def _bounded(text: str) -> str:
    if len(text) > MAX_TEXT:
        raise ValueError('提取文字超过 100,000 字符，请拆分文件')
    return text


def _text(path: Path) -> str:
    raw = path.read_bytes()
    encodings = ['utf-16'] if raw.startswith((b'\xff\xfe', b'\xfe\xff')) else ['utf-8-sig', 'gb18030']
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
        except UnicodeError:
            continue
        if any(ord(ch) < 32 and ch not in '\n\r\t\f' for ch in text):
            raise ValueError('文本包含二进制控制字符')
        return _bounded(text)
    raise ValueError('文本编码无法识别，请另存为 UTF-8')


def _docx(path: Path) -> str:
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        size = sum(entry.file_size for entry in entries)
        compressed = sum(entry.compress_size for entry in entries)
        if len(entries) > 1000 or size > 50 * 1024 * 1024 or size > max(1, compressed) * 100:
            raise ValueError('DOCX 解压规模超限，请拆分文件')
        names = [entry.filename for entry in entries]
        if len(set(names)) != len(names) or any(entry.flag_bits & 1 for entry in entries):
            raise ValueError('DOCX 含重复或加密条目')
        if any('vbaproject' in name.lower() for name in names):
            raise ValueError('不支持含宏的 Word 文档')
        content_types = fromstring(archive.read('[Content_Types].xml'), forbid_dtd=True)
        expected = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'
        if not any(node.get('PartName') == '/word/document.xml' and node.get('ContentType') == expected for node in content_types):
            raise ValueError('不是有效的 DOCX Word 文档')
        document = fromstring(archive.read('word/document.xml'), forbid_dtd=True)
        body = document.find(_WORD + 'body')
        if body is None:
            raise ValueError('DOCX 缺少正文')

        def paragraph(node):
            return ''.join((part.text or '') if part.tag == _WORD + 't' else '\t' if part.tag == _WORD + 'tab' else '\n' if part.tag in {_WORD + 'br', _WORD + 'cr'} else '' for part in node.iter())

        blocks = []
        length = 0
        for node in body:
            if node.tag == _WORD + 'p':
                block = paragraph(node)
            elif node.tag == _WORD + 'tbl':
                block = '\n'.join('\t'.join('\n'.join(paragraph(p) for p in cell.findall('.//' + _WORD + 'p')) for cell in row.findall(_WORD + 'tc')) for row in node.findall(_WORD + 'tr'))
            else:
                continue
            length += len(block) + 1
            if length > MAX_TEXT + 1:
                raise ValueError('提取文字超过 100,000 字符，请拆分文件')
            blocks.append(block)
        return _bounded('\n'.join(blocks))


def _pdf(path: Path) -> dict:
    from pypdf import PdfReader

    with path.open('rb') as stream:
        if not stream.read(8).startswith(b'%PDF-'):
            raise ValueError('文件内容不是 PDF')
    reader = PdfReader(path, strict=True)
    if reader.is_encrypted:
        raise ValueError('不支持加密 PDF，请先移除密码')
    if len(reader.pages) > 500:
        raise ValueError('PDF 超过 500 页，请拆分文件')
    blocks, empty = [], []
    length = 0
    for index, page in enumerate(reader.pages, 1):
        text = page.extract_text() or ''
        if not text.strip():
            empty.append(index)
        block = f'[第 {index} 页]\n{text}'
        length += len(block) + 2
        if length > MAX_TEXT:
            raise ValueError('提取文字超过 100,000 字符，请拆分文件')
        blocks.append(block)
    if not blocks or len(empty) == len(blocks):
        raise ValueError('PDF 无可提取文字，扫描件请先 OCR 或转为文本')
    warning = '仅提取文字，不含图片和完整排版。'
    if empty:
        warning += f'以下页面无可提取文字：{", ".join(map(str, empty))}。'
    return {'text': '\n\n'.join(blocks), 'warning': warning}


def extract_document(path: str | Path) -> dict:
    path = Path(path)
    try:
        extension = path.suffix.lower()
        if extension in {'.md', '.txt'}:
            result = {'text': _text(path), 'warning': ''}
        elif extension == '.docx':
            result = {'text': _docx(path), 'warning': '仅提取正文段落和表格，不含图片、批注、修订及完整排版。'}
        elif extension == '.pdf':
            from pypdf import apply_configuration
            with apply_configuration(zlib_maximum_output_length=50 * 1024 * 1024, jbig2dec_binary=None):
                result = _pdf(path)
        else:
            raise ValueError('仅支持 MD、TXT、DOCX、PDF；旧 DOC 请转为 DOCX')
        _bounded(result['text'])
        if not result['text'].strip():
            raise ValueError('文件没有可提取的文字')
        return result
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('文档损坏或格式不受支持') from exc


def _extract_child(path, sender):
    try:
        sender.send({'ok': extract_document(path)})
    except Exception as exc:
        sender.send({'error': str(exc) if isinstance(exc, ValueError) else '文档解析失败'})
    finally:
        sender.close()


def extract_isolated(path: Path, timeout: float = 30) -> dict:
    if not _EXTRACTION_LOCK.acquire(blocking=False):
        raise ValueError('文档解析繁忙，请稍后重试')
    process = None
    receiver = sender = None
    try:
        context = multiprocessing.get_context('spawn')
        receiver, sender = context.Pipe(duplex=False)
        process = context.Process(target=_extract_child, args=(str(path), sender), daemon=True)
        process.start()
        sender.close()
        deadline = time.monotonic() + timeout
        child = psutil.Process(process.pid)
        while not receiver.poll(min(0.05, max(0, deadline - time.monotonic()))):
            if time.monotonic() >= deadline:
                raise ValueError('文档解析超时，请拆分或转换后重试')
            try:
                if child.memory_info().rss > 512 * 1024 * 1024:
                    raise ValueError('文档解析内存超限，请拆分或转换后重试')
            except psutil.NoSuchProcess:
                raise ValueError('文档解析进程异常退出')
        try:
            result = receiver.recv()
        except EOFError as exc:
            raise ValueError('文档解析进程异常退出') from exc
        if 'error' in result:
            raise ValueError(result['error'])
        return result['ok']
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
        if receiver is not None:
            receiver.close()
        if sender is not None:
            sender.close()
        _EXTRACTION_LOCK.release()
