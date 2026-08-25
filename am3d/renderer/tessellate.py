"""Spline tessellation and normal estimation (renderer foundation).

In the pure-spline pipeline there are **no polygon meshes** in the data
model — geometry exists only as B-spline control nets.  This module turns a
Project's patch / spline objects into the triangle soup the GPU consumes at
render time, then estimates smooth vertex normals so the surface looks
continuous regardless of tessellation density.

This is the bridge between the spline kernel (tiny files) and the multi-pass
rasterizer (dense geometry).
"""

from __future__ import annotations

import numpy as np

from am3d.spline import kernel

from am3d.core.project import Project


class MeshData:
    """A triangulated result ready for GPU upload."""

    def __init__(self, vertices, indices, normals=None, uvs=None, name="mesh"):
        self.vertices = np.asarray(vertices, dtype=np.float64).reshape(-1, 3)
        self.indices = np.asarray(indices, dtype=np.int64).reshape(-1, 3)
        if uvs is None:
            uvs = np.zeros((len(self.vertices), 2), dtype=np.float64)
        self.uvs = np.asarray(uvs, dtype=np.float64).reshape(-1, 2)
        self.normals = normals if normals is not None else self.compute_normals()
        self.name = name

    def compute_normals(self):
        """Angle-weighted smooth vertex normals via face accumulation."""
        tri = self.vertices[self.indices]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        unit = n / np.maximum(np.linalg.norm(n, axis=1), 1e-12)[:, None]
        # Weight each (unit) face normal by the corner angle at the vertex.
        vn = np.zeros_like(self.vertices)
        for c in range(3):
            a = tri[:, (c + 1) % 3] - tri[:, c]
            b = tri[:, (c + 2) % 3] - tri[:, c]
            denom = np.linalg.norm(a, axis=1) * np.linalg.norm(b, axis=1)
            cos = np.einsum("ij,ij->i", a, b) / np.maximum(denom, 1e-12)
            ang = np.arccos(np.clip(cos, -1.0, 1.0))
            np.add.at(vn, self.indices[:, c], unit * ang[:, None])
        n_len = np.linalg.norm(vn, axis=1, keepdims=True)
        return vn / np.maximum(n_len, 1e-12)


def tessellate_splines(splines):
    """Tessellate an iterable of :class:`Spline` into a single mesh.

    Closed splines are treated as rings (fanned from their centroid);
    open splines become polylines.
    """
    out_v = []
    out_u = []
    out_t = []
    offset = 0
    for spl in splines:
        pts = spl.point_array()
        if len(pts) < 3:
            continue
        deg = min(max(spl.degree, 1), 3, len(pts) - 1)
        knots = kernel.make_clamped_knots(deg, len(pts))
        if spl.closed:
            samples = kernel.eval_curve(np.linspace(0.0, 1.0, 65), deg, knots, pts)
            centroid = samples.mean(axis=0)
            n = samples.shape[0]
            ring_idx = offset
            c_idx = offset + n
            out_v.append(samples)
            out_v.append(centroid[None, :])
            # ring UVs: u along the curve, v=1; centroid sits at v=0
            ring_uv = np.stack([np.linspace(0.0, 1.0, n),
                                np.ones(n)], axis=1)
            out_u.append(ring_uv)
            out_u.append(np.array([[0.5, 0.0]]))
            for i in range(n - 1):
                out_t.append([c_idx, ring_idx + i, ring_idx + i + 1])
            offset += n + 1
        else:
            samples = kernel.eval_curve(np.linspace(0.0, 1.0, 33), deg, knots, pts)
            m = samples.shape[0]
            out_v.append(samples)
            out_u.append(np.stack([np.linspace(0.0, 1.0, m),
                                   np.full(m, 0.5)], axis=1))
            offset += m
    if not out_v:
        return MeshData(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    v = np.concatenate(out_v, axis=0)
    uv = np.concatenate(out_u, axis=0) if out_u else None
    t = np.array(out_t, dtype=np.int64).reshape(-1, 3) if out_t else \
        np.zeros((0, 3), dtype=np.int64)
    return MeshData(v, t, uvs=uv)


def tessellate_object(obj, nu=16, nv=16):
    """Tessellate an Object3D: patches become grids, splines become rings.

    Each patch receives its own parameter-space UVs, then all patches of the
    object are packed into a shared grid atlas so one texture can cover the
    whole object.
    """
    from .uv_mapping import atlas_grid_layout, patch_uvs

    patch_items = [(p.name, p.interior) for p in obj.patches
                   if p.interior is not None]
    cells = atlas_grid_layout(len(patch_items))

    all_v = []
    all_u = []
    all_t = []
    offset = 0

    for (pname, interior), cell in zip(patch_items, cells):
        v, t = kernel.build_patch_grid(interior, nu=nu, nv=nv)
        uv = patch_uvs(nu, nv)
        if cell is not None:
            ou, ov, su, sv = cell
            uv = uv * np.array([su, sv]) + np.array([ou, ov])
        all_v.append(v)
        all_u.append(uv)
        all_t.append(t + offset)
        offset += v.shape[0]

    for spl in obj.splines.values():
        m = tessellate_splines([spl])
        all_v.append(m.vertices)
        all_u.append(m.uvs)
        all_t.append(m.indices + offset)
        offset += m.vertices.shape[0]

    if not all_v:
        return MeshData(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    return MeshData(np.concatenate(all_v), np.concatenate(all_t),
                    uvs=np.concatenate(all_u))


def tessellate_project(project: Project, nu=16, nv=16):
    """Tessellate every object in a Project; returns dict name -> MeshData."""
    return {name: tessellate_object(obj, nu, nv)
            for name, obj in project.objects.items()}