"""Deterministic checks for generated native projects and exported files.

The checker deliberately reads saved files back through the application's
public loaders and independent export parsers. It verifies structure and
selected caller-authored requirements; it does not grade artistic quality.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import unicodedata
import uuid

import numpy as np

from am3d.ai.policy import MAX_ATLAS_PIXELS, MAX_OBJECTS, MAX_OUTPUT_BYTES
from am3d.core.script import Session
from am3d.core.serializer import (
    ProjectFormatError,
    load_project,
    project_content_digest,
    validate_generation_envelope,
)
from am3d.core.paths import (classify_portable_relative_path,
                             extended_io_path, split_segments)


from ._check_report import _check
from ._scene_checks import (
    _check_recipe_intentions, _check_geometry, _check_requirements,
    _normalize_text, _name_match, _find_name, _disclosure_tokens, _dimensions,
    _target_color, _mat_color, _expected_components, _bounds_by_object,
    _check_relations,
)
from ._animation_checks import _check_animation
from ._preview_checks import _check_preview, _render_material_preview

_MAX_TREE_BYTES = MAX_OUTPUT_BYTES
_MAX_FILE_COUNT = 4096
_MAX_REPORT_BYTES = 256 * 1024
_MAX_IMAGE_DIMENSION = 8192
_MAX_IMAGE_PIXELS = 33_554_432
_MAX_GLB_IMAGES = MAX_OBJECTS
_MAX_GLB_IMAGE_BYTES = MAX_OUTPUT_BYTES
_MAX_GLB_IMAGE_PIXELS = MAX_ATLAS_PIXELS
_ALLOWED_SUFFIXES = {".am3d", ".obj", ".glb", ".mtl", ".png"}


class _ResourceLimitExceeded(ValueError):
    def __init__(self, kind: str, actual: int, limit: int, unit: str):
        super().__init__(kind)
        self.details = {"kind": kind, "actual": int(actual),
                        "limit": int(limit), "unit": unit}


def _register_resource_limit(report: dict, details: dict):
    """Persist only explicit, host-created resource guard measurements."""
    report["resource_limit"] = True
    safe = {}
    kind = details.get("kind")
    if isinstance(kind, str) and kind in {
            "output_tree_bytes", "output_file_bytes", "obj_input_bytes",
            "obj_dependency_bytes", "obj_dependency_count",
            "glb_image_count", "glb_image_bytes", "glb_image_dimension",
            "glb_image_pixels", "png_dimension", "png_pixels"}:
        safe["kind"] = kind
    unit = details.get("unit")
    if isinstance(unit, str) and unit in {"bytes", "pixels", "count"}:
        safe["unit"] = unit
    for key in ("actual", "limit"):
        value = details.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            safe[key] = value
    if "kind" not in safe or "actual" not in safe or "limit" not in safe:
        return
    items = report.setdefault("resource_limit_details", [])
    if len(items) < 8 and safe not in items:
        items.append(safe)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _has_link(path: Path) -> bool:
    try:
        mode = path.lstat().st_mode
    except OSError:
        return False
    attrs = getattr(path.lstat(), "st_file_attributes", 0)
    return stat.S_ISLNK(mode) or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _safe_root(path: Path) -> Path:
    path = Path(extended_io_path(path))
    if not path.is_dir() or _has_link(path):
        raise ValueError("output root is missing or is a link")
    resolved = Path(os.path.realpath(path))
    if resolved != path.resolve():
        # Path.resolve catches junctions on Windows; realpath catches symlinks
        # on POSIX. A differing spelling is rejected instead of normalized.
        raise ValueError("output root does not resolve to itself")
    current = path.parent
    while current != current.parent:
        if current.exists() and _has_link(current):
            raise ValueError("output root has a linked parent")
        current = current.parent
    return resolved


def _safe_file(root: Path, relative: str | Path) -> Path:
    raw_text = os.fspath(relative)
    if classify_portable_relative_path(raw_text) is not None:
        raise ValueError("artifact path must be relative to output root")
    parts = split_segments(raw_text)
    if not parts:
        raise ValueError("artifact path must name a file")
    path = root.joinpath(*parts)
    current = root
    for part in parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if _has_link(current):
                raise ValueError("artifact path contains a symlink or junction")
    resolved = Path(os.path.realpath(path))
    if os.path.commonpath((str(root), str(resolved))) != str(root):
        raise ValueError("artifact path resolves outside output root")
    return path


def _tree_manifest(root: Path) -> tuple[list[dict], int]:
    files: list[dict] = []
    total = 0
    portable_paths = set()
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        dirs.sort()
        names.sort()
        for name in list(dirs):
            path = base / name
            if _has_link(path):
                raise ValueError("output tree contains a symlink or junction")
            relative = path.relative_to(root).as_posix()
            if classify_portable_relative_path(relative) is not None:
                raise ValueError("output tree contains a non-portable path")
            key = unicodedata.normalize("NFC", relative).casefold()
            if key in portable_paths:
                raise ValueError("output tree contains colliding portable paths")
            portable_paths.add(key)
        for name in names:
            path = base / name
            if _has_link(path) or not path.is_file():
                raise ValueError("output tree contains a linked or non-file artifact")
            relative = path.relative_to(root).as_posix()
            if classify_portable_relative_path(relative) is not None:
                raise ValueError("output tree contains a non-portable path")
            key = unicodedata.normalize("NFC", relative).casefold()
            if key in portable_paths:
                raise ValueError("output tree contains colliding portable paths")
            portable_paths.add(key)
            if path.suffix.lower() not in _ALLOWED_SUFFIXES:
                # Worker protocol files and bounded scratch files are outside
                # application artifact integrity; all other extensions fail.
                if name in {".ai_worker_input.json", ".ai_worker_result.json",
                            ".ai_worker_result.json.tmp"} or path.relative_to(root).as_posix().startswith("tmp/"):
                    continue
                raise ValueError("output tree contains an unapproved artifact type")
            size = path.stat().st_size
            total += size
            if size <= 0:
                raise ValueError("output tree contains an empty artifact")
            if total > _MAX_TREE_BYTES:
                raise ValueError("output tree exceeds 256 MiB")
            files.append({"path": relative,
                          "sha256": _sha256(path), "bytes": size})
            if len(files) > _MAX_FILE_COUNT:
                raise ValueError("output tree contains too many artifacts")
    return files, total


def _preflight_tree_byte_budget(root: Path) -> int:
    """Stat the output tree before any native/export parser reads its files."""
    total = 0
    for current, dirs, names in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        dirs.sort()
        names.sort()
        for name in list(dirs):
            if _has_link(base / name):
                raise ValueError("output tree contains a linked directory")
        for name in names:
            path = base / name
            if _has_link(path) or not path.is_file():
                raise ValueError("output tree contains a linked or non-file entry")
            relative = path.relative_to(root).as_posix()
            # These fixed worker protocol and scratch files are not artifacts
            # and are excluded by the final manifest as well.
            if name in {".ai_worker_input.json", ".ai_worker_result.json",
                        ".ai_worker_result.json.tmp"} or relative.startswith("tmp/"):
                continue
            size = path.stat().st_size
            if size < 0:
                raise ValueError("output file has an invalid size")
            if size > _MAX_TREE_BYTES:
                raise _ResourceLimitExceeded("output_file_bytes", size,
                                             _MAX_TREE_BYTES, "bytes")
            total += size
            if total > _MAX_TREE_BYTES:
                raise _ResourceLimitExceeded("output_tree_bytes", total,
                                             _MAX_TREE_BYTES, "bytes")
    return total


def _canonical_json(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def _build_generation(recipe: dict, brief, generation) -> dict | None:
    if generation is None:
        return None
    if not isinstance(generation, dict):
        raise ProjectFormatError("generation metadata must be an object")
    run_id = generation.get("run_id")
    try:
        parsed_id = uuid.UUID(run_id)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ProjectFormatError("generation metadata needs a host-created run UUID") from exc
    if str(parsed_id) != run_id:
        raise ProjectFormatError("generation run UUID must use canonical lowercase text")
    parent = generation.get("parent_generation_id")
    if parent is not None:
        try:
            if str(uuid.UUID(parent)) != parent:
                raise ValueError
        except (ValueError, TypeError, AttributeError) as exc:
            raise ProjectFormatError("parent generation id must be a canonical UUID") from exc
    accepted_brief = generation.get("accepted_brief", brief)
    recipe_copy = json.loads(_canonical_json(recipe).decode("utf-8"))
    envelope = {
        "version": 1,
        "run_id": run_id,
        "parent_generation_id": parent,
        "accepted_brief": accepted_brief,
        "recipe": recipe_copy,
        "recipe_sha256": hashlib.sha256(_canonical_json(recipe_copy)).hexdigest(),
        "application": generation.get("application", {}),
        "warnings": generation.get("warnings", []),
        "artifact_refs": generation.get("artifact_refs", []),
    }
    return validate_generation_envelope(envelope)


def _export_material_expectations(recipe: dict, scene) -> tuple[dict, dict]:
    """Map reopened native material intent to the exporter's opaque names."""
    from am3d.core.scene import scene_material_colors, scene_patch_material_colors
    from am3d.recipes._export_paths import _artifact_object_names

    specs = recipe.get("objects", []) or []
    names = [item.get("name") for item in specs
             if isinstance(item, dict) and isinstance(item.get("name"), str)]
    mapping = _artifact_object_names(names, scene.meshes.keys(), True)
    flat = scene_material_colors(scene)
    patches = scene_patch_material_colors(scene)
    flat_expected = {mapping[name]: tuple(color) for name, color in flat.items()
                     if name in mapping}
    patch_expected = {
        (mapping[name], patch): tuple(color)
        for name, values in patches.items() if name in mapping
        for patch, color in values.items()
    }
    return flat_expected, patch_expected


def _verify_obj_materials(details: dict, expected_flat: dict,
                          expected_patches: dict) -> list[str]:
    issues = []
    assignments = details.get("object_materials", {})
    actual_materials = details.get("materials", {})
    for object_name, rgba in expected_flat.items():
        expected_name = f"mat_{object_name}"
        actual_names = assignments.get(object_name, [])
        if not actual_names or any(name != expected_name
                                   and not name.startswith(f"mat_{object_name}__")
                                   for name in actual_names):
            issues.append("OBJ surface material assignment differs from reopened native material")
            continue
        if expected_name in actual_names:
            material = actual_materials.get(expected_name, {})
            kd = material.get("Kd")
            if kd is None or not np.allclose(np.asarray(kd), np.asarray(rgba[:3]), atol=2e-5):
                issues.append("OBJ flat material color differs from reopened native material")
    for (object_name, patch_name), rgba in expected_patches.items():
        expected_name = f"mat_{object_name}__{patch_name}"
        if expected_name not in assignments.get(object_name, []):
            issues.append("OBJ patch material assignment differs from reopened native material")
            continue
        kd = actual_materials.get(expected_name, {}).get("Kd")
        if kd is None or not np.allclose(np.asarray(kd), np.asarray(rgba[:3]), atol=2e-5):
            issues.append("OBJ patch material color differs from reopened native material")
    return issues


def _set_resource_info(resource_info: dict | None, kind: str,
                       actual: int, limit: int, unit: str):
    if isinstance(resource_info, dict) and not resource_info:
        resource_info.update({"kind": kind, "actual": int(actual),
                              "limit": int(limit), "unit": unit})


def _verify_glb_images(gltf: dict, binary: bytes, *,
                       resource_info: dict | None = None) -> list[str]:
    """Preflight and decode bounded, embedded PNGs without exposing payload data."""
    import io
    from PIL import Image

    issues = []
    images = gltf.get("images", [])
    views = gltf.get("bufferViews", [])
    buffers = gltf.get("buffers", [])
    if len(images) > _MAX_GLB_IMAGES:
        _set_resource_info(resource_info, "glb_image_count", len(images),
                           _MAX_GLB_IMAGES, "count")
        return ["GLB contains too many embedded images"]
    if not images:
        return issues

    # Validate every reference and aggregate byte size before taking slices
    # from the BIN chunk or handing bytes to Pillow.
    refs = []
    total_bytes = 0
    for image in images:
        if not isinstance(image, dict):
            issues.append("GLB image declaration is invalid")
            continue
        if "uri" in image:
            issues.append("GLB external image references are not allowed")
            continue
        if image.get("mimeType") != "image/png":
            issues.append("GLB embedded image MIME type is unsupported")
            continue
        view_index = image.get("bufferView")
        if (not isinstance(view_index, int) or isinstance(view_index, bool)
                or not 0 <= view_index < len(views)):
            issues.append("GLB image does not reference an embedded buffer view")
            continue
        view = views[view_index]
        offset = view.get("byteOffset", 0) if isinstance(view, dict) else None
        length = view.get("byteLength") if isinstance(view, dict) else None
        buffer_index = view.get("buffer", 0) if isinstance(view, dict) else None
        declared = (buffers[buffer_index].get("byteLength")
                    if isinstance(buffer_index, int) and not isinstance(buffer_index, bool)
                    and 0 <= buffer_index < len(buffers)
                    and isinstance(buffers[buffer_index], dict) else None)
        if (buffer_index != 0 or len(buffers) != 1
                or not isinstance(declared, int) or isinstance(declared, bool)
                or declared <= 0 or not isinstance(offset, int) or isinstance(offset, bool)
                or not isinstance(length, int) or isinstance(length, bool)
                or offset < 0 or length <= 0 or offset + length > len(binary)
                or offset + length > declared):
            issues.append("GLB embedded image range is invalid")
            continue
        total_bytes += length
        refs.append((offset, length))
    if issues:
        return issues
    if total_bytes > _MAX_GLB_IMAGE_BYTES:
        _set_resource_info(resource_info, "glb_image_bytes", total_bytes,
                           _MAX_GLB_IMAGE_BYTES, "bytes")
        return ["GLB embedded images exceed the bounded byte limit"]

    payloads = [bytes(memoryview(binary)[offset:offset + length])
                for offset, length in refs]
    pixel_total = 0
    for payload in payloads:
        try:
            with Image.open(io.BytesIO(payload)) as image:
                if image.format != "PNG":
                    issues.append("GLB embedded image payload is not PNG")
                    continue
                width, height = image.size
                if width < 1 or height < 1:
                    issues.append("GLB embedded image dimensions are invalid")
                    continue
                if width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
                    _set_resource_info(resource_info, "glb_image_dimension",
                                       max(width, height), _MAX_IMAGE_DIMENSION,
                                       "pixels")
                    issues.append("GLB embedded image dimensions exceed limits")
                    continue
                pixel_total += width * height
                if pixel_total > _MAX_GLB_IMAGE_PIXELS:
                    _set_resource_info(resource_info, "glb_image_pixels",
                                       pixel_total, _MAX_GLB_IMAGE_PIXELS,
                                       "pixels")
                    issues.append("GLB embedded images exceed the pixel limit")
                    break
        except Exception:
            issues.append("GLB embedded image is not a decodable PNG")
    if issues:
        return issues

    # verify() checks PNG chunk/CRC integrity; a fresh open followed by load()
    # forces compressed pixel decoding. Dimensions and aggregate pixels are
    # already bounded. Do not convert/copy the decoded pixels into an array.
    for payload in payloads:
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.verify()
            with Image.open(io.BytesIO(payload)) as image:
                if image.format != "PNG":
                    raise ValueError
                image.load()
        except Exception:
            issues.append("GLB embedded image is not a decodable PNG")
            break
    return issues


def _verify_glb_materials(gltf: dict, expected_flat: dict,
                          expected_patches: dict, binary: bytes, *,
                          resource_info: dict | None = None) -> list[str]:
    issues = []
    images = gltf.get("images", [])
    views = gltf.get("bufferViews", [])
    buffers = gltf.get("buffers", [])
    issues.extend(_verify_glb_images(gltf, binary,
                                     resource_info=resource_info))
    textures = gltf.get("textures", [])
    for texture in textures:
        source = texture.get("source") if isinstance(texture, dict) else None
        if (not isinstance(source, int) or isinstance(source, bool)
                or not 0 <= source < len(images)):
            issues.append("GLB texture references an invalid embedded image")
    materials = gltf.get("materials", [])
    for material in materials:
        pbr = material.get("pbrMetallicRoughness", {}) if isinstance(material, dict) else {}
        texture_info = pbr.get("baseColorTexture") if isinstance(pbr, dict) else None
        if isinstance(texture_info, dict):
            texture_index = texture_info.get("index")
            if (not isinstance(texture_index, int) or isinstance(texture_index, bool)
                    or not 0 <= texture_index < len(textures)):
                issues.append("GLB material references an invalid texture")
    by_mesh = {item.get("name"): item for item in gltf.get("meshes", [])
               if isinstance(item, dict) and isinstance(item.get("name"), str)}
    for object_name, rgba in expected_flat.items():
        mesh = by_mesh.get(object_name)
        if not mesh:
            issues.append("GLB is missing a reopened native component")
            continue
        primitives = mesh.get("primitives", [])
        if not primitives:
            issues.append("GLB component has no material-bearing surface primitive")
            continue
        for primitive in primitives:
            index = primitive.get("material")
            material = materials[index] if isinstance(index, int) and 0 <= index < len(materials) else None
            pbr = material.get("pbrMetallicRoughness", {}) if isinstance(material, dict) else {}
            actual_name = material.get("name") if isinstance(material, dict) else None
            if actual_name not in {f"mat_{object_name}", *(f"mat_{object_name}__{patch}" for patch in expected_patches if patch[0] == object_name)}:
                issues.append("GLB material assignment differs from reopened native component material")
                continue
            if actual_name == f"mat_{object_name}":
                color = pbr.get("baseColorFactor")
                if not isinstance(color, list) or len(color) < 3 or not np.allclose(
                        np.asarray(color[:3]), np.asarray(rgba[:3]), atol=2e-5):
                    issues.append("GLB flat material color differs from reopened native material")
    for (object_name, patch_name), rgba in expected_patches.items():
        mesh = by_mesh.get(object_name)
        if not mesh:
            issues.append("GLB is missing a reopened native component")
            continue
        expected_name = f"mat_{object_name}__{patch_name}"
        matches = []
        for primitive in mesh.get("primitives", []):
            index = primitive.get("material")
            material = materials[index] if isinstance(index, int) and 0 <= index < len(materials) else None
            if isinstance(material, dict) and material.get("name") == expected_name:
                matches.append(material)
        if not matches:
            issues.append("GLB patch material assignment differs from reopened native material")
            continue
        for material in matches:
            color = material.get("pbrMetallicRoughness", {}).get("baseColorFactor")
            if not isinstance(color, list) or len(color) < 3 or not np.allclose(
                    np.asarray(color[:3]), np.asarray(rgba[:3]), atol=2e-5):
                issues.append("GLB patch material color differs from reopened native material")
    return issues


def _safe_export_parser_issues(kind: str, issues) -> list[str]:
    """Convert untrusted parser messages into stable non-echoing diagnostics."""
    from collections import Counter

    counts = Counter()
    for issue in issues:
        text = str(issue).casefold()
        if "position" in text and "missing" in text:
            code = "missing_position_attribute"
        elif "normal" in text:
            code = "invalid_normal_data"
        elif "texture-coordinate" in text or "texcoord" in text or " uv " in f" {text} ":
            code = "invalid_texture_coordinates"
        elif "index" in text or "indices" in text:
            code = "invalid_geometry_indices"
        elif "material" in text:
            code = "invalid_material_reference"
        elif "texture" in text or "image" in text:
            code = "invalid_texture_reference"
        elif "accessor min" in text or "accessor max" in text or "bounds" in text:
            code = "invalid_geometry_bounds"
        elif any(token in text for token in ("parse", "header", "magic", "chunk", "json")):
            code = "malformed_export_container"
        else:
            code = "malformed_export_structure"
        counts[code] += 1
    label = "OBJ" if kind == "obj" else "GLB"
    return [f"{label} parser check {code}: {count} issue(s)"
            for code, count in sorted(counts.items())]


def _expected_export_formats(requirements, accepted_brief) -> tuple[set[str], bool]:
    """Return independently requested export formats in canonical writer form."""
    aliases = {"gltf": "glb"}
    supported = {"am3d", "obj", "glb", "gltf", "spritesheet",
                 "toon_sheet", "animation_sheet"}
    values = []
    malformed = False

    if isinstance(requirements, dict):
        requested = requirements.get("required_exports", []) or []
        if isinstance(requested, str):
            requested = [requested]
        if isinstance(requested, (list, tuple, set)):
            values.extend(requested)
        elif requested:
            malformed = True

    if isinstance(accepted_brief, dict):
        requested = accepted_brief.get("exports", ())
    else:
        requested = getattr(accepted_brief, "exports", ())
    if isinstance(requested, str):
        requested = (requested,)
    if isinstance(requested, (list, tuple, set)):
        values.extend(requested)
    elif requested:
        malformed = True

    formats = set()
    for value in values:
        if not isinstance(value, str) or value.casefold() not in supported:
            malformed = True
            continue
        normalized = value.casefold()
        formats.add(aliases.get(normalized, normalized))
    return formats, malformed


def _sheet_artifact_path(base: str, object_name: str, index: int) -> Path:
    """Mirror the executor's per-object sheet suffix and extension rule."""
    from am3d.recipes.executor import _artifact_object_name

    object_id = _artifact_object_name(object_name, index, True)
    candidate = f"{base}_{object_id}"
    stem, suffix = os.path.splitext(candidate)
    final = candidate if suffix.casefold() == ".png" else stem + ".png"
    return Path(*split_segments(final))


def _verify_exports(root: Path, recipe: dict, report: dict,
                    requirements: dict | None = None, scene=None,
                    accepted_brief=None) -> list[str]:
    from PIL import Image
    from am3d.export.validate import read_glb, validate_glb, validate_obj

    try:
        _preflight_tree_byte_budget(root)
    except _ResourceLimitExceeded as exc:
        _register_resource_limit(report, exc.details)
        _check(report, "requested_exports", False,
               "Requested exports were not parsed because the output byte budget was exceeded.",
               {"files": [], "issues": ["output tree exceeds the policy byte limit"],
                "resource_limit": exc.details})
        return []
    except (OSError, ValueError):
        _check(report, "requested_exports", False,
               "Requested exports were not parsed because the output tree exceeds its byte budget.",
               {"files": [], "issues": ["output tree exceeds the policy byte limit"]})
        return []

    expected_files = []
    errors = []
    expected_flat, expected_patches = _export_material_expectations(recipe, scene) if scene is not None else ({}, {})
    export_specs = recipe.get("exports", []) or []
    required_formats, malformed_required_formats = _expected_export_formats(
        requirements, accepted_brief)
    present_formats = {
        str(item.get("format", "")).casefold()
        for item in export_specs if isinstance(item, dict)
    }
    present_formats = {"glb" if value == "gltf" else value
                       for value in present_formats}
    missing_formats = sorted(required_formats - present_formats)
    if missing_formats:
        errors.append("missing required export formats: "
                      + ", ".join(missing_formats[:8]))
    if malformed_required_formats:
        errors.append("required export format is unsupported or malformed")
    for index, spec in enumerate(export_specs):
        if not isinstance(spec, dict):
            errors.append(f"export[{index}] is not an object")
            continue
        fmt = str(spec.get("format", "")).casefold()
        path_text = spec.get("path")
        if not isinstance(path_text, str) or not path_text:
            errors.append(f"export[{index}] has no path")
            continue
        if classify_portable_relative_path(path_text) is not None:
            errors.append(f"export[{index}] path is not relative")
            continue

        if fmt in {"spritesheet", "toon_sheet"}:
            if scene is None:
                errors.append(f"required {fmt} object sheets could not be derived from the reopened scene")
                continue
            mesh_items = [(name, mesh) for name, mesh in scene.meshes.items()
                          if len(mesh.vertices)]
            if not mesh_items:
                errors.append(f"required {fmt} object sheets could not be derived from renderable geometry")
                continue
            for object_index, (object_name, _mesh) in enumerate(mesh_items):
                final = _sheet_artifact_path(path_text, object_name,
                                             object_index)
                try:
                    path = _safe_file(root, final)
                except ValueError:
                    errors.append(f"export[{index}] object sheet path is unsafe")
                    continue
                if not path.is_file() or path.stat().st_size <= 0:
                    errors.append(f"required {fmt} object sheet is missing")
                    continue
                if path.stat().st_size > _MAX_TREE_BYTES:
                    _register_resource_limit(report, _ResourceLimitExceeded(
                        "output_file_bytes", path.stat().st_size,
                        _MAX_TREE_BYTES, "bytes").details)
                    errors.append("requested export exceeds the policy byte limit")
                    continue
                expected_files.append(final.as_posix())
                try:
                    with Image.open(path) as image:
                        image.verify()
                    with Image.open(path) as image:
                        width, height = image.size
                        if width < 1 or height < 1:
                            errors.append(f"{fmt} PNG dimensions are invalid")
                        elif width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
                            _register_resource_limit(report, {
                                "kind": "png_dimension", "actual": max(width, height),
                                "limit": _MAX_IMAGE_DIMENSION, "unit": "pixels"})
                            errors.append(f"{fmt} PNG dimensions exceed limits")
                        elif width * height > _MAX_IMAGE_PIXELS:
                            _register_resource_limit(report, {
                                "kind": "png_pixels", "actual": width * height,
                                "limit": _MAX_IMAGE_PIXELS, "unit": "pixels"})
                            errors.append(f"{fmt} PNG dimensions exceed limits")
                except Exception as exc:
                    errors.append(f"{fmt} PNG could not be decoded ({type(exc).__name__})")
            continue

        base = Path(*split_segments(path_text))
        suffix = {"am3d": ".am3d", "obj": ".obj", "glb": ".glb", "gltf": ".glb",
                  "spritesheet": ".png", "toon_sheet": ".png", "animation_sheet": ".png"}.get(fmt)
        if not suffix:
            errors.append(f"export[{index}] format is unsupported")
            continue
        final = base if base.suffix.lower() == suffix else base.with_suffix(suffix)
        try:
            path = _safe_file(root, final)
        except ValueError as exc:
            errors.append(f"export[{index}]: {exc}")
            continue
        if not path.is_file() or path.stat().st_size <= 0:
            errors.append(f"required {fmt} file is missing")
            continue
        if path.stat().st_size > _MAX_TREE_BYTES:
            _register_resource_limit(report, _ResourceLimitExceeded(
                "output_file_bytes", path.stat().st_size,
                _MAX_TREE_BYTES, "bytes").details)
            errors.append("requested export exceeds the policy byte limit")
            continue
        expected_files.append(final.as_posix())
        if fmt == "obj":
            result = validate_obj(str(path), root=str(root), return_details=True)
            issues = list(result.get("issues", []))
            if result.get("resource_limit") and isinstance(
                    result.get("resource_limit_details"), dict):
                _register_resource_limit(report, result["resource_limit_details"])
            if not result.get("object_materials") and expected_flat:
                issues.append("OBJ has no assigned materials for reopened native surfaces")
            issues.extend(_verify_obj_materials(result, expected_flat, expected_patches))
            expected_files.extend(result.get("resources", []))
            errors.extend(_safe_export_parser_issues("obj", issues))
        elif fmt in {"glb", "gltf"}:
            issues = validate_glb(str(path))
            resource_info = {}
            try:
                gltf, _binary, _offset = read_glb(str(path))
                primitives = [primitive for mesh in gltf.get("meshes", [])
                              for primitive in mesh.get("primitives", [])]
                if not primitives:
                    issues.append("GLB contains no mesh primitives")
                issues.extend(_verify_glb_materials(
                    gltf, expected_flat, expected_patches, _binary,
                    resource_info=resource_info))
            except Exception:
                issues = [*issues, "GLB could not be safely parsed"]
            if resource_info:
                _register_resource_limit(report, resource_info)
            errors.extend(_safe_export_parser_issues("glb", issues))
        elif fmt == "am3d":
            try:
                saved = load_project(str(path))
                if recipe.get("objects") and not saved.objects:
                    errors.append("native export contains no recipe objects")
            except Exception as exc:
                errors.append(f"native export could not be reopened ({type(exc).__name__})")
        elif fmt not in {"am3d"}:
            try:
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    w, h = image.size
                    if w < 1 or h < 1:
                        errors.append(f"{fmt} PNG dimensions are invalid")
                    elif w > _MAX_IMAGE_DIMENSION or h > _MAX_IMAGE_DIMENSION:
                        _register_resource_limit(report, {
                            "kind": "png_dimension", "actual": max(w, h),
                            "limit": _MAX_IMAGE_DIMENSION, "unit": "pixels"})
                        errors.append(f"{fmt} PNG dimensions exceed limits")
                    elif w * h > _MAX_IMAGE_PIXELS:
                        _register_resource_limit(report, {
                            "kind": "png_pixels", "actual": w * h,
                            "limit": _MAX_IMAGE_PIXELS, "unit": "pixels"})
                        errors.append(f"{fmt} PNG dimensions exceed limits")
            except Exception as exc:
                errors.append(f"{fmt} PNG could not be decoded ({type(exc).__name__})")
    native_requested = any(Path(p).name == "project.am3d" for p in expected_files)
    if not native_requested:
        # The host recipe normalizer always installs this native artifact.
        path = root / "project.am3d"
        if path.is_file():
            expected_files.append("project.am3d")
        else:
            errors.append("required native project export is missing")
    _check(report, "requested_exports", not errors,
           "Independently parsed requested exports and verified required files.",
           {"files": expected_files[:64], "issues": errors[:16]})
    return expected_files


def check_artifacts(recipe: dict, output_dir: str | Path, brief=None,
                    generation: dict | None = None,
                    requirements: dict | None = None) -> dict:
    """Validate a private worker output directory before host publication.

    ``requirements`` is caller-authored expected data (for example a frozen
    benchmark fixture). It is the source for component/material/geometry
    checks; the model's own recipe cannot relax it.
    """
    report = {"ok": False, "status": "failed", "checks": [], "artifacts": [],
              "measurements": {}, "limitations": [], "resource_limit": False}
    try:
        root = _safe_root(Path(output_dir))
    except Exception as exc:
        _check(report, "output_root", False, "Output directory is missing or unsafe.",
               {"reason": type(exc).__name__})
        return report

    try:
        initial_tree_bytes = _preflight_tree_byte_budget(root)
    except _ResourceLimitExceeded as exc:
        _register_resource_limit(report, exc.details)
        _check(report, "output_tree_preflight", False,
               "Output files exceed the bounded byte budget.",
               {"reason": "output_byte_limit_exceeded",
                "actual_bytes": exc.details["actual"],
                "limit_bytes": exc.details["limit"]})
        return report
    except (OSError, ValueError):
        _check(report, "output_tree_preflight", False,
               "Output files exceed the bounded byte budget or contain unsafe links.",
               {"reason": "output_tree_preflight_failed"})
        return report
    _check(report, "output_tree_preflight", True,
           "Stat-checked output size before loading native or exported files.",
           {"bytes": initial_tree_bytes, "maximum_bytes": _MAX_TREE_BYTES})

    recipe = recipe if isinstance(recipe, dict) else {}
    requirements = requirements if isinstance(requirements, dict) else {}
    report["measurements"]["recipe_name"] = str(recipe.get("name", ""))[:128]

    native = root / "project.am3d"
    try:
        native = _safe_file(root, "project.am3d")
        if not native.is_file() or native.stat().st_size <= 0:
            raise ValueError("required project.am3d is missing or empty")
        original = Session()
        original.load_project(str(native))
        if recipe.get("objects") and not original.project.objects:
            raise ValueError("native project contains no recipe objects")
        envelope = _build_generation(recipe, brief, generation)
        if envelope is None:
            raise ProjectFormatError("host generation metadata is required for completion")
        original.project.generation = envelope
        original.save_project(str(native))
        # Adding host-owned provenance must not push the project outside the
        # byte budget before the independent fresh-load pass.
        _preflight_tree_byte_budget(root)
        # Reopen the file that the host would publish, then save/reopen once
        # more to cover both native load and serializer round-trip behavior.
        reopened = Session()
        reopened.load_project(str(native))
        with tempfile.TemporaryDirectory(prefix="am3d-v1-reopen-") as tmp:
            roundtrip_path = Path(tmp) / "roundtrip.am3d"
            reopened.save_project(str(roundtrip_path))
            roundtrip = Session()
            roundtrip.load_project(str(roundtrip_path))
        if reopened.project.generation != roundtrip.project.generation:
            raise ValueError("generation envelope changed across save/reopen")
        if (project_content_digest(reopened.project, reopened.actions)
                != project_content_digest(roundtrip.project, roundtrip.actions)):
            raise ValueError("project content changed across save/reopen")
        _check(report, "native_roundtrip", True,
               "Native project loaded, received bounded provenance, and survived a fresh save/reopen.",
               {"format_version": 2, "generation_run_id": envelope["run_id"]})
        session = reopened
    except _ResourceLimitExceeded as exc:
        _register_resource_limit(report, exc.details)
        _check(report, "native_roundtrip", False,
               "Native project exceeded the output byte budget after provenance was saved.",
               {"reason": "output_byte_limit_exceeded",
                "actual_bytes": exc.details["actual"],
                "limit_bytes": exc.details["limit"]})
        return report
    except Exception:
        _check(report, "native_roundtrip", False,
               "Native project or provenance could not be verified.",
               {"reason": "native_project_or_provenance_verification_failed"})
        return report

    _check_recipe_intentions(report, recipe, session)

    scene = session.evaluate_scene(visible_only=True, apply_transforms=True,
                                   nu=16, nv=16)
    geometry_names, bounds_min, bounds_max, diagonal = _check_geometry(report, scene)
    _check_requirements(report, recipe, requirements, brief, generation,
                        session.project, scene, geometry_names, bounds_min, bounds_max)

    _check_animation(report, recipe, requirements, brief, session, scene, diagonal)

    _check_preview(report, root, scene)

    accepted_brief = (generation.get("accepted_brief", brief)
                      if isinstance(generation, dict) else brief)
    requested_files = _verify_exports(
        root, recipe, report, requirements, scene=scene,
        accepted_brief=accepted_brief)

    try:
        artifacts, total_bytes = _tree_manifest(root)
        png_issues = []
        try:
            from PIL import Image
            for item in artifacts:
                if not item["path"].casefold().endswith(".png"):
                    continue
                path = _safe_file(root, item["path"])
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    width, height = image.size
                if width < 1 or height < 1:
                    png_issues.append(f"{item['path']}: dimensions are invalid")
                elif width > _MAX_IMAGE_DIMENSION or height > _MAX_IMAGE_DIMENSION:
                    _register_resource_limit(report, {
                        "kind": "png_dimension", "actual": max(width, height),
                        "limit": _MAX_IMAGE_DIMENSION, "unit": "pixels"})
                    png_issues.append(f"{item['path']}: dimensions exceed image limits")
                elif width * height > _MAX_IMAGE_PIXELS:
                    _register_resource_limit(report, {
                        "kind": "png_pixels", "actual": width * height,
                        "limit": _MAX_IMAGE_PIXELS, "unit": "pixels"})
                    png_issues.append(f"{item['path']}: dimensions exceed image limits")
        except Exception as exc:
            png_issues.append(f"PNG validation failed ({type(exc).__name__})")
        _check(report, "png_resources", not png_issues,
               "Decoded every PNG output and checked bounded dimensions.",
               {"issues": png_issues[:16]})
        by_path = {item["path"]: item for item in artifacts}
        missing = [path for path in requested_files if path not in by_path]
        if "preview.png" in by_path:
            requested_files = [*requested_files, "preview.png"]
        else:
            missing.append("preview.png")
        manifest_ok = not missing and all(item["bytes"] > 0 for item in artifacts)
        report["artifacts"] = artifacts
        report["measurements"]["artifact_count"] = len(artifacts)
        report["measurements"]["artifact_bytes"] = total_bytes
        _check(report, "artifact_manifest", manifest_ok,
               "Verified relative artifact paths, file hashes, sizes, and required outputs.",
               {"missing": missing[:16], "count": len(artifacts), "bytes": total_bytes})
    except Exception:
        _check(report, "artifact_manifest", False,
               "Output artifact tree could not be safely manifested.",
               {"reason": "artifact_tree_manifest_failed"})

    report["ok"] = all(item["status"] == "passed" for item in report["checks"])
    report["status"] = "passed" if report["ok"] else "failed"
    try:
        if len(_canonical_json(report)) > _MAX_REPORT_BYTES:
            # Keep the complete artifact manifest whenever it fits. If the
            # full checked evidence cannot cross the bounded worker protocol,
            # fail the candidate instead of publishing a partial manifest.
            for item in report["checks"]:
                if isinstance(item.get("details"), dict):
                    for key, value in list(item["details"].items()):
                        if isinstance(value, list):
                            item["details"][key] = value[:8]
                        elif isinstance(value, str):
                            item["details"][key] = value[:1024]
            report["limitations"].append("Verbose check details were bounded to fit the worker report limit.")
            if len(_canonical_json(report)) > _MAX_REPORT_BYTES:
                report["ok"] = False
                report["status"] = "failed"
                _check(report, "report_limit", False,
                       "Complete artifact evidence exceeds the bounded checker report limit.",
                       {"artifact_count": report["measurements"].get("artifact_count", 0),
                        "limit_bytes": _MAX_REPORT_BYTES})
                report["artifacts"] = []
                for item in report["checks"]:
                    if isinstance(item.get("details"), dict):
                        item["details"] = {key: value for key, value in
                                            item["details"].items()
                                            if not isinstance(value, list)}
                if len(_canonical_json(report)) > _MAX_REPORT_BYTES:
                    report = {"ok": False, "status": "failed",
                              "checks": [{"id": "report_limit", "status": "failed",
                                          "summary": "Checker report exceeded its bounded size."}],
                              "artifacts": [],
                              "measurements": {"artifact_count": report["measurements"].get("artifact_count", 0)},
                              "limitations": []}
    except (TypeError, ValueError):
        report["ok"] = False
        report["status"] = "failed"
        report["checks"].append({"id": "report_serialization", "status": "failed",
                                 "summary": "Checker report could not be serialized as bounded JSON."})
    return report
