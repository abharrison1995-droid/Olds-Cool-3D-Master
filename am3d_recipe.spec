# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the packaged headless recipe entry point.

Builds a single-file console executable (am3d-recipe.exe) wrapping
am3d.recipes.cli:main -- the same entry point pyproject.toml's
[project.scripts] exposes as `am3d-recipe` for source installs. Packaged
separately from am3d.spec (the windowed GUI build) because the recipe
pipeline never touches PySide6/Qt or the optional GPU renderer (see
am3d/renderer/*.py -- pure numpy + Pillow), so bundling it standalone
keeps this executable small and lets an external agent invoke it without
installing Python or the GUI's Qt runtime.
"""

import sys
from pathlib import Path

sys.setrecursionlimit(5000)

block_cipher = None

a = Analysis(
    ["am3d/recipes/__main__.py"],
    pathex=[],
    binaries=[],
    datas=[
        # Bundled for reference alongside the packaged CLI, matching the
        # GUI build's am3d.spec precedent.
        ("docs/recipes/recipe-v1.schema.json", "docs/recipes"),
        ("docs/recipes/EXTERNAL_AGENT_GUIDE.md", "docs/recipes"),
    ],
    hiddenimports=[
        "numpy",
        "msgpack",
        "PIL",
        "PIL.Image",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # The recipe pipeline is pure software (numpy + Pillow) -- never
        # imports PySide6/Qt or the optional moderngl GPU renderer -- so
        # excluding them keeps this a small, self-contained console exe.
        "PySide6",
        "moderngl",
        "am3d.ui",
        "am3d.gpu",
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

# Onefile build: everything (interpreter, deps, datas) baked into one exe,
# so an external agent only needs to copy/invoke a single file -- no
# accompanying _internal/ folder to keep alongside it.
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="am3d-recipe",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
