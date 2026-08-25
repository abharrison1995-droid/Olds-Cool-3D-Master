"""Tests for the renderer tessellation bridge."""

from __future__ import annotations

import numpy as np

from am3d.core.project import Spline, ControlPoint
from am3d.renderer.tessellate import (
    MeshData,
    tessellate_object,
    tessellate_project,
    tessellate_splines,
)
from am3d.core.project import Project


def _square_spline():
    # A closed cubic square: 4 corners, closed ring.
    return Spline(name="square", closed=True, cps=[
        ControlPoint([0, 0, 0]), ControlPoint([1, 0, 0]),
        ControlPoint([1, 1, 0]), ControlPoint([0, 1, 0]),
    ])


def test_mesh_normals_unit_length():
    m = tessellate_splines([_square_spline()])
    assert m.vertices.shape[1] == 3
    assert m.normals.shape == m.vertices.shape
    lens = np.linalg.norm(m.normals, axis=1)
    assert np.allclose(lens, 1.0, atol=1e-6)


def test_mesh_normals_angle_weighted():
    # Vertex 0 is shared by a large +Z-facing triangle and a small +X-facing
    # one; both corner angles are pi/2, so the angle-weighted normal is the
    # normalized sum of the two *unit* face normals — face area must not
    # bias it (the old area-squared weighting would lean toward +Z).
    verts = np.array([[0, 0, 0], [2, 0, 0], [0, 2, 0], [0, 0, 1]],
                     dtype=np.float64)
    idx = np.array([[0, 1, 2], [0, 2, 3]])
    m = MeshData(verts, idx)
    expected = np.array([1.0, 0.0, 1.0]) / np.sqrt(2.0)
    assert np.allclose(m.normals[0], expected, atol=1e-9)


def test_short_spline_degree_clamped_to_point_count():
    # A 3-point spline asking for degree 3 must fall back to degree 2
    # instead of crashing in make_clamped_knots.
    spl = Spline(name="tri", closed=True, degree=3, cps=[
        ControlPoint([0, 0, 0]), ControlPoint([1, 0, 0]),
        ControlPoint([0, 1, 0]),
    ])
    m = tessellate_splines([spl])
    assert m.vertices.shape[0] > 0


def test_mesh_triangles_valid():
    m = tessellate_splines([_square_spline()])
    assert m.indices.shape[1] == 3
    assert m.indices.max() < m.vertices.shape[0]
    assert m.indices.min() >= 0


def test_tessellate_project_returns_mesh_per_object():
    p = Project()
    obj = p.create_object("plate")
    obj.add_spline(_square_spline())
    result = tessellate_project(p)
    assert "plate" in result
    assert result["plate"].vertices.shape[0] > 0


def test_tessellate_object_with_lathed_patch():
    p = Project()
    obj = p.create_object("vase")
    from am3d.spline import kernel
    profile = np.array([[0.5, 0.0], [1.0, 1.0], [0.6, 2.0], [0.4, 2.5]])
    net = kernel.build_lathe_net(profile, axis="y", sections=16)
    from am3d.core.project import Patch
    obj.patches.append(Patch(name="p", splines=[], interior=net))
    m = tessellate_object(obj, nu=12, nv=6)
    assert m.vertices.shape[0] == 12 * 6
    assert m.indices.shape[0] == (12 - 1) * (6 - 1) * 2


# ---------------------------------------------------------------------------
# UV mapping
# ---------------------------------------------------------------------------
def test_patch_uvs_shape_and_corners():
    from am3d.renderer.uv_mapping import patch_uvs
    uv = patch_uvs(4, 3)
    assert uv.shape == (12, 2)
    # row-major: first vertex is (u=0, v=0), last is (u=1, v=1)
    assert np.allclose(uv[0], [0, 0])
    assert np.allclose(uv[-1], [1, 1])


def test_atlas_layout_tiles_within_unit_square():
    from am3d.renderer.uv_mapping import atlas_grid_layout
    cells = atlas_grid_layout(4, columns=2)
    assert len(cells) == 4
    for ou, ov, su, sv in cells:
        assert -1e-9 <= ou <= 1 + 1e-9
        assert -1e-9 <= ov <= 1 + 1e-9
        assert su * 2 <= 1 + 1e-9 and sv * 2 <= 1 + 1e-9


def test_tessellated_object_has_uvs_in_bounds():
    p = Project()
    obj = p.create_object("multi")
    from am3d.core.project import Patch
    from am3d.spline.kernel import build_lathe_net
    prof = np.array([[0.5, 0.0], [1.0, 1.0], [0.7, 2.0], [0.5, 3.0]])
    for i in range(3):
        obj.patches.append(Patch(name=f"p{i}", splines=[],
                                 interior=build_lathe_net(prof, sections=10)))
    m = tessellate_object(obj, nu=8, nv=5)
    assert m.uvs.shape == (m.vertices.shape[0], 2)
    assert m.uvs.min() >= -1e-9 and m.uvs.max() <= 1 + 1e-9