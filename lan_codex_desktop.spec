# -*- mode: python ; coding: utf-8 -*-
import sys
import re
from pathlib import Path
from importlib.metadata import distribution

project_root = Path(SPECPATH)
icon_directory = project_root / 'lan_codex_share' / 'desktop' / 'assets'
licenses = []
for package in ("PySide6", "PySide6_Essentials", "shiboken6", "tomlkit", "PyYAML"):
    dist = distribution(package)
    for file in dist.files or []:
        if "license" in str(file).lower() or "copying" in str(file).lower():
            source = Path(dist.locate_file(file))
            if source.is_file():
                licenses.append((str(source), "licenses/" + package + "/" + str(file.parent)))
license_directory = project_root / "build" / "desktop-licenses"
if not (license_directory / "LGPL-3.0-only.txt").is_file():
    raise RuntimeError("Run python scripts/prepare_desktop_licenses.py before the desktop build")
licenses.append((str(license_directory), "licenses/Qt"))
licenses.append((str(project_root / "THIRD_PARTY_DESKTOP.md"), "licenses"))
licenses.append((str(icon_directory), 'lan_codex_share/desktop/assets'))

a = Analysis([str(project_root / "run_lan_codex_desktop.py")], pathex=[str(project_root)],
             binaries=[], datas=licenses, hiddenimports=[], hookspath=[], hooksconfig={},
             runtime_hooks=[], excludes=["PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineQuick"], noarchive=False)
if sys.platform == "win32":
    # Qt 6.11 uses the Windows ICU API. Conda ICU DLLs found on PATH expose a
    # different ABI and must not shadow the operating system's ICU libraries.
    a.binaries = [entry for entry in a.binaries
                  if not re.fullmatch(r"icu(?:uc|in|dt)\d*\.dll", Path(entry[0]).name, re.IGNORECASE)]
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="lan_codex_desktop", debug=False,
          bootloader_ignore_signals=False, strip=False, upx=False, console=False,
          disable_windowed_traceback=False, argv_emulation=False, target_arch=None,
          codesign_identity=None, entitlements_file=None,
          icon=str(icon_directory / 'app-icon.ico') if sys.platform == 'win32' else None)
collection = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="lan_codex_desktop")
if sys.platform == "darwin":
    app = BUNDLE(collection, name="LAN Codex Share.app", bundle_identifier="org.lancodexshare.desktop",
                 icon=str(icon_directory / 'app-icon.icns'))
