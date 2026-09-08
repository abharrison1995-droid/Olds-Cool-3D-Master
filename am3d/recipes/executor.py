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


def _mat_kwargs(mat):
    """Extract the fields a MaterialRecipe copy needs from a live recipe."""
    return {
        "color": list(mat.color),
        "roughness": mat.roughness,
        "metalness": mat.metalness,
        "texture": mat.texture,
        "pattern": mat.pattern,
        "params": dict(mat.params),
        "objects": list(mat.objects),
    }


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
    m = np.asarray(transform, dtype=np.float64).reshape(4, 4)
    if np.array_equal(m, np.eye(4)):
        return mesh
    mesh.vertices = mesh.vertices @ m[:3, :3].T + m[:3, 3]
    normals = mesh.normals @ m[:3, :3].T
    mesh.normals = normals / np.maximum(
        np.linalg.norm(normals, axis=1, keepdims=True), 1e-12)
    return mesh


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
            else:
                result.add_error(f"{type(exc).__name__}: {exc}")
        finally:
            self.session = original
        return result

    # -- phases --------------------------------------------------------------
    def _build_objects(self, recipe: Recipe, res: ExecutionResult) -> None:
        from am3d.core.project import Patch

        s = self.session
        for spec in recipe.objects:
            s.create_object(spec.name)
            obj = s.get_object(spec.name)

            built = (build_primitive(spec.primitive, spec.params)
                     if spec.primitive else {"patches": [], "splines": []})

            for pname, net, du, dv in built["patches"]:
                obj.patches.append(Patch(name=f"{spec.name}_{pname}",
                                         splines=[], interior=net))

            for idx, sr in enumerate(spec.splines):
                name = sr.name if sr.name != "spline" else f"spline_{idx}"
                s.add_spline(spec.name, sr.points, degree=sr.degree,
                             name=name, closed=sr.closed)

            for br in spec.bones:
                s.add_bone(spec.name, br.name, br.head, br.tail,
                           parent=br.parent)
            res.objects.append(spec.name)

    def _build_materials(self, recipe: Recipe, res: ExecutionResult) -> None:
        s = self.session
        for mat in recipe.materials:
            material = s.create_material(mat.name, color=tuple(mat.color))
            # Carry the procedural pattern / graph through for the bake stage.
            if mat.pattern or mat.graph:
                material.pattern = mat.pattern
                material.params = dict(mat.params)

                material.texture = mat.texture
                material.graph = list(mat.graph)
                material.objects = list(mat.objects)
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
                act = retarget_action(src, bones, bones,
                                      mapping=dict(spec.params.get("mapping", {})),
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

    def _bake_atlases(self, recipe: Recipe):
        """Per-object baked texture atlases from the recipe materials.

        Returns ``{object_name: atlas}`` for every geometry object that has
        patches; objects without a matching material get no entry.
        """
        from am3d.renderer.materials import bake_atlas
        from am3d.renderer.tessellate import tessellate_object

        textured = [m for m in recipe.materials
                    if m.pattern or m.texture or m.graph]
        if not textured:
            return {}

        def matches(mat, obj_name):
            return not mat.objects or obj_name in mat.objects

        atlases = {}
        for spec in recipe.objects:
            mats_for_obj = {m.name: m for m in textured
                            if matches(m, spec.name)}
            if not mats_for_obj:
                continue
            obj = self.session.get_object(spec.name)
            if not obj or not obj.patches:
                continue
            patches = obj.patches
            fallback = next(iter(mats_for_obj.values()))
            patch_mats = {}
            for pname in (p.name for p in patches):
                mat = mats_for_obj.get(pname)
                if mat is None:
                    for mname, candidate in mats_for_obj.items():
                        if pname.endswith(f"_{mname}"):
                            mat = candidate
                            break
                patch_mats[pname] = mat if mat is not None else fallback
            mesh = tessellate_object(obj)
            atlases[spec.name] = bake_atlas(mesh, patch_mats,
                                            cell_size=256)
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
                        staged_items.append((staged_path, final_path, fmt, {"format": "am3d", "version": 1}))
                    except Exception as exc:
                        res.add_error(
                            f"failed to export .am3d project: {exc}",
                            code="export_error", stage="write",
                            path=f"recipe.exports[{index}].path",
                            hint="Check that the project state is valid.")
                    continue

                meshes = {}
                for name, mesh in tessellate_project(self.session.project).items():
                    if not len(mesh.vertices):
                        continue
                    obj = self.session.project.objects[name]
                    meshes[name] = _apply_object_transform(mesh, obj.transform)

                if fmt == "obj":
                    from am3d.export.obj import write_obj
                    final_path = _with_ext(base, ".obj")
                    staged_path = os.path.join(stage_dir, f"export_{index}.obj")
                    try:
                        write_obj(staged_path, meshes)
                        staged_items.append((staged_path, final_path, fmt, {"format": "obj", "mesh_count": len(meshes)}))
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
                        write_glb(staged_path, meshes)
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
