"""Viewport widget: renders the tessellated project with orbit/pan/zoom.

Compatibility shim — the implementation now lives in
:mod:`am3d.ui.viewport3d`; the module and class names are kept so existing
imports (``from am3d.ui.viewport import Viewport``) keep working.
"""

from __future__ import annotations

from .viewport3d import Viewport

__all__ = ["Viewport"]
