"""Shared deterministic names for recipe export artifacts."""

import os
import hashlib
from am3d.core.paths import sanitize_filename_component


def _with_ext(path: str, ext: str) -> str:
    root, current = os.path.splitext(path)
    return path if current.lower() == ext.lower() else root + ext


def _artifact_object_name(name: str, index: int, safe_artifact_names: bool) -> str:
    """Portable opaque component for names that become writer paths.

    Native scene names stay untouched. The index is deterministic for a
    recipe and the digest makes the identifier robust if a caller supplies
    repeated or reordered names outside normal schema validation.
    """
    if not safe_artifact_names:
        return name
    digest = hashlib.blake2s(str(name).encode("utf-8"), digest_size=4).hexdigest()
    return f"object_{index:03d}_{digest}"


def _artifact_object_names(recipe_names, mesh_names, safe_artifact_names: bool) -> dict[str, str]:
    """Map every mesh writer name, including session-only meshes in API use."""
    names = list(recipe_names)
    known = set(names)
    names.extend(name for name in mesh_names if name not in known)
    return {name: _artifact_object_name(name, index, safe_artifact_names)
            for index, name in enumerate(names)}


def _named_sheet_path(path: str, object_name: str) -> str:
    """Derive a portable per-object PNG path while preserving the full stem."""
    stem, suffix = os.path.splitext(path)
    if suffix.lower() != ".png":
        stem = path
    safe_name = sanitize_filename_component(object_name)
    return f"{stem}_{safe_name}.png"
