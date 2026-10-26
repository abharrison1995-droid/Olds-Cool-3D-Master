"""Native scene geometry and caller-authored requirement checks.

These stages mutate only the supplied report. File confinement, native
round trips, export parsing and final publication remain with their owners.
"""
from __future__ import annotations

import re
import numpy as np

from ._check_report import _check

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


def _check_recipe_intentions(report, recipe, session):
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


def _check_geometry(report, scene):
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
    return renderable_surface_meshes, bounds_min, bounds_max, diagonal


def _check_requirements(report, recipe, requirements, brief, generation, project, scene,
                        geometry_names, bounds_min, bounds_max):
    components = _expected_components(requirements, brief)
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
