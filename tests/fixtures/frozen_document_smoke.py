"""Build with PyInstaller to verify spawn extraction without any live service."""
if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()

    from pathlib import Path
    import tempfile
    import zipfile
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject
    from lan_codex_share.document_extract import extract_isolated
    from lan_codex_share.archive_worker import run_archive

    with tempfile.TemporaryDirectory(prefix='document-frozen-') as temporary:
        root = Path(temporary)
        text = root / 'hello.md'
        text.write_text('hello', encoding='utf-8')
        assert extract_isolated(text)['text'] == 'hello'
        docx = root / 'hello.docx'
        with zipfile.ZipFile(docx, 'w') as archive:
            archive.writestr('[Content_Types].xml', '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
            archive.writestr('word/document.xml', '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>hello</w:t></w:r></w:p></w:body></w:document>')
        assert extract_isolated(docx)['text'] == 'hello'
        writer = PdfWriter()
        page = writer.add_blank_page(width=200, height=200)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
        stream = DecodedStreamObject()
        stream.set_data(b'BT /F1 12 Tf 10 100 Td (hello pdf) Tj ET')
        page[NameObject('/Contents')] = writer._add_object(stream)
        pdf = root / 'hello.pdf'
        writer.write(pdf)
        assert 'hello pdf' in extract_isolated(pdf)['text']
        bundle = root / 'bundle.zip'
        xlsx = root / 'values.xlsx'
        with zipfile.ZipFile(xlsx, 'w') as archive:
            archive.writestr('[Content_Types].xml', '<Types><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>')
            archive.writestr('xl/workbook.xml', '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="Values" r:id="r1"/></sheets></workbook>')
            archive.writestr('xl/_rels/workbook.xml.rels', '<Relationships><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
            archive.writestr('xl/worksheets/sheet1.xml', '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData><row><c r="A1"><f>2+2</f><v>4</v></c></row></sheetData></worksheet>')
        with zipfile.ZipFile(bundle, 'w') as archive:
            archive.write(text, 'docs/hello.md')
            archive.write(docx, 'docs/hello.docx')
            archive.write(xlsx, 'docs/values.xlsx')
        listing = run_archive(str(bundle), 'list')
        version = listing['version']
        assert listing['entries'][0]['name'] == 'docs'
        assert run_archive(str(bundle), 'preview', version=version, member=0)['content'] == 'hello'
        assert run_archive(str(bundle), 'download', version=version, member=1)['data'] == docx.read_bytes()
        assert run_archive(str(bundle), 'preview', version=version, member=2)['rows'] == [['4']]
    print('MD/DOCX/PDF extraction and isolated ZIP roundtrip PASS')
