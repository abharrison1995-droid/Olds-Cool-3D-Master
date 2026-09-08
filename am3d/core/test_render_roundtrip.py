"""Original-vs-reopened render comparison (Phase 4, V3 plan Section 8).

Each test builds a scene, renders it under fixed camera/render settings,
saves and reloads the project into a fresh :class:`Session`, renders the
reopened scene under the *same* settings, and asserts the two renders are
equivalent — numerically (raw float buffers, near-exact) and tolerantly
(after an actual PNG encode/decode round-trip, the way an exported or
externally-viewed image would be judged). See
:func:`am3d.renderer.compare.assert_renders_match`.

Scenes covered mirror the acceptance list verbatim: empty, an occluding
two-object scene, a scene with an invisible object, and objects that are
translated, rotated, and non-uniformly scaled.

Visual inspection: ``scripts/render_roundtrip_evidence.py`` renders the
same six scenarios and writes original/reopened/diff PNGs to
``docs/evidence/v3/phase-4/render_roundtrip/`` for a human to eyeball —
these automated tests only check the numeric/tolerant side.
"""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.project import Patch
from am3d.core.script import Session
from am3d.recipes.primitives import build_primitive
from am3d.renderer.compare import assert_renders_match
from am3d.renderer.sprite import render_scene

# Fixed render settings every scenario below renders with, both before and
# after the save/reload — this *is* the "fixed settings" the acceptance
# criterion asks for. A render at any other yaw/pitch/size/color is not
# comparable to these and shouldn't be expected to match.
RENDER_KW = dict(yaw_deg=25.0, pitch_deg=15.0, size=64,
                 color=(0.7, 0.75, 0.9), supersample=2)


def _add_primitive(session, name, primitive="sphere", params=None,
                   transform=None, visible=True):
    session.create_object(name)
    obj = session.project.objects[name]
    built = build_primitive(primitive, params or {})
    for pname, net, du, dv in built["patches"]:
        obj.patches.append(Patch(name=pname, splines=[], interior=net))
    if transform is not None:
        obj.transform = np.asarray(transform, dtype=np.float64)
    obj.visible = visible
    return obj


def _render_current(session):
    scene = session.evaluate_scene(apply_transforms=True, visible_only=True)
    meshes = {n: m for n, m in scene.meshes.items() if len(m.vertices)}
    return render_scene(meshes, **RENDER_KW)


def _save_reload(session, tmp_path, name="scene.am3d"):
    path = tmp_path / name
    session.save_project(str(path))
    reloaded = Session()
    reloaded.load_project(str(path))
    return reloaded


def _translation(x=0.0, y=0.0, z=0.0):
    m = np.eye(4, dtype=np.float64)
    m[:3, 3] = [x, y, z]
    return m


def _rotation_y(deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    m = np.eye(4, dtype=np.float64)
    m[[0, 0, 2, 2], [0, 2, 0, 2]] = [c, s, -s, c]
    return m


def _scale(sx=1.0, sy=1.0, sz=1.0):
    m = np.eye(4, dtype=np.float64)
    m[0, 0], m[1, 1], m[2, 2] = sx, sy, sz
    return m


def test_render_roundtrip_empty_scene(tmp_path):
    s1 = Session()
    s1.new_project("empty")

    img1 = _render_current(s1)
    s2 = _save_reload(s1, tmp_path)
    img2 = _render_current(s2)

    assert img1.shape == (64, 64, 4)
    assert np.all(img1[..., 3] == 0.0), "empty scene must render fully transparent"
    assert_renders_match(img1, img2)


def test_render_roundtrip_occluding_two_objects(tmp_path):
    s1 = Session()
    s1.new_project("occlusion")
    _add_primitive(s1, "near", "sphere", {"radius": 0.6, "sections": 10, "rings": 6},
                   transform=_translation(z=0.4))
    _add_primitive(s1, "far", "sphere", {"radius": 0.6, "sections": 10, "rings": 6},
                   transform=_translation(z=-0.4))

    img1 = _render_current(s1)
    assert np.any(img1[..., 3] > 0), "two overlapping spheres should paint something"
    s2 = _save_reload(s1, tmp_path)
    img2 = _render_current(s2)

    assert_renders_match(img1, img2)


def test_render_roundtrip_invisible_object_excluded(tmp_path):
    s1 = Session()
    s1.new_project("invisible")
    _add_primitive(s1, "shown", "box", {"width": 1.0, "height": 1.0, "depth": 1.0})
    _add_primitive(s1, "hidden", "sphere", {"radius": 5.0, "sections": 10, "rings": 6},
                   visible=False)

    img1 = _render_current(s1)

    # A scene that never had the hidden object must render identically —
    # if visibility silently stopped being honoured, the huge hidden sphere
    # would swamp the frame and this comparison would catch it.
    baseline = Session()
    baseline.new_project("invisible_baseline")
    _add_primitive(baseline, "shown", "box", {"width": 1.0, "height": 1.0, "depth": 1.0})
    assert_renders_match(img1, _render_current(baseline))

    s2 = _save_reload(s1, tmp_path)
    img2 = _render_current(s2)
    assert_renders_match(img1, img2)


def test_render_roundtrip_translated_object(tmp_path):
    s1 = Session()
    s1.new_project("translated")
    _add_primitive(s1, "orb", "sphere", {"radius": 0.5, "sections": 10, "rings": 6},
                   transform=_translation(x=1.3, y=-0.6, z=0.2))

    img1 = _render_current(s1)
    s2 = _save_reload(s1, tmp_path)
    img2 = _render_current(s2)

    assert_renders_match(img1, img2)


def test_render_roundtrip_rotated_object(tmp_path):
    s1 = Session()
    s1.new_project("rotated")
    _add_primitive(s1, "box", "box", {"width": 1.4, "height": 0.6, "depth": 0.9},
                   transform=_rotation_y(37.0))

    img1 = _render_current(s1)
    s2 = _save_reload(s1, tmp_path)
    img2 = _render_current(s2)

    assert_renders_match(img1, img2)


def test_render_roundtrip_non_uniformly_scaled_object(tmp_path):
    s1 = Session()
    s1.new_project("scaled")
    _add_primitive(s1, "orb", "sphere", {"radius": 0.5, "sections": 10, "rings": 6},
                   transform=_scale(sx=2.0, sy=0.5, sz=1.3))

    img1 = _render_current(s1)
    s2 = _save_reload(s1, tmp_path)
    img2 = _render_current(s2)

    assert_renders_match(img1, img2)
