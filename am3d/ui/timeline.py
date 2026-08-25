"""Compatibility shim — the timeline is now the dope sheet.

:class:`TimelineDock` lives in :mod:`am3d.ui.dopesheet` (Phase 5); this
module re-exports it so older imports keep working.
"""

from .dopesheet import TimelineDock  # noqa: F401
