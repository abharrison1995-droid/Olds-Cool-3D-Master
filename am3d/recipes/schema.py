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


# Primitive names accepted in ObjectRecipe.primitive.
PRIMITIVES = frozenset({
    "sphere", "box", "cylinder", "cone", "torus", "plane",
    "lathe", "extrude",
})

# Procedural action generators accepted in ActionRecipe.kind.
ACTION_KINDS = frozenset({"walk", "idle", "jump", "custom", "retarget"})

# Only formats ``RecipeExecutor._run_exports`` actually writes belong here.
# Advertising a format with no writer makes the run report success while
# producing no file, so this set and that dispatch must stay in step.
EXPORT_FORMATS = frozenset({"obj", "glb", "spritesheet",
                            "toon_sheet", "am3d"})

# Accepted spellings that are not writer names in their own right.
_FORMAT_ALIASES = {"gltf": "glb"}      # we always emit binary glTF


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


@dataclass
class ObjectRecipe:
    """One scene object: either a primitive or hand-authored splines."""

    name: str
    primitive: str | None = None          # see PRIMITIVES
    params: dict = field(default_factory=dict)
    splines: list = field(default_factory=list)   # list[SplineRecipe | dict]
    bones: list = field(default_factory=list)     # list[BoneRecipe | dict]


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


def recipe_from_dict(data: dict) -> Recipe:
    """Build a validated :class:`Recipe` from a plain dict (parsed JSON)."""
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

    recipe = Recipe(version=version, name=str(data.get("name", "asset")))

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
        if obj.primitive is not None and obj.primitive not in PRIMITIVES:
            raise RecipeValidationError(
                "unsupported_primitive",
                f"object {obj.name!r}: unknown primitive {obj.primitive!r} "
                f"(choose from {sorted(PRIMITIVES)})",
                path=f"{path}.primitive")
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
        if act.kind not in ACTION_KINDS:
            raise RecipeValidationError(
                "unsupported_action_kind",
                f"action {act.name!r}: unknown kind {act.kind!r} "
                f"(choose from {sorted(ACTION_KINDS)})",
                path=f"{path}.kind")
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
        fmt = normalize_export_format(ex.format)
        if fmt not in EXPORT_FORMATS:
            raise RecipeValidationError(
                "unsupported_export_format",
                f"unknown export format {ex.format!r} "
                f"(choose from {sorted(EXPORT_FORMATS)})",
                path=f"{path}.format")
        ex.format = fmt
        recipe.exports.append(ex)

    return recipe


def validate_recipe(recipe: Recipe) -> list:
    """Validate *recipe*, returning a list of :class:`ValidationIssue` strings."""
    problems: list[ValidationIssue] = []
    if recipe.version != CURRENT_RECIPE_VERSION:
        problems.append(ValidationIssue(
            f"unsupported recipe version {recipe.version!r}; supported version is {CURRENT_RECIPE_VERSION}",
            code="unsupported_version", path="recipe.version",
            hint=f"Use version {CURRENT_RECIPE_VERSION}."))

    seen_objects = set()
    for index, obj in enumerate(recipe.objects):
        path = f"recipe.objects[{index}]"
        if not obj.name:
            problems.append(ValidationIssue(
                "every object needs a 'name'",
                code="missing_name", path=f"{path}.name"))
        elif obj.name in seen_objects:
            problems.append(ValidationIssue(
                f"duplicate object name {obj.name!r}",
                code="duplicate_name", path=f"{path}.name"))
        seen_objects.add(obj.name)

        if obj.primitive is not None and obj.primitive not in PRIMITIVES:
            problems.append(ValidationIssue(
                f"object {obj.name!r}: unknown primitive {obj.primitive!r} (choose from {sorted(PRIMITIVES)})",
                code="unsupported_primitive", path=f"{path}.primitive",
                hint=f"Choose from {sorted(PRIMITIVES)}"))

        if obj.primitive is None and not obj.splines and not obj.bones:
            problems.append(ValidationIssue(
                f"object {obj.name!r}: no primitive, splines or bones",
                code="empty_object", path=path,
                hint="Specify a primitive or add splines/bones."))

        bone_names = set()
        for b_idx, bone in enumerate(obj.bones):
            b_path = f"{path}.bones[{b_idx}]"
            if not bone.name:
                problems.append(ValidationIssue(
                    f"object {obj.name!r}: bone at index {b_idx} has no name",
                    code="missing_name", path=f"{b_path}.name"))
            elif bone.name in bone_names:
                problems.append(ValidationIssue(
                    f"object {obj.name!r}: duplicate bone name {bone.name!r}",
                    code="duplicate_bone_name", path=f"{b_path}.name"))
            bone_names.add(bone.name)

        for b_idx, bone in enumerate(obj.bones):
            b_path = f"{path}.bones[{b_idx}]"
            if bone.parent and bone.parent not in bone_names:
                problems.append(ValidationIssue(
                    f"object {obj.name!r}: bone {bone.name!r} references unknown parent {bone.parent!r}",
                    code="missing_parent_bone", path=f"{b_path}.parent"))

        # Bone hierarchy cycle detection
        parent_map = {b.name: b.parent for b in obj.bones if b.parent}
        for b_idx, bone in enumerate(obj.bones):
            visited = {bone.name}
            curr = bone.parent
            while curr:
                if curr in visited:
                    problems.append(ValidationIssue(
                        f"object {obj.name!r}: cyclic bone hierarchy detected involving bone {bone.name!r}",
                        code="cyclic_bone_hierarchy",
                        path=f"{path}.bones[{b_idx}].parent",
                        hint="Ensure bone parent references form an acyclic tree."))
                    break
                visited.add(curr)
                curr = parent_map.get(curr)

    seen_materials = set()
    for index, material in enumerate(recipe.materials):
        path = f"recipe.materials[{index}]"
        if not material.name:
            problems.append(ValidationIssue(
                "material name must not be empty",
                code="missing_name", path=f"{path}.name"))
        elif material.name in seen_materials:
            problems.append(ValidationIssue(
                f"duplicate material name {material.name!r}",
                code="duplicate_material_name", path=f"{path}.name"))
        seen_materials.add(material.name)

        if not (0.0 <= material.roughness <= 1.0) or not math.isfinite(material.roughness):
            problems.append(ValidationIssue(
                f"material {material.name!r}: roughness must be between 0.0 and 1.0",
                code="invalid_value", path=f"{path}.roughness"))
        if not (0.0 <= material.metalness <= 1.0) or not math.isfinite(material.metalness):
            problems.append(ValidationIssue(
                f"material {material.name!r}: metalness must be between 0.0 and 1.0",
                code="invalid_value", path=f"{path}.metalness"))

        for target_obj in material.objects:
            if target_obj not in seen_objects:
                problems.append(ValidationIssue(
                    f"material {material.name!r} coats unknown object {target_obj!r}",
                    code="unknown_target_object", path=f"{path}.objects",
                    hint=f"Target one of the defined objects: {sorted(seen_objects)}"))

    object_bones = {o.name: [b.name for b in o.bones or []] for o in recipe.objects}
    defined_actions = set()
    for index, act in enumerate(recipe.actions):
        path = f"recipe.actions[{index}]"
        if not act.name:
            problems.append(ValidationIssue(
                "action name must not be empty",
                code="missing_name", path=f"{path}.name"))
        elif act.name in defined_actions:
            problems.append(ValidationIssue(
                f"duplicate action name {act.name!r}",
                code="duplicate_action_name", path=f"{path}.name"))
        defined_actions.add(act.name)

        if act.kind not in ACTION_KINDS:
            problems.append(ValidationIssue(
                f"action {act.name!r}: unknown kind {act.kind!r} (choose from {sorted(ACTION_KINDS)})",
                code="unsupported_action_kind", path=f"{path}.kind"))

        if not math.isfinite(act.duration) or act.duration <= 0:
            problems.append(ValidationIssue(
                f"action {act.name!r}: duration must be a positive number",
                code="invalid_value", path=f"{path}.duration"))

        if act.character and act.character not in seen_objects:
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
                if ch.bone and ch.bone not in char_bones:
                    problems.append(ValidationIssue(
                        f"action {act.name!r}: channel {ch_idx} references unknown bone {ch.bone!r} for character {act.character!r}",
                        code="unknown_bone",
                        path=f"{path}.channels[{ch_idx}].bone",
                        hint=f"Choose from character bones: {sorted(char_bones)}"))

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
        if not ex.path:
            problems.append(ValidationIssue(
                f"export format {ex.format!r} has empty path",
                code="missing_path", path=f"{path}.path"))
        if normalize_export_format(ex.format) not in EXPORT_FORMATS:
            problems.append(ValidationIssue(
                f"export {ex.path!r}: unknown format {ex.format!r} (choose from {sorted(EXPORT_FORMATS)})",
                code="unsupported_export_format", path=f"{path}.format"))

    return problems
