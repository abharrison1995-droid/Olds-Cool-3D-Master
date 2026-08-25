"""Tests for procedural texture generation and atlas baking."""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.project import Material, Project, Patch
from am3d.recipes.primitives import build_primitive
from am3d.renderer.materials import (
    PATTERNS,
    bake_atlas,
    bricks,
    checkerboard,
    gradient,
    height_to_normal,
    noise,
    resolve_albedo,
    solid,
)
from am3d.renderer.tessellate import tessellate_object


def test_all_patterns_registered():
    assert set(PATTERNS) == {"solid", "checker", "gradient", "noise", "bricks"}


@pytest.mark.parametrize("name", ["solid", "checker", "gradient",
                                  "noise", "bricks"])
def test_patterns_produce_valid_rgba(name):
    tex = PATTERNS[name](size=32) if name != "solid" else solid(size=32)
    assert tex.shape == (32, 32, 4)
    assert tex.min() >= 0.0 and tex.max() <= 1.0
    assert np.all(tex[..., 3] == 1.0), "patterns must be fully opaque"


def test_checkerboard_alternates():
    tex = checkerboard(cells=2, size=32)
    # block index = floor(v/size*2) + floor(u/size*2), so:
    a = tex[4, 4]      # block (0,0)
    b = tex[4, 20]     # block (0,1) -> different colour
    c = tex[12, 12]    # still inside block (0,0)
    assert not np.allclose(a, b)
    assert np.allclose(a, c)


def test_gradient_direction():
    tex = gradient(top=(1, 1, 1), bottom=(0, 0, 0), size=16)
    assert tex[0, :, 0].mean() < tex[-1, :, 0].mean()


def test_noise_is_deterministic_per_seed():
    a = noise(seed=3, size=32)
    b = noise(seed=3, size=32)
    c = noise(seed=4, size=32)
    assert np.allclose(a, b)
    assert not np.allclose(a, c)


def test_bricks_have_mortar_lines():
    tex = bricks(size=64)
    # mortar colour appears somewhere in the image
    mortar = np.array([0.82, 0.80, 0.76])
    hit = np.any(np.linalg.norm(tex[..., :3] - mortar, axis=-1) < 0.05)
    assert hit


def test_height_to_normal_flat_is_up():
    flat = np.ones((16, 16))
    n = height_to_normal(flat)
    # flat surface: z ~ 1 -> blue channel near 1
    assert np.allclose(n[..., 2], 1.0, atol=1e-6)


def test_height_to_normal_encodes_slope():
    ramp = np.tile(np.linspace(0, 1, 32), (32, 1))
    n = height_to_normal(ramp, strength=1.0)
    # slope in x tilts the normal's x component away from 0.5
    assert abs(n[..., 0] - 0.5).max() > 0.05


def test_resolve_albedo_from_material_color():
    m = Material("plain", color=(1.0, 0.0, 0.0))
    tex = resolve_albedo(m, size=8)
    assert tex.shape == (8, 8, 4)
    assert np.allclose(tex[0, 0], [1, 0, 0, 1])


def test_resolve_albedo_with_pattern():
    class MatWithPattern(Material):
        pattern = "checker"
        params = {"cells": 4}

    tex = resolve_albedo(MatWithPattern("c"), size=32)
    assert tex.shape == (32, 32, 4)


def test_resolve_albedo_unknown_pattern_raises():
    with pytest.raises(ValueError, match="unknown pattern"):
        resolve_albedo(Material("x"), pattern="dragon_scales")


def _sphere_mesh():
    p = Project()
    obj = p.create_object("orb")
    built = build_primitive("box")          # box = 6 patches -> real atlas
    for name, net, du, dv in built["patches"]:
        obj.patches.append(Patch(name=name, splines=[], interior=net))
    return tessellate_object(obj, nu=4, nv=4), obj


def test_bake_atlas_shape_and_content():
    mesh, obj = _sphere_mesh()
    mats = {patch.name: Material(patch.name, (0.5, 0.5, 0.9))
            for patch in obj.patches}
    atlas = bake_atlas(mesh, mats, cell_size=32)
    assert atlas.ndim == 3
    assert atlas.shape[2] == 4
    assert atlas.min() >= 0 and atlas.max() <= 1


def test_bake_atlas_empty_defaults_to_grey():
    from am3d.renderer.tessellate import MeshData
    empty = MeshData(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    atlas = bake_atlas(empty, {}, cell_size=16)
    assert atlas.shape == (16, 16, 4)


def test_bake_atlas_layout_matches_uv_mapping_grid():
    """Atlas tiles must land exactly where atlas_grid_layout puts the UVs.

    ceil(sqrt(n)) columns: n=2 -> 2x1, n=5 -> 3x2.  The old round()-based
    layout gave 1x2 for n=2 (wrong tiles) and 2x2 for n=5 (clipped tile).
    """
    from am3d.renderer.uv_mapping import atlas_grid_layout

    mesh, _ = _sphere_mesh()
    cell = 16
    two = {"a": Material("a", (1.0, 0.0, 0.0)),
           "b": Material("b", (0.0, 0.0, 1.0))}
    atlas = bake_atlas(mesh, two, cell_size=cell)
    assert atlas.shape == (cell, 2 * cell, 4)          # 2 cols x 1 row
    cells = atlas_grid_layout(2)
    for (name, mat), (ou, ov, su, sv) in zip(two.items(), cells):
        r = int((ov + sv / 2) * atlas.shape[0])
        c = int((ou + su / 2) * atlas.shape[1])
        assert np.allclose(atlas[r, c, :3], mat.color, atol=1e-6), name

    five = {f"m{i}": Material(f"m{i}", (0.5, 0.5, 0.5)) for i in range(5)}
    atlas5 = bake_atlas(mesh, five, cell_size=cell)
    assert atlas5.shape == (2 * cell, 3 * cell, 4)     # 3 cols x 2 rows