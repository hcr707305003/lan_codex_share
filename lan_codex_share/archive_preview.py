"""Inert previews for bounded ZIP members; called only in an isolated worker."""
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from defusedxml.ElementTree import fromstring

from .archive_reader import ArchiveError, checked_archive, read_member, safe_name
from .document_extract import extract_document
from .workspace_files import IMAGE_MIME, MARKDOWN_EXTENSIONS, TEXT_EXTENSIONS, TEXT_FILENAMES

_S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_TEXT_LIMIT = 2 * 1024 * 1024


def _xlsx(path, sheet):
    with checked_archive(path) as (archive, _, names, _):
        if len(names) > 1000 or sum(i.file_size for i in archive.infolist()) > 50 * 1024 * 1024:
            raise ArchiveError('XLSX 内部解压规模超限', 413)
        if any('vbaproject' in name.lower() for name in names):
            raise ArchiveError('不支持含宏的 Excel 预览')
        mapping = dict(zip(names, archive.infolist()))
        consumed = 0

        def xml(name):
            nonlocal consumed
            if name not in mapping:
                raise ArchiveError('XLSX 缺少必要的内容')
            info = mapping[name]
            consumed += info.file_size
            if consumed > 50 * 1024 * 1024:
                raise ArchiveError('XLSX 解析内容超限', 413)
            with archive.open(info) as f:
                data = f.read(info.file_size + 1)
            if len(data) != info.file_size:
                raise ArchiveError('XLSX 内容大小异常')
            return fromstring(data, forbid_dtd=True)

        content_types = xml('[Content_Types].xml')
        expected = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'
        if not any(node.get('PartName') == '/xl/workbook.xml' and node.get('ContentType') == expected for node in content_types):
            raise ArchiveError('不是有效的 XLSX 工作簿')
        sheets = xml('xl/workbook.xml').findall(_S + 'sheets/' + _S + 'sheet')
        if len(sheets) > 200:
            raise ArchiveError('XLSX 工作表数量超过 200 张', 413)
        if not sheets:
            return {'sheets': [], 'sheet': 0, 'rows': [], 'truncated': False}
        if not isinstance(sheet, int) or not 0 <= sheet < len(sheets):
            raise ArchiveError('工作表索引无效')
        relationships = xml('xl/_rels/workbook.xml.rels')
        selected = [r for r in relationships if r.get('Id') == sheets[sheet].get(_R + 'id')]
        if len(selected) != 1:
            raise ArchiveError('工作表关系无效')
        relation = selected[0]
        if relation.get('TargetMode') == 'External' or relation.get('Type') != _R[1:-1] + '/worksheet':
            raise ArchiveError('不能预览外部或非表格工作表')
        target = relation.get('Target', '')
        target = safe_name(target[1:] if target.startswith('/xl/') else 'xl/' + target)
        if not target.startswith('xl/'):
            raise ArchiveError('工作表路径无效')
        shared = []
        if 'xl/sharedStrings.xml' in mapping:
            shared = [''.join(n.itertext()) for n in xml('xl/sharedStrings.xml').findall(_S + 'si')]
        cells, max_row, max_col, truncated, text_size = {}, 0, 0, False, 0
        table = xml(target)
        for row in table.findall(_S + 'sheetData/' + _S + 'row'):
            for cell in row.findall(_S + 'c'):
                match = re.fullmatch(r'([A-Z]{1,3})([1-9][0-9]{0,6})', cell.get('r', ''))
                if not match:
                    raise ArchiveError('工作表单元格坐标无效')
                col = 0
                for letter in match[1]:
                    col = col * 26 + ord(letter) - 64
                r = int(match[2])
                if r > 200 or col > 50:
                    truncated = True
                    continue
                value = cell.findtext(_S + 'v')
                kind = cell.get('t')
                if cell.find(_S + 'f') is not None and value is None:
                    value = '公式结果未缓存'
                elif kind == 's':
                    if value is None or not value.isdigit() or int(value) >= len(shared):
                        raise ArchiveError('工作表共享字符串索引无效')
                    value = shared[int(value)]
                elif kind == 'inlineStr':
                    value = ''.join(n.text or '' for n in cell.findall('.//' + _S + 't'))
                elif kind == 'b':
                    value = 'TRUE' if value == '1' else 'FALSE'
                value = value or ''
                text_size += len(value.encode('utf-8'))
                if text_size > _TEXT_LIMIT:
                    raise ArchiveError('工作表预览文本超过 2 MiB，请下载查看', 413)
                cells[r, col] = value
                max_row, max_col = max(max_row, r), max(max_col, col)
        return {'sheets': [s.get('name', '工作表') for s in sheets], 'sheet': sheet,
                'rows': [[cells.get((r, c), '') for c in range(1, max_col + 1)] for r in range(1, max_row + 1)],
                'truncated': truncated}


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
