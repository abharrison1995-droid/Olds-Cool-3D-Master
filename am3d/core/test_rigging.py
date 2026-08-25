"""Tests for rigging: FK, 2-bone IK, and SmartSkins."""

from __future__ import annotations

import numpy as np

from am3d.core import rigging
from am3d.core.project import Bone


def test_fk_parent_then_child():
    hip = Bone(name="hip", head=[0, 0, 0], tail=[0, 1, 0])
    upper = Bone(name="upper", parent="hip", head=[0, 1, 0], tail=[0, 2, 0])
    world = rigging.fk_pose([hip, upper])
    # A child's world translation is the parent's world transform applied to
    # the child's local head offset (rigid-body propagation).
    expected = world["hip"][:3, :3] @ np.array([0, 1, 0]) + world["hip"][:3, 3]
    assert np.allclose(world["upper"][:3, 3], expected, atol=1e-9)
    assert np.allclose(world["hip"][:3, 3], [0, 0, 0], atol=1e-9)


def test_fk_translation_propagates_to_child():
    hip = Bone(name="hip", head=[0, 0, 0], tail=[0, 1, 0])
    upper = Bone(name="upper", parent="hip", head=[0, 1, 0], tail=[0, 2, 0])
    t = np.eye(4)
    t[0, 3] = 5.0
    world = rigging.fk_pose([hip, upper], {"hip": t})
    expected = world["hip"][:3, :3] @ np.array([0, 1, 0]) + world["hip"][:3, 3]
    assert np.allclose(world["upper"][:3, 3], expected, atol=1e-9)
    # hip translation (5,0,0) must appear in the child's world position.
    assert abs(world["upper"][0, 3] - 5.0) < 1e-9


def test_ik_tip_reaches_target():
    root = np.array([0.0, 0.0, 0.0])
    mid = np.array([1.0, 0.0, 0.0])
    tip = np.array([2.0, 0.0, 0.0])
    target = np.array([0.0, 1.8, 0.0])
    mid_out, tip_out = rigging.ik_two_bone(root, mid, tip, target)
    # chain lengths: 1 and 1
    assert np.allclose(np.linalg.norm(mid_out - root), 1.0, atol=1e-6)
    assert np.allclose(np.linalg.norm(tip_out - mid_out), 1.0, atol=1e-6)
    # tip should be at distance ~1.8 from root
    assert abs(np.linalg.norm(tip_out - root) - 1.8) < 1e-6


def test_ik_preserves_bone_lengths_when_out_of_reach():
    root = np.array([0.0, 0.0, 0.0])
    mid = np.array([1.0, 0.0, 0.0])
    tip = np.array([2.0, 0.0, 0.0])
    target = np.array([10.0, 0.0, 0.0])  # too far
    mid_out, tip_out = rigging.ik_two_bone(root, mid, tip, target)
    assert np.allclose(np.linalg.norm(mid_out - root), 1.0, atol=1e-6)
    assert np.allclose(np.linalg.norm(tip_out - mid_out), 1.0, atol=1e-6)
    assert abs(np.linalg.norm(tip_out - root) - 2.0) < 1e-6


def _identity_bones():
    a = Bone(name="a", head=[0, 0, 0], tail=[1, 0, 0])
    b = Bone(name="b", parent="a", head=[1, 0, 0], tail=[2, 0, 0])
    return [a, b]


def test_smartskin_rest_is_identity():
    # With identical rest & posed transforms (identity), deforming leaves a
    # control point unchanged and level.  Weighted blend of identity = point.
    rest = {"a": np.eye(4), "b": np.eye(4)}
    posed = {"a": np.eye(4), "b": np.eye(4)}
    weights = {"a": 0.5, "b": 0.5}
    out = rigging.smartskin_deform([1, 2, 3], weights, posed, rest, 0.5)
    assert np.allclose(out, [1, 2, 3], atol=1e-9)


def test_smartskin_bulge_pushes_outward_on_bend():
    # When a joint bends, the SmartSkins correction must push the affected
    # control point farther from the joint than plain linear blending does.
    rest = {"a": np.eye(4), "b": np.eye(4)}
    # Pose where bone a's axis bends 90 deg (forward +X -> +Y), collapsing the
    # region around the joint.
    th = np.radians(90)
    # Rotate about Y so the z-forward axis of the identity rest transforms
    # actually bends (a Z-rotation would leave the forward axis untouched).
    rot = np.array([[np.cos(th), 0, np.sin(th), 0],
                    [0, 1, 0, 0],
                    [-np.sin(th), 0, np.cos(th), 0],
                    [0, 0, 0, 1]])
    posed = {"a": rot, "b": rot}
    weights = {"a": 0.5, "b": 0.5}
    cp = np.array([1.0, 0.0, 0.0])
    plain = rigging.smartskin_deform(cp, weights, posed, rest, bulge_strength=0.0)
    corrected = rigging.smartskin_deform(cp, weights, posed, rest, bulge_strength=1.0)
    joint = np.zeros(3)
    d0 = float(np.linalg.norm(plain - joint))
    d1 = float(np.linalg.norm(corrected - joint))
    assert d1 > d0, f"bulge should push outward: plain={d0:.4f} corrected={d1:.4f}"


def test_smartskin_single_bone_weight():
    # A CP weighted to a single bone must not crash on the top-two unpack
    # and must follow that bone's rest->pose delta.
    rest = {"a": np.eye(4)}
    posed = {"a": np.eye(4)}
    posed["a"][0, 3] = 3.0  # translate +X
    out = rigging.smartskin_deform([1, 1, 1], {"a": 1.0}, posed, rest)
    assert np.allclose(out, [4, 1, 1], atol=1e-9)


def test_smartskin_applies_rest_to_pose_delta():
    # Linear blending must apply the delta T_cur @ inv(T_rest) to the rest
    # position, not the animated world matrix directly.  Rest translated to
    # (1,0,0), pose to (2,0,0): the delta is +1 in X, so a CP at the rest
    # joint origin (1,0,0) lands on (2,0,0) — not (3,0,0).
    rest = np.eye(4)
    rest[0, 3] = 1.0
    posed = np.eye(4)
    posed[0, 3] = 2.0
    out = rigging.smartskin_deform([1, 0, 0], {"a": 1.0},
                                   {"a": posed}, {"a": rest})
    assert np.allclose(out, [2, 0, 0], atol=1e-9)