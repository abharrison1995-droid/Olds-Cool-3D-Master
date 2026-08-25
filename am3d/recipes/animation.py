"""Procedural animation generators — instant reusable Actions.

An LLM asks for ``{"kind": "walk"}`` and gets back a fully keyed,
skeleton-compatible :class:`~am3d.core.animation.Action` without touching a
single keyframe by hand.

Generators are *convention-driven*: bones whose names contain ``left`` or
``right`` swing in opposite phase, hierarchy depth attenuates the motion,
and cycles start/end on the same pose so they loop cleanly.
"""

from __future__ import annotations

import math

from am3d.core.animation import Action, Interpolation

_SAMPLES = 13          # keys per cycle (smooth-interpolated)
_DEG = math.pi / 180.0


def _depth_map(bones) -> dict:
    """bone name -> hierarchy depth (root = 0)."""
    parents = {b.name: b.parent for b in bones}
    depths = {}

    def depth(name, seen=()):
        if name in depths:
            return depths[name]
        if name in seen:
            return 0
        p = parents.get(name)
        d = 0 if not p else depth(p, seen + (name,)) + 1
        depths[name] = d
        return d

    for b in bones:
        depth(b.name)
    return depths


def _side_of(name: str) -> int:
    """+1 right, -1 left, 0 centred."""
    low = name.lower()
    if "right" in low or "_r_" in low or low.startswith("r_") \
            or low.endswith("_r"):
        return 1
    if "left" in low or "_l_" in low or low.startswith("l_") \
            or low.endswith("_l"):
        return -1
    return 0


def _root_of(bones):
    return next((b for b in bones if not b.parent), None)


def _add_sampled_rotation(act: Action, bone_name: str, duration: float,
                          fn, interp: str = Interpolation.SMOOTH) -> None:
    ch = act.add_channel(bone_name, "rotate")
    for i in range(_SAMPLES):
        t = duration * i / (_SAMPLES - 1)
        ch.add_key(t, fn(t), interp)


def generate_walk_cycle(bones, name: str = "walk", duration: float = 1.0,
                        stride: float = 0.5, amplitude_deg: float = 24.0,
                        bob: float = 0.04) -> Action:
    """Looping walk: opposing limb swings, root translation and body bob."""
    act = Action(name=name, duration=float(duration))
    act.signature = tuple(f"{b.name}->{b.parent or 'root'}" for b in bones)
    act.metadata["generator"] = "walk"
    depths = _depth_map(bones)
    root = _root_of(bones)

    if root is not None:
        ch = act.add_channel(root.name, "translate")
        dur = float(duration)
        for i in range(_SAMPLES):
            t = dur * i / (_SAMPLES - 1)
            phase = 2.0 * math.pi * i / (_SAMPLES - 1)
            ch.add_key(t, [stride * i / (_SAMPLES - 1),
                           bob * abs(math.sin(phase)), 0.0])

    amp = float(amplitude_deg) * _DEG
    for bone in bones:
        if root is not None and bone.name == root.name:
            continue
        falloff = 1.0 / (1.0 + 0.45 * depths.get(bone.name, 1))
        side = _side_of(bone.name)
        phase = math.pi if side < 0 else 0.0
        swing = amp * falloff
        twist = 0.35 * swing

        def rot(t, _phase=phase, _swing=swing, _twist=twist, _side=side):
            w = 2.0 * math.pi * float(t) / float(duration)
            if _side == 0:
                return [_swing * 0.3 * math.sin(w),
                        _twist * math.sin(w + math.pi / 2), 0.0]
            return [_swing * math.sin(w + _phase), 0.0, 0.0]

        _add_sampled_rotation(act, bone.name, duration, rot)
    return act


def generate_idle(bones, name: str = "idle", duration: float = 2.4,
                  sway_deg: float = 2.0, breathe: float = 0.012) -> Action:
    """Gentle standing loop: weight shift plus a breathing bob."""
    act = Action(name=name, duration=float(duration))
    act.signature = tuple(f"{b.name}->{b.parent or 'root'}" for b in bones)
    act.metadata["generator"] = "idle"
    depths = _depth_map(bones)
    root = _root_of(bones)

    if root is not None:
        ch = act.add_channel(root.name, "translate")
        dur = float(duration)
        for i in range(_SAMPLES):
            t = dur * i / (_SAMPLES - 1)
            phase = 2.0 * math.pi * i / (_SAMPLES - 1)
            ch.add_key(t, [0.0, breathe * math.sin(phase), 0.0])

    amp = float(sway_deg) * _DEG
    for bone in bones:
        if root is not None and bone.name == root.name:
            continue
        falloff = 1.0 / (1.0 + 0.6 * depths.get(bone.name, 1))
        side = _side_of(bone.name)
        phase = math.pi / 2 if side < 0 else (
            -math.pi / 2 if side > 0 else 0.0)

        def rot(t, _phase=phase, _amp=amp * falloff):
            w = 2.0 * math.pi * float(t) / float(duration)
            return [_amp * 0.4 * math.sin(w + _phase),
                    _amp * math.sin(w * 0.5 + _phase), 0.0]

        _add_sampled_rotation(act, bone.name, duration, rot)
    return act


def generate_jump(bones, name: str = "jump", duration: float = 1.2,
                  crouch: float = -0.22, height: float = 0.65) -> Action:
    """Anticipate -> launch -> airborne -> land -> recover."""
    act = Action(name=name, duration=float(duration))
    act.signature = tuple(f"{b.name}->{b.parent or 'root'}" for b in bones)
    act.metadata["generator"] = "jump"
    root = _root_of(bones)
    if root is None:
        return act

    dur = float(duration)
    timeline = [
        (0.00, 0.0), (0.22, crouch), (0.42, height),
        (0.72, 0.02), (0.86, crouch * 0.4), (1.00, 0.0),
    ]
    ch = act.add_channel(root.name, "translate")
    for frac, y in timeline:
        ch.add_key(dur * frac, [0.0, float(y), 0.0], Interpolation.SMOOTH)

    depths = _depth_map(bones)
    for bone in bones:
        if bone.name == root.name:
            continue
        falloff = 1.0 / (1.0 + 0.5 * depths.get(bone.name, 1))
        bend = 38.0 * falloff * _DEG

        def rot(t, _bend=bend, _dur=dur):
            f = float(t) / _dur
            if f < 0.30:
                k = f / 0.30
            elif f < 0.55:
                k = 1.0 - (f - 0.30) / 0.25
            elif f < 0.80:
                k = (f - 0.55) / 0.25
            else:
                k = 1.0 - (f - 0.80) / 0.20
            return [_bend * max(0.0, min(1.0, k)), 0.0, 0.0]

        _add_sampled_rotation(act, bone.name, dur, rot)
    return act


_GENERATORS = {
    "walk": generate_walk_cycle,
    "idle": generate_idle,
    "jump": generate_jump,
}


def generate_action(kind: str, bones, name: str | None = None,
                    **params) -> Action:
    """Build any procedural Action by kind ('walk' | 'idle' | 'jump')."""
    key = str(kind).lower()
    if key not in _GENERATORS:
        raise ValueError(
            f"unknown action kind {kind!r} "
            f"(choose from {sorted(_GENERATORS)})")
    if not bones:
        raise ValueError("generate_action needs at least one bone")
    if name:
        params.setdefault("name", name)
    return _GENERATORS[key](bones, **params)