"""Declarative asset recipes — the contract an LLM emits.

A *recipe* is a plain-JSON description of everything needed to build one or
more assets: objects (from primitives or explicit splines), materials,
reusable actions and export targets.  An LLM only has to produce a dict that
matches :class:`Recipe`; :mod:`am3d.recipes.executor` turns it into real
geometry, rigs and files on disk with a single call.

Minimal example::

    {
      "name": "knight",
      "objects": [
        {"name": "body", "primitive": "sphere", "params": {"radius": 0.6}},
        {"name": "hero", "bones": [
            {"name": "hip",  "head": [0,0.9,0], "tail": [0,1.0,0]},
            {"name": "spine","head": [0,1.0,0], "tail": [0,1.4,0],
             "parent": "hip"}
        ]}
      ],
      "actions": [{"kind": "walk", "name": "walk", "duration": 1.2,
                   "character": "hero"}],
      "exports": [{"format": "obj", "path": "out/knight"}]
    }
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import re

import numpy as np

from .capabilities import (CAPABILITIES, capabilities_for,
                           validate_parameters)


CURRENT_RECIPE_VERSION = 1


class RecipeValidationError(ValueError):
    """A validation failure with a stable machine-readable location."""

    def __init__(self, code: str, message: str, *, path: str = "recipe",
                 hint: str | None = None, stage: str = "schema"):
        self.code = code
        self.stage = stage
        self.path = path
        self.hint = hint
        super().__init__(message)

    def to_record(self) -> dict:
        record = {
            "code": self.code,
            "stage": self.stage,
            "path": self.path,
            "message": str(self),
        }
        if self.hint:
            record["hint"] = self.hint
        return record


class ValidationIssue(str):
    """A human-readable validation issue carrying structured diagnostics."""

    def __new__(cls, message: str, *, code: str = "validation_error",
                path: str = "recipe", stage: str = "schema",
                hint: str | None = None):
        obj = super().__new__(cls, message)
        obj.code = code
        obj.stage = stage
        obj.path = path
        obj.hint = hint
        obj.message = message
        return obj

    def to_record(self) -> dict:
        record = {
            "code": self.code,
            "stage": self.stage,
            "path": self.path,
            "message": self.message,
        }
        if self.hint:
            record["hint"] = self.hint
        return record


# Capability names accepted in recipe documents. Keeping these views derived
# from the registry prevents the validator, CLI and schema guide from drifting.
PRIMITIVES = frozenset(cap.name for cap in capabilities_for("primitive"))

# Procedural action generators accepted in ActionRecipe.kind.
ACTION_KINDS = frozenset(cap.name for cap in capabilities_for("action_kind"))

# Only formats ``RecipeExecutor._run_exports`` actually writes belong here.
# Advertising a format with no writer makes the run report success while
# producing no file, so this set and that dispatch must stay in step.
EXPORT_FORMATS = frozenset(cap.name for cap in capabilities_for("export_format"))

# Accepted spellings that are not writer names in their own right.
_FORMAT_ALIASES = {"gltf": "glb"}      # we always emit binary glTF

AI_OBJECT_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_ .-]{0,63}$")


def normalize_export_format(fmt) -> str:
    """Canonical writer name for a user-supplied export format.

    Applied by ``recipe_from_dict``, ``validate_recipe`` and the executor
    alike, so an alias means the same thing on every path into a run.
    """
    fmt = str(fmt).lower()
    return _FORMAT_ALIASES.get(fmt, fmt)


@dataclass
class SplineRecipe:
    """An explicit spline; ``points`` is ``[[x, y, z], ...]``."""

    points: list
    name: str = "spline"
    degree: int = 3
    closed: bool = False


@dataclass
class BoneRecipe:
    name: str
    head: list
    tail: list
    parent: str | None = None
    weights: dict = field(default_factory=dict)
    cp_weights: dict = field(default_factory=dict)


@dataclass
class ObjectRecipe:
    """One scene object: either a primitive or hand-authored splines."""

    name: str
    primitive: str | None = None          # see PRIMITIVES
    params: dict = field(default_factory=dict)
    splines: list = field(default_factory=list)   # list[SplineRecipe | dict]
    bones: list = field(default_factory=list)     # list[BoneRecipe | dict]
    transform: list = field(default_factory=list)


@dataclass
class MaterialRecipe:
    name: str
    color: list = field(default_factory=lambda: [0.8, 0.8, 0.8])
    roughness: float = 0.5
    metalness: float = 0.0
    texture: str | None = None
    # Procedural pattern ("checker"|"bricks"|"noise"|"gradient"|"solid")
    # plus its params dict; resolved by the renderer at bake time.
    pattern: str | None = None
    params: dict = field(default_factory=dict)
    # Optional node-graph chain (list of {"type", "params"} dicts).  When
    # present it supersedes `pattern`; evaluated by the material graph.
    graph: list = field(default_factory=list)
    # Which objects this material coats ([] = all geometry objects).
    objects: list = field(default_factory=list)


@dataclass
class KeyframeRecipe:
    time: float
    value: list                    # [x] / [x, y] / [x, y, z]
    interp: str = "smooth"


@dataclass
class ChannelRecipe:
    bone: str
    property: str = "translate"
    keys: list = field(default_factory=list)      # list[KeyframeRecipe | dict]


@dataclass
class ActionRecipe:
    """A reusable animation clip; ``kind`` selects a procedural generator."""

    name: str
    kind: str = "custom"                  # walk | idle | jump | custom | retarget
    duration: float = 1.0
    character: str | None = None          # object to apply it to
    channels: list = field(default_factory=list)
    params: dict = field(default_factory=dict)
    source_action: str | None = None       # for kind="retarget": source action name


@dataclass
class ExportRecipe:
    format: str = "obj"                   # see EXPORT_FORMATS
    path: str = "./out"
    params: dict = field(default_factory=dict)


@dataclass
class Recipe:
    """Top-level asset recipe."""

    version: int = CURRENT_RECIPE_VERSION
    name: str = "asset"
    objects: list = field(default_factory=list)
    materials: list = field(default_factory=list)
    actions: list = field(default_factory=list)
    exports: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        import json
        return json.dumps(self.to_dict(), indent=indent)


# ---------------------------------------------------------------------------
# Dict -> dataclass coercion (tolerant of LLM output shapes)
# ---------------------------------------------------------------------------
def _validate_finite_sequence(seq, path: str, expected_len: int | None = None):
    if not isinstance(seq, (list, tuple)):
        raise RecipeValidationError("invalid_type", f"{path} must be a list", path=path)
    if expected_len is not None and len(seq) != expected_len:
        raise RecipeValidationError("invalid_length", f"{path} must have {expected_len} items", path=path)
    for i, item in enumerate(seq):
        if not isinstance(item, (int, float)) or isinstance(item, bool) or not math.isfinite(item):
            raise RecipeValidationError("invalid_value", f"{path}[{i}] must be a finite number", path=f"{path}[{i}]")


def _coerce(value, cls, path: str):
    if isinstance(value, cls):
        return value
    if isinstance(value, dict):
        known = set(cls.__dataclass_fields__)
        unknown = sorted(set(value) - known)
        if unknown:
            key = unknown[0]
            raise RecipeValidationError(
                "unknown_field",
                f"unknown field {key!r} for {cls.__name__}",
                path=f"{path}.{key}",
                hint="Remove the field or use a documented field name.")
        try:
            instance = cls(**value)
        except TypeError as exc:
            raise RecipeValidationError(
                "invalid_field", str(exc), path=path) from exc

        if isinstance(instance, SplineRecipe):
            if not isinstance(instance.points, (list, tuple)):
                raise RecipeValidationError("invalid_type", f"{path}.points must be a list", path=f"{path}.points")
            for i, pt in enumerate(instance.points):
                _validate_finite_sequence(pt, f"{path}.points[{i}]", expected_len=3)
        elif isinstance(instance, BoneRecipe):
            _validate_finite_sequence(instance.head, f"{path}.head", expected_len=3)
            _validate_finite_sequence(instance.tail, f"{path}.tail", expected_len=3)
            raw_w = instance.cp_weights or instance.weights
            if raw_w:
                if not isinstance(raw_w, dict):
                    raise RecipeValidationError("invalid_type", f"{path}.weights must be a dictionary", path=f"{path}.weights")
                for k, v in raw_w.items():
                    try:
                        int(k)
                    except (ValueError, TypeError):
                        raise RecipeValidationError("invalid_index", f"{path}.weights keys must be integer indices, got {k!r}", path=f"{path}.weights")
                    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) or v < 0.0:
                        raise RecipeValidationError("invalid_value", f"{path}.weights values must be finite non-negative numbers", path=f"{path}.weights")
        elif isinstance(instance, MaterialRecipe):
            if instance.color is not None:
                _validate_finite_sequence(instance.color, f"{path}.color")
                if len(instance.color) not in (3, 4):
                    raise RecipeValidationError("invalid_length", f"{path}.color must have 3 or 4 elements", path=f"{path}.color")
                for i, c in enumerate(instance.color):
                    if not (0.0 <= c <= 1.0):
                        raise RecipeValidationError("invalid_value", f"{path}.color[{i}] must be between 0.0 and 1.0", path=f"{path}.color[{i}]")
            if not isinstance(instance.roughness, (int, float)) or isinstance(instance.roughness, bool) or not math.isfinite(instance.roughness) or not (0.0 <= instance.roughness <= 1.0):
                raise RecipeValidationError("invalid_value", f"{path}.roughness must be between 0.0 and 1.0", path=f"{path}.roughness")
            if not isinstance(instance.metalness, (int, float)) or isinstance(instance.metalness, bool) or not math.isfinite(instance.metalness) or not (0.0 <= instance.metalness <= 1.0):
                raise RecipeValidationError("invalid_value", f"{path}.metalness must be between 0.0 and 1.0", path=f"{path}.metalness")
        elif isinstance(instance, ActionRecipe):
            if not isinstance(instance.duration, (int, float)) or isinstance(instance.duration, bool) or not math.isfinite(instance.duration) or instance.duration <= 0:
                raise RecipeValidationError("invalid_value", f"{path}.duration must be a positive finite number", path=f"{path}.duration")
        elif isinstance(instance, KeyframeRecipe):
            if not isinstance(instance.time, (int, float)) or isinstance(instance.time, bool) or not math.isfinite(instance.time):
                raise RecipeValidationError("invalid_value", f"{path}.time must be a finite number", path=f"{path}.time")
            _validate_finite_sequence(instance.value, f"{path}.value")
        return instance

    raise RecipeValidationError(
        "invalid_type",
        f"cannot coerce {type(value).__name__} into {cls.__name__}",
        path=path,
        hint=f"Provide an object matching {cls.__name__}.")


def _compile_trs_shorthand(transform, path: str):
    """Compile the documented translate/rotate_deg/scale shorthand."""
    if not isinstance(transform, dict):
        return transform
    allowed = {"translate", "rotate_deg", "scale"}
    unknown = sorted(set(transform) - allowed)
    if unknown:
        key = unknown[0]
        raise RecipeValidationError(
            "unknown_field", f"unknown TRS transform field {key!r}",
            path=f"{path}.{key}",
            hint=f"Use only: {sorted(allowed)}.")
    from am3d.core.mathutil import compose_trs
    defaults = {"translate": (0.0, 0.0, 0.0),
                "rotate_deg": (0.0, 0.0, 0.0),
                "scale": (1.0, 1.0, 1.0)}
    values = {}
    for key, default in defaults.items():
        value = transform.get(key, default)
        _validate_finite_sequence(value, f"{path}.{key}", expected_len=3)
        values[key] = value
    if any(abs(float(v)) < 1e-12 for v in values["scale"]):
        raise RecipeValidationError(
            "singular_transform", "TRS transform scale components must be non-zero",
            path=f"{path}.scale")
    return compose_trs(values["translate"], values["rotate_deg"],
                       values["scale"]).tolist()


def recipe_from_dict(data: dict) -> Recipe:
    """Parse a :class:`Recipe` from JSON-shaped data.

    Structural errors raise immediately. Semantic capability errors are
    collected by :func:`validate_recipe` so callers receive all bad paths.
    """
    if not isinstance(data, dict):
        raise RecipeValidationError(
            "invalid_type", "recipe root must be a JSON object", path="recipe")

    known = {"version", "name", "objects", "materials", "actions",
             "exports"}
    unknown = sorted(set(data) - known)
    if unknown:
        key = unknown[0]
        raise RecipeValidationError(
            "unknown_field", f"unknown recipe field {key!r}",
            path=f"recipe.{key}",
            hint="Remove the field or use a documented recipe field.")

    for field_name in ("objects", "materials", "actions", "exports"):
        val = data.get(field_name)
        if val is not None and not isinstance(val, list):
            raise RecipeValidationError(
                "invalid_type",
                f"recipe.{field_name} must be a list, got {type(val).__name__}",
                path=f"recipe.{field_name}",
                hint=f"Provide a list of {field_name} definitions.")

    version = data.get("version", CURRENT_RECIPE_VERSION)
    if isinstance(version, bool) or not isinstance(version, int):
        raise RecipeValidationError(
            "invalid_version", "recipe version must be an integer",
            path="recipe.version", hint=f"Use version {CURRENT_RECIPE_VERSION}.")
    if version != CURRENT_RECIPE_VERSION:
        raise RecipeValidationError(
            "unsupported_version",
            f"unsupported recipe version {version!r}; supported version is "
            f"{CURRENT_RECIPE_VERSION}",
            path="recipe.version",
            hint=f"Set version to {CURRENT_RECIPE_VERSION}.")

    recipe = Recipe(version=version, name=data.get("name", "asset"))

    for index, od in enumerate(data.get("objects", []) or []):
        path = f"recipe.objects[{index}]"
        if not isinstance(od, dict) and not isinstance(od, ObjectRecipe):
            raise RecipeValidationError(
                "invalid_type",
                f"object definition must be a JSON object, got {type(od).__name__}",
                path=path,
                hint="Provide a dictionary with at least 'name'.")
        obj = _coerce(od, ObjectRecipe, path)
        if not obj.name:
            raise RecipeValidationError(
                "missing_name", "every object needs a 'name'",
                path=f"{path}.name")
        if not isinstance(obj.splines, list):
            raise RecipeValidationError("invalid_type", f"{path}.splines must be a list", path=f"{path}.splines")
        if not isinstance(obj.bones, list):
            raise RecipeValidationError("invalid_type", f"{path}.bones must be a list", path=f"{path}.bones")
        obj.splines = [
            _coerce(sd, SplineRecipe, f"{path}.splines[{i}]")
            for i, sd in enumerate(obj.splines or [])]
        obj.bones = [
            _coerce(bd, BoneRecipe, f"{path}.bones[{i}]")
            for i, bd in enumerate(obj.bones or [])]
        if isinstance(obj.transform, dict):
            obj.transform = _compile_trs_shorthand(obj.transform,
                                                    f"{path}.transform")
        if obj.transform:
            if not isinstance(obj.transform, (list, tuple)):
                raise RecipeValidationError("invalid_type", f"{path}.transform must be a list", path=f"{path}.transform")
            def _check_num(v):
                if isinstance(v, bool) or not isinstance(v, (int, float)):
                    raise RecipeValidationError("invalid_value", f"{path}.transform elements must be numbers", path=f"{path}.transform")
            if any(isinstance(row, (list, tuple)) for row in obj.transform):
                for row in obj.transform:
                    if not isinstance(row, (list, tuple)):
                        raise RecipeValidationError("invalid_type", f"{path}.transform matrix rows must be lists", path=f"{path}.transform")
                    for val in row:
                        _check_num(val)
            else:
                for val in obj.transform:
                    _check_num(val)
            t_arr = np.asarray(obj.transform, dtype=np.float64)
            if not np.all(np.isfinite(t_arr)):
                raise RecipeValidationError("invalid_value", f"{path}.transform values must be finite", path=f"{path}.transform")
            if t_arr.shape == (4, 4) or t_arr.size == 16:
                m = t_arr.reshape(4, 4)
                det = float(np.linalg.det(m[:3, :3]))
                if abs(det) < 1e-12:
                    raise RecipeValidationError("singular_transform", f"object {obj.name!r} transform is singular (det={det:.3e})", path=f"{path}.transform")
            elif t_arr.size != 3:
                raise RecipeValidationError("invalid_shape", f"{path}.transform must be a 4x4 matrix (16 elements) or a 3-element translation", path=f"{path}.transform")
        recipe.objects.append(obj)

    for index, md in enumerate(data.get("materials", []) or []):
        path = f"recipe.materials[{index}]"
        if not isinstance(md, dict) and not isinstance(md, MaterialRecipe):
            raise RecipeValidationError(
                "invalid_type",
                f"material definition must be a JSON object, got {type(md).__name__}",
                path=path,
                hint="Provide a dictionary with at least 'name'.")
        recipe.materials.append(_coerce(md, MaterialRecipe, path))

    for index, ad in enumerate(data.get("actions", []) or []):
        path = f"recipe.actions[{index}]"
        if not isinstance(ad, dict) and not isinstance(ad, ActionRecipe):
            raise RecipeValidationError(
                "invalid_type",
                f"action definition must be a JSON object, got {type(ad).__name__}",
                path=path,
                hint="Provide a dictionary with at least 'name'.")
        act = _coerce(ad, ActionRecipe, path)
        if not isinstance(act.channels, list):
            raise RecipeValidationError("invalid_type", f"{path}.channels must be a list", path=f"{path}.channels")
        act.channels = [
            _coerce(cd, ChannelRecipe, f"{path}.channels[{i}]")
            for i, cd in enumerate(act.channels or [])]
        for channel_index, ch in enumerate(act.channels):
            if not isinstance(ch.keys, list):
                raise RecipeValidationError(
                    "invalid_type",
                    f"{path}.channels[{channel_index}].keys must be a list",
                    path=f"{path}.channels[{channel_index}].keys")
            ch.keys = [
                _coerce(kd, KeyframeRecipe,
                        f"{path}.channels[{channel_index}].keys[{i}]")
                for i, kd in enumerate(ch.keys or [])]
        recipe.actions.append(act)

    for index, ed in enumerate(data.get("exports", []) or []):
        path = f"recipe.exports[{index}]"
        if not isinstance(ed, dict) and not isinstance(ed, ExportRecipe):
            raise RecipeValidationError(
                "invalid_type",
                f"export definition must be a JSON object, got {type(ed).__name__}",
                path=path,
                hint="Provide a dictionary with 'format' and 'path'.")
        ex = _coerce(ed, ExportRecipe, path)
        if isinstance(ex.format, str):
            ex.format = normalize_export_format(ex.format)
        recipe.exports.append(ex)

    return recipe


def validate_recipe(recipe: Recipe, *, ai_mode: bool = False) -> list:
    """Validate *recipe* and collect all schema and registry issues."""
    problems: list[ValidationIssue] = []

    def registry_issues(category, name, values, path):
        for issue in validate_parameters(category, name, values, path):
            problems.append(ValidationIssue(
                f"{issue['path']}: {issue['message']}",
                code=issue["code"], path=issue["path"],
                hint=issue.get("hint")))

    if not isinstance(recipe.name, str):
        problems.append(ValidationIssue(
            f"expected string recipe name, received {type(recipe.name).__name__}",
            code="invalid_type", path="recipe.name"))
    elif not recipe.name:
        problems.append(ValidationIssue(
            "recipe name must not be empty", code="missing_name",
            path="recipe.name"))
    if recipe.version != CURRENT_RECIPE_VERSION:
        problems.append(ValidationIssue(
            f"unsupported recipe version {recipe.version!r}; supported version is {CURRENT_RECIPE_VERSION}",
            code="unsupported_version", path="recipe.version",
            hint=f"Use version {CURRENT_RECIPE_VERSION}."))

    seen_objects = set()
    for index, obj in enumerate(recipe.objects):
        path = f"recipe.objects[{index}]"
        if not isinstance(obj.name, str):
            problems.append(ValidationIssue(
                f"expected string object name, received {type(obj.name).__name__}",
                code="invalid_type", path=f"{path}.name"))
        elif not obj.name:
            problems.append(ValidationIssue(
                "every object needs a 'name'",
                code="missing_name", path=f"{path}.name"))
        elif ai_mode and not AI_OBJECT_NAME_RE.fullmatch(obj.name):
            problems.append(ValidationIssue(
                f"AI object name {obj.name!r} must match {AI_OBJECT_NAME_RE.pattern}",
                code="invalid_name", path=f"{path}.name",
                hint="Use 1–64 letters, digits, spaces, '.', '_' or '-'; start with a letter, digit or underscore."))
        elif obj.name in seen_objects:
            problems.append(ValidationIssue(
                f"duplicate object name {obj.name!r}",
                code="duplicate_name", path=f"{path}.name"))
        if isinstance(obj.name, str):
            seen_objects.add(obj.name)

        if obj.primitive is not None and not isinstance(obj.primitive, str):
            problems.append(ValidationIssue(
                f"expected primitive name string, received {type(obj.primitive).__name__}",
                code="invalid_type", path=f"{path}.primitive"))
        elif obj.primitive is not None and obj.primitive not in PRIMITIVES:
            valid = sorted(PRIMITIVES)
            problems.append(ValidationIssue(
                f"expected primitive in {valid}, received {obj.primitive!r}",
                code="unsupported_primitive", path=f"{path}.primitive",
                hint=f"Choose from {valid}"))

        valid_object_params = {"auto_weights", "skeleton"}
        primitive_is_known = (isinstance(obj.primitive, str) and
                              obj.primitive in PRIMITIVES)
        if primitive_is_known:
            valid_object_params |= set(CAPABILITIES[("primitive", obj.primitive)].params)
        params = obj.params
        if not isinstance(params, dict):
            registry_issues("object_metadata", "object", params,
                            f"{path}.params")
        else:
            primitive_params = {key: value for key, value in params.items()
                                if key not in valid_object_params or
                                key not in {"auto_weights", "skeleton"}}
            if primitive_is_known:
                registry_issues("primitive", obj.primitive,
                                primitive_params, f"{path}.params")
            elif primitive_params:
                for key in sorted(primitive_params):
                    problems.append(ValidationIssue(
                        f"unknown object parameter {key!r}; valid keys: {sorted(valid_object_params)}",
                        code="unknown_parameter", path=f"{path}.params.{key}",
                        hint=f"Use one of: {sorted(valid_object_params)}."))
            metadata_params = {key: value for key, value in params.items()
                               if key in {"auto_weights", "skeleton"}}
            registry_issues("object_metadata", "object", metadata_params,
                            f"{path}.params")

        if obj.primitive is None and not obj.splines and not obj.bones:
            problems.append(ValidationIssue(
                f"object {obj.name!r}: no primitive, splines or bones",
                code="empty_object", path=path,
                hint="Specify a primitive or add splines/bones."))

        bone_names = set()
        for b_idx, bone in enumerate(obj.bones):
            b_path = f"{path}.bones[{b_idx}]"
            if not isinstance(bone.name, str):
                problems.append(ValidationIssue(
                    f"expected string bone name, received {type(bone.name).__name__}",
                    code="invalid_type", path=f"{b_path}.name"))
            elif not bone.name:
                problems.append(ValidationIssue(
                    f"object {obj.name!r}: bone at index {b_idx} has no name",
                    code="missing_name", path=f"{b_path}.name"))
            elif bone.name in bone_names:
                problems.append(ValidationIssue(
                    f"object {obj.name!r}: duplicate bone name {bone.name!r}",
                    code="duplicate_bone_name", path=f"{b_path}.name"))
            if isinstance(bone.name, str):
                bone_names.add(bone.name)
            if bone.parent is not None and not isinstance(bone.parent, str):
                problems.append(ValidationIssue(
                    f"expected string or null bone parent, received {type(bone.parent).__name__}",
                    code="invalid_type", path=f"{b_path}.parent"))

        for spline_idx, spline in enumerate(obj.splines):
            if not isinstance(spline.name, str):
                problems.append(ValidationIssue(
                    f"expected string spline name, received {type(spline.name).__name__}",
                    code="invalid_type", path=f"{path}.splines[{spline_idx}].name"))

        for b_idx, bone in enumerate(obj.bones):
            b_path = f"{path}.bones[{b_idx}]"
            if (isinstance(bone.parent, str) and bone.parent and
                    bone.parent not in bone_names):
                problems.append(ValidationIssue(
                    f"object {obj.name!r}: bone {bone.name!r} references unknown parent {bone.parent!r}",
                    code="missing_parent_bone", path=f"{b_path}.parent"))

        # Bone hierarchy cycle detection
        parent_map = {b.name: b.parent for b in obj.bones
                      if isinstance(b.name, str) and isinstance(b.parent, str)
                      and b.parent}
        for b_idx, bone in enumerate(obj.bones):
            if not isinstance(bone.name, str):
                continue
            visited = {bone.name}
            curr = bone.parent
            while isinstance(curr, str) and curr:
                if curr in visited:
                    problems.append(ValidationIssue(
                        f"object {obj.name!r}: cyclic bone hierarchy detected involving bone {bone.name!r}",
                        code="cyclic_bone_hierarchy",
                        path=f"{path}.bones[{b_idx}].parent",
                        hint="Ensure bone parent references form an acyclic tree."))
                    break
                visited.add(curr)
                curr = parent_map.get(curr)

        for b_idx, bone in enumerate(obj.bones):
            for w_field in ("weights", "cp_weights"):
                raw_w = getattr(bone, w_field, None)
                if raw_w:
                    w_path = f"{path}.bones[{b_idx}].{w_field}"
                    if not isinstance(raw_w, dict):
                        problems.append(ValidationIssue(f"{w_path} must be a dictionary", code="invalid_type", path=w_path))
                    else:
                        for k, v in raw_w.items():
                            try:
                                ik = int(k)
                                if ik < 0:
                                    problems.append(ValidationIssue(f"{w_path}: control point index must be non-negative", code="invalid_value", path=w_path))
                                    break
                            except (ValueError, TypeError):
                                problems.append(ValidationIssue(f"{w_path}: control point key {k!r} must be an integer", code="invalid_key", path=w_path))
                                break
                            if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
                                problems.append(ValidationIssue(f"{w_path}: weight for CP {k} must be a non-negative finite number", code="invalid_value", path=w_path))
                                break

        if getattr(obj, "transform", None):
            t_path = f"{path}.transform"
            t = obj.transform
            if not isinstance(t, (list, tuple)):
                problems.append(ValidationIssue(f"object {obj.name!r}: transform must be a list", code="invalid_type", path=t_path))
            else:
                has_invalid = False
                flat_items = []
                for row in t:
                    if isinstance(row, (list, tuple)):
                        for item in row:
                            flat_items.append(item)
                    else:
                        flat_items.append(row)
                for item in flat_items:
                    if isinstance(item, bool) or not isinstance(item, (int, float)):
                        problems.append(ValidationIssue(f"object {obj.name!r}: transform elements must be numbers", code="invalid_value", path=t_path))
                        has_invalid = True
                        break
                if not has_invalid:
                    t_arr = np.asarray(t, dtype=np.float64)
                    if not np.all(np.isfinite(t_arr)):
                        problems.append(ValidationIssue(f"object {obj.name!r}: transform values must be finite", code="invalid_value", path=t_path))
                    elif t_arr.shape == (4, 4) or t_arr.size == 16:
                        m = t_arr.reshape(4, 4)
                        det = float(np.linalg.det(m[:3, :3]))
                        if abs(det) < 1e-12:
                            problems.append(ValidationIssue(f"object {obj.name!r}: transform matrix has near-zero determinant ({det:.3e}) and is singular", code="singular_transform", path=t_path, hint="Ensure transform scale factors are non-zero."))
                    elif t_arr.size != 3:
                        problems.append(ValidationIssue(f"object {obj.name!r}: transform must be 16 elements (4x4) or 3 elements (translation)", code="invalid_shape", path=t_path))

    # Check params.skeleton references
    obj_names = {o.name for o in recipe.objects
                 if isinstance(o.name, str)}
    for index, obj in enumerate(recipe.objects):
        skel_ref = obj.params.get("skeleton") if isinstance(obj.params, dict) else None
        if skel_ref and skel_ref not in obj_names:
            problems.append(ValidationIssue(
                f"object {obj.name!r} references nonexistent skeleton {skel_ref!r}",
                code="missing_reference",
                path=f"recipe.objects[{index}].params.skeleton",
                hint="The referenced skeleton object must exist in recipe.objects."
            ))

    seen_materials = set()
    for index, material in enumerate(recipe.materials):
        path = f"recipe.materials[{index}]"
        if not isinstance(material.name, str):
            problems.append(ValidationIssue(
                f"expected string material name, received {type(material.name).__name__}",
                code="invalid_type", path=f"{path}.name"))
        elif not material.name:
            problems.append(ValidationIssue(
                "material name must not be empty",
                code="missing_name", path=f"{path}.name"))
        elif material.name in seen_materials:
            problems.append(ValidationIssue(
                f"duplicate material name {material.name!r}",
                code="duplicate_material_name", path=f"{path}.name"))
        if isinstance(material.name, str):
            seen_materials.add(material.name)

        if material.pattern is not None:
            if not isinstance(material.pattern, str):
                problems.append(ValidationIssue(
                    f"expected pattern name string, received {type(material.pattern).__name__}",
                    code="invalid_type", path=f"{path}.pattern"))
            elif material.pattern not in {cap.name for cap in capabilities_for("pattern")}:
                valid = sorted(cap.name for cap in capabilities_for("pattern"))
                problems.append(ValidationIssue(
                    f"expected material pattern in {valid}, received {material.pattern!r}",
                    code="unsupported_pattern", path=f"{path}.pattern",
                    hint=f"Choose from {valid}."))
            else:
                registry_issues("pattern", material.pattern, material.params,
                                f"{path}.params")
        elif material.params not in ({}, None):
            problems.append(ValidationIssue(
                "material params require a recognized pattern",
                code="unexpected_parameter", path=f"{path}.params"))

        if not isinstance(material.graph, list):
            problems.append(ValidationIssue(
                f"expected graph node list, received {type(material.graph).__name__}",
                code="invalid_type", path=f"{path}.graph"))
        else:
            graph_names = {cap.name for cap in capabilities_for("graph_node")}
            for node_index, node in enumerate(material.graph):
                n_path = f"{path}.graph[{node_index}]"
                if not isinstance(node, dict):
                    problems.append(ValidationIssue(
                        f"expected graph node object, received {type(node).__name__}",
                        code="invalid_type", path=n_path))
                    continue
                unknown_node_fields = sorted(set(node) - {"type", "params"})
                for key in unknown_node_fields:
                    problems.append(ValidationIssue(
                        f"unknown graph node field {key!r}; valid keys: ['params', 'type']",
                        code="unknown_field", path=f"{n_path}.{key}"))
                node_name = node.get("type", "source")
                if not isinstance(node_name, str):
                    problems.append(ValidationIssue(
                        f"expected graph node type string, received {type(node_name).__name__}",
                        code="invalid_type", path=f"{n_path}.type"))
                    continue
                if node_name not in graph_names:
                    valid = sorted(graph_names)
                    problems.append(ValidationIssue(
                        f"expected graph node in {valid}, received {node_name!r}",
                        code="unsupported_node", path=f"{n_path}.type",
                        hint=f"Choose from {valid}."))
                    continue
                cap = CAPABILITIES[("graph_node", node_name)]
                if ai_mode and not cap.model_visible:
                    problems.append(ValidationIssue(
                        f"graph node {node_name!r} is not available in AI mode",
                        code="unsupported_capability", path=f"{n_path}.type"))
                registry_issues("graph_node", node_name,
                                node.get("params", {}), f"{n_path}.params")

        if not (0.0 <= material.roughness <= 1.0) or not math.isfinite(material.roughness):
            problems.append(ValidationIssue(
                f"material {material.name!r}: roughness must be between 0.0 and 1.0",
                code="invalid_value", path=f"{path}.roughness"))
        if not (0.0 <= material.metalness <= 1.0) or not math.isfinite(material.metalness):
            problems.append(ValidationIssue(
                f"material {material.name!r}: metalness must be between 0.0 and 1.0",
                code="invalid_value", path=f"{path}.metalness"))

        if not isinstance(material.objects, list):
            problems.append(ValidationIssue(
                f"expected object name list, received {type(material.objects).__name__}",
                code="invalid_type", path=f"{path}.objects"))
        for obj_idx, target_obj in enumerate(material.objects if isinstance(material.objects, list) else []):
            if not isinstance(target_obj, str):
                problems.append(ValidationIssue(
                    f"expected string object name, received {type(target_obj).__name__}",
                    code="invalid_type", path=f"{path}.objects[{obj_idx}]"))
                continue
            if target_obj not in seen_objects:
                problems.append(ValidationIssue(
                    f"material {material.name!r} coats unknown object {target_obj!r}",
                    code="unknown_target_object", path=f"{path}.objects",
                    hint=f"Target one of the defined objects: {sorted(seen_objects)}"))

    object_bones = {o.name: [b.name for b in o.bones or []]
                    for o in recipe.objects if isinstance(o.name, str)}
    defined_actions = set()
    for index, act in enumerate(recipe.actions):
        path = f"recipe.actions[{index}]"
        if not isinstance(act.name, str):
            problems.append(ValidationIssue(
                f"expected string action name, received {type(act.name).__name__}",
                code="invalid_type", path=f"{path}.name"))
        elif not act.name:
            problems.append(ValidationIssue(
                "action name must not be empty",
                code="missing_name", path=f"{path}.name"))
        elif act.name in defined_actions:
            problems.append(ValidationIssue(
                f"duplicate action name {act.name!r}",
                code="duplicate_action_name", path=f"{path}.name"))
        if isinstance(act.name, str):
            defined_actions.add(act.name)

        if not isinstance(act.kind, str):
            problems.append(ValidationIssue(
                f"expected action kind string, received {type(act.kind).__name__}",
                code="invalid_type", path=f"{path}.kind"))
        elif act.kind not in ACTION_KINDS:
            valid = sorted(ACTION_KINDS)
            problems.append(ValidationIssue(
                f"expected action kind in {valid}, received {act.kind!r}",
                code="unsupported_action_kind", path=f"{path}.kind",
                hint=f"Choose from {valid}."))
        else:
            registry_issues("action_kind", act.kind, act.params,
                            f"{path}.params")

        if not math.isfinite(act.duration) or act.duration <= 0:
            problems.append(ValidationIssue(
                f"action {act.name!r}: duration must be a positive number",
                code="invalid_value", path=f"{path}.duration"))

        if act.character is not None and not isinstance(act.character, str):
            problems.append(ValidationIssue(
                f"expected string or null character, received {type(act.character).__name__}",
                code="invalid_type", path=f"{path}.character"))
        elif act.character and act.character not in seen_objects:
            problems.append(ValidationIssue(
                f"action {act.name!r}: unknown character {act.character!r}",
                code="unknown_character", path=f"{path}.character"))
        elif act.character and not object_bones.get(act.character):
            problems.append(ValidationIssue(
                f"action {act.name!r}: character {act.character!r} declares no bones, so the action cannot be applied to it",
                code="action_precondition", path=f"{path}.character"))
        if act.character and act.character in object_bones:
            char_bones = set(object_bones[act.character])
            for ch_idx, ch in enumerate(act.channels or []):
                if isinstance(ch.bone, str) and ch.bone and ch.bone not in char_bones:
                    problems.append(ValidationIssue(
                        f"action {act.name!r}: channel {ch_idx} references unknown bone {ch.bone!r} for character {act.character!r}",
                        code="unknown_bone",
                        path=f"{path}.channels[{ch_idx}].bone",
                        hint=f"Choose from character bones: {sorted(char_bones)}"))

        for channel_index, channel in enumerate(act.channels or []):
            ch_path = f"{path}.channels[{channel_index}]"
            if not isinstance(channel.bone, str):
                problems.append(ValidationIssue(
                    f"expected string bone name, received {type(channel.bone).__name__}",
                    code="invalid_type", path=f"{ch_path}.bone"))
            if not isinstance(channel.property, str):
                problems.append(ValidationIssue(
                    f"expected channel property string, received {type(channel.property).__name__}",
                    code="invalid_type", path=f"{ch_path}.property"))
            elif ("channel_property", channel.property) not in CAPABILITIES:
                valid = sorted(cap.name for cap in capabilities_for("channel_property"))
                problems.append(ValidationIssue(
                    f"expected channel property in {valid}, received {channel.property!r}",
                    code="unsupported_channel_property", path=f"{ch_path}.property",
                    hint=f"Choose from {valid}."))
            for key_index, key in enumerate(channel.keys or []):
                k_path = f"{ch_path}.keys[{key_index}]"
                if not isinstance(key.interp, str):
                    problems.append(ValidationIssue(
                        f"expected interpolation string, received {type(key.interp).__name__}",
                        code="invalid_type", path=f"{k_path}.interp"))
                elif ("interpolation", key.interp) not in CAPABILITIES:
                    valid = sorted(cap.name for cap in capabilities_for("interpolation"))
                    problems.append(ValidationIssue(
                        f"expected interpolation in {valid}, received {key.interp!r}",
                        code="unsupported_interpolation", path=f"{k_path}.interp",
                        hint=f"Choose from {valid}."))
                expected_value_len = 1 if channel.property == "weight" else 3
                if isinstance(key.value, (list, tuple)) and len(key.value) != expected_value_len:
                    problems.append(ValidationIssue(
                        f"expected {expected_value_len} values for channel property {channel.property!r}, received {len(key.value)}",
                        code="invalid_length", path=f"{k_path}.value"))

        if act.kind == "retarget":
            if not act.character:
                problems.append(ValidationIssue(
                    f"action {act.name!r}: retarget needs a character",
                    code="action_precondition", path=f"{path}.character"))
            if not act.source_action:
                problems.append(ValidationIssue(
                    f"action {act.name!r}: retarget needs source_action",
                    code="action_precondition", path=f"{path}.source_action"))
            elif act.source_action not in defined_actions:
                problems.append(ValidationIssue(
                    f"action {act.name!r}: source_action {act.source_action!r} is not defined earlier in this recipe (sources must precede the actions that use them)",
                    code="missing_reference", path=f"{path}.source_action"))
        elif act.kind != "custom" and not act.character:
            problems.append(ValidationIssue(
                f"action {act.name!r}: procedural kind {act.kind!r} needs a character with bones",
                code="action_precondition", path=f"{path}.character"))

    for index, ex in enumerate(recipe.exports):
        path = f"recipe.exports[{index}]"
        if not isinstance(ex.format, str):
            problems.append(ValidationIssue(
                f"expected export format string, received {type(ex.format).__name__}",
                code="invalid_type", path=f"{path}.format"))
        elif normalize_export_format(ex.format) not in EXPORT_FORMATS:
            valid = sorted(EXPORT_FORMATS | set(_FORMAT_ALIASES))
            problems.append(ValidationIssue(
                f"expected export format in {valid}, received {ex.format!r}",
                code="unsupported_export_format", path=f"{path}.format",
                hint=f"Choose from {valid}."))
        else:
            registry_issues("export_format", normalize_export_format(ex.format),
                            ex.params, f"{path}.params")
        if not isinstance(ex.path, str):
            problems.append(ValidationIssue(
                f"expected export path string, received {type(ex.path).__name__}",
                code="invalid_type", path=f"{path}.path"))
        elif not ex.path:
            problems.append(ValidationIssue(
                f"export format {ex.format!r} has empty path",
                code="missing_path", path=f"{path}.path"))

    return problems
