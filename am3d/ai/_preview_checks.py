"""Material-aware whole-scene software previews and visibility measurements."""
from __future__ import annotations

import numpy as np
from ._check_report import _check

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


def _check_preview(report, root, scene):
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
