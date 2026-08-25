"""Standard-format asset export.

* :mod:`am3d.export.obj`  — Wavefront OBJ (universally readable)
* :mod:`am3d.export.gltf` — binary glTF 2.0 (`.glb`) for engines/web
"""

from __future__ import annotations

from .gltf import write_glb  # noqa: F401
from .obj import write_obj_into  # noqa: F401
from .obj import write_obj  # noqa: F401

__all__ = ["write_glb", "write_obj", "write_obj_into", "write_obj_zip"]