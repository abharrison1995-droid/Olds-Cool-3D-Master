"""Deterministic post-execution checks for local recipe generation.

This module deliberately orchestrates the application's existing Session,
serializer, scene evaluator, software renderer and independent export readers.
It contains no Qt imports and creates no second scene representation.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

import numpy as np

from .contracts import GenerationCheckResult


CHECK_VERSION = 1
PREVIEW_SIZE = 512


@dataclass(frozen=True)
class CheckOutput:
    checks: tuple[GenerationCheckResult, ...]
    preview_path: str

    @property
    def ok(self) -> bool:
        return all(item.ok for item in self.checks)


def _check(name: str, ok: bool, code: str = "", message: str = "",
           details: dict | None = None, **extra) -> GenerationCheckResult:
    return GenerationCheckResult(name, bool(ok), code, message,
                                 {**(details or {}), **extra})


def _inside(root: Path, candidate: Path) -> bool:
    try:
        return os.path.commonpath((str(root.resolve()), str(candidate.resolve()))) == str(root.resolve())
    except (OSError, ValueError):
        return False


def _geometry_checks(session) -> tuple[list[GenerationCheckResult], object | None]:
    checks = []
    try:
        scene = session.evaluate_scene(visible_only=True, apply_transforms=True,
                                      nu=32, nv=32)
        meshes = {name: mesh for name, mesh in scene.meshes.items()
                  if len(mesh.vertices)}
    except Exception:
        return [_check("scene_evaluation", False, "scene_invalid",
                       "The saved project could not be evaluated.")], None

    checks.append(_check("renderable_geometry", bool(meshes),
                         "no_renderable_geometry" if not meshes else "",
                         "No visible renderable geometry was produced." if not meshes else "",
                         object_count=len(meshes)))
    finite = True
    valid_indices = True
    vertex_count = triangle_count = 0
    for mesh in meshes.values():
        vertices = np.asarray(mesh.vertices)
        indices = np.asarray(mesh.indices)
        vertex_count += len(vertices)
        triangle_count += len(indices)
        finite = finite and bool(np.isfinite(vertices).all())
        normals = getattr(mesh, "normals", None)
        if normals is not None:
            finite = finite and bool(np.isfinite(np.asarray(normals)).all())
        if indices.size:
            valid_indices = valid_indices and bool(
                np.issubdtype(indices.dtype, np.integer) and
                int(indices.min()) >= 0 and int(indices.max()) < len(vertices))
    checks.append(_check("finite_geometry", finite,
                         "non_finite_geometry" if not finite else "",
                         "Evaluated geometry contains non-finite coordinates." if not finite else "",
                         vertices=vertex_count, triangles=triangle_count))
    checks.append(_check("valid_indices", valid_indices,
                         "invalid_mesh_indices" if not valid_indices else "",
                         "Evaluated mesh indices are outside their vertex arrays." if not valid_indices else ""))

    try:
        lo, hi = (np.asarray(scene.bounds[0], dtype=np.float64),
                  np.asarray(scene.bounds[1], dtype=np.float64))
        bounds_finite = lo.shape == (3,) and hi.shape == (3,) and bool(
            np.isfinite(lo).all() and np.isfinite(hi).all())
        nonzero = bounds_finite and float(np.linalg.norm(hi - lo)) > 1e-10
    except Exception:
        lo = hi = np.zeros(3)
        bounds_finite = nonzero = False
    checks.append(_check("scene_bounds", bounds_finite and nonzero,
                         "invalid_scene_bounds" if not (bounds_finite and nonzero) else "",
                         "Scene bounds must be finite and have nonzero extent." if not (bounds_finite and nonzero) else "",
                         minimum=lo.tolist() if bounds_finite else [],
                         maximum=hi.tolist() if bounds_finite else []))

    # Spline control data remains authoritative, so inspect it directly as
    # well as the derived evaluated mesh.
    source_finite = True
    for obj in session.project.objects.values():
        for spline in getattr(obj, "splines", {}).values():
            for cp in getattr(spline, "cps", []):
                try:
                    source_finite = source_finite and bool(
                        np.isfinite(np.asarray(cp.position, dtype=np.float64)).all() and
                        np.isfinite(float(cp.weight)))
                except (TypeError, ValueError, AttributeError):
                    source_finite = False
        for patch in getattr(obj, "patches", []):
            interior = getattr(patch, "interior", None)
            if interior is not None:
                source_finite = source_finite and bool(
                    np.isfinite(np.asarray(interior, dtype=np.float64)).all())
        for bone in getattr(session.project, "skeletons", {}).get(obj.name, {}).values():
            for endpoint in (getattr(bone, "head", None), getattr(bone, "tail", None)):
                if endpoint is not None:
                    source_finite = source_finite and bool(
                        np.isfinite(np.asarray(endpoint, dtype=np.float64)).all())
    checks.append(_check("authoritative_spline_data", source_finite,
                         "non_finite_source_geometry" if not source_finite else "",
                         "Spline or patch source data contains non-finite values." if not source_finite else ""))
    return checks, scene


def _animation_checks(session) -> list[GenerationCheckResult]:
    assignments = getattr(session, "action_assignments", {})
    if not assignments:
        return [_check("assigned_animation_samples", True,
                       details={"assigned_actions": 0})]
    checks = []
    by_action: dict[str, set[str]] = {}
    for object_name, action_name in assignments.items():
        by_action.setdefault(action_name, set()).add(object_name)
    for action_name, object_names in sorted(by_action.items()):
        action = session.actions.get(action_name)
        if action is None:
            checks.append(_check("assigned_animation_samples", False,
                                 "missing_assigned_action",
                                 "A saved object refers to an action that is missing.",
                                 action=action_name))
            continue
        duration = float(getattr(action, "duration", 0.0) or 0.0)
        sampled = bool(np.isfinite(duration) and duration > 0)
        for fraction in (0.0, 0.25, 0.5, 0.75):
            try:
                scene = session.evaluate_scene(action_name=action_name,
                                               time=duration * fraction,
                                               visible_only=False,
                                               nu=16, nv=16,
                                               apply_transforms=True)
                for object_name in object_names:
                    mesh = scene.meshes.get(object_name)
                    if mesh is None or not np.isfinite(mesh.vertices).all():
                        sampled = False
                        break
            except Exception:
                sampled = False
            if not sampled:
                break
        checks.append(_check("assigned_animation_samples", sampled,
                             "animation_sample_invalid" if not sampled else "",
                             "An assigned action failed a deterministic 0/25/50/75% sample." if not sampled else "",
                             action=action_name, sample_fractions=[0, .25, .5, .75],
                             targets=sorted(object_names)))
    return checks


def _preview(session, path: Path, scene) -> list[GenerationCheckResult]:
    if scene is None:
        return [_check("whole_scene_preview", False, "preview_scene_unavailable",
                       "The scene could not be rendered for the required preview.")]
    try:
        from am3d.renderer.sprite import render_scene
        from PIL import Image

        image = render_scene(scene.meshes, size=PREVIEW_SIZE)
        rgba = (np.clip(image, 0.0, 1.0) * 255).astype(np.uint8)
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(rgba, "RGBA").save(path, format="PNG", optimize=True)
        with Image.open(path) as decoded:
            decoded.verify()
        with Image.open(path) as decoded:
            width, height = decoded.size
            alpha = np.asarray(decoded.convert("RGBA"))[:, :, 3]
        occupancy = float(np.count_nonzero(alpha)) / float(width * height)
        ok = (width == PREVIEW_SIZE and height == PREVIEW_SIZE and
              0.0001 <= occupancy <= 0.995 and path.is_file())
        return [_check("whole_scene_preview", ok,
                       "preview_blank_or_invalid" if not ok else "",
                       "The preview is missing, blank, clipped, or has unexpected dimensions." if not ok else "",
                       width=width, height=height, foreground_fraction=occupancy)]
    except Exception:
        return [_check("whole_scene_preview", False, "preview_render_failed",
                       "The deterministic whole-scene preview could not be rendered.")]


def _export_checks(manifest, export_root: Path) -> list[GenerationCheckResult]:
    checks = []
    for index, item in enumerate(manifest):
        path = Path(item.get("path", ""))
        fmt = str(item.get("format", "")).lower()
        allowed = path.is_file() and _inside(export_root, path)
        issues: list[str] = []
        if allowed:
            try:
                if fmt == "obj":
                    from am3d.export.validate import validate_obj
                    issues = validate_obj(str(path))
                elif fmt in {"glb", "gltf"}:
                    from am3d.export.validate import validate_glb
                    issues = validate_glb(str(path))
                elif (fmt in {"png", "atlas", "spritesheet", "toon_sheet",
                              "animation_sheet"} or path.suffix.lower() == ".png"):
                    from PIL import Image
                    with Image.open(path) as img:
                        img.verify()
                elif fmt == "am3d":
                    from am3d.core.script import Session
                    Session().load_project(str(path))
                elif fmt == "mtl":
                    # The independent OBJ reader checks MTL references and
                    # content as part of validating its owning OBJ.
                    pass
                else:
                    issues = ["no independent validator is registered for this artifact"]
            except Exception as exc:
                issues = [f"independent parser failed ({type(exc).__name__})"]
        else:
            issues = ["artifact is missing or escapes the private output directory"]
        checks.append(_check(f"export_{index}", not issues,
                             "export_validation_failed" if issues else "",
                             "; ".join(issues[:4]), format=fmt,
                             relative_path=path.name))
    if not manifest:
        checks.append(_check("requested_exports", True,
                             details={"exports": 0}))
    return checks


def run_generation_checks(session, manifest, output_root: str | os.PathLike,
                          preview_path: str | os.PathLike, *,
                          on_preview=None) -> CheckOutput:
    """Reopen and check a generated project, then always produce its preview."""
    export_root = Path(output_root).resolve()
    preview = Path(preview_path)
    checks, scene = _geometry_checks(session)
    checks.extend(_animation_checks(session))
    checks.extend(_export_checks(manifest, export_root))
    if on_preview is not None:
        on_preview()
    checks.extend(_preview(session, preview, scene))
    return CheckOutput(tuple(checks), str(preview))
