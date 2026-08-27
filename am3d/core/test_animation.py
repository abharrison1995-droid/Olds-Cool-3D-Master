"""Tests for the animation / Action-reuse system."""

from __future__ import annotations

import numpy as np

from am3d.core.animation import (
    Action,
    ActionBlender,
    Channel,
    Interpolation,
    skeleton_signature,
)
from am3d.core.project import Bone


def test_channel_linear_interpolation():
    ch = Channel(bone="hip", property="translate")
    ch.add_key(0.0, [0, 0, 0], Interpolation.LINEAR)
    ch.add_key(1.0, [10, 0, 0], Interpolation.LINEAR)
    mid = ch.sample(0.5)
    assert np.allclose(mid, [5, 0, 0], atol=1e-9)


def test_channel_clamps_ends():
    ch = Channel()
    ch.add_key(0.0, [1, 1, 1])
    ch.add_key(2.0, [3, 3, 3])
    assert np.allclose(ch.sample(-5), [1, 1, 1])
    assert np.allclose(ch.sample(99), [3, 3, 3])


def test_channel_step():
    ch = Channel()
    ch.add_key(0.0, [0], Interpolation.STEP)
    ch.add_key(1.0, [1], Interpolation.STEP)
    assert ch.sample(0.7) == [0]


def test_action_compatibility():
    bones = [Bone(name="hip"), Bone(name="upper", parent="hip"),
             Bone(name="lower", parent="upper")]
    a = Action(name="walk", duration=1.0)
    a.add_channel("hip").add_key(0, [0, 0, 0])
    a.add_channel("upper").add_key(0, [0, 0, 0])
    a.signature = skeleton_signature(bones)
    assert a.compatible_with(bones)

    other = [Bone(name="root"), Bone(name="head", parent="root")]
    assert not a.compatible_with(other)


def test_action_sample_shape():
    a = Action(name="idle", duration=2.0)
    ch = a.add_channel("arm")
    ch.add_key(0.0, [0, 0, 0])
    ch.add_key(2.0, [0, 1, 0])
    frame = a.sample(1.0)
    assert "arm" in frame and "translate" in frame["arm"]


def test_action_blender_mixes():
    a1 = Action("a1", duration=1.0)
    a1.add_channel("root").add_key(0, [0, 0, 0])
    a2 = Action("a2", duration=1.0)
    a2.add_channel("root").add_key(0, [2, 0, 0])
    bl = ActionBlender([a1, a2])
    frame = bl.sample(0.0, weights=[0.5, 0.5])
    assert np.allclose(frame["root"]["translate"], [1, 0, 0], atol=1e-9)


def test_smooth_uses_out_and_in_tangents():
    # Explicit tangents must be honoured (out_tangent on k0, in_tangent on k1).
    ch = Channel()
    k0 = ch.add_key(0.0, [0.0], Interpolation.SMOOTH)
    k1 = ch.add_key(1.0, [1.0], Interpolation.SMOOTH)
    k0.in_tangent = np.array([100.0])   # wrong source — must be ignored
    k1.out_tangent = np.array([-100.0])  # wrong source — must be ignored
    k0.out_tangent = np.array([0.0])
    k1.in_tangent = np.array([0.0])
    mid = ch.sample(0.5)
    assert np.allclose(mid, [0.5], atol=1e-9)


def test_smooth_catmull_rom_scales_with_interval():
    # Same key values, different time spacing: with unit-spaced keys the
    # midpoint equals the untimed Catmull-Rom value; with a longer span the
    # tangent magnitudes must grow with (k1.time - k0.time).
    def _midpoint(dt):
        ch = Channel()
        ch.add_key(0.0, [0.0], Interpolation.SMOOTH)
        ch.add_key(dt, [1.0], Interpolation.SMOOTH)
        ch.add_key(2 * dt, [2.0], Interpolation.SMOOTH)
        ch.add_key(3 * dt, [3.0], Interpolation.SMOOTH)
        # sample the middle interval (key1 -> key2) at its midpoint
        return ch.sample(1.5 * dt)[0]

    # Uniform spacing -> linear ramp, midpoint must be 1.5 regardless of dt.
    assert np.isclose(_midpoint(1.0), 1.5, atol=1e-9)
    assert np.isclose(_midpoint(10.0), 1.5, atol=1e-9)

    # Non-uniform spacing: neighbours at t=0 and t=10 around a long interval
    # must bend the curve; without span scaling the tangent is too small.
    ch = Channel()
    ch.add_key(0.0, [0.0], Interpolation.SMOOTH)
    ch.add_key(1.0, [0.0], Interpolation.SMOOTH)
    ch.add_key(9.0, [8.0], Interpolation.SMOOTH)
    ch.add_key(10.0, [9.0], Interpolation.SMOOTH)
    # Interval key1 -> key2 (span 8), sample at t = 0.25.
    # m0 = (k1-kp)/2*span = (8-0)*0.5*8 = 32, m1 = (kn-k0)/2*span = 36.
    t = 0.25
    h00 = (1 + 2 * t) * (1 - t) ** 2
    h10 = t * (1 - t) ** 2
    h01 = t * t * (3 - 2 * t)
    h11 = t * t * (t - 1)
    expected = h00 * 0.0 + h10 * 32.0 + h01 * 8.0 + h11 * 36.0
    assert np.isclose(ch.sample(3.0)[0], expected, atol=1e-9)
    # and the scaled result clearly differs from the unscaled one
    unscaled = h00 * 0.0 + h10 * 4.0 + h01 * 8.0 + h11 * 4.5
    assert not np.isclose(ch.sample(3.0)[0], unscaled, atol=1e-6)


def test_action_blender_renormalizes_partial_bones():
    # 'arm' exists only in a2: with weights [0.5, 0.5] its value must not be
    # halved by the missing weight mass from a1.
    a1 = Action("a1", duration=1.0)
    a1.add_channel("root").add_key(0, [0, 0, 0])
    a2 = Action("a2", duration=1.0)
    a2.add_channel("root").add_key(0, [2, 0, 0])
    a2.add_channel("arm").add_key(0, [4, 0, 0])
    bl = ActionBlender([a1, a2])
    frame = bl.sample(0.0, weights=[0.5, 0.5])
    assert np.allclose(frame["root"]["translate"], [1, 0, 0], atol=1e-9)
    assert np.allclose(frame["arm"]["translate"], [4, 0, 0], atol=1e-9)

# -- a channel holds at most one key per time ---------------------------


def _ch():
    from am3d.core.animation import Channel
    return Channel(bone="hip", property="rotate")


def test_add_key_at_same_time_replaces_rather_than_duplicating():
    """The newer write must win; previously it was silently unreachable."""
    ch = _ch()
    ch.add_key(1.0, [1, 1, 1])
    ch.add_key(1.0, [2, 2, 2])
    assert len(ch.keys) == 1
    assert np.allclose(ch.sample(1.0), [2, 2, 2])


def test_add_key_replace_returns_the_same_keyframe_object():
    """Callers holding the key (undo commands) must not be orphaned."""
    ch = _ch()
    first = ch.add_key(1.0, [1, 1, 1])
    again = ch.add_key(1.0, [2, 2, 2])
    assert again is first
    assert np.allclose(first.value, [2, 2, 2])


def test_add_key_replace_updates_interpolation():
    from am3d.core.animation import Interpolation

    ch = _ch()
    ch.add_key(1.0, [1, 1, 1], Interpolation.SMOOTH)
    k = ch.add_key(1.0, [2, 2, 2], Interpolation.STEP)
    assert k.interp == Interpolation.STEP


def test_add_key_replace_clears_stale_tangents():
    """Tangents described the old value's velocity."""
    ch = _ch()
    k = ch.add_key(1.0, [1, 1, 1])
    k.in_tangent = np.array([9.0, 9.0, 9.0])
    k.out_tangent = np.array([9.0, 9.0, 9.0])
    ch.add_key(1.0, [2, 2, 2])
    assert k.in_tangent is None and k.out_tangent is None


def test_add_key_keeps_keys_sorted_and_unique():
    ch = _ch()
    for t in (2.0, 0.0, 1.0, 2.0, 0.0):
        ch.add_key(t, [t, 0, 0])
    times = [k.time for k in ch.keys]
    assert times == sorted(times)
    assert len(times) == len(set(times)) == 3


def test_add_key_distinct_times_still_accumulate():
    """Guard against over-correcting into replacing everything."""
    ch = _ch()
    for t in (0.0, 0.5, 1.0):
        ch.add_key(t, [t, 0, 0])
    assert len(ch.keys) == 3


def test_key_at_finds_and_misses():
    ch = _ch()
    ch.add_key(1.0, [1, 1, 1])
    assert ch.key_at(1.0) is ch.keys[0]
    assert ch.key_at(1.5) is None


def test_session_insert_keyframe_still_replaces_after_delegation():
    """insert_keyframe now delegates to add_key; behaviour must not change."""
    from am3d.core.project import Project
    from am3d.core.script import Session

    s = Session(Project("p"))
    s.create_action("a")
    s.insert_keyframe("a", "hip", "rotate", 1.0, [0.5, 0, 0])
    s.insert_keyframe("a", "hip", "rotate", 1.0, [0.9, 0, 0])
    ch = s.get_action("a").get_channel("hip", "rotate")
    assert len(ch.keys) == 1
    assert np.isclose(ch.keys[0].value[0], 0.9)
