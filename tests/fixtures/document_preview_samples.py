"""Generate public, synthetic preview samples; never use private user documents."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tests.test_document_store import docx_bytes
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject, DictionaryObject


def create_samples(root):
    root.mkdir(parents=True, exist_ok=True)
    (root / 'preview.md').write_text('# 文档预览测试\n\n| 名称 | 状态 |\n| --- | --- |\n| 上传附件 | 可预览 |\n\n<script>window.previewUnsafe = true</script>\n\n![remote](https://example.org/preview-should-not-load.png)\n', encoding='utf-8')
    (root / 'preview.txt').write_text('纯文本预览\n<script>不执行</script>\n' + '长内容自适应' * 80, encoding='utf-8')
    (root / 'preview.docx').write_bytes(docx_bytes('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Word 正文测试</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>姓名</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>示例</w:t></w:r></w:p></w:tc></w:tr></w:tbl><w:p><w:r><w:t>表格之后</w:t></w:r></w:p></w:body></w:document>'))
    writer = PdfWriter()
    page = writer.add_blank_page(width=400, height=600)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 18 Tf 40 500 Td (Document preview PDF) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    writer.write(root / 'preview.pdf')


if __name__ == '__main__':
    create_samples(Path(__file__).resolve().parents[2] / 'output' / 'playwright' / 'preview-samples')
