"""PySide6 UI for 3D MASTER:2005 (four-mode workspace).

Entry point: ``python -m am3d.ui`` or the ``am3d`` console script. Public
application exports are loaded lazily so fixed data-only commands in
``am3d.ui.__main__`` can dispatch before importing Qt.
"""

from __future__ import annotations

__all__ = ["main", "MainWindow"]


def __getattr__(name: str):
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    from .app import MainWindow, main

    globals().update({"main": main, "MainWindow": MainWindow})
    return globals()[name]


def __dir__():
    return sorted(set(globals()) | set(__all__))
