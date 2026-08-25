"""Tests for the toon / ink-line NPR pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.project import Material, Patch, Project
from am3d.recipes.primitives import build_primitive
from am3d.renderer.tessellate import MeshData, tessellate_object
from am3d.renderer.toon import (
    cel_shade,
    composite_toon,
    detect_ink,
    dilate_mask,
    render_toon_sheet,
    toon_render_view,
)


def _box_mesh():
    p = Project()
    obj = p.create_object("crate")
    built = build_primitive("box")
    for name, net, du, dv in built["patches"]:
        obj.patches.append(Patch(name=name, splines=[], interior=net))
    return tessellate_object(obj, nu=3, nv=3), obj


def test_cel_shade_produces_discrete_bands():
    normals = np.array([
        [0, 0, 1.0],      # facing light fully
        [1.0, 0, 0],      # perpendicular
        [0, 1.0, 0],
        [0.7071, 0, 0.7071],
    ])
    factors = cel_shade(normals, bands=4)
    # only a small set of distinct values
    assert len(np.unique(np.round(factors, 6))) <= 4
    assert factors.min() >= 0.35 - 1e-9
    assert factors.max() <= 1.0 + 1e-9


def test_cel_shade_facing_light_is_brightest():
    n = np.array([[0, 0, 1.0], [1.0, 0, 0]])
    f = cel_shade(n, light=(0, 0, 1.0), bands=4)
    assert f[0] > f[1]


def test_detect_ink_finds_depth_discontinuity():
    depth = np.zeros((32, 32))
    depth[:, 16:] = 1.0                     # hard vertical step
    flat_normals = np.zeros((32, 32, 3))
    flat_normals[..., 2] = 1.0
    mask = detect_ink(depth, flat_normals, depth_thresh=0.2,
                      normal_thresh=0.99)
    assert mask[:, 15:18].any()
    # far from the step there is no ink
    assert not mask[:, :8].any()


def test_detect_ink_finds_normal_crease():
    depth = np.zeros((32, 32))              # constant depth
    normals = np.zeros((32, 32, 3))
    normals[:16] = [0.0, 0.0, 1.0]          # facing +Z
    normals[16:] = [1.0, 0.0, 0.0]          # facing +X (90-degree crease)
    mask = detect_ink(depth, normals, depth_thresh=5.0, normal_thresh=0.6)
    assert mask[14:18, :].any()


def test_dilate_mask_grows():
    m = np.zeros((9, 9), dtype=bool)
    m[4, 4] = True
    grown = dilate_mask(m, pixels=1)
    assert grown[4, 4]
    assert grown[3, 4] and grown[5, 4]
    assert not grown[0, 0]


def test_composite_toon_applies_cel_and_ink():
    base = np.ones((16, 16, 3))
    alpha = np.ones((16, 16))
    cel = np.full((16, 16), 0.5)
    ink = np.zeros((16, 16), dtype=bool)
    ink[8, :] = True
    frame = composite_toon(base, alpha, cel_factors=cel, ink_mask=ink,
                           ink_px_width=1)
    assert frame.shape == (16, 16, 4)
    assert np.allclose(frame[0, 0, :3], 0.5)          # cel applied
    assert frame[8, 0, 0] < 0.1                        # ink line dark
    assert frame[..., 3].max() == 1.0                  # opaque


def test_toon_render_view_has_content_and_shape():
    mesh, _ = _box_mesh()
    img = toon_render_view(mesh, size=64)
    assert img.shape == (64, 64, 4)
    assert img[..., 3].max() > 0
    # background transparent
    assert img[0, 0, 3] == 0


def test_toon_render_view_draws_ink_lines():
    mesh, _ = _box_mesh()
    with_ink = toon_render_view(mesh, size=96, ink=True)
    without = toon_render_view(mesh, size=96, ink=False)
    lum_with = with_ink[..., :3].mean(axis=-1)
    lum_without = without[..., :3].mean(axis=-1)
    # frames are float RGBA in 0..1 (render-boundary contract)
    dark_with = ((lum_with < 60 / 255) & (with_ink[..., 3] > 200 / 255)).sum()
    dark_without = ((lum_without < 60 / 255)
                    & (without[..., 3] > 200 / 255)).sum()
    assert dark_with > dark_without


def test_toon_sheet_tiles():
    mesh, _ = _box_mesh()
    sheet = render_toon_sheet(mesh, views=4, size=32, columns=2)
    arr = np.asarray(sheet)
    assert arr.shape == (2 * 32, 2 * 32, 4)
    assert arr[..., 3].max() > 0


def test_empty_mesh_renders_blank_toon():
    empty = MeshData(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    img = toon_render_view(empty, size=32)
    assert img.shape == (32, 32, 4)
    assert img[..., 3].max() == 0


def test_toon_render_view_unit_scale_contract():
    """Regression: 0..1 float RGBA for every supersample factor."""
    mesh, _ = _box_mesh()
    for ss in (1, 2, 3):
        img = toon_render_view(mesh, size=32, supersample=ss)
        assert img.dtype == np.float32
        assert img.shape == (32, 32, 4)
        assert img.min() >= 0.0
        assert img.max() <= 1.0
        assert img[..., 3].max() == pytest.approx(1.0)