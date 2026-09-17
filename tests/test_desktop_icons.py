import os
from pathlib import Path
import struct

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
import pytest
pytest.importorskip('PySide6')
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from lan_codex_share.desktop.icons import asset_path, app_icon, ui_icon


def test_runtime_icons_are_cwd_independent(tmp_path, monkeypatch):
    app = QApplication.instance() or QApplication([])
    monkeypatch.chdir(tmp_path)
    assert asset_path('app-icon.svg').is_file()
    assert not app_icon().pixmap(16, 16).isNull()
    assert not ui_icon('settings', '#123456').pixmap(24, 24).isNull()


def test_generated_platform_containers():
    ico = asset_path('app-icon.ico').read_bytes()
    assert struct.unpack_from('<HHH', ico) == (0, 1, 7)
    for i, size in enumerate((16, 24, 32, 48, 64, 128, 256)):
        w, h, _, _, planes, bits, length, offset = struct.unpack_from('<BBBBHHII', ico, 6 + i * 16)
        assert (w or 256, h or 256, planes, bits) == (size, size, 1, 32)
        assert QImage.fromData(ico[offset:offset + length]).width() == size
    icns = asset_path('app-icon.icns').read_bytes()
    assert icns[:4] == b'icns'
    assert struct.unpack_from('>I', icns, 4)[0] == len(icns)
    offset, chunks = 8, []
    while offset < len(icns):
        length = struct.unpack_from('>I', icns, offset + 4)[0]
        assert length > 8
        assert not QImage.fromData(icns[offset + 8:offset + length]).isNull()
        chunks.append(icns[offset:offset + 4])
        offset += length
    assert chunks == [b'icp4', b'icp5', b'icp6', b'ic07', b'ic08', b'ic09', b'ic10']
    assert offset == len(icns)
    assert QImage(str(asset_path('app-icon.png'))).width() == 512


def test_specs_use_same_icon_assets():
    root = Path(__file__).resolve().parents[1]
    desktop = (root / 'lan_codex_desktop.spec').read_text()
    share = (root / 'lan_codex_share.spec').read_text()
    assert 'app-icon.ico' in desktop and 'app-icon.icns' in desktop
    assert 'lan_codex_share/desktop/assets' in desktop
    assert 'app-icon.ico' in share
    compile(desktop, 'lan_codex_desktop.spec', 'exec')
    compile(share, 'lan_codex_share.spec', 'exec')
