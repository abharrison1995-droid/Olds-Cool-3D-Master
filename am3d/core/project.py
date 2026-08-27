"""Core document data model for 3D MASTER:2005.

This module holds the lightweight, scriptable in-memory representation of a
project: objects made of splines, patches and hooks; skeletons of bones with
CP weights; reusable Actions; and materials.  These are plain Python
dataclasses so an external agentic pipeline can construct, inspect and edit
scenes directly without the GUI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from .mathutil import normalize


@dataclass
class ControlPoint:
    """A spline control point (optionally rational)."""

    position: np.ndarray = field(default_factory=lambda: np.zeros(3))
    weight: float = 1.0

    def __post_init__(self):
        self.position = np.asarray(self.position, dtype=np.float64).reshape(3)

    @classmethod
    def from_tuple(cls, x, y, z, w=1.0) -> "ControlPoint":
        return cls(np.array([x, y, z], dtype=np.float64), float(w))


@dataclass
class Spline:
    """An ordered list of control points forming a single B-spline."""

    name: str = "spline"
    cps: list = field(default_factory=list)      # list[ControlPoint]
    degree: int = 3
    closed: bool = False

    def point_array(self) -> np.ndarray:
        return np.array([c.position for c in self.cps], dtype=np.float64)

    def weights_array(self):
        return np.array([c.weight for c in self.cps], dtype=np.float64)

    def __len__(self):
        return len(self.cps)


@dataclass
class Hook:
    """A coupling forcing two control points to share a position."""

    source: tuple = ()
    target: tuple = ()
    strength: float = 1.0


@dataclass
class Patch:
    """A 3- or 4-sided patch built from intersecting splines."""

    name: str = "patch"
    # For a 4-sided patch: [[top], [right], [bottom], [left]] spline ids
    # resolving in order around the boundary.  For 3-sided similarly.
    splines: list = field(default_factory=list)
    # (optionally loosened to a full interior control grid)
    interior: Optional[np.ndarray] = None


@dataclass
class Object3D:
    """An Object-Mode spline model (the 'patch' sandbox)."""

    name: str = "object"
    splines: dict = field(default_factory=dict)   # name -> Spline
    patches: list = field(default_factory=list)   # list[Patch]
    hooks: list = field(default_factory=list)      # list[Hook]
    transform: np.ndarray = field(
        default_factory=lambda: np.eye(4, dtype=np.float64))
    visible: bool = True

    def add_spline(self, spline: Spline):
        self.splines[spline.name] = spline
        return spline


@dataclass
class Bone:
    name: str = "bone"
    parent: Optional[str] = None
    # local head/tail in object space
    head: np.ndarray = field(default_factory=lambda: np.zeros(3))
    tail: np.ndarray = field(default_factory=lambda: np.array([0.0, 1.0, 0.0]))
    # cp weights: control-point index -> weight
    cp_weights: dict = field(default_factory=dict)

    def __post_init__(self):
        self.head = np.asarray(self.head, dtype=np.float64).reshape(3)
        self.tail = np.asarray(self.tail, dtype=np.float64).reshape(3)


@dataclass
class Material:
    """A material with procedural / mapped channels bound to the patch UV."""

    name: str = "material"
    color: tuple = (0.8, 0.8, 0.8)
    bump_map: Optional[str] = None
    transparency_map: Optional[str] = None
    specular_map: Optional[str] = None


class Project:
    """Top-level document container."""

    def __init__(self, name: str = "Untitled"):
        self.name = name
        self.objects: dict = {}            # name -> Object3D
        self.skeletons: dict = {}          # name -> Skeleton
        self.materials: dict = {}          # name -> Material
        self.mode = "object"               # object|segment|material|choreography
        self.frame = 0.0
        self.fps = 30.0
        # Render options consumed by the viewport / toon renderer.
        self.render_settings = {"supersample": 2, "toon": True}
        # Choreography options consumed by the dope sheet / playback:
        # frame range at ``fps`` (default 0..120 @ 30 fps == the old 4.0 s).
        self.animation_settings = {"frame_start": 0, "frame_end": 120,
                                   "fps": 30.0}
        # Session-level state persisted in format_version >= 2
        self.active_action: str | None = None
        self.action_assignments: dict = {}

    # ---- object management -------------------------------------------------
    def create_object(self, name: str) -> Object3D:
        obj = Object3D(name=name)
        self.objects[name] = obj
        return obj

    def get_object(self, name: str) -> Object3D:
        return self.objects[name]

    def remove_object(self, name: str):
        self.objects.pop(name, None)

    def rename_object(self, name: str, new_name: str):
        """Rename an object, preserving dict order and its skeleton key."""
        if name not in self.objects:
            raise KeyError(f"no such object: {name!r}")
        if new_name != name and new_name in self.objects:
            raise KeyError(f"object {new_name!r} already exists")
        if new_name == name:
            return
        self.objects = {
            (new_name if key == name else key): obj
            for key, obj in self.objects.items()
        }
        self.objects[new_name].name = new_name
        if name in self.skeletons:
            self.skeletons[new_name] = self.skeletons.pop(name)

    # ---- convenience spline creation --------------------------------------
    def add_spline(self, object_name: str, spline: Spline):
        self.objects[object_name].add_spline(spline)

    def set_mode(self, mode: str):
        if mode not in ("object", "segment", "material", "choreography"):
            raise ValueError(f"unknown mode {mode!r}")
        self.mode = mode