"""Tests for the pure-spline geometry kernel.

Verifies:
  * clamped knot-vector construction
  * the de Boor / Cox-de Boor basis and point emission
  * cubic curve interpolation of its endpoints
  * the exact weights sum to 1 for a clamped basis
  * surface tessellation produces the expected vertex/triangle counts
"""

from __future__ import annotations

import numpy as np
import pytest

from am3d.spline import kernel


def test_make_clamped_knots_length():
    k = kernel.make_clamped_knots(3, 6)
    assert k.shape[0] == 6 + 3 + 1
    assert k[0] == 0.0 and k[-1] == 1.0


def test_clamped_knots_pierce_ends():
    # A cubic clamped spline must pass through its end control points.
    deg = 3
    cps = np.array([[0, 0, 0], [1, 2, 0], [3, -1, 0], [4, 0, 0], [5, 1, 0]],
                   dtype=np.float64)
    knots = kernel.make_clamped_knots(deg, len(cps))
    p0 = kernel.deboor(0.0, deg, knots, cps)
    p1 = kernel.deboor(1.0, deg, knots, cps)
    assert np.allclose(p0, cps[0], atol=1e-9)
    assert np.allclose(p1, cps[-1], atol=1e-9)


def test_deboor_interpolates_control_points_degree1():
    # Linear B-splines (degree 1) interpolate all control points.
    deg = 1
    cps = np.array([[0, 0, 0], [2, 4, 0], [5, 1, 3]], dtype=np.float64)
    knots = kernel.make_clamped_knots(deg, len(cps))
    for i, cp in enumerate(cps):
        t = i / (len(cps) - 1)
        p = kernel.deboor(t, deg, knots, cps)
        assert np.allclose(p, cp, atol=1e-9)


def test_rational_sphere_quarter():
    # A NURBS quarter-circle arc with standard weights: weight = sqrt(2)/2
    # for the middle point.  Check endpoints and the midpoint.
    deg = 2
    cps = np.array([[1, 0, 0], [1, 1, 0], [0, 1, 0]], dtype=np.float64)
    w = np.array([1.0, np.sqrt(2) / 2.0, 1.0])
    knots = kernel.make_clamped_knots(deg, len(cps))
    p0 = kernel.deboor(0.0, deg, knots, cps, w)
    pm = kernel.deboor(0.5, deg, knots, cps, w)
    p1 = kernel.deboor(1.0, deg, knots, cps, w)
    half = np.sqrt(2) / 2.0
    assert np.allclose(p0, [1, 0, 0], atol=1e-9)
    assert np.allclose(p1, [0, 1, 0], atol=1e-9)
    assert np.allclose(pm, [half, half, 0], atol=1e-6)


def test_basis_partition_of_unity():
    # For a clamped cubic spline the sum of non-zero basis functions equals 1.
    deg = 3
    cps = np.random.RandomState(0).rand(6, 3)
    knots = kernel.make_clamped_knots(deg, len(cps))
    for u in [0.0, 0.1, 0.37, 0.5, 0.83, 1.0]:
        span = kernel.find_span(u, deg, knots)
        total = 0.0
        for i in range(span - deg, span + 1):
            total += kernel.basis(i, deg, u, knots)
        assert abs(total - 1.0) < 1e-9, (u, total)


def test_eval_curve_array_shapes():
    cps = np.array([[0, 0, 0], [1, 2, 0], [3, 0, 1], [4, 1, 2]], dtype=np.float64)
    knots = kernel.make_clamped_knots(3, len(cps))
    pts = kernel.eval_curve(64, 3, knots, cps)
    assert pts.shape == (64, 3)
    scalar = kernel.eval_curve(0.5, 3, knots, cps)
    assert scalar.shape == (1, 3)


def test_eval_curve_int_zero_and_one_are_parameters():
    # eval_curve(0) / eval_curve(1) must evaluate at t=0 / t=1, not be
    # mistaken for "number of samples" (which only applies for int > 1).
    cps = np.array([[0, 0, 0], [1, 2, 0], [3, 0, 1], [4, 1, 2]], dtype=np.float64)
    knots = kernel.make_clamped_knots(3, len(cps))
    p0 = kernel.eval_curve(0, 3, knots, cps)
    p1 = kernel.eval_curve(1, 3, knots, cps)
    assert p0.shape == (1, 3) and p1.shape == (1, 3)
    assert np.allclose(p0[0], cps[0], atol=1e-9)
    assert np.allclose(p1[0], cps[-1], atol=1e-9)


def test_build_patch_grid_counts():
    # A (4,4,3) cubic net tessellated at 8x8 gives 64 verts, 98 triangles
    # ((8-1)*(8-1)*2 = 98).
    rng = np.random.RandomState(1)
    grid = rng.rand(4, 4, 3)
    verts, tris = kernel.build_patch_grid(grid, nu=8, nv=8)
    assert verts.shape == (64, 3)
    assert tris.shape == (98, 3)
    assert tris.max() == 63


def test_build_patch_grid_corner_interpolation():
    # Clamped surfaces interpolate the grid's 4 corners exactly.
    rng = np.random.RandomState(2)
    grid = rng.rand(5, 5, 3)
    grid[0, 0] = [0, 0, 0]
    grid[0, -1] = [1, 0, 0]
    grid[-1, 0] = [0, 1, 0]
    grid[-1, -1] = [1, 1, 0]
    nu, nv = 20, 20
    verts, _ = kernel.build_patch_grid(grid, nu=nu, nv=nv)
    g = verts.reshape(nu, nv, 3)
    assert np.allclose(g[0, 0], grid[0, 0], atol=1e-9)
    assert np.allclose(g[0, -1], grid[0, -1], atol=1e-9)
    assert np.allclose(g[-1, 0], grid[-1, 0], atol=1e-9)
    assert np.allclose(g[-1, -1], grid[-1, -1], atol=1e-9)


def test_lathe_nets_circular():
    profile = np.array([[1.0, 0.0], [2.0, 0.0]], dtype=np.float64)
    net = kernel.build_lathe_net(profile, axis="y", sections=12)
    assert net.shape == (12, 2, 3)
    # Profile's y stays 0 across the revolution (axial coordinate preserved).
    assert np.allclose(net[..., 1], 0.0, atol=1e-9)
    # Each ring is a circle in XZ of radius = its profile x-coordinate.
    radii = np.hypot(net[..., 0], net[..., 2])
    assert np.allclose(radii[:, 0], 1.0, atol=1e-9)
    assert np.allclose(radii[:, 1], 2.0, atol=1e-9)


def test_extrude_net_straight():
    profile = np.array([[0, 0, 0], [1, 0, 0], [1, 0, 1], [0, 0, 1]], dtype=np.float64)
    net = kernel.build_extrude_net(profile, height=4.0, n_rings=3)
    assert net.shape == (3, 4, 3)
    # Bottom ring sits at y=0, top at y=4, middle at y=2.
    assert np.allclose(net[0, :, 1], 0.0)
    assert np.allclose(net[2, :, 1], 4.0)
    assert np.allclose(net[1, :, 1], 2.0)
    # XZ footprint preserved (no twist).
    assert np.allclose(net[:, :, [0, 2]], np.tile(profile[:, [0, 2]], (3, 1, 1)), atol=1e-9)


def test_extrude_net_rejects_single_ring():
    # n_rings < 2 would divide by (n_rings - 1); it must raise instead.
    profile = np.array([[0, 0, 0], [1, 0, 0]], dtype=np.float64)
    with pytest.raises(ValueError):
        kernel.build_extrude_net(profile, height=1.0, n_rings=1)

# ---------------------------------------------------------------------------
# Patch-grid input validation (finding API-01)
#
# Before the fix these inputs either produced silently degenerate geometry
# (nu=1 -> 16 vertices and zero triangles; all-zero weights -> every vertex
# collapsed onto the origin) or leaked a numpy internal message that named no
# parameter of this API ("negative dimensions are not allowed", "cannot
# reshape array of size 2 into shape (4,)").
# ---------------------------------------------------------------------------

def _flat_grid(mu=4, mv=4):
    grid = np.zeros((mu, mv, 3), dtype=np.float64)
    grid[..., 0] = np.arange(mu)[:, None]
    grid[..., 1] = np.arange(mv)[None, :]
    return grid


@pytest.mark.parametrize("kwargs, expect", [
    ({"nu": 1}, "nu must be at least 2"),
    ({"nv": 1}, "nv must be at least 2"),
    ({"nu": 0}, "nu must be at least 2"),
    ({"nv": -3}, "nv must be at least 2"),
    ({"nu": 1.5}, "nu must be an integer"),
    ({"nv": "8"}, "nv must be an integer"),
    ({"degree_u": 0}, "degree_u must be at least 1"),
    ({"degree_v": -1}, "degree_v must be at least 1"),
    ({"degree_u": 3.0}, "degree_u must be an integer"),
    ({"degree_u": 5}, "at least 6 control points along u"),
    ({"degree_v": 9}, "at least 10 control points along v"),
    ({"weights_u": [1.0, 1.0]}, "expected 4, got 2"),
    ({"weights_v": [1.0] * 5}, "expected 4, got 5"),
    ({"weights_u": [0.0] * 4}, "must be strictly positive"),
    ({"weights_v": [1.0, -1.0, 1.0, 1.0]}, "must be strictly positive"),
    ({"weights_u": [1.0, float("nan"), 1.0, 1.0]}, "NaN or infinite"),
])
def test_patch_grid_rejects_invalid_inputs_with_a_named_message(kwargs, expect):
    with pytest.raises(ValueError) as excinfo:
        kernel.build_patch_grid(_flat_grid(), **kwargs)
    assert expect in str(excinfo.value)


def test_patch_grid_rejects_a_non_finite_control_net():
    grid = _flat_grid()
    grid[2, 1, 0] = np.inf
    with pytest.raises(ValueError, match="NaN or infinite coordinates"):
        kernel.build_patch_grid(grid)


def test_patch_grid_still_accepts_the_smallest_valid_resolution():
    verts, tris = kernel.build_patch_grid(_flat_grid(), nu=2, nv=2)
    assert verts.shape == (4, 3)
    assert tris.shape == (2, 3)


def test_patch_grid_accepts_positive_weights_unchanged():
    grid = _flat_grid()
    plain, _ = kernel.build_patch_grid(grid, nu=6, nv=6)
    unit, _ = kernel.build_patch_grid(grid, nu=6, nv=6,
                                      weights_u=[1.0] * 4,
                                      weights_v=[1.0] * 4)
    assert np.allclose(plain, unit)


def test_eval_surface_validates_through_the_same_path():
    with pytest.raises(ValueError, match="nu must be at least 2"):
        kernel.eval_surface(_flat_grid(), nu=1)


def test_tessellating_an_object_reports_a_bad_resolution_clearly():
    """The exposed caller: evaluate_scene/tessellate_object take nu/nv."""
    from am3d.core.script import Session
    from am3d.renderer.tessellate import tessellate_object
    from am3d.ui.operators import CreatePrimitiveCommand

    s = Session()
    CreatePrimitiveCommand(s, "box", "box").redo()
    obj = s.get_object("box")
    assert len(tessellate_object(obj, nu=2, nv=2).indices) > 0
    with pytest.raises(ValueError, match="nu must be at least 2"):
        tessellate_object(obj, nu=1, nv=8)
