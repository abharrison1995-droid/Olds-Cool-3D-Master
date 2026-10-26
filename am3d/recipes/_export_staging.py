"""Format-specific recipe writers into a private staging directory.

The executor owns path authorization, output budgets, duplicate destinations,
publication and session commit. These writers only accumulate staged artifacts.
"""
from __future__ import annotations

import os

from .schema import RecipeValidationError, normalize_export_format
from am3d.core.paths import sanitize_filename_component
from ._export_paths import (_with_ext, _artifact_object_name,
                            _artifact_object_names, _named_sheet_path)


class ExportStager:
    def __init__(self, session, recipe, result, stage_dir, atlases,
                 safe_artifact_names):
        self.session = session
        self.recipe = recipe
        self.result = result
        self.stage_dir = stage_dir
        self.atlases = atlases
        self.safe_artifact_names = safe_artifact_names
        self.items = []
        # Private to this export transaction; never shared with an editor or
        # another recipe. Frame evaluation below deliberately bypasses it.
        self._static_scene = None

    def stage_export(self, index, spec):
        fmt = normalize_export_format(spec.format)
        if fmt == "am3d":
            self._stage_native(index, spec)
            # Saving synchronizes project/session animation state. Do not
            # assume that a previously evaluated scene remains valid.
            self._static_scene = None
            return
        from am3d.core.scene import scene_material_colors, scene_patch_material_colors
        if self._static_scene is None:
            self._static_scene = self.session.evaluate_scene(
                apply_transforms=True, visible_only=True)
        scene = self._static_scene
        meshes = {name: mesh for name, mesh in scene.meshes.items() if len(mesh.vertices)}
        mat_colors = scene_material_colors(scene)
        patch_colors = scene_patch_material_colors(scene)
        if fmt == "obj":
            self._stage_obj(index, spec, meshes, mat_colors, patch_colors)
        elif fmt == "glb":
            self._stage_glb(index, spec, meshes, mat_colors, patch_colors)
        elif fmt in ("spritesheet", "toon_sheet"):
            self._stage_orbit_sheet(index, spec, meshes)
        elif fmt == "animation_sheet":
            self._stage_animation_sheet(index, spec, meshes)
        else:
            self.result.add_error(
                f"export format {fmt!r} passed validation but has no "
                f"writer; no file was produced for {spec.path!r}",
                code="unsupported_export_format", stage="schema",
                path=f"recipe.exports[{index}].format")

    def _stage_native(self, index, spec):
        res = self.result
        stage_dir = self.stage_dir
        staged_items = self.items
        base = spec.path
        fmt = normalize_export_format(spec.format)
        final_path = _with_ext(base, ".am3d")
        staged_path = os.path.join(stage_dir, f"export_{index}.am3d")
        try:
            self.session.save_project(staged_path)
            staged_items.append((staged_path, final_path, fmt, {"format": "am3d", "version": 2}))
        except (MemoryError, RecipeValidationError):
            raise
        except Exception as exc:
            res.add_error(
                f"failed to export .am3d project: {exc}",
                code="export_error", stage="write",
                path=f"recipe.exports[{index}].path",
                hint="Check that the project state is valid.")
        return


    def _stage_obj(self, index, spec, meshes, mat_colors, patch_colors):
        recipe = self.recipe
        res = self.result
        stage_dir = self.stage_dir
        staged_items = self.items
        base = spec.path
        fmt = normalize_export_format(spec.format)
        atlases = self.atlases
        from am3d.export.obj import write_obj
        final_path = _with_ext(base, ".obj")
        # Named after the final basename (not "export_{index}"):
        # write_obj derives the sidecar filename and the OBJ's
        # `mtllib` reference from this path's stem, and both
        # must match what actually lands next to final_path.
        obj_stage_dir = os.path.join(stage_dir, f"export_{index}")
        os.makedirs(obj_stage_dir, exist_ok=True)
        staged_path = os.path.join(
            obj_stage_dir, os.path.basename(final_path))
        # Baked atlases carry pattern/texture appearance into
        # the export instead of collapsing to a flat colour
        # (finding MAT-01). Only objects actually in this export.
        object_ids = _artifact_object_names(
            (spec.name for spec in recipe.objects), meshes,
            self.safe_artifact_names)
        export_meshes = {object_ids[name]: mesh
                         for name, mesh in meshes.items()}
        export_materials = ({object_ids[name]: color
                             for name, color in mat_colors.items()}
                            if mat_colors else None)
        export_patch_materials = (
            {object_ids[name]: patch_map
             for name, patch_map in patch_colors.items()}
            if patch_colors else None)
        obj_textures = {object_ids[n]: a for n, a in atlases.items()
                        if n in meshes}
        try:
            write_obj(staged_path, export_meshes,
                      materials=export_materials,
                      patch_materials=export_patch_materials,
                      textures=obj_textures or None)
            staged_items.append((staged_path, final_path, fmt, {"format": "obj", "mesh_count": len(meshes)}))
            if mat_colors or patch_colors or obj_textures:
                mtl_staged = os.path.splitext(staged_path)[0] + ".mtl"
                mtl_final = os.path.splitext(final_path)[0] + ".mtl"
                staged_items.append((mtl_staged, mtl_final, "mtl", {"format": "mtl", "sidecar_of": final_path}))
            # The PNG sidecars the MTL's map_Kd points at must
            # be published too, or the OBJ lands referencing
            # images that are not there.
            from am3d.export.textures import texture_filename
            stem = os.path.splitext(os.path.basename(final_path))[0]
            for obj_name in obj_textures:
                img = texture_filename(stem, obj_name)
                staged_items.append((
                    os.path.join(obj_stage_dir, img),
                    os.path.join(os.path.dirname(final_path), img),
                    "png",
                    {"format": "png", "sidecar_of": final_path}))
        except (MemoryError, RecipeValidationError):
            raise
        except Exception as exc:
            res.add_error(
                f"failed to write OBJ: {exc}",
                code="export_error", stage="write",
                path=f"recipe.exports[{index}].path")


    def _stage_glb(self, index, spec, meshes, mat_colors, patch_colors):
        recipe = self.recipe
        res = self.result
        stage_dir = self.stage_dir
        staged_items = self.items
        base = spec.path
        fmt = normalize_export_format(spec.format)
        atlases = self.atlases
        from am3d.export.gltf import write_glb
        final_path = _with_ext(base, ".glb")
        staged_path = os.path.join(stage_dir, f"export_{index}.glb")
        try:
            object_ids = _artifact_object_names(
                (spec.name for spec in recipe.objects), meshes,
                self.safe_artifact_names)
            export_meshes = {object_ids[name]: mesh
                             for name, mesh in meshes.items()}
            export_materials = ({object_ids[name]: color
                                 for name, color in mat_colors.items()}
                                if mat_colors else None)
            export_patch_materials = (
                {object_ids[name]: patch_map
                 for name, patch_map in patch_colors.items()}
                if patch_colors else None)
            write_glb(staged_path, export_meshes,
                      materials=export_materials,
                      patch_materials=export_patch_materials,
                      textures={object_ids[n]: a for n, a in atlases.items()
                                if n in meshes} or None)
            staged_items.append((staged_path, final_path, fmt, {"format": "glb", "mesh_count": len(meshes)}))
        except (MemoryError, RecipeValidationError):
            raise
        except Exception as exc:
            res.add_error(
                f"failed to write GLB: {exc}",
                code="export_error", stage="write",
                path=f"recipe.exports[{index}].path")


    def _stage_orbit_sheet(self, index, spec, meshes):
        res = self.result
        stage_dir = self.stage_dir
        staged_items = self.items
        base = spec.path
        fmt = normalize_export_format(spec.format)
        from am3d.renderer.sprite import save_sprite_sheet
        if not meshes:
            res.add_error(
                f"cannot export {fmt!r}: no renderable geometry found in recipe",
                code="missing_geometry", stage="write",
                path=f"recipe.exports[{index}].format",
                hint="Add geometry (primitives or splines) to objects before exporting sheets.")
            return
        p = dict(spec.params)
        for object_index, (oname, mesh) in enumerate(meshes.items()):
            artifact_name = _artifact_object_name(
                oname, object_index, True) if self.safe_artifact_names else (
                    sanitize_filename_component(oname))
            final_path = _named_sheet_path(base, artifact_name)
            staged_path = os.path.join(stage_dir,
                                       f"export_{index}_{artifact_name}.png")
            views = int(p.get("views", 8))
            size = int(p.get("size", 256))
            common = {
                "views": views,
                "size": size,
                "color": tuple(p.get("color", (0.72, 0.74, 0.82))),
                "silhouette": bool(p.get("silhouette", False)),
            }
            meta = {"format": fmt, "views": views, "size": size, "object": oname}
            try:
                if fmt == "spritesheet":
                    save_sprite_sheet(mesh, staged_path, **common)
                else:
                    from am3d.renderer.toon import save_toon_sheet
                    save_toon_sheet(mesh, staged_path,
                                    views=common["views"],
                                    size=common["size"],
                                    color=tuple(p.get("color", (0.85, 0.78, 0.55))),
                                    bands=int(p.get("bands", 4)),
                                    ink=bool(p.get("ink", True)))
                staged_items.append((staged_path, final_path, fmt, meta))
            except (MemoryError, RecipeValidationError):
                raise
            except Exception as exc:
                res.add_error(
                    f"failed to generate {fmt} for {oname!r}: {exc}",
                    code="render_error", stage="write",
                    path=f"recipe.exports[{index}].path")
        return


    def _stage_animation_sheet(self, index, spec, meshes):
        res = self.result
        stage_dir = self.stage_dir
        staged_items = self.items
        base = spec.path
        fmt = normalize_export_format(spec.format)
        if not meshes:
            res.add_error(
                f"cannot export 'animation_sheet': no renderable geometry",
                code="missing_geometry", stage="write",
                path=f"recipe.exports[{index}].format",
                hint="Add geometry (primitives or splines) to objects.")
            return
        p = dict(spec.params)
        action_name = p.get("action") or self.session.active_action
        n_frames = int(p.get("frames", 8))
        size = int(p.get("size", 256))
        color = tuple(p.get("color", (0.72, 0.74, 0.82)))
        # Determine time range from action duration or explicit start/end
        duration = 1.0
        if action_name and action_name in self.session.actions:
            duration = self.session.actions[action_name].duration or 1.0
        t_start = float(p.get("start", 0.0))
        t_end = float(p.get("end", duration))
        from am3d.renderer.sprite import render_scene
        import math as _math
        cols = int(p.get("columns", n_frames))
        rows = int(_math.ceil(n_frames / cols))
        try:
            import numpy as _np
            sheet = _np.zeros((rows * size, cols * size, 4), dtype=_np.uint8)
            for fi in range(n_frames):
                t = t_start + (t_end - t_start) * fi / max(n_frames - 1, 1)
                frame_scene = self.session.evaluate_scene(
                    action_name=action_name, time=t,
                    apply_transforms=True, visible_only=True)
                # Merge every visible mesh through one shared
                # z-buffer (render_scene) rather than rendering
                # each independently and taking a per-pixel max â€”
                # the max-blend composite lost real occlusion:
                # a nearer but darker surface could be overwritten
                # by a farther but brighter one.
                live_meshes = {n: m for n, m in frame_scene.meshes.items()
                              if len(m.vertices)}
                frame_img = render_scene(live_meshes, size=size, color=color)
                r_idx, c_idx = divmod(fi, cols)
                sheet[r_idx * size:(r_idx + 1) * size,
                      c_idx * size:(c_idx + 1) * size] = (
                    _np.clip(frame_img, 0.0, 1.0) * 255).astype(_np.uint8)

            from PIL import Image as _PIL_Image
            pil_sheet = _PIL_Image.fromarray(sheet, "RGBA")
            # One composited whole-scene sheet per export spec â€”
            # unlike spritesheet/toon_sheet (per-object orbit
            # views), an animation sheet is a single character's
            # posed frames over time, so all visible meshes are
            # flattened into each frame rather than split by name.
            final_path = _with_ext(base, ".png")
            staged_path = os.path.join(stage_dir, f"export_{index}_anim.png")
            pil_sheet.save(staged_path, format="PNG")
            meta = {"format": "animation_sheet", "frames": n_frames,
                    "columns": cols, "rows": rows, "size": size,
                    "action": action_name, "start": t_start, "end": t_end}
            staged_items.append((staged_path, final_path, fmt, meta))
        except (MemoryError, RecipeValidationError):
            raise
        except Exception as exc:
            res.add_error(
                f"failed to render animation_sheet: {exc}",
                code="render_error", stage="write",
                path=f"recipe.exports[{index}].path")
        return


    def stage_atlases(self, atlas_dir):
        recipe = self.recipe
        res = self.result
        stage_dir = self.stage_dir
        staged_items = self.items
        atlases = self.atlases
        # Save any baked atlases alongside exports
        if atlases and atlas_dir:
            from am3d.renderer.materials import save_image
            object_indices = {spec.name: object_index
                              for object_index, spec in enumerate(recipe.objects)}
            for oname, atlas in atlases.items():
                artifact_name = _artifact_object_name(
                    oname, object_indices.get(oname, len(object_indices)),
                    self.safe_artifact_names)
                final_path = _with_ext(
                    os.path.join(atlas_dir, f"{artifact_name}_atlas"), ".png")
                staged_path = os.path.join(stage_dir, f"atlas_{artifact_name}.png")
                if hasattr(atlas, "shape") and len(atlas.shape) >= 2:
                    height, width = int(atlas.shape[0]), int(atlas.shape[1])
                else:
                    width = int(getattr(atlas, "width", 256))
                    height = int(getattr(atlas, "height", 256))
                meta = {"object": oname, "width": width, "height": height}
                try:
                    save_image(atlas, staged_path)
                    staged_items.append((staged_path, final_path, "atlas", meta))
                except (MemoryError, RecipeValidationError):
                    raise
                except Exception as exc:
                    res.add_error(
                        f"atlas for {oname!r} not saved: {exc}",
                        code="write_error", stage="write",
                        path="recipe.materials")
