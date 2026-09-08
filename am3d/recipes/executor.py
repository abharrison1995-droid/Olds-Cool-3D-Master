"""Recipe execution: JSON in -> geometry, rigs, actions and files out.

The single entry point an LLM pipeline needs::

    result = RecipeExecutor().execute(recipe_dict_or_Recipe)

Recipes are validated first (:func:`am3d.recipes.schema.validate_recipe`),
then applied to a live :class:`~am3d.core.script.Session`, then exported.
"""

from __future__ import annotations

import os
import copy
import shutil
import tempfile
from dataclasses import dataclass, field

import numpy as np

from .animation import generate_action
from .primitives import build_primitive
from .schema import (Recipe, RecipeValidationError, recipe_from_dict,
                     validate_recipe)


@dataclass
class ExecutionResult:
    """What happened during one recipe run."""

    ok: bool = True
    objects: list = field(default_factory=list)
    materials: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    exports: list = field(default_factory=list)     # (format, path)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    error_records: list = field(default_factory=list)
    manifest: list = field(default_factory=list)
    partial_publication: bool = False

    def add_error(self, message: str, *, code: str = "execution_error",
                  stage: str = "runtime", path: str = "recipe",
                  hint: str | None = None) -> None:
        self.ok = False
        self.errors.append(message)
        record = {
            "code": code,
            "stage": stage,
            "path": path,
            "message": message,
        }
        if hint:
            record["hint"] = hint
        self.error_records.append(record)
        if self.manifest:
            self.partial_publication = True

    def add_artifact(self, requested_format: str, path: str, *,
                     status: str = "written", metadata: dict | None = None):
        entry = {
            "format": requested_format,
            "path": os.path.abspath(os.fspath(path)),
            "status": status,
        }
        if status == "written":
            try:
                entry["size_bytes"] = os.path.getsize(path)
            except OSError:
                entry["size_bytes"] = None
        if metadata:
            entry.update(metadata)
        self.manifest.append(entry)


def _ensure_parent(path: str) -> str:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path


def _with_ext(path: str, ext: str) -> str:
    root, current = os.path.splitext(path)
    return path if current.lower() == ext.lower() else root + ext


def _atlas_outdir(export_specs) -> str:
    """Where to write baked atlases: the first export's directory."""
    for spec in export_specs:
        parent = os.path.dirname(spec.path)
        if parent:
            return parent
    return "." if export_specs else ""


def _apply_object_transform(mesh, transform):
    """Bake an Object3D's 4x4 transform into its tessellated mesh.

    OBJ/glB exports and sprite renders all consume the same meshes, so the
    object's placement must live in world-space vertex data (for glTF this
    is equivalent to putting the transform on the node).
    """
    from am3d.core.mathutil import transform_mesh_geometry
    v, n, idx = transform_mesh_geometry(mesh.vertices, mesh.normals, mesh.indices, transform)
    mesh.vertices = v
    if n is not None:
        mesh.normals = n
    if idx is not None:
        mesh.indices = idx
    return mesh


def _collect_material_colors(session) -> dict:
    """Build ``{object_name: (r, g, b, a)}`` from session material bindings.

    Returns a dict of flat colours for every object that has a bound material
    with an explicit colour.  Objects without a material binding are omitted.
    """
    project = session.project
    result = {}
    for obj_name, obj in project.objects.items():
        mat_name = getattr(obj, "material", None)
        if not mat_name:
            continue
        mat = project.materials.get(mat_name)
        if mat is None:
            continue
        color = getattr(mat, "color", None)
        if color is not None and len(color) >= 3:
            r, g, b = float(color[0]), float(color[1]), float(color[2])
            a = float(color[3]) if len(color) >= 4 else 1.0
            result[obj_name] = (r, g, b, a)
    return result


class RecipeExecutor:
    """Applies a validated :class:`Recipe` to a scripting session."""

    def __init__(self, session=None, *, output_root: str | None = None,
                 base_dir: str | None = None):
        if session is None:
            from am3d.core.script import Session
            session = Session()
        self.session = session
        self.output_root = (os.path.abspath(os.fspath(output_root))
                            if output_root is not None else None)
        self.base_dir = (os.path.abspath(os.fspath(base_dir))
                         if base_dir is not None else None)

    @staticmethod
    def _commit_session(target, candidate) -> None:
        """Publish a successful candidate without replacing the caller object."""
        target.project = candidate.project
        target.actions = candidate.actions
        target.poses = candidate.poses
        target.pose_offsets = candidate.pose_offsets
        target.posed_transforms = candidate.posed_transforms
        target.active_action = candidate.active_action
        target.action_assignments = candidate.action_assignments

    def _resolve_output_path(self, path: str, index: int = 0) -> str:
        raw = os.fspath(path)
        drive, _ = os.path.splitdrive(raw)
        if self.output_root is not None:
            if drive:
                raise RecipeValidationError(
                    "output_path_escape",
                    f"export path {raw!r} must not specify a drive letter when --out is supplied",
                    path=f"recipe.exports[{index}].path",
                    hint="Use a relative artifact name below the output root.",
                    stage="resource")
            if os.path.isabs(raw):
                raise RecipeValidationError(
                    "output_path_escape",
                    "export path must be relative when --out is supplied",
                    path=f"recipe.exports[{index}].path",
                    hint="Use a relative artifact name below the output root.",
                    stage="resource")
            root = os.path.realpath(os.path.abspath(self.output_root))
            candidate = os.path.realpath(os.path.abspath(os.path.join(root, raw)))
            try:
                common = os.path.commonpath((root, candidate))
            except ValueError as exc:
                raise RecipeValidationError(
                    "output_path_escape",
                    f"export path {raw!r} escapes the output root: {exc}",
                    path=f"recipe.exports[{index}].path",
                    hint="Use a relative path within the output root.",
                    stage="resource") from exc
            if candidate == root or common != root:
                raise RecipeValidationError(
                    "output_path_escape",
                    f"export path {raw!r} escapes the requested output root",
                    path=f"recipe.exports[{index}].path",
                    hint="Remove '..' segments or provide a child path within the output root.",
                    stage="resource")
            return candidate
        if self.base_dir is not None and not os.path.isabs(raw):
            return os.path.realpath(os.path.abspath(os.path.join(self.base_dir, raw)))
        return raw

    def _prepare_output_paths(self, recipe: Recipe) -> None:
        """Resolve output paths before any session or filesystem mutation."""
        for index, spec in enumerate(recipe.exports):
            try:
                spec.path = self._resolve_output_path(spec.path, index)
            except TypeError as exc:
                raise RecipeValidationError(
                    "invalid_type", "export path must be a string or path-like value",
                    path=f"recipe.exports[{index}].path") from exc

    @staticmethod
    def _record_artifact(res: ExecutionResult, fmt: str, path: str,
                         metadata: dict | None = None) -> None:
        if os.path.isfile(path):
            res.add_artifact(fmt, path, metadata=metadata)
        else:
            res.add_artifact(fmt, path, status="missing", metadata=metadata)
            res.add_error(
                f"export writer did not produce {path!r}",
                code="missing_artifact", stage="write",
                path="recipe.exports[].path",
                hint="Inspect the writer error and retry the export.")

    def execute(self, recipe) -> ExecutionResult:
        result = ExecutionResult()
        original = self.session
        try:
            if not isinstance(recipe, Recipe):
                recipe = recipe_from_dict(recipe)
            else:
                recipe = copy.deepcopy(recipe)

            problems = validate_recipe(recipe)
            if problems:
                for problem in problems:
                    if hasattr(problem, "to_record"):
                        rec = problem.to_record()
                        result.add_error(rec["message"], code=rec["code"],
                                         stage=rec["stage"], path=rec["path"],
                                         hint=rec.get("hint"))
                    else:
                        result.add_error(str(problem), code="validation_error",
                                         stage="schema")
                return result

            self._prepare_output_paths(recipe)
            from am3d.core.script import Session
            candidate = Session()
            self.session = candidate
            candidate.new_project(recipe.name)
            self._build_objects(recipe, result)
            self._build_materials(recipe, result)
            self._build_actions(recipe, result)
            if not result.ok:
                return result
            self._run_exports(recipe, result)
            if result.ok:
                self._commit_session(original, candidate)
        except Exception as exc:                      # surfaced to the LLM
            if isinstance(exc, RecipeValidationError):
                result.add_error(str(exc), code=exc.code, stage=exc.stage,
                                 path=exc.path, hint=exc.hint)
            elif isinstance(exc, FileNotFoundError):
                target_file = exc.filename or str(exc)
                result.add_error(f"resource file not found: {target_file}",
                                 code="missing_resource", stage="resource",
                                 path="recipe.materials",
                                 hint="Check that all texture or image resource paths exist relative to base_dir or project root.")
            else:
                result.add_error(f"{type(exc).__name__}: {exc}")
        finally:
            self.session = original
        return result

    # -- phases --------------------------------------------------------------
    def _build_objects(self, recipe: Recipe, res: ExecutionResult) -> None:
        from am3d.core.project import Patch
        from am3d.core.rigging import auto_weight_object

        s = self.session
        for spec in recipe.objects:
            s.create_object(spec.name)
            obj = s.get_object(spec.name)

            if getattr(spec, "transform", None):
                t_arr = np.asarray(spec.transform, dtype=np.float64)
                if t_arr.shape == (4, 4) or t_arr.size == 16:
                    obj.transform = t_arr.reshape(4, 4)
                elif t_arr.size == 3:
                    m = np.eye(4, dtype=np.float64)
                    m[:3, 3] = t_arr.reshape(3)
                    obj.transform = m

            prim_params = dict(spec.params) if isinstance(spec.params, dict) else {}
            prim_params.pop("skeleton", None)
            prim_params.pop("auto_weights", None)

            built = (build_primitive(spec.primitive, prim_params)
                     if spec.primitive else {"patches": [], "splines": []})

            for pname, net, du, dv in built["patches"]:
                obj.patches.append(Patch(name=f"{spec.name}_{pname}",
                                         splines=[], interior=net))

            for idx, sr in enumerate(spec.splines):
                name = sr.name if sr.name != "spline" else f"spline_{idx}"
                s.add_spline(spec.name, sr.points, degree=sr.degree,
                             name=name, closed=sr.closed)

            has_explicit_weights = False
            for br in spec.bones:
                bone = s.add_bone(spec.name, br.name, br.head, br.tail,
                                  parent=br.parent)
                raw_w = getattr(br, "cp_weights", None) or getattr(br, "weights", None)
                if raw_w:
                    bone.cp_weights = {int(k): float(v) for k, v in raw_w.items()}
                    has_explicit_weights = True

            bones = s.get_bones(spec.name)
            has_geometry = bool(obj.patches or obj.splines)
            auto_w = spec.params.get("auto_weights") if isinstance(spec.params, dict) else False
            if bones and has_geometry and (not has_explicit_weights or auto_w):
                auto_weight_object(obj, bones)

            res.objects.append(spec.name)

        # Pass 2: resolve cross-object skeleton references
        for idx, spec in enumerate(recipe.objects):
            skel_ref = spec.params.get("skeleton") if isinstance(spec.params, dict) else None
            if not skel_ref:
                continue
            obj = s.get_object(spec.name)
            bones = s.get_bones(spec.name)
            if not bones:
                if skel_ref not in s.project.skeletons:
                    res.add_error(
                        f"object {spec.name!r} references nonexistent skeleton {skel_ref!r}",
                        code="missing_reference", stage="schema",
                        path=f"recipe.objects[{idx}].params.skeleton",
                        hint="The referenced skeleton object must exist in recipe.objects."
                    )
                    continue
                ref_bones = s.get_bones(skel_ref)
                for rb in ref_bones:
                    s.add_bone(spec.name, rb.name, rb.head, rb.tail, parent=rb.parent)
                new_bones = s.get_bones(spec.name)
                auto_weight_object(obj, new_bones)

    def _build_materials(self, recipe: Recipe, res: ExecutionResult) -> None:
        from am3d.core.serializer import resolve_resource_path
        s = self.session
        for mat in recipe.materials:
            material = s.create_material(mat.name, color=tuple(mat.color))
            material.roughness = float(mat.roughness)
            material.metalness = float(mat.metalness)
            tex_path = mat.texture
            if tex_path:
                resolved = resolve_resource_path(tex_path, self.base_dir)
                if not os.path.exists(resolved):
                    raise FileNotFoundError(tex_path)
            material.texture = tex_path
            material.pattern = mat.pattern
            material.params = dict(mat.params or {})
            material.graph = list(mat.graph or [])
            material.objects = list(mat.objects or [])
            if mat.objects:
                for oname in mat.objects:
                    if oname in s.project.objects:
                        obj = s.project.objects[oname]
                        obj.material = material.name
            res.materials.append(mat.name)

    def _build_actions(self, recipe: Recipe, res: ExecutionResult) -> None:
        s = self.session
        for index, spec in enumerate(recipe.actions):
            bones = s.get_bones(spec.character) if spec.character else []

            if spec.kind == "custom":
                act = s.create_action(spec.name, duration=spec.duration)
                for cr in spec.channels:
                    ch = act.add_channel(cr.bone, cr.property)
                    for kr in cr.keys:
                        ch.add_key(kr.time, kr.value, kr.interp)
                if bones:
                    act.signature = tuple(
                        f"{b.name}->{b.parent or 'root'}" for b in bones)
            elif spec.kind == "retarget":
                if not bones or not spec.source_action:
                    res.add_error(
                        f"action {spec.name!r}: retarget needs character + "
                        "source_action; action not created",
                        code="action_precondition", stage="schema",
                        path=f"recipe.actions[{index}].character")
                    continue
                src = s.actions.get(spec.source_action)
                if src is None:
                    res.add_error(
                        f"action {spec.name!r}: source action "
                        f"{spec.source_action!r} not found; action not "
                        f"created", code="missing_reference", stage="schema",
                        path=f"recipe.actions[{index}].source_action")
                    continue
                from am3d.core.retarget import retarget_action
                src_char = spec.params.get("source_character") if isinstance(spec.params, dict) else None
                if not src_char:
                    for c_name, a_name in s.action_assignments.items():
                        if a_name == spec.source_action and c_name in s.project.skeletons:
                            src_char = c_name
                            break
                source_bones = s.get_bones(src_char) if src_char else None
                if not source_bones:
                    src_bone_names = {ch.bone for ch in src.channels}
                    for skel_name, skel in s.project.skeletons.items():
                        if skel_name != spec.character and src_bone_names.issubset(set(skel.keys())):
                            source_bones = list(skel.values())
                            break
                if not source_bones:
                    source_bones = bones

                _explicit_mapping = spec.params.get("mapping") if isinstance(spec.params, dict) else None
                act = retarget_action(src, source_bones, bones,
                                      mapping=dict(_explicit_mapping) if _explicit_mapping else None,
                                      default_duration=spec.duration)
                act.name = spec.name
                s.actions[act.name] = act
            else:
                if not bones:
                    res.add_error(
                        f"action {spec.name!r}: procedural kind "
                        f"{spec.kind!r} needs a character with bones; "
                        f"action not created", code="action_precondition",
                        stage="schema", path=f"recipe.actions[{index}].character")
                    continue
                act = generate_action(spec.kind, bones, name=spec.name,
                                      duration=spec.duration,
                                      **dict(spec.params))
                s.actions[act.name] = act

            if spec.character and bones:
                s.assign_action(act.name, spec.character)
            if s.active_action is None:
                s.set_active_action(act.name)
            res.actions.append(act.name)

    def _bake_atlases(self, recipe):
        """Per-object baked texture atlases from the recipe materials.

        Returns ``{object_name: atlas}`` for every geometry object that has
        patches; objects without a matching material get no entry.
        """
        from .schema import Recipe, recipe_from_dict
        from am3d.renderer.materials import bake_atlas
        from am3d.renderer.tessellate import tessellate_object

        if not isinstance(recipe, Recipe):
            recipe = recipe_from_dict(recipe)

        session_mats = list(self.session.project.materials.values())
        textured = [m for m in session_mats
                    if getattr(m, "pattern", None) or getattr(m, "texture", None) or getattr(m, "graph", None)]
        textured_by_name = {m.name: m for m in textured}
        if not textured:
            return {}

        def matches(mat, obj_name):
            objs = getattr(mat, "objects", None)
            return not objs or obj_name in objs

        atlases = {}
        for spec in recipe.objects:
            mats_for_obj = {m.name: m for m in textured
                            if matches(m, spec.name)}
            obj = self.session.get_object(spec.name)
            if not obj or not obj.patches:
                continue

            active_patches = [p for p in obj.patches if p.interior is not None]
            if not active_patches:
                continue

            obj_mat_name = getattr(obj, "material", None)
            has_textured_patch = any(
                getattr(p, "material", None) in textured_by_name for p in active_patches)
            has_obj_mat = obj_mat_name in textured_by_name
            if not (has_textured_patch or has_obj_mat or mats_for_obj):
                continue

            fallback = (
                textured_by_name.get(obj_mat_name)
                or (next(iter(mats_for_obj.values())) if mats_for_obj else next(iter(textured)))
            )

            patch_mats = []
            for patch in active_patches:
                pname = patch.name
                mat = None
                p_mat = getattr(patch, "material", None)
                if p_mat and p_mat in textured_by_name:
                    mat = textured_by_name[p_mat]
                elif obj_mat_name and obj_mat_name in textured_by_name:
                    mat = textured_by_name[obj_mat_name]
                if mat is None:
                    mat = mats_for_obj.get(pname)
                if mat is None:
                    for mname, candidate in mats_for_obj.items():
                        if pname.endswith(f"_{mname}"):
                            mat = candidate
                            break
                patch_mats.append(mat if mat is not None else fallback)

            mesh = tessellate_object(obj)
            atlases[spec.name] = bake_atlas(mesh, patch_mats,
                                            cell_size=256,
                                            base_dir=self.base_dir)
        return atlases

    def _run_exports(self, recipe: Recipe, res: ExecutionResult) -> None:
        from .schema import normalize_export_format
        from am3d.renderer.sprite import save_sprite_sheet
        from am3d.renderer.tessellate import tessellate_project

        atlases = self._bake_atlases(recipe)
        atlas_dir = _atlas_outdir(recipe.exports)

        # Stage all exports into a temporary directory first.
        # Only publish staged files to destination paths if all exports succeed.
        staged_items = []

        with tempfile.TemporaryDirectory(prefix="am3d_stage_") as stage_dir:
            for index, spec in enumerate(recipe.exports):
                fmt = normalize_export_format(spec.format)
                base = spec.path

                if fmt == "am3d":
                    final_path = _with_ext(base, ".am3d")
                    staged_path = os.path.join(stage_dir, f"export_{index}.am3d")
                    try:
                        self.session.save_project(staged_path)
                        staged_items.append((staged_path, final_path, fmt, {"format": "am3d", "version": 2}))
                    except Exception as exc:
                        res.add_error(
                            f"failed to export .am3d project: {exc}",
                            code="export_error", stage="write",
                            path=f"recipe.exports[{index}].path",
                            hint="Check that the project state is valid.")
                    continue

                scene = self.session.evaluate_scene(apply_transforms=True, visible_only=True)
                meshes = {name: mesh for name, mesh in scene.meshes.items() if len(mesh.vertices)}
                mat_colors = _collect_material_colors(self.session)

                if fmt == "obj":
                    from am3d.export.obj import write_obj
                    final_path = _with_ext(base, ".obj")
                    # Named after the final basename (not "export_{index}"):
                    # write_obj derives the sidecar filename and the OBJ's
                    # `mtllib` reference from this path's stem, and both
                    # must match what actually lands next to final_path.
                    staged_path = os.path.join(stage_dir, os.path.basename(final_path))
                    try:
                        write_obj(staged_path, meshes, materials=mat_colors or None)
                        staged_items.append((staged_path, final_path, fmt, {"format": "obj", "mesh_count": len(meshes)}))
                        if mat_colors:
                            mtl_staged = os.path.splitext(staged_path)[0] + ".mtl"
                            mtl_final = os.path.splitext(final_path)[0] + ".mtl"
                            staged_items.append((mtl_staged, mtl_final, "mtl", {"format": "mtl", "sidecar_of": final_path}))
                    except Exception as exc:
                        res.add_error(
                            f"failed to write OBJ: {exc}",
                            code="export_error", stage="write",
                            path=f"recipe.exports[{index}].path")
                elif fmt == "glb":
                    from am3d.export.gltf import write_glb
                    final_path = _with_ext(base, ".glb")
                    staged_path = os.path.join(stage_dir, f"export_{index}.glb")
                    try:
                        write_glb(staged_path, meshes, materials=mat_colors or None)
                        staged_items.append((staged_path, final_path, fmt, {"format": "glb", "mesh_count": len(meshes)}))
                    except Exception as exc:
                        res.add_error(
                            f"failed to write GLB: {exc}",
                            code="export_error", stage="write",
                            path=f"recipe.exports[{index}].path")
                elif fmt in ("spritesheet", "toon_sheet"):
                    if not meshes:
                        res.add_error(
                            f"cannot export {fmt!r}: no renderable geometry found in recipe",
                            code="missing_geometry", stage="write",
                            path=f"recipe.exports[{index}].format",
                            hint="Add geometry (primitives or splines) to objects before exporting sheets.")
                        continue
                    p = dict(spec.params)
                    for oname, mesh in meshes.items():
                        final_path = _with_ext(f"{base}_{oname}", ".png")
                        staged_path = os.path.join(stage_dir, f"export_{index}_{oname}.png")
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
                        except Exception as exc:
                            res.add_error(
                                f"failed to generate {fmt} for {oname!r}: {exc}",
                                code="render_error", stage="write",
                                path=f"recipe.exports[{index}].path")
                    continue
                elif fmt == "animation_sheet":
                    # Time-stepped animation frame rendering — distinct from orbit-view spritesheets
                    if not meshes:
                        res.add_error(
                            f"cannot export 'animation_sheet': no renderable geometry",
                            code="missing_geometry", stage="write",
                            path=f"recipe.exports[{index}].format",
                            hint="Add geometry (primitives or splines) to objects.")
                        continue
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
                    from am3d.renderer.sprite import render_view
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
                            # Composite all meshes into one frame
                            frame_img = _np.zeros((size, size, 4), dtype=_np.float32)
                            for mname, fmesh in frame_scene.meshes.items():
                                if len(fmesh.vertices) == 0:
                                    continue
                                frame_img = _np.maximum(frame_img,
                                    render_view(fmesh, size=size, color=color))
                            r_idx, c_idx = divmod(fi, cols)
                            sheet[r_idx * size:(r_idx + 1) * size,
                                  c_idx * size:(c_idx + 1) * size] = (
                                _np.clip(frame_img, 0.0, 1.0) * 255).astype(_np.uint8)

                        from PIL import Image as _PIL_Image
                        pil_sheet = _PIL_Image.fromarray(sheet, "RGBA")
                        # One composited whole-scene sheet per export spec —
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
                    except Exception as exc:
                        res.add_error(
                            f"failed to render animation_sheet: {exc}",
                            code="render_error", stage="write",
                            path=f"recipe.exports[{index}].path")
                    continue
                else:
                    res.add_error(
                        f"export format {fmt!r} passed validation but has no "
                        f"writer; no file was produced for {base!r}",
                        code="unsupported_export_format", stage="schema",
                        path=f"recipe.exports[{index}].format")
                    continue

            # Save any baked atlases alongside exports
            if atlases and atlas_dir:
                from am3d.renderer.materials import save_image
                for oname, atlas in atlases.items():
                    final_path = _with_ext(f"{atlas_dir}/{oname}_atlas", ".png")
                    staged_path = os.path.join(stage_dir, f"atlas_{oname}.png")
                    meta = {"format": "png", "object": oname, "width": getattr(atlas, "width", 256), "height": getattr(atlas, "height", 256)}
                    try:
                        save_image(atlas, staged_path)
                        staged_items.append((staged_path, final_path, "atlas", meta))
                    except Exception as exc:
                        res.add_error(
                            f"atlas for {oname!r} not saved: {exc}",
                            code="write_error", stage="write",
                            path="recipe.materials")

            # Only publish if ALL staged exports succeeded without errors
            if not res.ok:
                return

            # Publish staged artifacts safely to final paths
            for staged_path, final_path, fmt, meta in staged_items:
                _ensure_parent(final_path)
                try:
                    shutil.copy2(staged_path, final_path)
                    res.exports.append((fmt, final_path))
                    self._record_artifact(res, fmt, final_path, metadata=meta)
                except Exception as exc:
                    res.add_error(
                        f"failed to publish artifact to {final_path!r}: {exc}",
                        code="publish_error", stage="write",
                        path="recipe.exports")
