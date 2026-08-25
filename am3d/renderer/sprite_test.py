"""Tests for the headless sprite-sheet renderer."""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.project import Patch, Project
from am3d.recipes.primitives import build_primitive
from am3d.renderer.sprite import render_sprite_sheet, render_view, save_sprite_sheet
from am3d.renderer.tessellate import MeshData, tessellate_object


def _sphere_mesh(nu=10, nv=8):
    p = Project()
    obj = p.create_object("orb")
    built = build_primitive("sphere", {"radius": 1.0, "sections": 12,
                                       "rings": 6})
    from am3d.core.project import Patch
    for name, net, du, dv in built["patches"]:
        obj.patches.append(Patch(name=name, splines=[], interior=net))
    return tessellate_object(obj, nu=nu, nv=nv)


def test_render_view_returns_rgba_and_has_content():
    mesh = _sphere_mesh()
    img = render_view(mesh, yaw_deg=30, size=64)
    assert img.shape == (64, 64, 4)
    alpha = img[..., 3]
    assert alpha.max() > 0, "sphere should be visible against transparent bg"
    # background stays transparent at the corners
    assert alpha[0, 0] == 0


def test_render_view_silhouette_mode_flat_color():
    mesh = _sphere_mesh()
    img = render_view(mesh, size=48, silhouette=True,
                      color=(1.0, 0.0, 0.0))
    # Only fully-opaque pixels: the AA pass blends RGB at silhouette edges.
    # Frames are float RGBA in 0..1 (render-boundary contract).
    mask = img[..., 3] == 1.0
    assert mask.any()
    rgb = img[mask][:, :3]
    assert np.allclose(rgb, np.array([1.0, 0.0, 0.0]), atol=2 / 255)


def test_sprite_sheet_tiles_frames():
    mesh = _sphere_mesh()
    sheet = render_sprite_sheet(mesh, views=4, size=32, columns=2)
    arr = np.asarray(sheet)
    assert arr.shape == (2 * 32, 2 * 32, 4)
    assert arr[..., 3].max() > 0


def test_empty_mesh_renders_blank():
    from am3d.renderer.tessellate import MeshData
    empty = MeshData(np.zeros((0, 3)), np.zeros((0, 3), dtype=np.int64))
    img = render_view(empty, size=32)
    assert img.shape == (32, 32, 4)
    assert img[..., 3].max() == 0


def test_save_sprite_sheet_png(tmp_path):
    pytest.importorskip("PIL")
    mesh = _sphere_mesh()
    out = tmp_path / "orb.png"
    saved = save_sprite_sheet(mesh, str(out), views=4, size=32)
    assert saved == str(out)
    assert out.stat().st_size > 0


def test_render_view_unit_scale_contract():
    """Regression: render_view always returns float RGBA in 0..1."""
    mesh = _sphere_mesh()
    for ss in (1, 2):
        img = render_view(mesh, size=32, supersample=ss)
        assert img.dtype == np.float32
        assert img.shape == (32, 32, 4)
        assert img.min() >= 0.0
        assert img.max() <= 1.0
        assert img[..., 3].max() == pytest.approx(1.0)


def test_render_view_no_pil_downsamples(monkeypatch):
    """Regression: ss>1 without PIL must downsample (block mean), not crop."""
    import am3d.renderer.sprite as sprite
    monkeypatch.setattr(sprite, "_HAS_PIL", False)
    mesh = _sphere_mesh()
    img = sprite.render_view(mesh, size=48, supersample=2)
    assert img.shape == (48, 48, 4)
    assert img.dtype == np.float32
    assert img.max() <= 1.0  # 0..1 contract
    coverage = (img[..., 3] > 0).mean()
    # Centered sphere covers roughly half the frame; a top-left crop of the
    # supersampled buffer would fill nearly all of it.
    assert 0.2 < coverage < 0.9