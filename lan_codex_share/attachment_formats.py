"""Shared attachment format policy; source code is always inert user material."""
from pathlib import Path

TEXT_EXTENSIONS = frozenset('.md .txt .html .htm .css .js .ts .jsx .tsx .vue .py .java .go .php .sh .ps1 .json .yaml .yml .toml .xml .csv .sql .log .svg'.split())
ARCHIVE_EXTENSIONS = frozenset({'.zip', '.tar.gz'})
FILE_EXTENSIONS = TEXT_EXTENSIONS | ARCHIVE_EXTENSIONS | {'.xlsx', '.xls'}
FORMAT_HINT = '图片、源码、配置、数据、日志、SVG、MD、TXT、HTML、DOCX、PDF、XLSX、XLS、ZIP、TAR.GZ；旧 DOC 请转为 DOCX'


def extension_of(path):
    return '.tar.gz' if str(path).lower().endswith('.tar.gz') else Path(path).suffix.lower()
