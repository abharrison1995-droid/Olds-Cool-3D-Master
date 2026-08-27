# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 3D MASTER:2005 beta."""

import sys
from pathlib import Path

sys.setrecursionlimit(5000)

block_cipher = None

# Icon path (optional)
icon_path = "am3d/ui/icon.ico"
if not Path(icon_path).exists():
    icon_path = None

a = Analysis(
    ["am3d/ui/__main__.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("am3d/ui/theme_am2005.qss", "am3d/ui"),
    ],
    hiddenimports=[
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
        "numpy",
        "msgpack",
        "moderngl",
        "PIL",
        "PIL.Image",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "matplotlib",
        "cv2",
        "tensorflow",
        "torch",
        "IPython",
        "jupyter",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="3D MASTER 2005",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon_path,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="3D MASTER 2005 Beta",
)
