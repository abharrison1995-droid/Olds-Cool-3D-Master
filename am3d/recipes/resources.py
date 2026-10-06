"""Allocation-free recipe estimates and AI-mode resource ceilings."""

from __future__ import annotations

from am3d.core.sheet_layout import calculate_sheet_layout

from .capabilities import CAPABILITIES


LIMITS = {
    "objects": 128,
    "patches": 1024,
    "bones_per_skeleton": 64,
    "copied_bones": 256,
    "actions": 16,
    "channels": 256,
    "keys": 4096,
    "authored_points": 4096,
    "subdivisions": 128,
    "materials": 32,
    "graph_nodes_per_material": 32,
    "triangles": 250_000,
    "sheet_pixels": 16_000_000,
    "sheet_cells": 16,
    "sheet_cell_size": 256,
    "texture_pixels": 64_000_000,
    "atlas_cell_size": 256,
    "atlas_pixels": 64_000_000,
    "memory_bytes": 1024 * 1024 * 1024,
    "published_bytes": 256 * 1024 * 1024,
}


def _primitive_counts(obj):
    """Return conservative control-point/patch counts for one object."""
    params = obj.params if isinstance(obj.params, dict) else {}
    name = obj.primitive
    if not name:
        return 0, 0, 0
    cap = CAPABILITIES.get(("primitive", name))
    values = {key: spec.default for key, spec in cap.params.items()
              if spec.has_default} if cap else {}
    values.update({key: value for key, value in params.items()
                   if cap and key in cap.params})
    if name in {"sphere", "cylinder", "cone"}:
        sections = int(values.get("sections", 16))
        rings = int(values.get("rings", 8))
        extra = 2 if name == "cylinder" and values.get("capped", True) else 0
        return (sections + 1) * (rings + extra), 1, max(sections, rings)
    if name == "torus":
        major = int(values.get("major_sections", 24))
        minor = int(values.get("minor_sections", 12))
        return (major + 1) * (minor + 1), 1, max(major, minor)
    if name == "box":
        n = int(values.get("n", 4))
        return 6 * n * n, 6, n
    if name == "plane":
        n = int(values.get("n", 4))
        return n * n, 1, n
    if name == "lathe":
        profile = values.get("profile", ())
        sections = int(values.get("sections", 24))
        return (sections + 1) * len(profile), 1, sections
    if name == "extrude":
        profile = values.get("profile", ())
        rings = int(values.get("rings", 4))
        return rings * len(profile), 1, rings
    return 0, 0, 0


def estimate_recipe_resources(recipe, *, tessellation=32) -> dict:
    """Estimate expensive work without constructing geometry or textures."""
    points = patches = geometry_objects = authored_points = max_subdivision = 0
    max_bones = max((len(obj.bones) for obj in recipe.objects), default=0)
    copied_bones = 0
    for obj in recipe.objects:
        built_points, built_patches, subdivision = _primitive_counts(obj)
        spline_points = sum(len(spline.points) for spline in obj.splines)
        points += built_points + spline_points
        authored_points += spline_points
        patches += built_patches + len(obj.splines)
        geometry_objects += int(bool(built_points or spline_points))
        max_subdivision = max(max_subdivision, subdivision)
        if obj.primitive in {"lathe", "extrude"}:
            params = obj.params if isinstance(obj.params, dict) else {}
            authored_points += len(params.get("profile", ()) or ())
        skel = (obj.params.get("skeleton")
                if isinstance(obj.params, dict) else None)
        if skel:
            skeleton = next((other for other in recipe.objects
                             if other.name == skel), None)
            if skeleton is not None:
                copied_bones += len(skeleton.bones)

    object_bones = {obj.name: len(obj.bones) for obj in recipe.objects}
    channels = keys = 0
    action_keys = {}
    action_channels = {}
    for action in recipe.actions:
        if action.kind == "custom":
            channel_count = len(action.channels)
            action_key_count = sum(len(channel.keys)
                                   for channel in action.channels)
        elif action.kind in {"walk", "idle", "jump"}:
            bone_count = object_bones.get(action.character, 0)
            channel_count = bone_count
            samples = 6 if action.kind == "jump" else 13
            action_key_count = bone_count * samples
        elif action.kind == "retarget":
            source_name = action.source_action
            channel_count = action_channels.get(source_name, 0)
            action_key_count = action_keys.get(source_name, 0)
        else:
            channel_count = action_key_count = 0
        channels += channel_count
        keys += action_key_count
        action_keys[action.name] = action_key_count
        action_channels[action.name] = channel_count
    graph_nodes = max((len(material.graph) for material in recipe.materials),
                      default=0)
    graph_node_total = sum(len(material.graph) for material in recipe.materials)

    triangles = patches * int(tessellation) * int(tessellation) * 2
    sheet_pixels = sheet_cells = max_sheet_cell_size = 0
    for export in recipe.exports:
        params = export.params if isinstance(export.params, dict) else {}
        fmt = str(export.format).lower()
        if fmt in {"spritesheet", "toon_sheet"}:
            frames = int(params.get("views", 8))
            cell = int(params.get("size", 256))
            layout = calculate_sheet_layout(frames, frames, cell)
            sheet_cells = max(sheet_cells, layout.allocated_cells)
            max_sheet_cell_size = max(max_sheet_cell_size, cell)
            sheet_pixels += layout.pixels * geometry_objects
        elif fmt == "animation_sheet":
            frames = int(params.get("frames", 8))
            columns = int(params.get("columns", frames))
            cell = int(params.get("size", 256))
            layout = calculate_sheet_layout(frames, columns, cell)
            sheet_cells = max(sheet_cells, layout.allocated_cells)
            max_sheet_cell_size = max(max_sheet_cell_size, cell)
            sheet_pixels += layout.pixels

    texture_pixels = 0
    uses_baked_textures = any(
        str(export.format).lower() in {"obj", "glb", "gltf"}
        for export in recipe.exports)
    if uses_baked_textures:
        for material in recipe.materials:
            if material.pattern:
                size = int((material.params or {}).get("size", 256))
                texture_pixels += size * size
            if material.graph:
                for node in material.graph:
                    node_params = node.get("params", {}) if isinstance(node, dict) else {}
                    size = int(node_params.get("size", 256)) if isinstance(node_params, dict) else 256
                    texture_pixels += size * size
    atlas_cells = patches if texture_pixels else 0
    atlas_pixels = atlas_cells * LIMITS["atlas_cell_size"] ** 2
    estimated_memory_bytes = (points * 3 * 8 + texture_pixels * 4 +
                              atlas_pixels * 4 + sheet_pixels * 4 +
                              triangles * 64 + 16 * 1024 * 1024)
    estimated_published_bytes = sheet_pixels * 4
    project_bytes = (points * 24 + max_bones * 256 + keys * 32 +
                     64 * 1024)
    for export in recipe.exports:
        fmt = str(export.format).lower()
        if fmt == "obj":
            estimated_published_bytes += triangles * 128 + atlas_pixels * 8
        elif fmt in {"glb", "gltf"}:
            estimated_published_bytes += triangles * 64 + atlas_pixels * 4
        elif fmt == "am3d":
            estimated_published_bytes += project_bytes

    return {
        "objects": len(recipe.objects),
        "objects_with_geometry": geometry_objects,
        "patches": patches,
        "control_points": points,
        "authored_points": authored_points,
        "bones_per_skeleton": max_bones,
        "copied_bones": copied_bones,
        "actions": len(recipe.actions),
        "channels": channels,
        "keys": keys,
        "materials": len(recipe.materials),
        "graph_nodes_per_material": graph_nodes,
        "graph_nodes": graph_node_total,
        "max_subdivision": max_subdivision,
        "triangles_at_32x32_per_patch": triangles,
        "texture_pixels": texture_pixels,
        "sheet_cells": sheet_cells,
        "max_sheet_cell_size": max_sheet_cell_size,
        "sheet_pixels": sheet_pixels,
        "atlas_cells": atlas_cells,
        "atlas_pixels": atlas_pixels,
        "estimated_memory_bytes": estimated_memory_bytes,
        "estimated_published_bytes": estimated_published_bytes,
    }


def resource_limit_issues(estimate: dict) -> list[dict]:
    """Return path-addressed AI-mode limit violations."""
    checks = [
        ("objects", "objects", "recipe.objects"),
        ("patches", "patches", "recipe.objects"),
        ("bones_per_skeleton", "bones_per_skeleton", "recipe.objects[].bones"),
        ("copied_bones", "copied_bones", "recipe.objects[].params.skeleton"),
        ("actions", "actions", "recipe.actions"),
        ("channels", "channels", "recipe.actions[].channels"),
        ("keys", "keys", "recipe.actions[].channels[].keys"),
        ("authored_points", "authored_points", "recipe.objects[].splines"),
        ("max_subdivision", "subdivisions", "recipe.objects[].params"),
        ("materials", "materials", "recipe.materials"),
        ("graph_nodes_per_material", "graph_nodes_per_material", "recipe.materials[].graph"),
        ("triangles_at_32x32_per_patch", "triangles", "recipe.objects"),
        ("sheet_cells", "sheet_cells", "recipe.exports[].params"),
        ("max_sheet_cell_size", "sheet_cell_size", "recipe.exports[].params"),
        ("sheet_pixels", "sheet_pixels", "recipe.exports[].params"),
        ("texture_pixels", "texture_pixels", "recipe.materials"),
        ("atlas_pixels", "atlas_pixels", "recipe.materials"),
        ("estimated_memory_bytes", "memory_bytes", "recipe"),
        ("estimated_published_bytes", "published_bytes", "recipe.exports"),
    ]
    issues = []
    for metric, limit_key, path in checks:
        actual = estimate.get(metric, 0)
        ceiling = LIMITS[limit_key]
        if actual > ceiling:
            issues.append({
                "code": "resource_limit",
                "stage": "resource",
                "path": path,
                "message": f"estimated {metric} is {actual}; AI-mode limit is {ceiling}",
                "hint": "Reduce the recipe size or per-item parameters before execution.",
            })
    return issues


def built_scene_limit_issues(session, recipe) -> list[dict]:
    """Recount constructed objects and actions as a backstop to estimates."""
    project = session.project
    patches = sum(len(obj.patches) for obj in project.objects.values())
    control_points = sum(
        int(patch.interior.shape[0] * patch.interior.shape[1])
        for obj in project.objects.values()
        for patch in obj.patches
        if getattr(patch, "interior", None) is not None)
    bones_per_skeleton = max(
        (len(skeleton) for skeleton in project.skeletons.values()), default=0)
    copied_bones = 0
    for obj in recipe.objects:
        skeleton_name = (obj.params.get("skeleton")
                         if isinstance(obj.params, dict) else None)
        if skeleton_name:
            copied_bones += len(project.skeletons.get(skeleton_name, {}))
    channels = sum(len(action.channels) for action in session.actions.values())
    keys = sum(len(channel.keys) for action in session.actions.values()
               for channel in action.channels)
    graph_nodes = max((len(material.graph)
                       for material in project.materials.values()), default=0)
    actual = {
        "objects": (len(project.objects), "objects", "recipe.objects"),
        "patches": (patches, "patches", "recipe.objects"),
        "bones_per_skeleton": (bones_per_skeleton, "bones_per_skeleton",
                                "recipe.objects[].bones"),
        "copied_bones": (copied_bones, "copied_bones",
                         "recipe.objects[].params.skeleton"),
        "actions": (len(session.actions), "actions", "recipe.actions"),
        "channels": (channels, "channels", "recipe.actions[].channels"),
        "keys": (keys, "keys", "recipe.actions[].channels[].keys"),
        "materials": (len(project.materials), "materials", "recipe.materials"),
        "graph_nodes_per_material": (graph_nodes, "graph_nodes_per_material",
                                     "recipe.materials[].graph"),
        "triangles": (patches * 32 * 32 * 2, "triangles", "recipe.objects"),
        "control_net_bytes": (control_points * 3 * 8, "memory_bytes",
                              "recipe.objects"),
    }
    issues = []
    for metric, (actual_value, limit_key, path) in actual.items():
        ceiling = LIMITS[limit_key]
        if actual_value > ceiling:
            issues.append({
                "code": "resource_limit",
                "stage": "resource",
                "path": path,
                "message": f"built {metric} is {actual_value}; AI-mode limit is {ceiling}",
                "hint": "Reduce the recipe size or per-item parameters and retry.",
            })
    return issues
