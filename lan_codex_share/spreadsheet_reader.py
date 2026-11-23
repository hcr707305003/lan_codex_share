"""Inert Excel readers shared by upload extraction and bounded table previews."""
from pathlib import Path
import re

from defusedxml.ElementTree import fromstring

from .archive_reader import ArchiveError, checked_archive, safe_name

_S = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
_R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
_TEXT_LIMIT = 2 * 1024 * 1024


def _xlsx(path, sheet, *, consume=None):
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
        # OPC allows an extension Default when a part has no explicit Override.
        # An explicit non-XLSX type must never fall back to the default.
        overrides = [node.get('ContentType') for node in content_types
                     if node.tag.rsplit('}', 1)[-1] == 'Override'
                     and node.get('PartName') == '/xl/workbook.xml']
        defaults = [node.get('ContentType') for node in content_types
                    if node.tag.rsplit('}', 1)[-1] == 'Default'
                    and node.get('Extension', '').lower() == 'xml']
        workbook_types = overrides if overrides else defaults
        if len(workbook_types) != 1 or workbook_types[0] != expected:
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
                if consume is None and (r > 200 or col > 50):
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
                if consume is not None:
                    if value:
                        consume(r, col, value)
                    continue
                text_size += len(value.encode('utf-8'))
                if text_size > _TEXT_LIMIT:
                    raise ArchiveError('工作表预览文本超过 2 MiB，请下载查看', 413)
                cells[r, col] = value
                max_row, max_col = max(max_row, r), max(max_col, col)
        return {'sheets': [s.get('name', '工作表') for s in sheets], 'sheet': sheet,
                'rows': [[cells.get((r, c), '') for c in range(1, max_col + 1)] for r in range(1, max_row + 1)],
                'truncated': truncated}


def _xls(path, sheet, *, consume=None):
    import xlrd

    with Path(path).open('rb') as stream:
        if stream.read(8) != b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
            raise ArchiveError('不是有效的 XLS 工作簿，请另存为 XLSX 后上传')
    try:
        book = xlrd.open_workbook(str(path), on_demand=True)
    except xlrd.XLRDError as exc:
        raise ArchiveError('XLS 损坏、已加密或格式不受支持，请另存为 XLSX 后上传') from exc
    try:
        if book.nsheets > 200:
            raise ArchiveError('XLS 工作表数量超过 200 张', 413)
        if not isinstance(sheet, int) or not 0 <= sheet < book.nsheets:
            raise ArchiveError('工作表索引无效')
        table = book.sheet_by_index(sheet)
        rows, text_size = [], 0
        for r in range(table.nrows if consume else min(table.nrows, 200)):
            values = []
            for c in range(table.row_len(r) if consume else min(table.row_len(r), 50)):
                cell = table.cell(r, c)
                value = cell.value
                if cell.ctype == xlrd.XL_CELL_DATE:
                    value = xlrd.xldate_as_datetime(value, book.datemode).isoformat(sep=' ')
                elif cell.ctype == xlrd.XL_CELL_BOOLEAN:
                    value = 'TRUE' if value else 'FALSE'
                elif cell.ctype == xlrd.XL_CELL_ERROR:
                    value = xlrd.error_text_from_code.get(value, '#ERROR!')
                elif cell.ctype == xlrd.XL_CELL_NUMBER and value.is_integer():
                    value = int(value)
                value = str(value)
                if consume is not None:
                    if value:
                        consume(r + 1, c + 1, value)
                else:
                    text_size += len(value.encode('utf-8'))
                    if text_size > _TEXT_LIMIT:
                        raise ArchiveError('工作表预览文本超过 2 MiB，请下载查看', 413)
                    values.append(value)
            if consume is None:
                rows.append(values)
        return {'sheets': book.sheet_names(), 'sheet': sheet, 'rows': rows,
                'truncated': table.nrows > 200 or table.ncols > 50}
    finally:
        book.release_resources()


def read_spreadsheet(path, sheet=0, *, consume=None):
    reader = _xls if Path(path).suffix.lower() == '.xls' else _xlsx
    return reader(path, sheet, consume=consume)


def extract_spreadsheet(path, max_text):
    """Bound the model excerpt, never reject a workbook for its text volume."""
    blocks, length = [], 0
    has_values = False
    truncated = False

    def append(text):
        nonlocal length, truncated
        remaining = max_text - length - 1
        if len(text) > max(0, remaining):
            truncated = True
            text = text[:max(0, remaining)]
        if not text:
            return False
        length += len(text) + 1
        blocks.append(text)
        return True

    def consume(row, column, value):
        nonlocal has_values
        has_values = True
        letters = ''
        while column:
            column, remainder = divmod(column - 1, 26)
            letters = chr(65 + remainder) + letters
        append(f'{letters}{row}\t{value}')

    sheet, names = 0, None
    while names is None or sheet < len(names):
        start = len(blocks)
        result = read_spreadsheet(path, sheet, consume=consume)
        names = result['sheets']
        if not names:
            break
        if append(f'[工作表：{names[sheet]}]'):
            heading = blocks.pop()
            blocks.insert(start, heading)
        sheet += 1
    if not has_values:
        raise ValueError('工作簿没有可提取的单元格内容')
    warning = '按工作表提取单元格保存值，不执行公式、宏或外部链接；公式未保存结果时会标记，日期可能显示原始数值。不含样式、图片、图表和批注。'
    if truncated:
        warning = '表格较大，随消息提供的是内容节选；完整原文件已保留并提供给 Codex，可按需读取全部工作表，无需拆表。' + warning
    return {'text': '\n'.join(blocks), 'text_truncated': truncated,
            'sheet_names': names, 'warning': warning}
