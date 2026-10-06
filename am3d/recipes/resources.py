"""Cheap, allocation-free recipe resource estimates used by preflight."""

from __future__ import annotations

from .capabilities import CAPABILITIES


def estimate_recipe_resources(recipe, *, tessellation=32) -> dict:
    """Estimate control points and worst-case downstream raster work.

    This is deliberately conservative and does not build geometry. M1b adds
    rejection against the project limits and verifies the estimate against
    actual worker output.
    """
    points = patches = geometry_objects = sheet_pixels = texture_pixels = 0
    for obj in recipe.objects:
        p = obj.params or {}
        if obj.primitive:
            cap = CAPABILITIES.get(("primitive", obj.primitive))
            if cap is not None:
                values = {key: spec.default for key, spec in cap.params.items()
                          if spec.has_default}
                values.update({k: v for k, v in p.items()
                               if k in cap.params})
                name = obj.primitive
                if name in {"sphere", "cylinder", "cone"}:
                    sections = values.get("sections", 16)
                    rings = values.get("rings", 8)
                    count = (sections + 1) * (rings + 2)
                    patches += 1
                elif name == "torus":
                    count = ((values.get("major_sections", 24) + 1) *
                             (values.get("minor_sections", 12) + 1))
                    patches += 1
                elif name == "box":
                    n = values.get("n", 4)
                    count = 6 * n * n
                    patches += 6
                elif name == "plane":
                    n = values.get("n", 4)
                    count = n * n
                    patches += 1
                elif name == "lathe":
                    profile = values.get("profile", ())
                    count = (values.get("sections", 24) + 1) * (len(profile) + 1)
                    patches += 1
                elif name == "extrude":
                    profile = values.get("profile", ())
                    count = values.get("rings", 4) * len(profile)
                    patches += 1
                else:
                    count = 0
                points += count
                geometry_objects += int(count > 0)
        points += sum(len(spline.points) for spline in obj.splines)
        if obj.splines:
            geometry_objects += 1
            patches += len(obj.splines)

    triangles = patches * int(tessellation) * int(tessellation) * 2
    for export in recipe.exports:
        fmt = export.format
        p = export.params or {}
        if fmt in ("spritesheet", "toon_sheet"):
            sheets = int(p.get("views", 8)) * int(p.get("size", 256)) ** 2
            sheet_pixels += sheets * max(geometry_objects, 1)
        elif fmt == "animation_sheet":
            sheet_pixels += (int(p.get("frames", 8)) *
                             int(p.get("size", 256)) ** 2)
    for material in recipe.materials:
        if material.pattern or material.graph:
            size = 256
            if material.pattern and material.params:
                size = int(material.params.get("size", size))
            elif material.graph:
                for node in material.graph:
                    if isinstance(node, dict):
                        size = max(size, int(node.get("params", {}).get("size", size)))
            texture_pixels += size * size
    return {
        "objects_with_geometry": geometry_objects,
        "patches": patches,
        "control_points": points,
        "triangles_at_32x32_per_patch": triangles,
        "texture_pixels": texture_pixels,
        "sheet_pixels": sheet_pixels,
    }
