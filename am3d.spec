# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 3D MASTER:2005 beta."""

import sys
from pathlib import Path

sys.setrecursionlimit(5000)

block_cipher = None

# Every path below is resolved against the spec file's own directory
# (SPECPATH), not the working directory PyInstaller happens to be invoked
# from: `pyinstaller /path/to/am3d.spec` run from anywhere else used to
# produce a build silently missing the theme, the bundled Examples and the
# recipe docs, because those relative datas resolved to nothing.
ROOT = Path(SPECPATH).resolve()


def _data(rel, dest):
    src = ROOT / rel
    if not src.exists():
        raise SystemExit(f"am3d.spec: required data file missing: {src}")
    return (str(src), dest)


# Icon path (optional)
icon_path = str(ROOT / "am3d/ui/icon.ico")
if not Path(icon_path).exists():
    icon_path = None

a = Analysis(
    [str(ROOT / "am3d/ui/__main__.py")],
    pathex=[],
    binaries=[],
    datas=[
        _data("am3d/ui/theme_am2005.qss", "am3d/ui"),
        # MainWindow._example_projects() (am3d/ui/app.py) resolves the
        # bundled Examples via Path(__file__).resolve().parents[2] / "assets"
        # -- in a frozen build that's <dist>/_internal/assets, not the repo's
        # top-level assets/. Without this, the packaged app silently shows
        # "(No examples installed)" even though build_windows.ps1 separately
        # copies assets/ into the release folder for human browsing.
        _data("assets", "assets"),
        # Recipe schema/agent guide referenced by docs/recipes/ -- bundled
        # for reference alongside the packaged app, per Phase 6's "bundle
        # ... recipe schema/agent guide" requirement.
        _data("docs/recipes/recipe-v1.schema.json", "docs/recipes"),
        _data("docs/recipes/EXTERNAL_AGENT_GUIDE.md", "docs/recipes"),
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
