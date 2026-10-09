from io import BytesIO
import zipfile

import pytest

from lan_codex_share.archive_reader import ArchiveError, inspect_archive
from lan_codex_share.archive_preview import preview_member


def xlsx_bytes(sheet_xml=None, extra=()):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>')
        z.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="方案" sheetId="1" r:id="r1"/><sheet name="空表" sheetId="2" r:id="r2"/></sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels', '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/><Relationship Id="r2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr('xl/worksheets/sheet1.xml', sheet_xml or '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="1"><c r="A1"><f>1+1</f></c><c r="B1"><f>2+2</f><v>4</v></c><c r="C1" t="inlineStr"><is><t>标题</t></is></c></row></sheetData></worksheet>')
        z.writestr('xl/worksheets/sheet2.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData/></worksheet>')
        for name, value in extra:
            z.writestr(name, value)
    return stream.getvalue()


def preview(tmp_path, name, data, sheet=0):
    path = tmp_path / 'test.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr(name, data)
    return preview_member(str(path), inspect_archive(str(path))['version'], 0, sheet)


def test_xlsx_formula_cache_and_sheet_selection(tmp_path):
    result = preview(tmp_path, '方案.xlsx', xlsx_bytes())
    assert result['kind'] == 'spreadsheet'
    assert result['rows'] == [['公式结果未缓存', '4', '标题']]
    assert result['sheets'] == ['方案', '空表']
    assert preview(tmp_path, '方案.xlsx', xlsx_bytes(), sheet=1)['rows'] == []


def test_sparse_sheet_is_bounded(tmp_path):
    sheet = '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row r="999999"><c r="ZZZ999999"><v>2</v></c></row><row r="1"><c r="A1" t="b"><v>1</v></c></row></sheetData></worksheet>'
    result = preview(tmp_path, 'large.xlsx', xlsx_bytes(sheet))
    assert result['truncated'] and result['rows'] == [['TRUE']]


@pytest.mark.parametrize('extra', [[('xl/vbaProject.bin', b'macro')], [('bad/../x', b'x')]])
def test_office_unsafe_parts_rejected(tmp_path, extra):
    with pytest.raises(ArchiveError):
        preview(tmp_path, 'bad.xlsx', xlsx_bytes(extra=extra))


def test_xml_entity_rejected(tmp_path):
    with pytest.raises(ArchiveError):
        preview(tmp_path, 'bad.xlsx', xlsx_bytes('<!DOCTYPE x [<!ENTITY x "boom">]><x>&x;</x>'))


@pytest.mark.parametrize('name,data,kind', [('a.md', b'# hi', 'markdown'), ('a.html', b'<script>bad</script>', 'code'),
    ('a.png', b'png', 'image'), ('a.pdf', b'%PDF-1.4', 'pdf'), ('a.zip', b'zip', 'download'), ('a.xlsm', b'macro', 'download')])
def test_member_types(tmp_path, name, data, kind):
    assert preview(tmp_path, name, data)['kind'] == kind


def test_docx_text(tmp_path):
    stream = BytesIO()
    with zipfile.ZipFile(stream, 'w') as z:
        z.writestr('[Content_Types].xml', '<Types><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>你好</w:t></w:r></w:p></w:body></w:document>')
    result = preview(tmp_path, 'a.docx', stream.getvalue())
    assert result['content'] == '你好'
