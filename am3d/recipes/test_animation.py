"""Tests for procedural action generators."""

from __future__ import annotations

import math

import numpy as np
import pytest

from am3d.core.animation import Action
from am3d.core.project import Bone
from am3d.recipes.animation import generate_action, generate_walk_cycle


def _biped():
    return [
        Bone(name="hip", head=[0, 0.9, 0], tail=[0, 1.0, 0]),
        Bone(name="spine", parent="hip", head=[0, 1.0, 0], tail=[0, 1.4, 0]),
        Bone(name="head", parent="spine", head=[0, 1.4, 0], tail=[0, 1.6, 0]),
        Bone(name="arm_l", parent="spine", head=[-0.2, 1.35, 0],
             tail=[-0.45, 1.05, 0]),
        Bone(name="arm_r", parent="spine", head=[0.2, 1.35, 0],
             tail=[0.45, 1.05, 0]),
        Bone(name="leg_l", parent="hip", head=[-0.12, 0.9, 0],
             tail=[-0.12, 0.45, 0]),
        Bone(name="leg_r", parent="hip", head=[0.12, 0.9, 0],
             tail=[0.12, 0.45, 0]),
    ]


def test_walk_covers_every_bone_and_loops():
    bones = _biped()
    act = generate_action("walk", bones)
    assert isinstance(act, Action)
    animated = {ch.bone for ch in act.channels}
    assert animated == {b.name for b in bones}
    # loopable: first and last sampled root positions match in Y/Z and the
    # swing phase returns to zero.
    ch = act.get_channel("hip", "translate")
    first, last = ch.keys[0], ch.keys[-1]
    assert np.isclose(first.value[0], 0.0)
    assert np.allclose(first.value[1:], last.value[1:], atol=1e-9)


def test_walk_legs_swing_in_opposite_phase():
    # Only the two legs: no root present, so both get 'rotate' channels.
    bones = [b for b in _biped() if b.name.startswith("leg")]
    act = generate_action("walk", bones, duration=1.0,
                          amplitude_deg=30.0)
    quarter_l = act.get_channel("leg_l", "rotate").sample(0.25)[0]
    quarter_r = act.get_channel("leg_r", "rotate").sample(0.25)[0]
    assert abs(quarter_l) > 1e-4 and abs(quarter_r) > 1e-4
    assert np.sign(quarter_l) != np.sign(quarter_r), "legs must counter-swing"


def test_idle_motion_is_subtle():
    bones = _biped()
    act = generate_action("idle", bones)
    for ch in act.channels:
        for key in ch.keys:
            assert np.abs(key.value).max() < 0.15


def test_jump_root_goes_up_then_returns():
    bones = _biped()
    act = generate_action("jump", bones, height=0.8)
    ch = act.get_channel("hip", "translate")
    ys = [k.value[1] for k in ch.keys]
    assert max(ys) == pytest.approx(0.8)
    assert min(ys) < 0                       # crouch dips below rest
    assert ys[-1] == pytest.approx(0.0)


def test_generate_action_rejects_unknown_kind_and_empty_bones():
    with pytest.raises(ValueError, match="unknown action kind"):
        generate_action("fly", _biped())
    with pytest.raises(ValueError, match="at least one bone"):
        generate_action("walk", [])


def test_generated_actions_are_serializable(tmp_path):
    from am3d.core.serializer import dump_action, load_action
    act = generate_walk_cycle(_biped())
    clone = load_action(dump_action(act))
    assert clone.signature == act.signature
    a = act.sample(0.3)
    b = clone.sample(0.3)
    for bone in a:
        for prop in a[bone]:
            assert np.allclose(a[bone][prop], b[bone][prop], atol=1e-6)