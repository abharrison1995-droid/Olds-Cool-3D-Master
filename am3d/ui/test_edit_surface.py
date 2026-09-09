"""Editable generated surfaces (findings EDIT-01, EDIT-02).

Before the fix a lathe/extrude baked its control net into ``Patch.interior``
with no link back to the profile spline, so editing the profile afterwards
moved only the construction curve while the rendered and exported surface
stayed frozen -- and the viewport drew the moved curve, so the edit looked
like it had taken effect. See
docs/evidence/desktop-release/phase-b/edit-01-reproduction.txt.
"""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.project import ControlPoint, Object3D, Spline
from am3d.core.scene import evaluate_scene
from am3d.core.script import Session
from am3d.ui.operators import (ExtrudeProfileCommand, InsertCPCommand,
                               LatheProfileCommand, MoveCPCommand,
                               RemoveCPCommand)

PROFILE = [(1.0, 0.0, 0.0), (1.5, 1.0, 0.0), (1.2, 2.0, 0.0), (0.8, 3.0, 0.0)]


def _session(points=PROFILE, name="vase"):
    session = Session()
    obj = Object3D(name=name)
    session.project.objects[name] = obj
    obj.add_spline(Spline(name="profile",
                          cps=[ControlPoint.from_tuple(*p) for p in points],
                          degree=min(3, len(points) - 1)))
    return session, obj


def _lathed(points=PROFILE, sections=8):
    session, obj = _session(points)
    profile = obj.splines["profile"].point_array()[:, [0, 1]]
    LatheProfileCommand(session, "vase", profile, sections=sections,
                        source_spline="profile").redo()
    return session, obj


def _surface_radius(session, name="vase"):
    """Max radius of vertices actually referenced by triangles.

    Deliberately ignores the construction spline's own ring vertices, which
    carry no triangles -- measuring those is what made the original defect
    look like it was working.
    """
    mesh = evaluate_scene(session).meshes[name]
    used = np.unique(mesh.indices)
    assert len(used), "the object produced no triangles at all"
    return float(np.linalg.norm(mesh.vertices[used][:, [0, 2]], axis=1).max())


# --- EDIT-01: the surface follows its profile -------------------------------

def test_moving_a_profile_cp_changes_the_rendered_surface():
    session, _ = _lathed()
    before = _surface_radius(session)
    MoveCPCommand(session, "vase", "profile", 1,
                  [1.5, 1.0, 0.0], [4.0, 1.0, 0.0]).redo()
    after = _surface_radius(session)
    assert after > before + 0.5, (
        f"surface did not follow the profile edit ({before} -> {after})")


def test_undo_and_redo_restore_the_surface_exactly():
    session, _ = _lathed()
    r0 = _surface_radius(session)
    cmd = MoveCPCommand(session, "vase", "profile", 1,
                        [1.5, 1.0, 0.0], [4.0, 1.0, 0.0])
    cmd.redo()
    r1 = _surface_radius(session)
    cmd.undo()
    assert _surface_radius(session) == pytest.approx(r0, abs=1e-12)
    cmd.redo()
    assert _surface_radius(session) == pytest.approx(r1, abs=1e-12)


def test_inserting_and_removing_profile_cps_rebuild_the_surface():
    session, obj = _lathed()
    before = _surface_radius(session)
    ins = InsertCPCommand(session, "vase", "profile", 2,
                          ControlPoint.from_tuple(5.0, 1.5, 0.0))
    ins.redo()
    assert _surface_radius(session) > before + 0.5
    ins.undo()
    assert _surface_radius(session) == pytest.approx(before, abs=1e-12)

    rem = RemoveCPCommand(session, "vase", "profile", 1)
    rem.redo()
    assert _surface_radius(session) == pytest.approx(
        _surface_radius(session))          # still evaluable
    rem.undo()
    assert _surface_radius(session) == pytest.approx(before, abs=1e-12)


def test_extruded_surfaces_follow_their_profile_too():
    session, obj = _session([(0.0, 0.0, 0.0), (1.0, 0.0, 0.0),
                             (1.0, 0.0, 1.0), (0.0, 0.0, 1.0)])
    ExtrudeProfileCommand(session, "vase",
                          obj.splines["profile"].point_array(),
                          height=1.0, rings=4,
                          source_spline="profile").redo()

    def extent():
        mesh = evaluate_scene(session).meshes["vase"]
        used = np.unique(mesh.indices)
        return float(mesh.vertices[used][:, 0].max())

    before = extent()
    MoveCPCommand(session, "vase", "profile", 1,
                  [1.0, 0.0, 0.0], [6.0, 0.0, 0.0]).redo()
    assert extent() > before + 1.0


def test_a_patch_without_a_generator_is_left_alone():
    """Hand-built geometry must not be silently rebuilt or destroyed."""
    session, obj = _session()
    from am3d.core.project import Patch
    net = np.zeros((4, 4, 3))
    net[..., 0] = np.arange(4)[:, None]
    net[..., 1] = np.arange(4)[None, :]
    obj.patches.append(Patch(name="hand", splines=[], interior=net.copy()))
    MoveCPCommand(session, "vase", "profile", 1,
                  [1.5, 1.0, 0.0], [4.0, 1.0, 0.0]).redo()
    assert np.allclose(obj.patches[0].interior, net)


def test_a_generator_whose_spline_vanished_keeps_the_last_good_surface():
    session, obj = _lathed()
    before = obj.patches[0].interior.copy()
    from am3d.core.generators import regenerate_object_patches
    del obj.splines["profile"]
    assert regenerate_object_patches(obj, "profile") == 0
    assert np.allclose(obj.patches[0].interior, before)


# --- EDIT-02: generated degrees must fit the net ----------------------------

def test_a_three_point_profile_produces_an_evaluable_surface():
    """Regression: the lathe clamped the degree but the patch discarded it,
    so tessellation asked for a cubic across a 3-wide net and raised
    "a degree-3 patch needs at least 4 control points along v"."""
    session, _ = _lathed(points=[(1.0, 0.0, 0.0), (1.5, 1.0, 0.0),
                                 (0.8, 2.0, 0.0)])
    mesh = evaluate_scene(session).meshes["vase"]
    assert len(mesh.indices) > 0
    assert np.isfinite(mesh.vertices).all()


def test_patch_degrees_are_clamped_to_the_net_that_exists():
    from am3d.core.project import Patch
    patch = Patch(name="p", interior=np.zeros((3, 6, 3)),
                  degree_u=3, degree_v=3)
    assert patch.effective_degrees() == (2, 3)


# --- persistence ------------------------------------------------------------

def test_generator_and_degrees_survive_save_and_reopen(tmp_path):
    session, obj = _lathed()
    MoveCPCommand(session, "vase", "profile", 1,
                  [1.5, 1.0, 0.0], [4.0, 1.0, 0.0]).redo()
    expected = _surface_radius(session)

    from am3d.core.serializer import load_project, save_project
    path = tmp_path / "vase.am3d"
    save_project(session.project, str(path))

    reopened = Session()
    reopened.project = load_project(str(path))
    assert _surface_radius(reopened) == pytest.approx(expected, abs=1e-9)

    patch = reopened.project.objects["vase"].patches[0]
    assert patch.generator == {"op": "lathe", "spline": "profile",
                               "params": {"sections": 8}}

    # And the surface is still editable after reopening.
    MoveCPCommand(reopened, "vase", "profile", 1,
                  [4.0, 1.0, 0.0], [1.5, 1.0, 0.0]).redo()
    assert _surface_radius(reopened) < expected - 0.5
