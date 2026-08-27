"""Recipe execution: JSON in -> geometry, rigs, actions and files out.

The single entry point an LLM pipeline needs::

    result = RecipeExecutor().execute(recipe_dict_or_Recipe)

Recipes are validated first (:func:`am3d.recipes.schema.validate_recipe`),
then applied to a live :class:`~am3d.core.script.Session`, then exported.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

import numpy as np

from .animation import generate_action
from .primitives import build_primitive
from .schema import Recipe, recipe_from_dict, validate_recipe


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

    def __init__(self, session=None):
        if session is None:
            from am3d.core.script import Session
            session = Session()
        self.session = session

    def execute(self, recipe) -> ExecutionResult:
        if not isinstance(recipe, Recipe):
            recipe = recipe_from_dict(recipe)

        problems = validate_recipe(recipe)
        if problems:
            raise ValueError("invalid recipe:\n  - " + "\n  - ".join(problems))

        result = ExecutionResult()
        try:
            self.session.new_project(recipe.name)
            self._build_objects(recipe, result)
            self._build_materials(recipe, result)
            self._build_actions(recipe, result)
            self._run_exports(recipe, result)
        except Exception as exc:                      # surfaced to the LLM
            result.ok = False
            result.errors.append(f"{type(exc).__name__}: {exc}")
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
        for spec in recipe.actions:
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
                    res.warnings.append(
                        f"action {spec.name!r}: retarget needs character + "
                        "source_action; skipped")
                    continue
                src = s.actions.get(spec.source_action)
                if src is None:
                    res.warnings.append(
                        f"action {spec.name!r}: source action "
                        f"{spec.source_action!r} not found; skipped")
                    continue
                from am3d.core.retarget import retarget_action
                act = retarget_action(src, bones, bones,
                                      mapping=dict(spec.params.get("mapping", {})),
                                      default_duration=spec.duration)
                act.name = spec.name
                s.actions[act.name] = act
            else:
                if not bones:
                    res.warnings.append(
                        f"action {spec.name!r}: procedural kind "
                        f"{spec.kind!r} needs a character with bones; skipped")
                    continue
                act = generate_action(spec.kind, bones, name=spec.name,
                                      duration=spec.duration,
                                      **dict(spec.params))
                s.actions[act.name] = act

            if spec.character and bones:
                s.apply_action_to_character(act.name, spec.character)
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
            # Map each patch name -> its material: an exact name match
            # first, then a match on the primitive patch suffix
            # (``<object>_<patch>``), then the first material as fallback.
            patch_mats = {}
            patches = self.session.get_object(spec.name).patches
            fallback = next(iter(mats_for_obj.values()))
            for pname in (p.name for p in patches):
                mat = mats_for_obj.get(pname)
                if mat is None:
                    for mname, candidate in mats_for_obj.items():
                        if pname.endswith(f"_{mname}"):
                            mat = candidate
                            break
                patch_mats[pname] = mat if mat is not None else fallback
            mesh = tessellate_object(self.session.get_object(spec.name))
            atlases[spec.name] = bake_atlas(mesh, patch_mats,
                                            cell_size=256)
        return atlases

    def _run_exports(self, recipe: Recipe, res: ExecutionResult) -> None:
        from am3d.core.serializer import save_project
        from .schema import normalize_export_format
        from am3d.renderer.sprite import save_sprite_sheet
        from am3d.renderer.tessellate import tessellate_project

        atlases = self._bake_atlases(recipe)
        atlas_dir = _atlas_outdir(recipe.exports)

        for spec in recipe.exports:
            fmt = normalize_export_format(spec.format)
            base = spec.path
            _ensure_parent(base)

            if fmt == "am3d":
                path = _with_ext(base, ".am3d")
                save_project(self.session.project, path)
                res.exports.append((fmt, path))
                continue

            meshes = {}
            for name, mesh in tessellate_project(self.session.project).items():
                if not len(mesh.vertices):
                    continue
                obj = self.session.project.objects[name]
                meshes[name] = _apply_object_transform(mesh, obj.transform)

            if fmt == "obj":
                from am3d.export.obj import write_obj
                path = _with_ext(base, ".obj")
                write_obj(path, meshes)
            elif fmt == "glb":
                from am3d.export.gltf import write_glb
                path = _with_ext(base, ".glb")
                write_glb(path, meshes)
            elif fmt in ("spritesheet", "toon_sheet"):
                p = dict(spec.params)
                paths = []
                for oname, mesh in meshes.items():
                    path = _with_ext(f"{base}_{oname}", ".png")
                    common = {
                        "views": int(p.get("views", 8)),
                        "size": int(p.get("size", 256)),
                        "color": tuple(p.get("color",
                                             (0.72, 0.74, 0.82))),
                        "silhouette": bool(p.get("silhouette", False)),
                    }
                    if fmt == "spritesheet":
                        save_sprite_sheet(mesh, path, **common)
                    else:
                        from am3d.renderer.toon import save_toon_sheet
                        save_toon_sheet(mesh, path,
                                        views=common["views"],
                                        size=common["size"],
                                        color=tuple(p.get("color",
                                                          (0.85, 0.78,
                                                           0.55))),
                                        bands=int(p.get("bands", 4)),
                                        ink=bool(p.get("ink", True)))
                    paths.append(path)
                res.exports.append((fmt, ", ".join(paths)))
                continue
            else:
                # Reached only if EXPORT_FORMATS and this dispatch drift
                # apart. Producing no file is a failure, not a warning:
                # a caller that sees ok=True is entitled to assume every
                # requested export exists on disk.
                res.ok = False
                res.errors.append(
                    f"export format {fmt!r} passed validation but has no "
                    f"writer; no file was produced for {base!r}")
                continue

            res.exports.append((fmt, path))

        # Save any baked atlases alongside exports so they can ship with
        # the assets (referenced by name: <out>_atlas_<object>.png).
        if atlases and atlas_dir:
            from am3d.core.script import ScriptingError
            from am3d.renderer.materials import save_image
            _ensure_parent(atlas_dir)
            for oname, atlas in atlases.items():
                try:
                    path = save_image(atlas,
                                      _with_ext(f"{atlas_dir}/{oname}_atlas",
                                                ".png"))
                    res.exports.append(("atlas", path))
                except Exception as exc:
                    res.warnings.append(
                        f"atlas for {oname!r} not saved: {exc}")