"""Generate platform icons from the package SVG, offline (requires desktop deps)."""
import os
from pathlib import Path
import struct

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QImage, QPainter
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QApplication


ASSETS = Path(__file__).resolve().parents[1] / 'lan_codex_share' / 'desktop' / 'assets'


def render_png(source, size):
    renderer = QSvgRenderer(str(source))
    if not renderer.isValid():
        raise ValueError('Invalid application icon SVG')
    image = QImage(size, size, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    renderer.render(painter)
    painter.end()
    payload = QByteArray()
    buffer = QBuffer(payload)
    buffer.open(QIODevice.WriteOnly)
    if not image.save(buffer, 'PNG'):
        raise ValueError('PNG export failed')
    return bytes(payload)


def ico_bytes(images):
    offset = 6 + 16 * len(images)
    entries, payloads = [], []
    for size, payload in images:
        entries.append(struct.pack('<BBBBHHII', size % 256, size % 256, 0, 0, 1, 32, len(payload), offset))
        payloads.append(payload)
        offset += len(payload)
    return struct.pack('<HHH', 0, 1, len(images)) + b''.join(entries + payloads)


def icns_bytes(images):
    types = {16: b'icp4', 32: b'icp5', 64: b'icp6', 128: b'ic07', 256: b'ic08', 512: b'ic09', 1024: b'ic10'}
    chunks = b''.join(types[size] + struct.pack('>I', len(data) + 8) + data for size, data in images if size in types)
    return b'icns' + struct.pack('>I', len(chunks) + 8) + chunks


def main():
    app = QApplication.instance() or QApplication([])
    images = [(size, render_png(ASSETS / 'app-icon.svg', size)) for size in (16, 24, 32, 48, 64, 128, 256, 512, 1024)]
    (ASSETS / 'app-icon.png').write_bytes(dict(images)[512])
    (ASSETS / 'app-icon.ico').write_bytes(ico_bytes([(s, p) for s, p in images if s <= 256]))
    (ASSETS / 'app-icon.icns').write_bytes(icns_bytes(images))
    print('Generated PNG, ICO and ICNS from app-icon.svg (no application package built).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
