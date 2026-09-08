"""Core data-model package.

Exposes the document model, the scriptable facade, and the animation +
rigging subsystems used across the four work modes.
"""

from __future__ import annotations

from . import animation, naming, rigging, scene, script  # noqa: F401
from .naming import allocate_unique_name  # noqa: F401
from .scene import EvaluatedScene, evaluate_scene  # noqa: F401
from .project import (  # noqa: F401
    Bone,
    ControlPoint,
    Hook,
    Material,
    Object3D,
    Patch,
    Project,
    Spline,
)

__all__ = [
    "animation", "naming", "rigging", "scene", "script",
    "allocate_unique_name", "evaluate_scene", "EvaluatedScene",
    "Bone", "ControlPoint", "Hook", "Material",
    "Object3D", "Patch", "Project", "Spline",
]