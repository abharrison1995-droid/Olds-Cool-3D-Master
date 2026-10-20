# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for 3D MASTER:2005 beta."""

import os
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
BUILD_PLATFORM = ("windows" if sys.platform == "win32" else
                  "linux" if sys.platform.startswith("linux") else None)
if BUILD_PLATFORM is None:
    raise SystemExit("am3d.spec: V1 frozen GUI builds are supported only on Windows and Linux")

IDENTITY_PATH = Path(os.environ.get(
    "AM3D_BUILD_IDENTITY_PATH",
    str(ROOT / "build" / BUILD_PLATFORM / "build_identity.json"),
)).resolve()
EXPECTED_IDENTITY_PATH = (ROOT / "build" / BUILD_PLATFORM /
                          "build_identity.json").resolve()
if IDENTITY_PATH != EXPECTED_IDENTITY_PATH or not IDENTITY_PATH.is_file():
    raise SystemExit("am3d.spec: generated build identity is missing from the platform build directory")

try:
    import certifi
except ImportError as exc:
    raise SystemExit("am3d.spec: certifi is required for bundled HTTPS trust") from exc
CA_BUNDLE = Path(certifi.where()).resolve()
if not CA_BUNDLE.is_file():
    raise SystemExit("am3d.spec: certifi CA bundle is missing")


def _data(rel, dest):
    src = ROOT / rel
    if not src.exists():
        raise SystemExit(f"am3d.spec: required data file missing: {src}")
    return (str(src), dest)


def _keyring_imports():
    if sys.platform == "win32":
        return [
            "keyring.backends.Windows",
            "win32ctypes",
            "win32ctypes.pywin32",
            "win32ctypes.pywin32.win32api",
            "win32ctypes.pywin32.win32cred",
        ]
    return [
        "keyring.backends.SecretService",
        "secretstorage",
        "secretstorage.util",
        "jeepney",
        "jeepney.io.async_",
        "cryptography",
        "cryptography.hazmat.bindings._rust",
    ]


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
        _data("docs/QUICK_START.md", "docs"),
        (str(IDENTITY_PATH), "am3d"),
        (str(CA_BUNDLE), "certifi"),
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
        "httpx",
        "httpcore",
        "h11",
        "anyio",
        "certifi",
        "idna",
        "keyring",
        *_keyring_imports(),
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # These are reachable only through build/test/command-line helpers in
        # the locked development environment, not through the desktop product:
        # AnyIO's TestRunner imports pytest outcomes lazily, HTTPX's optional
        # console command imports Pygments, and packaging/setuptools are
        # pulled by those paths or PyInstaller's build-time distutils shim.
        "pytest",
        "_pytest",
        "anyio.pytest_plugin",
        "httpx._main",
        "pygments",
        "packaging",
        "setuptools",
        "_distutils_hack",
        "distutils",
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

# PyInstaller's stock PySide6 runtime hook initializes Qt before the frozen
# entry point runs. The fixed worker and offline self-test must dispatch before
# Qt is imported, so keep the stock hook's normal GUI behavior in our guarded
# hook and substitute only that exact generated runtime-hook entry.
_pyside6_hook_path = ROOT / "scripts" / "pyi_rth_am3d_pyside6.py"
_pyside6_hook_indexes = [
    index for index, entry in enumerate(a.scripts)
    if entry[0] == "pyi_rth_pyside6"
]
if len(_pyside6_hook_indexes) != 1 or not _pyside6_hook_path.is_file():
    raise SystemExit("am3d.spec: expected exactly one PySide6 runtime hook to guard")
_pyside6_hook_index = _pyside6_hook_indexes[0]
_pyside6_hook_entry = a.scripts[_pyside6_hook_index]
a.scripts[_pyside6_hook_index] = (
    _pyside6_hook_entry[0], str(_pyside6_hook_path), _pyside6_hook_entry[2]
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
