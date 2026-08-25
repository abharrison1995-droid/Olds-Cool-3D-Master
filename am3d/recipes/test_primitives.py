"""Tests for procedural primitive builders.

Every builder must return nets that actually tessellate through
``build_patch_grid`` — that is the contract the executor relies on.
"""

from __future__ import annotations

import numpy as np
import pytest

from am3d.recipes.primitives import (
    BUILDERS,
    build_primitive,
    make_box,
    make_cone,
    make_cylinder,
    make_extrude_profile,
    make_lathe_profile,
    make_plane,
    make_sphere,
    make_torus,
)
from am3d.spline import kernel


def _tessellate(result, nu=10, nv=10):
    """Run every patch of a primitive result through the tessellator."""
    total = 0
    for name, net, du, dv in result["patches"]:
        verts, tris = kernel.build_patch_grid(net, du, dv, nu, nv)
        assert np.all(np.isfinite(verts)), f"{name}: non-finite vertices"
        total += len(verts)
    return total


def test_all_builders_registered():
    for key in ("sphere", "box", "cylinder", "cone", "torus", "plane",
                "lathe", "extrude"):
        assert key in BUILDERS


def test_sphere_is_round():
    r = make_sphere(radius=2.0, sections=24, rings=12)
    net = r["patches"][0][1]
    # every control point sits on the unit sphere of radius 2 (up to fp error)
    d = np.linalg.norm(net[:, :, :], axis=-1)
    assert np.allclose(d, 2.0, atol=1e-9)
    assert _tessellate(r) > 0


def test_cylinder_radius_constant_and_caps():
    r = make_cylinder(radius=0.5, height=2.0, sections=12, capped=True)
    net = r["patches"][0][1]
    radii = np.hypot(net[..., 0], net[..., 2])
    assert radii.max() <= 0.5 + 1e-9
    assert net[..., 1].min() >= -1e-9 and net[..., 1].max() <= 2.0 + 1e-9
    assert _tessellate(r) > 0


def test_cone_apex_pinches_to_zero():
    r = make_cone(radius=1.0, height=2.0)
    net = r["patches"][0][1]          # (sections+1, rings, 3)
    # The apex is the last v-row across every section; the base is v-row 0.
    apex_radii = np.hypot(net[:, -1, 0], net[:, -1, 2])
    base_radii = np.hypot(net[:, 0, 0], net[:, 0, 2])
    assert np.allclose(apex_radii, 0.0, atol=1e-9)
    assert np.allclose(base_radii, 1.0, atol=1e-9)


def test_torus_ring_closed():
    r = make_torus(major_radius=1.0, minor_radius=0.25,
                   major_sections=16, minor_sections=8)
    net = r["patches"][0][1]
    # first and last section must coincide (closed revolution)
    assert np.allclose(net[0], net[-1], atol=1e-9)


def test_torus_tube_profile_closed():
    r = make_torus(major_radius=1.0, minor_radius=0.25,
                   major_sections=16, minor_sections=8)
    net = r["patches"][0][1]
    # first and last v-rows must coincide (no seam around the tube)
    assert np.allclose(net[:, 0], net[:, -1], atol=1e-9)


def test_box_faces_are_flat_and_sized():
    w, h, d = 2.0, 3.0, 4.0
    r = make_box(width=w, height=h, depth=d)
    assert len(r["patches"]) == 6
    for name, grid, du, dv in r["patches"]:
        # each face is planar: all points share one coordinate at a bound
        for axis in range(3):
            vals = grid[..., axis]
            if np.ptp(vals) < 1e-9:
                bound = vals.ravel()[0]
                limit = (w, h, d)[axis] / 2
                assert abs(abs(bound) - limit) < 1e-9, name
                break
        else:
            raise AssertionError(f"{name}: no planar axis found")
    assert _tessellate(r) > 0


def test_plane_facing_z():
    r = make_plane(width=2.0, height=1.0)
    grid = r["patches"][0][1]
    assert np.allclose(grid[..., 2], 0.0)
    assert np.isclose(grid[..., 0].max(), 1.0)
    assert np.isclose(grid[..., 1].min(), -0.5)


def test_lathe_rejects_bad_profile():
    with pytest.raises(ValueError, match="m, 2"):
        make_lathe_profile([[1, 2, 3]])


def test_extrude_rejects_bad_profile():
    with pytest.raises(ValueError, match="m, 3"):
        make_extrude_profile([[1, 2]])


def test_build_primitive_dispatch_and_errors():
    out = build_primitive("SPHERE", {"radius": 1.5})
    assert out["patches"][0][0] == "sphere"
    with pytest.raises(ValueError, match="unknown primitive"):
        build_primitive("dragon")
    with pytest.raises(ValueError, match="bad params"):
        build_primitive("sphere", {"radius": [1, 2]})


@pytest.mark.parametrize("name,params", [
    ("sphere", {}), ("cylinder", {}), ("cone", {}),
    ("torus", {}), ("box", {}), ("plane", {}),
    ("sphere", {"radius": 3}), ("cylinder", {"capped": False}),
])
def test_default_params_tessellate(name, params):
    assert _tessellate(build_primitive(name, params)) > 0