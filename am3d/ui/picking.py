"""CPU ray-cast picking (pure numpy, no Qt — headless-testable).

Vectorized Möller–Trumbore ray/triangle intersection over tessellated
meshes, used by the viewport to pick objects from click positions.
"""

from __future__ import annotations

import numpy as np


def ray_triangles(origin, direction, vertices, indices):
    """Intersect one ray with a triangle soup.

    Returns an ``(T,)`` array of hit distances (``np.inf`` for misses).
    Triangles are treated as double-sided.
    """
    v = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
    tris = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
    if len(v) == 0 or len(tris) == 0:
        return np.full(len(tris), np.inf)
    o = np.asarray(origin, dtype=np.float64).reshape(3)
    d = np.asarray(direction, dtype=np.float64).reshape(3)

    v0, v1, v2 = v[tris[:, 0]], v[tris[:, 1]], v[tris[:, 2]]
    e1 = v1 - v0
    e2 = v2 - v0
    p = np.cross(d, e2)
    det = np.einsum("ij,ij->i", e1, p)

    t_out = np.full(len(tris), np.inf)
    ok = np.abs(det) > 1e-12
    if not ok.any():
        return t_out
    inv = 1.0 / det[ok]
    tv = o - v0[ok]
    u = np.einsum("ij,ij->i", tv, p[ok]) * inv
    q = np.cross(tv, e1[ok])
    vv = np.einsum("j,ij->i", d, q) * inv
    t = np.einsum("ij,ij->i", e2[ok], q) * inv
    hit = (u >= 0.0) & (vv >= 0.0) & (u + vv <= 1.0) & (t > 1e-9)
    idx = np.flatnonzero(ok)
    t_out[idx[hit]] = t[hit]
    return t_out


def pick_object(meshes: dict, origin, direction):
    """Nearest-hit object name in a ``name -> MeshData`` dict, or None."""
    best_name = None
    best_t = np.inf
    for name, mesh in meshes.items():
        t = ray_triangles(origin, direction, mesh.vertices, mesh.indices)
        if len(t) and t.min() < best_t:
            best_t = t.min()
            best_name = name
    return best_name
