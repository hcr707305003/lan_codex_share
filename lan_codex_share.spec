# -*- mode: python ; coding: utf-8 -*-

import os
from pathlib import Path


project_root = Path(SPECPATH)
analysis = Analysis(
    [str(project_root / "run_lan_codex_share.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=[(str(project_root / "lan_codex_share" / "web"), "lan_codex_share/web")],
    hiddenimports=["fcntl"] if os.name != "nt" else [],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="lan_codex_share",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
