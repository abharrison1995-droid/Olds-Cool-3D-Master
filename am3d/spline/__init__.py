"""The spline geometry kernel.

This is the mathematical heart of 3D MASTER:2005. All geometry is
defined by intersecting B-splines that form 3- and 4-sided patches.
There are **no polygon meshes** in the data model — surfaces are only
tessellated into triangles at render time, so they stay mathematically
smooth at any resolution without increasing file size.

The evaluation code lives in :mod:`am3d.spline.kernel`, which is
Numba-JIT-compiled for speed. Higher-level geometric *construction*
tools (extrusion, lathe, patch generation) live here too.
"""

from __future__ import annotations

from . import kernel  # noqa: F401
from .kernel import (  # noqa: F401
    deboor,
    basis,
    find_span,
    make_clamped_knots,
    eval_curve,
    eval_surface,
    build_patch_grid,
    build_lathe_net,
    build_extrude_net,
)

__all__ = [
    "kernel",
    "deboor",
    "basis",
    "find_span",
    "make_clamped_knots",
    "eval_curve",
    "eval_surface",
    "build_patch_grid",
    "build_lathe_net",
    "build_extrude_net",
]