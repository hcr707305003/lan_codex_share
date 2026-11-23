"""Inert previews for bounded ZIP members; called only in an isolated worker."""
from pathlib import Path
from tempfile import TemporaryDirectory

from .archive_reader import ArchiveError, checked_archive, read_member
from .document_extract import extract_document
from .workspace_files import IMAGE_MIME, MARKDOWN_EXTENSIONS, TEXT_EXTENSIONS, TEXT_FILENAMES

from .spreadsheet_reader import _xlsx

_TEXT_LIMIT = 2 * 1024 * 1024


def preview_member(path: str, version: str, member: int, sheet: int = 0, *, workdir=None) -> dict:
    result = read_member(path, version, member)
    data = result.pop('data')
    suffix = Path(result['name']).suffix.lower()
    result.update(kind='download', mime='application/octet-stream')
    if suffix in MARKDOWN_EXTENSIONS | TEXT_EXTENSIONS or result['name'].lower() in TEXT_FILENAMES:
        if len(data) > _TEXT_LIMIT:
            result['warning'] = '文本超过 2 MiB 预览上限，请下载原文件'
        else:
            try:
                content = data.decode('utf-8-sig')
            except UnicodeDecodeError:
                content = data.decode('utf-8', errors='replace')
                result['warning'] = '文件不是有效 UTF-8，无法解码的字节已替换显示。'
            result.update(kind='markdown' if suffix in MARKDOWN_EXTENSIONS else 'code', content=content)
    elif suffix in IMAGE_MIME:
        result.update(kind='image', mime=IMAGE_MIME[suffix], data=data)
    elif suffix == '.pdf':
        result.update(kind='pdf', mime='application/pdf', data=data)
    elif suffix in {'.docx', '.xlsx'}:
        with TemporaryDirectory(prefix='lan-archive-office-', dir=workdir) as tmp:
            local = Path(tmp) / ('document' + suffix)
            local.write_bytes(data)
            try:
                if suffix == '.xlsx':
                    result.update(kind='spreadsheet', **_xlsx(local, sheet),
                        warning='只显示已保存的值，不计算公式；最多前 200 行、50 列。日期可能显示原始数值，不还原格式、合并单元格或图表。')
                else:
                    # Check paths, special files and inner ZIP limits before XML parsing.
                    with checked_archive(local):
                        pass
                    document = extract_document(local)
                    result.update(kind='code', content=document['text'], warning=document['warning'])
            except ArchiveError:
                raise
            except Exception as exc:
                raise ArchiveError('Office 文档损坏、包含不安全内容或解析超限') from exc
    return result
