"""Core data-model package.

Exposes the document model, the scriptable facade, and the animation +
rigging subsystems used across the four work modes.
"""

from __future__ import annotations

from . import animation, rigging, script  # noqa: F401
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
    "animation", "rigging", "script",
    "Bone", "ControlPoint", "Hook", "Material",
    "Object3D", "Patch", "Project", "Spline",
]