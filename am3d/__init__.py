"""3D MASTER:2005 — a pure spline-based 3D character animation suite.

Inspired by the no-longer-updated Animation Master 2005, this is a
complete, decoupled 3D content pipeline built around B-spline patch
geometry — no polygon meshes anywhere.

The application is divided into four progressive work modes:

    1. Object Mode       — spline network modeling
    2. Segment Mode      — rigging / skeletal framework
    3. Material Mode     — shading pipeline
    4. Choreography Mode — layout / animation / rendering

This package exposes a clean, scriptable API designed so an external
agentic pipeline (e.g. an AI assistant) can drive it via Python:
calling, reading/modifying/writing project data and invoking tools the
same way a user would through the UI.

The canonical, public, scriptable API lives in :mod:`am3d.script` and is
re-exported at the package top level so `import am3d` provides everything
needed for automation.
"""

from __future__ import annotations

from . import spline  # noqa: F401  (geometry kernel)
from . import core     # noqa: F401  (document data model)
from .core.project import Project  # noqa: F401

__version__ = "0.2.0"

# Names re-exported from the scripting facade onto the package root.  An
# explicit allowlist (rather than a blanket hasattr) keeps private helpers,
# test hooks and stdlib names from leaking through `import am3d`.
_SCRIPT_EXPORTS = frozenset({
    "new_project", "save_project", "load_project",
    "create_object", "delete_object", "rename_object", "set_object_visible",
    "get_object",
    "add_spline", "extrude_spline", "lathe_spline", "add_bone", "get_bones",
    "create_material", "create_action", "get_action", "save_action_file",
    "load_action_file", "apply_action_to_character", "reset_default",
    "delete_action", "rename_action", "set_active_action", "assign_action",
    "unassign_action", "insert_keyframe", "remove_keyframe",
    "key_bone_from_pose", "apply_action_frame",
})

_script = None


def _get_script():
    """Lazily import the public scripting facade.

    Imported lazily so heavy GUI/GPU modules are not pulled in when only the
    spline kernel is needed.
    """
    global _script
    if _script is None:
        from am3d.core import script as _module
        _script = _module
    return _script


def __getattr__(name):
    """Expose the high-level scripting API straight off the package."""
    if name in _SCRIPT_EXPORTS:
        return getattr(_get_script(), name)
    if name == "script":
        return _get_script()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(set(globals()) | _SCRIPT_EXPORTS | {"script"})


__all__ = ["core", "spline", "script", "Project"]