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


def _check(report: dict, code: str, ok: bool, summary: str, details=None):
    stable_code = str(code)[:64]
    item = {"id": stable_code, "code": stable_code,
            "status": "passed" if ok else "failed",
            "severity": "info" if ok else "error",
            "path": (details.get("path") if isinstance(details, dict)
                     and isinstance(details.get("path"), str) else None),
            "summary": str(summary)[:512],
            "details": details if details is not None else {}}
    report["checks"].append(item)
    return ok


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


def _normalize_text(value) -> str:
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, dict):
        return " ".join(_normalize_text(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return " ".join(_normalize_text(item) for item in value)
    return ""


def _name_match(name: str, expected: str) -> bool:
    def tokens(value):
        raw = re.findall(r"[a-z0-9]+", str(value).casefold())
        normalized = []
        for word in raw:
            if word.endswith("ies") and len(word) > 4:
                word = word[:-3] + "y"
            elif word.endswith("s") and len(word) > 3 and not word.endswith("ss"):
                word = word[:-1]
            normalized.append(word)
        return normalized
    actual, wanted = tokens(name), tokens(expected)
    return bool(actual and wanted and set(wanted).issubset(actual))


def _find_name(names, expected):
    for name in names:
        if _name_match(name, expected):
            return name
    return None


def _disclosure_tokens(value):
    aliases = {
        "approximation": "approx", "approximations": "approx",
        "approximate": "approx", "approximated": "approx",
        "approximates": "approx", "stylised": "stylis", "stylized": "stylis",
        "representing": "represent", "represents": "represent",
        "represented": "represent", "representation": "represent",
        "fusion": "fus", "fused": "fus", "fuse": "fus",
        "transparent": "transpar", "transparency": "transpar",
        "accurate": "accur", "accuracy": "accur",
        "modeled": "model", "modelled": "model", "modeling": "model",
        "modelling": "model", "recesses": "recess", "recessed": "recess",
    }
    words = re.findall(r"[a-z0-9]+", str(value).casefold())
    return {aliases.get(word, word) for word in words}


def _dimensions(requirements, brief):
    value = requirements.get("target_dimensions_m") if isinstance(requirements, dict) else None
    if isinstance(value, dict):
        return value
    dimensions = brief.get("dimensions") if isinstance(brief, dict) else None
    if isinstance(dimensions, dict):
        return dimensions
    return None


def _target_color(material):
    if not isinstance(material, dict):
        return None
    return material.get("color_srgb", material.get("color"))


def _render_material_preview(scene, camera, width=512, height=512):
    """Software-render one fixed-camera scene with native flat material colors.

    The normal software renderer merges meshes and therefore falls back to a
    single generic color. This uses its existing projected triangle
    rasterizer, sharing one image and depth buffer across meshes so material
    colors remain visible without losing scene-wide occlusion.
    """
    from PIL import Image
    from am3d.gpu import _MatrixCamera
    from am3d.renderer.sprite import _rasterize_screen
    from am3d.core.scene import scene_triangle_colors

    meshes = [(name, mesh) for name, mesh in scene.meshes.items()
              if len(getattr(mesh, "vertices", ())) and len(getattr(mesh, "indices", ()))]
    if not meshes:
        raise ValueError("scene contains no visible triangle geometry")
    scale = 2
    out_shape = (height * scale, width * scale)
    rgba = np.zeros((*out_shape, 4), dtype=np.float32)
    depth = np.full(out_shape, np.inf, dtype=np.float32)
    camera_adapter = _MatrixCamera(camera)
    light = np.asarray([0.45, 0.75, 0.55], dtype=np.float64)
    light /= np.linalg.norm(light)
    object_colors = {}
    textured = []
    for name, mesh in meshes:
        mat_name = (scene.object_materials or {}).get(name)
        material = (scene.materials or {}).get(mat_name) if mat_name else None
        color = getattr(material, "color", None) if material else None
        if color is None or len(color) < 3:
            base = (0.7, 0.7, 0.75, 1.0)
        else:
            base = tuple(float(x) for x in color[:4])
            if len(base) == 3:
                base = (*base, 1.0)
        object_colors[name] = base
        if material and (getattr(material, "pattern", None)
                         or getattr(material, "texture", None)
                         or getattr(material, "graph", None)):
            textured.append(name)
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        triangles = np.asarray(mesh.indices, dtype=np.int64)
        if vertices.ndim != 2 or vertices.shape[1] != 3 or triangles.ndim != 2 or triangles.shape[1] != 3:
            raise ValueError("scene mesh has invalid triangle data")
        xs, ys, visible = camera_adapter.world_to_screen(vertices, width, height)
        view = camera_adapter.view_matrix()
        camera_vertices = vertices @ view[:3, :3].T + view[:3, 3]
        distance = -camera_vertices[:, 2]
        distance = np.where(visible & (distance > 1e-9), distance, np.inf)
        normals = np.asarray(getattr(mesh, "normals", ()), dtype=np.float64)
        if normals.shape == vertices.shape:
            normals = normals @ view[:3, :3].T
        else:
            normals = np.zeros_like(camera_vertices)
        per_triangle = scene_triangle_colors(scene, name)
        if per_triangle is None:
            per_triangle = np.tile(np.asarray(base, dtype=np.float32), (len(triangles), 1))
        _rasterize_screen(
            np.column_stack([xs, ys]), distance, normals, triangles,
            width, height, scale, base, silhouette=False, light=light,
            color_buffer=rgba, depth_buffer=depth,
            triangle_colors=per_triangle,
        )
    rgba = np.clip(rgba / 255.0, 0.0, 1.0)
    if scale > 1:
        encoded = (rgba * 255.0).round().astype(np.uint8)
        rgba = np.asarray(Image.fromarray(encoded, mode="RGBA").resize(
            (width, height), Image.Resampling.LANCZOS), dtype=np.float32) / 255.0
    return rgba, sorted(set(textured))


def _mat_color(material):
    color = getattr(material, "color", None)
    if color is None:
        return None
    try:
        vals = np.asarray(color, dtype=np.float64).reshape(-1)
    except (TypeError, ValueError):
        return None
    return vals[:3] if len(vals) >= 3 else None


def _expected_components(requirements, brief):
    if isinstance(requirements, dict):
        raw = requirements.get("required_components")
        if isinstance(raw, list):
            result = []
            for item in raw:
                if isinstance(item, str):
                    result.append(item)
                elif isinstance(item, dict) and item.get("required", True):
                    name = item.get("name") or item.get("component")
                    if name:
                        result.append(str(name))
            if result:
                return result
    raw = brief.get("required_components") if isinstance(brief, dict) else None
    result = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, dict) and item.get("required", True) and item.get("name"):
                result.append(str(item["name"]))
    return result


def _bounds_by_object(scene):
    result = {}
    for name, mesh in scene.meshes.items():
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        if vertices.ndim == 2 and vertices.shape[1] == 3 and len(vertices):
            result[name] = (vertices.min(axis=0), vertices.max(axis=0))
    return result


def _check_relations(report, requirements, boxes):
    relations = requirements.get("spatial_relations", []) if isinstance(requirements, dict) else []
    if not relations:
        return
    failed = []
    checked = 0
    def center(box):
        return (box[0] + box[1]) / 2.0
    for rel in relations[:128]:
        if not isinstance(rel, dict):
            failed.append("invalid relation record")
            continue
        subject_key = rel.get("subject", "")
        object_key = rel.get("object", "")
        subject = _find_name(boxes, subject_key)
        target = _find_name(boxes, object_key)
        predicate = str(rel.get("predicate", "")).casefold()
        if not subject or not target:
            failed.append(f"{subject_key} {predicate} {object_key}: named component missing")
            continue
        a, b = boxes[subject], boxes[target]
        ca, cb = center(a), center(b)
        eps = max(float(np.linalg.norm(b[1] - b[0])) * 0.005, 1e-8)
        ok = None
        if predicate == "above": ok = ca[1] > cb[1] + eps
        elif predicate == "below": ok = ca[1] < cb[1] - eps
        elif predicate in {"left_of", "left_of_passage", "below_left_end_of", "below_left_side_of"}:
            ok = ca[0] < cb[0] - eps
            if predicate.startswith("below_"): ok = ok and ca[1] < cb[1]
        elif predicate in {"right_of_passage", "below_right_end_of", "below_right_side_of"}:
            ok = ca[0] > cb[0] + eps
            if predicate.startswith("below_"): ok = ok and ca[1] < cb[1]
        elif predicate == "on_x_positive_side_of": ok = ca[0] > cb[0] + eps
        elif predicate == "on_x_negative_side_of": ok = ca[0] < cb[0] - eps
        elif predicate == "above_and_behind": ok = ca[1] > cb[1] + eps and ca[2] < cb[2] - eps
        elif predicate == "behind_and_larger_than":
            ok = ca[2] < cb[2] - eps and np.linalg.norm(a[1] - a[0]) > np.linalg.norm(b[1] - b[0])
        elif predicate == "extends_x_positive_from": ok = a[1][0] > b[1][0] + eps
        elif predicate in {"on_top_of", "under_front_edge_of", "under_base", "under_left_side_of",
                           "under_right_side_of", "under_front_left_side_of", "under_front_right_side_of",
                           "under_rear_left_side_of", "under_rear_right_side_of", "around_underside_of"}:
            if predicate == "on_top_of": ok = a[0][1] >= b[1][1] - eps
            else:
                ok = ca[1] < cb[1]
                if "left" in predicate: ok = ok and ca[0] < cb[0]
                if "right" in predicate: ok = ok and ca[0] > cb[0]
                if "front" in predicate: ok = ok and ca[2] > cb[2]
                if "rear" in predicate: ok = ok and ca[2] < cb[2]
        elif predicate in {"around", "around_upper_section_of", "around_lower_section_of"}:
            # A bounding box can prove a wrap-like placement only coarsely.
            # Record the limitation and check enclosure/vertical zone.
            enclosure = (a[0][0] <= cb[0] + eps and a[1][0] >= cb[0] - eps
                         and a[0][2] <= cb[2] + eps and a[1][2] >= cb[2] - eps)
            if predicate == "around_upper_section_of": enclosure &= ca[1] >= cb[1]
            if predicate == "around_lower_section_of": enclosure &= ca[1] <= cb[1]
            ok = enclosure
        elif predicate in {"on_front_face_of", "across_front_of"}:
            overlap = all(min(a[1][i], b[1][i]) - max(a[0][i], b[0][i]) >= -eps
                          for i in (0, 1))
            ok = ca[2] >= b[1][2] - eps and overlap
        elif predicate == "on_side_face_of":
            overlap = all(min(a[1][i], b[1][i]) - max(a[0][i], b[0][i]) >= -eps
                          for i in (1, 2))
            touches_side = (a[1][0] >= b[1][0] - eps
                            or a[0][0] <= b[0][0] + eps)
            ok = overlap and touches_side
        elif predicate == "behind_bench": ok = ca[2] < cb[2] - eps
        elif predicate in {"inside_front_of", "inside_sides_of", "inside_shelter", "between_frame_posts"}:
            axes = (0, 1, 2) if predicate == "inside_shelter" else ((0, 2) if predicate == "inside_sides_of" else (0, 1))
            ok = all(a[0][axis] >= b[0][axis] - eps and a[1][axis] <= b[1][axis] + eps for axis in axes)
            if predicate == "inside_front_of":
                ok = ok and ca[2] >= cb[2]
        elif predicate == "above_both_posts":
            post_boxes = [box for name, box in boxes.items() if "post" in name.casefold()]
            ok = bool(post_boxes) and ca[1] > max(float(box[1][1]) for box in post_boxes) - eps
        elif predicate == "at_end_of":
            extents = b[1] - b[0]
            axis = int(np.argmax(extents))
            close_to_end = min(abs(ca[axis] - b[0][axis]), abs(ca[axis] - b[1][axis])) <= max(extents[axis] * 0.3, eps)
            aligned = all(abs(ca[i] - cb[i]) <= max((b[1][i] - b[0][i]) * 0.5, eps)
                          for i in range(3) if i != axis)
            ok = close_to_end and aligned
        elif predicate == "perpendicular_to":
            axis_a = int(np.argmax(a[1] - a[0]))
            axis_b = int(np.argmax(b[1] - b[0]))
            ok = axis_a != axis_b
        elif predicate == "joins":
            ok = all(a[0][i] <= b[1][i] + eps and b[0][i] <= a[1][i] + eps for i in range(3))
        elif predicate in {"paired_across_x_with", "paired_with"}:
            lateral = (ca[0] - cb[0])
            close = abs(ca[1] - cb[1]) <= max((b[1][1] - b[0][1]) * 0.5, eps) and abs(ca[2] - cb[2]) <= max((b[1][2] - b[0][2]) * 0.5, eps)
            ok = abs(lateral) > eps and close
            if predicate == "paired_across_x_with":
                ok = ok and (("left" in str(subject_key).casefold() and "right" in str(object_key).casefold())
                             or ("right" in str(subject_key).casefold() and "left" in str(object_key).casefold()))
        elif predicate == "span_between_supports":
            ok = float(np.max(a[1] - a[0])) >= float(np.max(b[1] - b[0]))
        elif predicate == "on_roof": ok = ca[1] > cb[1]
        if ok is None:
            failed.append(f"{subject_key} {predicate} {object_key}: unsupported relation")
        elif not bool(ok):
            failed.append(f"{subject_key} {predicate} {object_key}: bounds do not satisfy relation")
        else:
            checked += 1
    _check(report, "spatial_relations", not failed,
           f"Verified {checked} of {len(relations)} required spatial relations by evaluated object bounds.",
           {"checked": checked, "required": len(relations), "issues": failed[:16],
            "method": "axis-aligned scene bounds; contact/surface relations need richer evidence"})


def _export_material_expectations(recipe: dict, scene) -> tuple[dict, dict]:
    """Map reopened native material intent to the exporter's opaque names."""
    from am3d.core.scene import scene_material_colors, scene_patch_material_colors
    from am3d.recipes.executor import _artifact_object_names

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

    project = session.project
    expected_objects = [str(item.get("name")) for item in recipe.get("objects", [])
                        if isinstance(item, dict) and item.get("name")]
    missing_objects = [name for name in expected_objects if name not in project.objects]
    recipe_materials = [str(item.get("name")) for item in recipe.get("materials", [])
                        if isinstance(item, dict) and item.get("name")]
    missing_materials = [name for name in recipe_materials if name not in project.materials]
    recipe_actions = [str(item.get("name")) for item in recipe.get("actions", [])
                      if isinstance(item, dict) and item.get("name")]
    loaded_actions = getattr(project, "actions", {})
    missing_actions = [name for name in recipe_actions if name not in loaded_actions]
    assignments_bad = []
    for item in recipe.get("materials", []) or []:
        if not isinstance(item, dict):
            continue
        material_name = item.get("name")
        for object_name in item.get("objects", []) or []:
            if object_name in project.objects and project.objects[object_name].material != material_name:
                assignments_bad.append(f"{object_name}:{material_name}")
    _check(report, "recipe_intentions", not (missing_objects or missing_materials or missing_actions or assignments_bad),
           "Reopened project retains the recipe's named objects, materials, actions, and material bindings.",
           {"missing_objects": missing_objects[:16], "missing_materials": missing_materials[:16],
            "missing_actions": missing_actions[:16], "bad_material_assignments": assignments_bad[:16]})

    scene = session.evaluate_scene(visible_only=True, apply_transforms=True,
                                   nu=16, nv=16)
    valid_surface_meshes = []
    renderable_surface_meshes = []
    degenerate_triangles = 0
    invalid_geometry = []
    all_vertices = []
    for name, mesh in scene.meshes.items():
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        normals = np.asarray(mesh.normals, dtype=np.float64)
        indices = np.asarray(mesh.indices, dtype=np.int64)
        if vertices.ndim != 2 or vertices.shape[1:] != (3,):
            invalid_geometry.append(f"{name}:vertex_shape")
            continue
        all_vertices.append(vertices)
        if not np.isfinite(vertices).all():
            invalid_geometry.append(f"{name}:nonfinite_vertices")
        if normals.shape != vertices.shape or not np.isfinite(normals).all():
            invalid_geometry.append(f"{name}:invalid_normals")
        if indices.ndim != 2 or indices.shape[1:] != (3,):
            invalid_geometry.append(f"{name}:triangle_shape")
            continue
        if len(indices):
            if int(indices.min()) < 0 or int(indices.max()) >= len(vertices):
                invalid_geometry.append(f"{name}:invalid_indices")
                continue
            tri = vertices[indices]
            areas2 = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0],
                                             tri[:, 2] - tri[:, 0]), axis=1)
            degenerate_triangles += int((areas2 <= 1e-12).sum())
            valid_surface_meshes.append(name)
            if np.isfinite(tri).all() and bool((areas2 > 1e-12).any()):
                extents = vertices.max(axis=0) - vertices.min(axis=0)
                if np.isfinite(extents).all() and float(np.linalg.norm(extents)) > 1e-12:
                    renderable_surface_meshes.append(name)
    if all_vertices and sum(len(v) for v in all_vertices):
        combined = np.concatenate([v for v in all_vertices if len(v)], axis=0)
        bounds_min, bounds_max = combined.min(axis=0), combined.max(axis=0)
        diagonal = float(np.linalg.norm(bounds_max - bounds_min))
        finite_bounds = np.isfinite(bounds_min).all() and np.isfinite(bounds_max).all()
        nonzero_bounds = diagonal > 1e-12
    else:
        bounds_min = bounds_max = np.zeros(3)
        diagonal, finite_bounds, nonzero_bounds = 0.0, True, False
    has_faces = bool(valid_surface_meshes) and any(
        len(np.asarray(mesh.indices)) for mesh in scene.meshes.values())
    geometry_ok = bool(has_faces and finite_bounds and nonzero_bounds and not invalid_geometry)
    report["measurements"].update({
        "visible_object_count": len(scene.meshes),
        "surface_object_count": len(valid_surface_meshes),
        "vertex_count": int(sum(len(v) for v in all_vertices)),
        "triangle_count": int(sum(len(m.indices) for m in scene.meshes.values())),
        "bounds_min": bounds_min.tolist(), "bounds_max": bounds_max.tolist(),
        "scene_diagonal": diagonal,
        "degenerate_triangles_reported": degenerate_triangles,
    })
    triangle_count = int(sum(len(m.indices) for m in scene.meshes.values()))
    geometry_bytes = int(sum(np.asarray(array).nbytes
                             for mesh in scene.meshes.values()
                             for array in (mesh.vertices, mesh.normals, mesh.indices)))
    from .policy import MAX_EVALUATED_TRIANGLES, MAX_ESTIMATED_MEMORY
    resource_ok = triangle_count <= MAX_EVALUATED_TRIANGLES and geometry_bytes <= MAX_ESTIMATED_MEMORY
    _check(report, "surface_geometry", geometry_ok,
           "Evaluated scene has finite vertices/normals, valid triangle indices and nonzero bounds.",
           {"surface_objects": valid_surface_meshes[:32],
            "issues": invalid_geometry[:16], "degenerate_triangles": degenerate_triangles})
    _check(report, "evaluated_resource_limits", resource_ok,
           "Measured evaluated geometry stays within V1 triangle and memory limits.",
           {"triangle_count": triangle_count,
            "triangle_limit": MAX_EVALUATED_TRIANGLES,
            "geometry_array_bytes": geometry_bytes,
            "estimated_memory_limit_bytes": MAX_ESTIMATED_MEMORY})

    components = _expected_components(requirements, brief)
    geometry_names = renderable_surface_meshes
    used_component_objects = set()
    missing_components = []
    for name in components:
        matched = next((candidate for candidate in geometry_names
                        if candidate not in used_component_objects
                        and _name_match(candidate, name)), None)
        if matched is None:
            missing_components.append(name)
        else:
            used_component_objects.add(matched)
    if components:
        _check(report, "required_components", not missing_components,
               "Matched each caller-authored required component to distinct reopened surface geometry.",
               {"required": components[:64], "missing": missing_components[:32],
                "matched_surface_objects": sorted(used_component_objects)[:64],
                "method": "case-insensitive token matching; one mesh cannot satisfy two required components"})

    dims = _dimensions(requirements, brief)
    if isinstance(dims, dict):
        tol = requirements.get("dimension_tolerance_fraction", 0.20) if isinstance(requirements, dict) else 0.20
        try:
            tol = float(tol)
            requested = [float(dims.get("width", 0)), float(dims.get("height", 0)),
                         float(dims.get("depth", 0))]
            actual = (bounds_max - bounds_min).tolist()
            axes = ("width", "height", "depth")
            bad = [axes[i] for i in range(3) if requested[i] > 0 and
                   abs(actual[i] - requested[i]) > requested[i] * tol]
            _check(report, "requested_dimensions", not bad,
                   "Compared evaluated scene bounds with independently supplied target dimensions.",
                   {"requested_m": requested, "actual_m": actual,
                    "tolerance_fraction": tol, "outside_tolerance": bad})
        except (TypeError, ValueError, OverflowError):
            _check(report, "requested_dimensions", False,
                   "Requested dimension evidence is malformed.")

    expected_materials = requirements.get("materials", []) if isinstance(requirements, dict) else []
    if not expected_materials and isinstance(brief, dict):
        expected_materials = brief.get("materials", []) or []
    material_issues = []
    for item in expected_materials[:64] if isinstance(expected_materials, list) else []:
        if not isinstance(item, dict):
            continue
        component = item.get("component")
        material_intent_name = item.get("name") if not component else None
        target_color = _target_color(item)
        if not (component or material_intent_name) or not isinstance(target_color, (list, tuple)):
            continue
        if component:
            object_name = _find_name(geometry_names, component)
            if object_name is None:
                material_issues.append(f"{component}: component missing")
                continue
            material_name = project.objects[object_name].material
            actual_material = project.materials.get(material_name)
            label = str(component)
        else:
            actual_material = project.materials.get(material_intent_name)
            material_name = material_intent_name if actual_material else None
            label = str(material_intent_name)
            assigned_objects = [name for name, obj in project.objects.items()
                                if obj.material == material_name and name in geometry_names]
            if actual_material is None:
                material_issues.append(f"{label}: named material missing")
                continue
            if not assigned_objects:
                material_issues.append(f"{label}: material is not assigned to surface geometry")
                continue
        actual_color = _mat_color(actual_material) if actual_material else None
        if actual_color is None:
            material_issues.append(f"{label}: no assigned color material")
            continue
        try:
            expected_color = np.asarray(target_color, dtype=np.float64)[:3]
            limit = float(item.get("tolerance_per_channel", 0.15))
            if expected_color.size != 3 or not np.isfinite(expected_color).all() or not np.isfinite(actual_color).all():
                raise ValueError
            if bool((np.abs(actual_color - expected_color) > limit).any()):
                material_issues.append(f"{label}: assigned color outside tolerance")
        except (TypeError, ValueError):
            material_issues.append(f"{label}: invalid color expectation")
    if expected_materials:
        _check(report, "material_assignments_and_color", not material_issues,
               "Checked assigned native material colors against caller-authored targets.",
               {"issues": material_issues[:16],
                "method": "native material assignment and sRGB base color; software preview color fidelity is reported separately"})

    _check_relations(report, requirements, _bounds_by_object(scene))

    disclosure_requirements = requirements.get("requirements", {}) if isinstance(requirements, dict) else {}
    expected_disclosures = (disclosure_requirements.get("expected_disclosures", [])
                            if isinstance(disclosure_requirements, dict) else [])
    if isinstance(expected_disclosures, list) and expected_disclosures:
        disclosure_sources = []
        if isinstance(brief, dict):
            disclosure_sources.extend(brief.get("approximations", []) or [])
        if generation:
            disclosure_sources.extend(generation.get("warnings", []) or [])
        combined = _normalize_text(disclosure_sources)
        disclosure_issues = []
        for item in expected_disclosures[:32]:
            if not isinstance(item, dict):
                disclosure_issues.append("invalid expected disclosure")
                continue
            if item.get("applies_if"):
                condition = str(item["applies_if"]).casefold()
                # The current fixture condition is the choice between a true
                # opening and a visible surface panel. Check the host recipe's
                # object names, not the model's own disclosure, for applicability.
                recipe_names = " ".join(str(obj.get("name", ""))
                                         for obj in recipe.get("objects", [])
                                         if isinstance(obj, dict)).casefold()
                if "surface panel" in condition and not ("panel" in recipe_names or "slot" in recipe_names):
                    continue
            keywords = item.get("semantic_keywords", [])
            if isinstance(keywords, str):
                keywords = [keywords]
            actual_tokens = _disclosure_tokens(combined)
            missing = []
            for phrase in keywords[:16]:
                required_tokens = _disclosure_tokens(phrase)
                required_tokens -= {"the", "a", "an", "of", "and", "or", "is", "are", "as", "rather", "than"}
                if required_tokens and not required_tokens.issubset(actual_tokens):
                    missing.append(str(phrase))
            if missing:
                disclosure_issues.append("missing expected topic: " + ", ".join(missing[:4]))
        _check(report, "expected_disclosures", not disclosure_issues,
               "Checked required approximation disclosures against normalized brief text and host warnings.",
               {"required": len(expected_disclosures), "issues": disclosure_issues[:16],
                "exact_phrasing_required": False})

    rig = requirements.get("rig", {}) if isinstance(requirements, dict) else {}
    animation = brief.get("animation") if isinstance(brief, dict) else None
    rig = rig if isinstance(rig, dict) else {}
    missing_bones = []
    rig_requested = bool(rig.get("required"))
    if rig_requested:
        required_bones = rig.get("expected_bones", []) or []
        bone_names = {bone.name for bones in project.skeletons.values() for bone in bones.values()}
        missing_bones = [name for name in required_bones if name not in bone_names]
        binding_issues = []
        bound_components = rig.get("bound_components", []) or []
        if not bound_components and project.skeletons:
            bound_components = list(project.skeletons)
        for component in bound_components[:64]:
            object_name = _find_name(project.objects, component)
            if object_name is None:
                binding_issues.append(f"{component}: object missing")
                continue
            bones = project.skeletons.get(object_name, {})
            if not bones:
                binding_issues.append(f"{component}: skeleton missing")
            elif not any(any(float(weight) > 0 for weight in bone.cp_weights.values())
                         for bone in bones.values()):
                binding_issues.append(f"{component}: no positive control-point weights")
        _check(report, "rig_binding", not (missing_bones or binding_issues),
               "Checked required skeleton bones and positive weighted geometry bindings.",
               {"required_bones": required_bones[:64], "missing_bones": missing_bones[:32],
                "bound_components": bound_components[:64], "issues": binding_issues[:16]})

    animation_requested = bool((rig.get("action_kind") or rig.get("must_deform_components")) or animation)
    if animation_requested:
        action_specs = recipe.get("actions", []) or []
        action_name = next((a.get("name") for a in action_specs
                            if isinstance(a, dict) and a.get("name")), None)
        if rig.get("action_kind"):
            kind = str(rig["action_kind"]).casefold()
            action_name = next((a.get("name") for a in action_specs
                                if isinstance(a, dict) and str(a.get("kind", "")).casefold() == kind), action_name)
        action_ok = bool(action_name and action_name in session.actions)
        intended = rig.get("must_deform_components", []) or []
        if not intended:
            intended = rig.get("bound_components", []) or []
        if not intended:
            intended = [name for name in project.skeletons if name in scene.meshes]
        recipe_specs = {item.get("name"): item for item in recipe.get("objects", [])
                        if isinstance(item, dict) and isinstance(item.get("name"), str)}
        assignment_failures = []
        assigned_components = []
        for component in intended[:64]:
            object_name = _find_name(scene.meshes, component)
            target_rig_name = _find_name(project.skeletons, component)
            if object_name is None or target_rig_name is None:
                assignment_failures.append(f"{component}: intended component has no reopened rig")
                continue
            target_bones = project.skeletons.get(target_rig_name, {})
            target_weighted = any(
                any(float(weight) > 0 for weight in bone.cp_weights.values())
                for bone in target_bones.values())
            if not target_weighted:
                assignment_failures.append(f"{component}: intended component has no weighted rig binding")
                continue
            directly_assigned = bool(action_name and
                                     session.action_assignments.get(target_rig_name) == action_name)
            shared_assigned = False
            spec = recipe_specs.get(object_name) or recipe_specs.get(target_rig_name)
            params = spec.get("params", {}) if isinstance(spec, dict) else {}
            skeleton_ref = params.get("skeleton") if isinstance(params, dict) else None
            if action_name and isinstance(skeleton_ref, str):
                master_name = _find_name(project.skeletons, skeleton_ref)
                if master_name and master_name != target_rig_name:
                    master_bones = project.skeletons.get(master_name, {})
                    def _skeleton_signature(bones):
                        return tuple((bone.name, bone.parent) for bone in bones.values())
                    shared_assigned = bool(
                        session.action_assignments.get(master_name) == action_name
                        and _skeleton_signature(target_bones) == _skeleton_signature(master_bones)
                        and target_weighted)
            if directly_assigned or shared_assigned:
                assigned_components.append(component)
            else:
                assignment_failures.append(f"{component}: action is not assigned to its rig or explicit shared rig")
        assigned_ok = bool(intended) and not assignment_failures
        duration = None
        if action_name and action_name in session.actions:
            duration = float(getattr(session.actions[action_name], "duration", 0.0) or 0.0)
        if not duration and isinstance(animation, dict):
            duration = float(animation.get("duration_seconds") or 0.0)
        if not duration:
            duration = 1.0
        thresholds = []
        motion_issues = []
        rendered_samples = 0
        sample_times = [duration * fraction for fraction in (0.0, 0.25, 0.5, 0.75)]
        camera = None
        try:
            from am3d.gpu import scene_camera
            camera = scene_camera(list(scene.meshes.values()))
        except Exception:
            camera = None
        for component in intended[:64]:
            object_name = _find_name(scene.meshes, component)
            if object_name is None:
                motion_issues.append(f"{component}: intended object missing")
                continue
            initial = np.asarray(scene.meshes[object_name].vertices, dtype=np.float64)
            max_displacement = 0.0
            for time_s in sample_times:
                sampled = session.evaluate_scene(action_name=action_name, time=time_s,
                                                 visible_only=True, apply_transforms=True,
                                                 nu=16, nv=16)
                mesh = sampled.meshes.get(object_name)
                if mesh is None or np.asarray(mesh.vertices).shape != initial.shape:
                    motion_issues.append(f"{component}: sampled mesh changed shape or disappeared")
                    continue
                vertices = np.asarray(mesh.vertices, dtype=np.float64)
                if not np.isfinite(vertices).all():
                    motion_issues.append(f"{component}: sampled non-finite geometry")
                    continue
                displacement = float(np.max(np.linalg.norm(vertices - initial, axis=1))) if len(initial) else 0.0
                max_displacement = max(max_displacement, displacement)
                try:
                    if camera is not None:
                        from am3d.render_job import render_frame_image
                        image = render_frame_image(session, camera, 128, 128,
                                                   time=time_s, action_name=action_name,
                                                   force_software=True)
                        if image.shape != (128, 128, 4) or not np.isfinite(image).all():
                            raise ValueError("invalid frame")
                        rendered_samples += 1
                except Exception:
                    # Rendering sample failure is reflected below as a check
                    # failure, rather than hiding it behind a geometry pass.
                    motion_issues.append(f"{component}: fixed-camera sample render failed")
                    break
            threshold = max(1e-6, 0.001 * diagonal)
            thresholds.append({"component": component, "max_displacement": max_displacement,
                               "required_displacement": threshold})
            if max_displacement <= threshold:
                motion_issues.append(f"{component}: motion did not exceed threshold")
        animation_ok = action_ok and assigned_ok and not missing_bones and bool(intended) and not motion_issues
        _check(report, "animation_and_deformation", animation_ok,
               "Checked bound action samples at 0%, 25%, 50%, and 75% of duration with one fixed camera.",
               {"action": action_name, "action_present": action_ok,
                "assignment_present": assigned_ok,
                "assigned_components": assigned_components[:32],
                "assignment_issues": assignment_failures[:16],
                "missing_bones": missing_bones[:16],
                "samples": thresholds[:32], "rendered_sample_frames": rendered_samples,
                "issues": motion_issues[:16],
                "human_review": "useful visible motion remains a human acceptance question"})

    # Generate the whole-scene preview with the shared scene camera and
    # software fallback. The preview proves visible, bounded geometry; when
    # software rendering cannot preserve per-object color it is stated below.
    preview_path = root / "preview.png"
    preview_ok = False
    preview_measurements = {}
    try:
        from am3d.gpu import scene_camera
        from am3d.render_job import save_image
        camera = scene_camera(list(scene.meshes.values()))
        frame, textured_objects = _render_material_preview(scene, camera, 512, 512)
        backend = "software material-aware"
        if not np.isfinite(frame).all():
            raise ValueError("renderer returned non-finite pixels")
        save_image(frame, str(preview_path))
        from PIL import Image
        with Image.open(preview_path) as image:
            image.verify()
        with Image.open(preview_path) as image:
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        if rgba.shape != (512, 512, 4):
            raise ValueError("preview has an unexpected pixel size")
        alpha = rgba[..., 3]
        foreground = alpha > 8
        occupancy = float(foreground.mean())
        rgb = rgba[..., :3][foreground]
        color_contrast = float(np.max(rgb.max(axis=0) - rgb.min(axis=0))) / 255.0 if len(rgb) else 0.0
        background = ~foreground
        alpha_contrast = (float(alpha[foreground].mean() - alpha[background].mean()) / 255.0
                          if foreground.any() and background.any() else 0.0)
        contrast = max(color_contrast, alpha_contrast)
        preview_ok = bool(np.isfinite(rgba).all() and 0.005 <= occupancy <= 0.95
                          and len(rgb) and contrast >= 0.05)
        preview_measurements = {"width": 512, "height": 512,
                                "foreground_fraction": occupancy,
                                "foreground_color_range": color_contrast,
                                "alpha_background_contrast": alpha_contrast,
                                "backend": str(backend)}
        if textured_objects:
            report["limitations"].append(
                "Preview uses assigned flat material base colors; procedural/image texture appearance is not rendered for: "
                + ", ".join(textured_objects[:16]))
    except Exception:
        preview_measurements = {"reason": "preview_render_or_decode_failed"}
    report["measurements"]["preview"] = preview_measurements
    _check(report, "whole_scene_preview", preview_ok,
           "Rendered and decoded a 512x512 auto-fit whole-scene preview with bounded foreground occupancy and color contrast.",
           preview_measurements)

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
