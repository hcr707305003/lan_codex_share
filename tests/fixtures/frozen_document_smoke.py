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
    print('Frozen MD/DOCX/PDF extraction PASS')
