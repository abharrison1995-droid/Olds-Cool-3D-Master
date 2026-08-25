"""Per-patch UV coordinate generation.

B-spline patches are tensor products, so their natural texture space is the
``(u, v)`` parameter domain: each tessellated vertex simply receives its
normalized parameter pair.  That gives seamless texturing per patch with
zero extra storage in the file — UVs are *derived*, not stored.
"""

from __future__ import annotations

import numpy as np


def patch_uvs(nu: int, nv: int) -> np.ndarray:
    """Return ``(nu*nv, 2)`` UVs matching ``build_patch_grid`` vertex order.

    Vertex order is row-major over ``(nu, nv)``, exactly as produced by
    :func:`am3d.spline.kernel.build_patch_grid`.
    """
    if nu < 1 or nv < 1:
        return np.zeros((0, 2), dtype=np.float64)
    u = np.linspace(0.0, 1.0, nu)
    v = np.linspace(0.0, 1.0, nv)
    uu, vv = np.meshgrid(u, v, indexing="ij")
    return np.stack([uu.ravel(), vv.ravel()], axis=1)


def grid_atlas_uvs(offset_u: float, offset_v: float,
                   scale_u: float = 1.0, scale_v: float = 1.0):
    """Wrap :func:`patch_uvs` values into an atlas cell.

    ``final_uv = offset + uv * scale`` — used to pack many patches into one
    shared 0..1 atlas without touching geometry.
    """
    def _map(uvs: np.ndarray) -> np.ndarray:
        out = uvs * np.array([scale_u, scale_v], dtype=np.float64)
        out += np.array([offset_u, offset_v], dtype=np.float64)
        return out
    return _map


def atlas_grid_layout(count: int, columns: int | None = None):
    """Plan a simple grid atlas for *count* patches.

    Returns a list of ``(offset_u, offset_v, scale_u, scale_v)`` tuples — one
    per patch — tiling them left-to-right, top-to-bottom inside 0..1.
    """
    if count <= 0:
        return []
    cols = columns if columns and columns > 0 else int(np.ceil(np.sqrt(count)))
    rows = int(np.ceil(count / cols))
    su, sv = 1.0 / cols, 1.0 / rows
    cells = []
    for i in range(count):
        col, row = i % cols, i // cols
        cells.append((col * su, 1.0 - (row + 1) * sv, su, sv))
    return cells