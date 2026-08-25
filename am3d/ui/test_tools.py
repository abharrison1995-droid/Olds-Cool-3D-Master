"""Headless tests for the spline-CP and bone-pose tool helpers."""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.project import ControlPoint, Spline
from am3d.core.script import Session
from am3d.ui import tools_bone, tools_spline
from am3d.ui.camera import Camera


def _spline(n=4, degree=3, closed=False):
    return Spline(name="sp",
                  cps=[ControlPoint.from_tuple(i, 0, 0) for i in range(n)],
                  degree=degree, closed=closed)


# -- spline CP editing -------------------------------------------------------

def test_insert_cp_after_midpoint():
    sp = _spline()
    idx = tools_spline.insert_cp_after(sp, 0)
    assert idx == 1
    assert len(sp.cps) == 5
    assert np.allclose(sp.cps[1].position, (0.5, 0, 0))


def test_insert_cp_at_open_end_extends():
    sp = _spline()
    idx = tools_spline.insert_cp_after(sp, 3)
    assert idx == 4
    assert np.allclose(sp.cps[4].position, (4, 0, 0))   # same direction
    # Closed spline wraps: midpoint between last and first.
    sp = _spline(closed=True)
    idx = tools_spline.insert_cp_after(sp, 3)
    assert np.allclose(sp.cps[4].position, (1.5, 0, 0))


def test_remove_cp_degree_guard():
    sp = _spline(n=5, degree=3)
    assert tools_spline.can_remove_cp(sp, 0)
    tools_spline.remove_cp(sp, 0)
    assert len(sp.cps) == 4
    assert not tools_spline.can_remove_cp(sp, 0)   # would drop below deg+1
    with pytest.raises(ValueError):
        tools_spline.remove_cp(sp, 0)


def test_remove_cp_bounds():
    sp = _spline()
    assert not tools_spline.can_remove_cp(sp, -1)
    assert not tools_spline.can_remove_cp(sp, 99)


def test_cp_hit_test_and_world_roundtrip():
    s = Session()
    obj = s.create_object("o")
    obj.add_spline(_spline())
    cam = Camera(yaw=0.0, pitch=0.0, distance=4.0)
    pos = tools_spline.cp_screen_positions(obj, cam, 640, 480)
    assert len(pos) == 4
    x, y, valid = pos[("sp", 2)]
    assert valid
    hit = tools_spline.hit_cp(obj, cam, 640, 480, x, y)
    assert hit == ("sp", 2)
    assert tools_spline.hit_cp(obj, cam, 640, 480, 3, 3) is None

    # world_to_object inverts the object transform.
    obj.transform[:3, 3] = (10, 0, 0)
    world = np.array([11.0, 0.0, 0.0])
    assert np.allclose(tools_spline.world_to_object(obj, world),
                       (1, 0, 0))


# -- bone posing ---------------------------------------------------------------

def _rigged():
    s = Session()
    s.create_object("char")
    s.add_bone("char", "hip", (0, 0, 0), (0, 1, 0))
    s.add_bone("char", "knee", (0, 1, 0), (0, 2, 0), parent="hip")
    return s


def test_pose_bone_and_apply_pose():
    s = _rigged()
    rest = tools_bone.bone_endpoints(s, "char")
    # Pose rotations are in the bone's local frame (local Z = bone
    # direction), so an X Euler tips the bone instead of rolling it.
    s.pose_bone("char", "hip", (90, 0, 0))       # Euler degrees accepted
    out = s.apply_pose("char")
    assert "char" in out and "hip" in out["char"]
    posed = tools_bone.bone_endpoints(s, "char")
    # Tipping the hip 90 deg about local X points its tail to -X world.
    assert np.allclose(posed["hip"][1], (-1, 0, 0), atol=1e-9)
    # ...and the child knee follows the parent's pose.
    assert not np.allclose(posed["knee"][0], rest["knee"][0])
    s.clear_pose("char")
    s.apply_pose("char")
    assert np.allclose(tools_bone.bone_endpoints(s, "char")["hip"][1],
                       (0, 1, 0))


def test_pose_bone_matrix_and_errors():
    s = _rigged()
    from am3d.core.mathutil import rot_matrix
    s.pose_bone("char", "knee", rot_matrix((0, 0, 1), 0.5))
    assert s.poses["char"]["knee"].shape == (3, 3)
    with pytest.raises(Exception):
        s.pose_bone("char", "missing", np.eye(3))
    with pytest.raises(Exception):
        s.pose_bone("char", "knee", np.zeros((2, 2)))


def test_compose_pose_accumulates():
    s = _rigged()
    # Local-X rotation tips the bone (local Z is the bone direction).
    r1 = tools_bone.compose_pose(s, "char", "hip", (1, 0, 0), 0.3)
    r2 = tools_bone.compose_pose(s, "char", "hip", (1, 0, 0), 0.3)
    assert not np.allclose(r1, r2)
    posed = tools_bone.bone_endpoints(s, "char")["hip"]
    rest_dir = np.array([0.0, 1.0, 0.0])
    posed_dir = posed[1] - posed[0]
    cos = float(np.dot(posed_dir, rest_dir) / np.linalg.norm(posed_dir))
    assert np.isclose(np.arccos(cos), 0.6, atol=1e-6)


def test_pose_resets_on_new_project():
    s = _rigged()
    s.pose_bone("char", "hip", (0, 0, 45))
    s.apply_pose("char")
    s.new_project("fresh")
    assert s.poses == {} and s.posed_transforms == {}
