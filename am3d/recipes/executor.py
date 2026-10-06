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

from ..core.sheet_layout import calculate_sheet_layout
from ..core.paths import (classify_portable_relative_path,
                          is_absolute_any_platform, normalize_separators,
                          sanitize_filename_component)
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


def _named_sheet_path(path: str, object_name: str) -> str:
    """Derive a per-object PNG from a path's stem, preserving its directory."""
    stem, suffix = os.path.splitext(path)
    if suffix.lower() != ".png":
        stem = path
    safe_name = sanitize_filename_component(object_name)
    return f"{stem}_{safe_name}.png"


def _destination_key(path: str) -> str:
    """Portable identity for a final destination, including Windows casing."""
    absolute = os.path.realpath(os.path.abspath(os.fspath(path)))
    return os.path.normcase(os.path.normpath(absolute)).replace("\\", "/").casefold()


def _has_duplicate_destinations(staged_items) -> bool:
    destinations = set()
    for _, final_path, _, _ in staged_items:
        key = _destination_key(final_path)
        if key in destinations:
            return True
        destinations.add(key)
    return False


def _atlas_outdir(export_specs) -> str:
    """Where to write a sidecar atlas when an OBJ export needs one."""
    for spec in export_specs:
        if str(spec.format).lower() != "obj":
            continue
        parent = os.path.dirname(spec.path)
        if parent:
            return parent
        return "."
    return ""


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


def _bones_in_parent_order(bones):
    """``(ordered, unresolvable)`` -- parents before their children.

    A recipe is a declarative document, so it may list a child bone before
    the parent it names; ``Session.add_bone`` is an imperative call that
    (correctly) requires the parent to exist already. Sorting here keeps
    both true. Order is otherwise the order written, so a recipe that was
    already in dependency order builds exactly as before. Bones naming a
    parent that does not exist -- or forming a cycle -- come back as
    *unresolvable* for the caller to report against the recipe.
    """
    remaining = list(bones)
    by_name = {b.name: b for b in remaining}
    placed, ordered = set(), []
    progress = True
    while remaining and progress:
        progress = False
        still = []
        for bone in remaining:
            parent = getattr(bone, "parent", None)
            if not parent or parent in placed:
                ordered.append(bone)
                placed.add(bone.name)
                progress = True
            elif parent not in by_name:
                still.append(bone)      # unknown parent: never resolvable
            else:
                still.append(bone)
        remaining = still
    return ordered, remaining


class RecipeExecutor:
    """Applies a validated :class:`Recipe` to a scripting session."""

    def __init__(self, session=None, *, output_root: str | None = None,
                 base_dir: str | None = None, ai_mode: bool = False):
        if session is None:
            from am3d.core.script import Session
            session = Session()
        self.session = session
        self.output_root = (os.path.abspath(os.fspath(output_root))
                            if output_root is not None else None)
        self.base_dir = (os.path.abspath(os.fspath(base_dir))
                         if base_dir is not None else None)
        self.ai_mode = bool(ai_mode)

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
        if self.output_root is not None:
            # The portable policy is deliberately host-independent: the same
            # recipe must be accepted or rejected identically on Linux and on
            # Windows, so syntax is judged by am3d.core.paths rather than by
            # os.path (see am3d/core/paths.py for why).
            verdict = classify_portable_relative_path(raw)
            if verdict is not None:
                reason, hint = verdict
                raise RecipeValidationError(
                    "output_path_escape",
                    f"export {reason}",
                    path=f"recipe.exports[{index}].path",
                    hint=hint,
                    stage="resource")
            root = os.path.realpath(os.path.abspath(self.output_root))
            candidate = os.path.realpath(
                os.path.abspath(os.path.join(root, normalize_separators(raw))))
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
                # Belt and braces: symlinked components can still resolve out
                # of the root even after the syntactic check passed.
                raise RecipeValidationError(
                    "output_path_escape",
                    f"export path {raw!r} escapes the requested output root",
                    path=f"recipe.exports[{index}].path",
                    hint="Remove '..' segments or provide a child path within the output root.",
                    stage="resource")
            return candidate
        if self.base_dir is not None and not is_absolute_any_platform(raw):
            return os.path.realpath(os.path.abspath(
                os.path.join(self.base_dir, normalize_separators(raw))))
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

    def _recheck_final_path(self, path: str, index: int) -> None:
        """Recheck a derived destination immediately before publication."""
        if self.output_root is None:
            return
        root = os.path.realpath(os.path.abspath(self.output_root))
        candidate = os.path.realpath(os.path.abspath(os.fspath(path)))
        try:
            common = os.path.commonpath((root, candidate))
        except ValueError as exc:
            raise RecipeValidationError(
                "output_path_escape", f"derived export path escapes the output root: {exc}",
                path=f"recipe.exports[{index}].path", stage="resource") from exc
        if candidate == root or common != root:
            raise RecipeValidationError(
                "output_path_escape", "derived export path escapes the output root",
                path=f"recipe.exports[{index}].path", stage="resource",
                hint="Use a relative path within the host-chosen output root.")

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
        if not isinstance(recipe, Recipe):
            try:
                recipe = recipe_from_dict(recipe)
            except RecipeValidationError:
                # A structured failure -- let it fall through to the
                # try/except below, which reports it as a normal
                # ExecutionResult error (schema-validation contract).
                pass
            except (TypeError, ValueError) as exc:
                # Any other parser failure -- e.g. TypeError from an
                # unhashable dict landing in a membership check -- has no
                # structured code/path/hint to report, so normalize it to
                # the same "invalid recipe" contract validate_recipe's
                # failures use below, instead of letting whatever the
                # parser happened to raise escape uncaught. This must
                # happen before the try/except below, which surfaces
                # failures as ExecutionResult errors rather than raising.
                raise ValueError(f"invalid recipe: {exc}") from exc

        result = ExecutionResult()
        original = self.session
        try:
            if not isinstance(recipe, Recipe):
                recipe = recipe_from_dict(recipe)
            else:
                recipe = copy.deepcopy(recipe)

            problems = validate_recipe(recipe, ai_mode=self.ai_mode)
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

            if self.ai_mode and recipe.exports and self.output_root is None:
                result.add_error(
                    "AI-mode exports require a host-chosen output root",
                    code="missing_output_root", stage="resource", path="--out",
                    hint="Provide a private output_root when creating the executor.")
                return result

            if self.ai_mode:
                from .resources import (estimate_recipe_resources,
                                        resource_limit_issues)
                estimate = estimate_recipe_resources(recipe)
                for issue in resource_limit_issues(estimate):
                    result.add_error(
                        issue["message"], code=issue["code"],
                        stage=issue["stage"], path=issue["path"],
                        hint=issue.get("hint"))
                if not result.ok:
                    return result

            self._prepare_output_paths(recipe)
            from am3d.core.script import Session
            candidate = Session()
            self.session = candidate
            candidate.new_project(recipe.name)
            self._build_objects(recipe, result)
            self._build_materials(recipe, result)
            self._build_actions(recipe, result)
            if self.ai_mode:
                from .resources import built_scene_limit_issues
                for issue in built_scene_limit_issues(self.session, recipe):
                    result.add_error(
                        issue["message"], code=issue["code"],
                        stage=issue["stage"], path=issue["path"],
                        hint=issue.get("hint"))
                if not result.ok:
                    return result
            self._check_action_effects(recipe, result)
            if not result.ok:
                return result
            self._run_exports(recipe, result)
            if result.ok:
                self._commit_session(original, candidate)
        except Exception as exc:                      # surfaced to the LLM
            if isinstance(exc, RecipeValidationError):
                result.add_error(str(exc), code=exc.code, stage=exc.stage,
                                 path=exc.path, hint=exc.hint)
            elif isinstance(exc, MemoryError):
                result.add_error(
                    "generation exceeded the available memory limit",
                    code="resource_exhausted", stage="resource",
                    path="recipe",
                    hint="Reduce geometry, texture, or render sizes and retry.")
            elif isinstance(exc, FileNotFoundError):
                result.add_error("resource file not found",
                                 code="missing_resource", stage="resource",
                                 path="recipe.materials",
                                 hint="Check that all texture or image resource paths exist relative to base_dir or project root.")
            else:
                result.add_error(f"{type(exc).__name__}: {exc}")
        finally:
            self.session = original
        return result

    def _check_action_effects(self, recipe: Recipe, res: ExecutionResult) -> None:
        """Warn or fail when a requested action changes no bound geometry."""
        if not recipe.actions:
            return
        for index, spec in enumerate(recipe.actions):
            action = self.session.actions.get(spec.name)
            if action is None:
                continue
            if not any(action_name == spec.name
                       for action_name in self.session.action_assignments.values()):
                # Actions may be reusable library data. Only check a clip that
                # the recipe actually assigned to a character.
                continue
            bound_names = {
                obj.name for obj in recipe.objects
                if (obj.name == spec.character or
                    (isinstance(obj.params, dict) and
                     obj.params.get("skeleton") == spec.character))
                and (obj.primitive or obj.splines)
                and any(getattr(bone, "cp_weights", None)
                        for bone in self.session.get_bones(obj.name))
            }
            if not bound_names:
                self._record_action_effect_failure(res, index, spec.name)
                continue
            duration = float(getattr(action, "duration", spec.duration) or spec.duration)
            key_times = sorted({float(key.time)
                                for channel in action.channels
                                for key in channel.keys})
            if len(key_times) > 32:
                key_times = [key_times[round(i * (len(key_times) - 1) / 31)]
                             for i in range(32)]
            sample_times = sorted({0.0, duration * 0.25, duration * 0.5,
                                   duration * 0.75, duration, *key_times})
            baseline = self.session.evaluate_scene(
                action_name=spec.name, time=0.0, visible_only=False,
                nu=8, nv=8, apply_transforms=True)
            moved = False
            for sample_time in sample_times:
                if abs(sample_time) <= 1e-12:
                    continue
                sampled = self.session.evaluate_scene(
                    action_name=spec.name, time=sample_time,
                    visible_only=False, nu=8, nv=8, apply_transforms=True)
                for object_name in bound_names:
                    mesh = baseline.meshes.get(object_name)
                    other = sampled.meshes.get(object_name)
                    if (mesh is not None and other is not None and
                            mesh.vertices.shape == other.vertices.shape and
                            mesh.vertices.size and
                            not np.allclose(mesh.vertices, other.vertices,
                                            rtol=1e-7, atol=1e-8)):
                        moved = True
                        break
                if moved:
                    break
            if moved:
                continue
            self._record_action_effect_failure(res, index, spec.name)

    def _record_action_effect_failure(self, res: ExecutionResult, index: int,
                                      action_name: str) -> None:
        message = f"action {action_name!r} changes no bound geometry"
        path = f"recipe.actions[{index}]"
        if self.ai_mode:
            res.add_error(message, code="no_action_effect", stage="check",
                          path=path,
                          hint="Bind geometry to this character and ensure the action moves its weighted bones.")
        else:
            res.warnings.append(f"{path}: {message}")

    # -- phases --------------------------------------------------------------
    def _build_objects(self, recipe: Recipe, res: ExecutionResult) -> None:
        from am3d.core.project import Patch
        from am3d.core.rigging import auto_weight_object

        s = self.session
        for object_index, spec in enumerate(recipe.objects):
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
                                         splines=[], interior=net,
                                         degree_u=int(du), degree_v=int(dv)))

            for spline_index, sr in enumerate(spec.splines):
                name = (sr.name if sr.name != "spline"
                        else f"spline_{spline_index}")
                s.add_spline(spec.name, sr.points, degree=sr.degree,
                             name=name, closed=sr.closed)

            has_explicit_weights = False
            ordered_bones, bad_parents = _bones_in_parent_order(spec.bones)
            for br in bad_parents:
                res.add_error(
                    f"bone {br.name!r} on object {spec.name!r} names a parent "
                    f"{br.parent!r} that is not defined on the same object",
                    code="missing_reference", stage="schema",
                    path=f"recipe.objects[{object_index}].bones",
                    hint="Every bone parent must be another bone of the same "
                         "object, and the parent chain must not be circular.")
            for br in ordered_bones:
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

        mesh_export_index = next(
            (i for i, spec in enumerate(recipe.exports)
             if normalize_export_format(spec.format) in {"obj", "glb"}),
            None)
        atlases = (self._bake_atlases(recipe)
                   if mesh_export_index is not None else {})

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
                    except MemoryError:
                        raise
                    except Exception as exc:
                        res.add_error(
                            f"failed to export .am3d project: {exc}",
                            code="export_error", stage="write",
                            path=f"recipe.exports[{index}].path",
                            hint="Check that the project state is valid.")
                    continue

                from am3d.core.scene import (scene_material_colors,
                                             scene_patch_material_colors)
                scene = self.session.evaluate_scene(apply_transforms=True, visible_only=True)
                meshes = {name: mesh for name, mesh in scene.meshes.items() if len(mesh.vertices)}
                mat_colors = scene_material_colors(scene)
                patch_colors = scene_patch_material_colors(scene)

                if fmt == "obj":
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
                    obj_textures = {n: a for n, a in atlases.items()
                                    if n in meshes}
                    try:
                        write_obj(staged_path, meshes,
                                  materials=mat_colors or None,
                                  patch_materials=patch_colors or None,
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
                    except MemoryError:
                        raise
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
                        write_glb(staged_path, meshes,
                                  materials=mat_colors or None,
                                  patch_materials=patch_colors or None,
                                  textures={n: a for n, a in atlases.items()
                                            if n in meshes} or None)
                        staged_items.append((staged_path, final_path, fmt, {"format": "glb", "mesh_count": len(meshes)}))
                    except MemoryError:
                        raise
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
                        safe_name = sanitize_filename_component(oname)
                        final_path = _named_sheet_path(base, oname)
                        staged_path = os.path.join(stage_dir, f"export_{index}_{safe_name}.png")
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
                        except MemoryError:
                            raise
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
                    from am3d.renderer.sprite import render_scene
                    cols = int(p.get("columns", n_frames))
                    layout = calculate_sheet_layout(n_frames, cols, size)
                    rows = layout.rows
                    try:
                        import numpy as _np
                        sheet = _np.zeros((layout.height, layout.width, 4),
                                          dtype=_np.uint8)
                        for fi in range(n_frames):
                            t = t_start + (t_end - t_start) * fi / max(n_frames - 1, 1)
                            frame_scene = self.session.evaluate_scene(
                                action_name=action_name, time=t,
                                apply_transforms=True, visible_only=True)
                            # Merge every visible mesh through one shared
                            # z-buffer (render_scene) rather than rendering
                            # each independently and taking a per-pixel max —
                            # the max-blend composite lost real occlusion:
                            # a nearer but darker surface could be overwritten
                            # by a farther but brighter one.
                            live_meshes = {n: m for n, m in frame_scene.meshes.items()
                                          if len(m.vertices)}
                            frame_img = render_scene(live_meshes, size=size, color=color)
                            r_idx, c_idx = divmod(fi, layout.columns)
                            sheet[r_idx * size:(r_idx + 1) * size,
                                  c_idx * size:(c_idx + 1) * size] = (
                                _np.clip(frame_img, 0.0, 1.0) * 255).astype(_np.uint8)

                        if sheet.shape[:2] != (layout.height, layout.width):
                            raise RuntimeError(
                                "animation sheet allocation differs from its validated layout")
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
                    except MemoryError:
                        raise
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
            obj_exports = [(i, spec) for i, spec in enumerate(recipe.exports)
                           if normalize_export_format(spec.format) == "obj"]
            if atlases and obj_exports:
                from am3d.renderer.materials import save_image
                for export_index, spec in obj_exports:
                    obj_path = _with_ext(spec.path, ".obj")
                    atlas_dir = os.path.dirname(obj_path) or "."
                    stem = os.path.splitext(os.path.basename(obj_path))[0]
                    for oname, atlas in atlases.items():
                        safe_name = sanitize_filename_component(oname)
                        suffix = f"_{safe_name}" if len(atlases) > 1 else ""
                        final_path = _with_ext(
                            os.path.join(atlas_dir, f"{stem}{suffix}_atlas"),
                            ".png")
                        staged_path = os.path.join(
                            stage_dir, f"atlas_{export_index}_{safe_name}.png")
                        height, width = atlas.shape[:2]
                        meta = {"object": oname,
                                "width": int(width), "height": int(height)}
                        try:
                            save_image(atlas, staged_path)
                            staged_items.append((staged_path, final_path,
                                                 "atlas", meta))
                        except MemoryError:
                            raise
                        except Exception as exc:
                            res.add_error(
                                f"atlas for {oname!r} not saved: {exc}",
                                code="write_error", stage="write",
                                path="recipe.materials")

            # Only publish if ALL staged exports succeeded without errors
            if not res.ok:
                return

            if self.ai_mode:
                from .resources import LIMITS
                staged_bytes = sum(os.path.getsize(item[0])
                                   for item in staged_items
                                   if os.path.isfile(item[0]))
                if staged_bytes > LIMITS["published_bytes"]:
                    res.add_error(
                        f"staged output is {staged_bytes} bytes; AI-mode limit is {LIMITS['published_bytes']} bytes",
                        code="resource_limit", stage="resource",
                        path="recipe.exports",
                        hint="Reduce the number or size of exports and retry.")
                    return

            if _has_duplicate_destinations(staged_items):
                res.add_error(
                    "multiple staged artifacts target the same final destination; no files were published",
                    code="duplicate_export_destination", stage="resource",
                    path="recipe.exports",
                    hint="Choose distinct paths for each export and derived sidecar.")
                return

            # Publish staged artifacts safely to final paths
            for staged_path, final_path, fmt, meta in staged_items:
                # Check before creating directories and again after resolving
                # them so a symlink cannot redirect an export outside its root.
                self._recheck_final_path(final_path, 0)
                _ensure_parent(final_path)
                try:
                    self._recheck_final_path(final_path, 0)
                    shutil.copy2(staged_path, final_path)
                    res.exports.append((fmt, final_path))
                    self._record_artifact(res, fmt, final_path, metadata=meta)
                except MemoryError:
                    raise
                except Exception as exc:
                    res.add_error(
                        f"failed to publish artifact to {final_path!r}: {exc}",
                        code="publish_error", stage="write",
                        path="recipe.exports")
