"""Tests for Phase 5: action CRUD, keyframe editing, and the
Action.sample -> pose -> FK chain used by the dope sheet / playback."""

from __future__ import annotations

import os

import numpy as np
import pytest

from am3d.core.script import Session, ScriptingError


def _hero_session():
    """A session with the demo's 2-bone hero skeleton."""
    s = Session()
    s.create_object("hero")
    s.add_bone("hero", "hip", (0, 0, 0), (0, 0.5, 0))
    s.add_bone("hero", "upper", (0, 0.5, 0), (0, 1.0, 0), parent="hip")
    return s


def test_action_crud():
    s = Session()
    s.create_action("walk", duration=2.0)
    assert s.active_action == "walk"
    with pytest.raises(ScriptingError):
        s.create_action("walk")                  # duplicate
    s.create_action("idle")
    s.rename_action("idle", "breathe")
    assert "breathe" in s.actions and "idle" not in s.actions
    s.set_active_action("breathe")
    assert s.active_action == "breathe"
    s.delete_action("walk")
    assert list(s.actions) == ["breathe"]
    with pytest.raises(ScriptingError):
        s.delete_action("walk")
    with pytest.raises(ScriptingError):
        s.set_active_action("walk")


def test_assignment_follows_rename_and_delete():
    s = _hero_session()
    s.create_action("walk")
    s.assign_action("walk", "hero")
    assert s.action_assignments == {"hero": "walk"}
    s.rename_action("walk", "run")
    assert s.action_assignments == {"hero": "run"}
    s.delete_action("run")
    assert s.action_assignments == {}


def test_keyframe_insert_replace_remove():
    s = _hero_session()
    s.create_action("a")
    s.insert_keyframe("a", "hip", "rotate", 0.0, [0.0, 0.0, 0.0])
    s.insert_keyframe("a", "hip", "rotate", 1.0, [0.5, 0.0, 0.0])
    ch = s.get_action("a").get_channel("hip", "rotate")
    assert len(ch.keys) == 2
    # Same time replaces instead of duplicating.
    s.insert_keyframe("a", "hip", "rotate", 1.0, [0.9, 0.0, 0.0])
    assert len(ch.keys) == 2
    assert np.isclose(ch.keys[1].value[0], 0.9)
    k = s.remove_keyframe("a", "hip", "rotate", 0)
    assert np.allclose(k.value, [0, 0, 0])
    assert len(ch.keys) == 1
    with pytest.raises(ScriptingError):
        s.remove_keyframe("a", "hip", "rotate", 5)


def test_apply_action_frame_drives_fk_pose():
    s = _hero_session()
    act = s.create_action("walk", duration=1.0)
    ch = act.add_channel("hip", "translate")
    ch.add_key(0.0, [0, 0, 0], "linear")
    ch.add_key(1.0, [0.5, 0, 0], "linear")
    rot = act.add_channel("upper", "rotate")
    rot.add_key(0.0, [0, 0, 0], "linear")
    rot.add_key(1.0, [0.5, 0, 0], "linear")
    s.assign_action("walk", "hero")

    s.apply_action_frame("hero", 0.0)
    t0 = {k: v.copy() for k, v in s.posed_transforms["hero"].items()}
    s.apply_action_frame("hero", 0.5)
    t1 = s.posed_transforms["hero"]

    # The translate channel moved the hip by half the amplitude...
    assert np.allclose(t1["hip"][:3, 3] - t0["hip"][:3, 3], [0.25, 0, 0],
                       atol=1e-9)
    # ...and the rotate channel bent the chain (upper tail moved sideways).
    assert not np.allclose(t1["upper"], t0["upper"])
    # Posed transforms equal rest @ sampled channels via fk_pose directly.
    sample = act.sample(0.5)
    assert np.allclose(sample["hip"]["translate"], [0.25, 0, 0])
    from am3d.core.mathutil import compose_trs
    expected_rot = compose_trs((0, 0, 0),
                               np.rad2deg(sample["upper"]["rotate"]),
                               (1, 1, 1))[:3, :3]
    assert np.allclose(s.poses["hero"]["upper"], expected_rot)


def test_walk_am3a_plays_on_hero_skeleton():
    """assets/walk.am3a loads, applies to the demo hero, animates."""
    path = os.path.join(os.path.dirname(__file__), "..", "..",
                        "assets", "walk.am3a")
    s = _hero_session()
    act = s.load_action_file(os.path.abspath(path))
    assert act.name == "walk"
    s.assign_action("walk", "hero")
    s.apply_action_frame("hero", 0.0)
    base = s.posed_transforms["hero"]["hip"][:3, 3].copy()
    for t in (0.25, 0.5, 0.75, 1.0):
        s.apply_action_frame("hero", t)
        world = s.posed_transforms["hero"]["hip"][:3, 3]
        sampled = act.sample(t)["hip"]["translate"]
        assert np.allclose(world - base, sampled, atol=1e-9)


def test_key_bone_from_pose_roundtrip():
    s = _hero_session()
    s.create_action("a")
    s.pose_bone("hero", "upper", (0.0, 0.0, 30.0))   # Euler XYZ degrees
    s.apply_pose("hero")
    keys = s.key_bone_from_pose("a", "hero", "upper", 0.5)
    assert len(keys) == 1                              # rotate key
    # Clear the pose, then replay the keyed frame: the pose comes back.
    s.clear_pose("hero")
    s.apply_action_frame("hero", 0.5, "a")
    assert "upper" in s.poses["hero"]
    world = s.posed_transforms["hero"]["upper"]
    s.clear_pose("hero")
    s.pose_bone("hero", "upper", (0.0, 0.0, 30.0))
    expected = s.apply_pose("hero")["hero"]["upper"]
    assert np.allclose(world, expected, atol=1e-6)


def test_animation_settings_serialize(tmp_path):
    s = _hero_session()
    # Defaults keep the old 0..120 @ 30 fps == 4.0 s behaviour.
    assert s.project.animation_settings == {"frame_start": 0,
                                            "frame_end": 120, "fps": 30.0}
    s.project.animation_settings.update({"frame_end": 240, "fps": 24.0})
    path = str(tmp_path / "p.am3d")
    s.save_project(path)
    s2 = Session()
    s2.load_project(path)
    assert s2.project.animation_settings["frame_end"] == 240
    assert s2.project.animation_settings["fps"] == 24.0
    assert s2.project.animation_settings["frame_start"] == 0


def test_old_project_without_animation_settings_loads():
    """Backward compat: a payload lacking the section keeps defaults."""
    from am3d.core.project import Project
    from am3d.core.serializer import dump_project, load_project_bytes
    import msgpack
    payload = dump_project(Project("old"))
    body = msgpack.unpackb(payload, raw=False)
    body.pop("animation_settings", None)
    p = load_project_bytes(msgpack.packb(body, use_bin_type=True))
    assert p.animation_settings == {"frame_start": 0, "frame_end": 120,
                                    "fps": 30.0}


def test_deform_object_skinned_and_plain():
    """deform_object moves weighted CPs with the pose, ignores unrigged."""
    from am3d.core.rigging import deform_object, fk_pose
    s = _hero_session()
    s.add_spline("hero", [(0, 0, 0), (0, 0.5, 0), (0, 1.0, 0)], name="spine")
    rig = s.project.skeletons["hero"]
    rig["upper"].cp_weights = {2: 1.0}       # top CP fully on "upper"

    obj = s.get_object("hero")
    bones = list(rig.values())
    rest = fk_pose(bones)
    unchanged = deform_object(obj, bones, rest, rest)
    assert np.allclose(unchanged.splines["spine"].point_array(),
                       obj.splines["spine"].point_array())

    s.pose_bone("hero", "upper", (0.0, 0.0, 45.0))
    posed = s.apply_pose("hero")["hero"]
    deformed = deform_object(obj, bones, posed, rest)
    assert not np.allclose(deformed.splines["spine"].cps[2].position,
                           obj.splines["spine"].cps[2].position)
    # Unweighted CPs and the source object stay untouched.
    assert np.allclose(deformed.splines["spine"].cps[0].position,
                       obj.splines["spine"].cps[0].position)
    assert np.allclose(obj.splines["spine"].cps[2].position, (0, 1, 0))

    # No weights at all -> identity (same object returned, no copy).
    s2 = _hero_session()
    obj2 = s2.get_object("hero")
    assert deform_object(obj2, list(s2.project.skeletons["hero"].values()),
                         {}, {}) is obj2


# -- dragging a key onto an occupied time overwrites it -----------------


def _move_setup():
    """Session with one action, one channel, keys at 0.0 / 1.0 / 2.0."""
    s = _hero_session()
    s.create_action("a")
    for t in (0.0, 1.0, 2.0):
        s.insert_keyframe("a", "hip", "rotate", t, [t, 0.0, 0.0])
    return s, s.get_action("a").get_channel("hip", "rotate")


def _move(s, index, to_time):
    from am3d.ui.operators import MoveKeyCommand
    cmd = MoveKeyCommand(s, "a", "hip", "rotate", index, to_time)
    cmd.redo()
    return cmd


def test_drag_onto_occupied_time_overwrites_target():
    s, ch = _move_setup()
    _move(s, 0, 1.0)                       # drag key at 0.0 onto 1.0
    times = [k.time for k in ch.keys]
    assert times == [1.0, 2.0]             # target gone, no duplicate
    assert np.isclose(ch.keys[0].value[0], 0.0)   # dragged key's value wins
    assert np.allclose(ch.sample(1.0), [0.0, 0.0, 0.0])


def test_drag_onto_occupied_time_undo_restores_both_keys():
    s, ch = _move_setup()
    cmd = _move(s, 0, 1.0)
    cmd.undo()
    times = [k.time for k in ch.keys]
    assert times == [0.0, 1.0, 2.0]
    assert np.isclose(ch.keys[0].value[0], 0.0)   # moved key back home
    assert np.isclose(ch.keys[1].value[0], 1.0)   # displaced key restored


def test_drag_overwrite_survives_repeated_undo_redo():
    """The command must be idempotent under undo/redo cycling."""
    s, ch = _move_setup()
    cmd = _move(s, 0, 1.0)
    for _ in range(3):
        cmd.undo()
        assert [k.time for k in ch.keys] == [0.0, 1.0, 2.0]
        cmd.redo()
        assert [k.time for k in ch.keys] == [1.0, 2.0]
    cmd.undo()
    assert len(ch.keys) == 3
    assert np.isclose(ch.keys[1].value[0], 1.0)


def test_drag_to_free_time_displaces_nothing():
    s, ch = _move_setup()
    cmd = _move(s, 0, 0.5)
    assert [k.time for k in ch.keys] == [0.5, 1.0, 2.0]
    assert cmd._displaced is None
    cmd.undo()
    assert [k.time for k in ch.keys] == [0.0, 1.0, 2.0]


def test_drag_onto_own_time_is_a_no_op():
    """Moving a key to where it already is must not delete it."""
    s, ch = _move_setup()
    cmd = _move(s, 1, 1.0)
    assert [k.time for k in ch.keys] == [0.0, 1.0, 2.0]
    assert cmd._displaced is None
    cmd.undo()
    assert [k.time for k in ch.keys] == [0.0, 1.0, 2.0]
