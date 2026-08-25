"""Animation & Action-reuse system.

This implements the Choreography-Mode foundations: keyframes, channels, and
reusable *Actions*.  An Action is an independent, saved asset (in the spirit
of Animation Master's Actions) that holds per-bone animation curves plus a
skeleton signature, so it can be dropped onto any character with a
compatible skeleton.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


class Interpolation:
    """Enum-like interpolation modes for keyframes."""

    LINEAR = "linear"
    STEP = "step"
    SMOOTH = "smooth"


@dataclass
class Keyframe:
    """A single pose value at a time with bezier-style tangents."""

    time: float
    value: np.ndarray
    interp: str = Interpolation.SMOOTH
    in_tangent: np.ndarray | None = None
    out_tangent: np.ndarray | None = None

    def __post_init__(self):
        self.value = np.asarray(self.value, dtype=np.float64)


def _smooth_bezier(t, p0, p1, m0, m1):
    """Hermite (Catmull-Rom/Cardinal-like) interpolation between keyframes.

    ``m0``/``m1`` are the outgoing/incoming tangents.
    """
    h00 = (1 + 2 * t) * (1 - t) ** 2
    h10 = t * (1 - t) ** 2
    h01 = t * t * (3 - 2 * t)
    h11 = t * t * (t - 1)
    return h00 * p0 + h10 * m0 + h01 * p1 + h11 * m1


@dataclass
class Channel:
    """Animated curve for one property of one bone/node."""

    bone: str = "root"
    property: str = "translate"   # translate | rotate | scale | weight
    keys: list = field(default_factory=list)   # list[Keyframe] sorted by time

    def add_key(self, time, value, interp=Interpolation.SMOOTH) -> Keyframe:
        k = Keyframe(float(time), np.asarray(value, dtype=np.float64), interp)
        self.keys.append(k)
        self.keys.sort(key=lambda k_: k_.time)
        return k

    def sample(self, time: float) -> np.ndarray:
        """Evaluate the channel at *time* (clamped at the ends)."""
        keys = self.keys
        if not keys:
            return np.zeros(0)
        if time <= keys[0].time:
            return keys[0].value.copy()
        if time >= keys[-1].time:
            return keys[-1].value.copy()
        # locate interval
        for i in range(len(keys) - 1):
            k0, k1 = keys[i], keys[i + 1]
            if k0.time <= time <= k1.time:
                span = k1.time - k0.time
                t = 0.0 if span <= 0 else (time - k0.time) / span
                if k1.interp == Interpolation.STEP:
                    return k0.value.copy()
                if k1.interp == Interpolation.LINEAR:
                    return (1 - t) * k0.value + t * k1.value
                # smooth: build tangents from neighbours
                kp = keys[i - 1] if i > 0 else k0
                kn = keys[i + 2] if i + 2 < len(keys) else k1
                # Catmull-Rom tangents must be scaled by the interval
                # duration so velocity is right for non-uniform key spacing.
                if k0.out_tangent is None:
                    m0 = (k1.value - kp.value) * 0.5 * span
                else:
                    m0 = k0.out_tangent
                if k1.in_tangent is None:
                    m1 = (kn.value - k0.value) * 0.5 * span
                else:
                    m1 = k1.in_tangent
                return _smooth_bezier(t, k0.value, k1.value, m0, m1)
        return keys[-1].value.copy()


def skeleton_signature(bones) -> tuple:
    """A JSON-able signature describing a skeleton's hierarchical layout.

    ``bones`` : sequence of objects with ``.name`` and ``.parent``.
    """
    return ("|".join(f"{b.name}->{b.parent or 'root'}" for b in bones))


@dataclass
class Action:
    """A reusable animation clip (an asset, reusable across characters)."""

    name: str = "action"
    duration: float = 1.0
    channels: list = field(default_factory=list)   # list[Channel]
    signature: tuple = ()
    metadata: dict = field(default_factory=dict)

    def add_channel(self, bone, prop="translate") -> Channel:
        ch = Channel(bone=bone, property=prop)
        self.channels.append(ch)
        return ch

    def get_channel(self, bone, prop="translate") -> Channel | None:
        for ch in self.channels:
            if ch.bone == bone and ch.property == prop:
                return ch
        return None

    def compatible_with(self, bones) -> bool:
        """True if *bones* (sequence with .name) covers this action's bones."""
        sig = skeleton_signature(bones)
        if not self.signature:
            return True
        names = {b.name for b in bones}
        return all(ch.bone in names for ch in self.channels)

    def sample(self, time: float):
        """Return dict bone_name -> {property: value} at *time*."""
        out = {}
        for ch in self.channels:
            val = ch.sample(time)
            if ch.bone not in out:
                out[ch.bone] = {}
            out[ch.bone][ch.property] = val
        return out


class ActionBlender:
    """Blend multiple actions together (simple cross-fade mix)."""

    def __init__(self, actions):
        self.actions = list(actions)

    def sample(self, time, weights=None):
        if not self.actions:
            return {}
        if weights is None:
            weights = np.ones(len(self.actions)) / len(self.actions)
        w = np.asarray(weights, dtype=np.float64)
        acc = {}
        wsum = {}
        for a, wi in zip(self.actions, w):
            frame = a.sample(time)
            for bone, props in frame.items():
                for prop, val in props.items():
                    acc.setdefault(bone, {})
                    wsum.setdefault(bone, {})
                    if prop in acc[bone]:
                        acc[bone][prop] = acc[bone][prop] + wi * val
                        wsum[bone][prop] += wi
                    else:
                        acc[bone][prop] = wi * val
                        wsum[bone][prop] = wi
        # Renormalize per bone/property by the weight mass that actually
        # contributed, so a bone present in only some actions is not scaled
        # down by the missing actions' weights.
        for bone, props in acc.items():
            for prop, val in props.items():
                ws = wsum[bone][prop]
                if ws > 0:
                    props[prop] = val / ws
        return acc