"""PySide6 UI for 3D MASTER:2005 (four-mode workspace).

Entry point: ``python -m am3d.ui.app`` or the ``am3d`` console script.
"""

from __future__ import annotations

from .app import main, MainWindow  # noqa: F401

__all__ = ["main", "MainWindow"]