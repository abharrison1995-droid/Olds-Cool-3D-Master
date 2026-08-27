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
def _coerce(value, cls):
    if isinstance(value, cls):
        return value
    if isinstance(value, dict):
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in value.items() if k in known})
    raise TypeError(f"cannot coerce {type(value).__name__} into {cls.__name__}")


def recipe_from_dict(data: dict) -> Recipe:
    """Build a validated :class:`Recipe` from a plain dict (parsed JSON)."""
    if not isinstance(data, dict):
        raise ValueError("recipe root must be a JSON object")

    recipe = Recipe(name=str(data.get("name", "asset")))

    for od in data.get("objects", []) or []:
        obj = _coerce(od, ObjectRecipe)
        if not obj.name:
            raise ValueError("every object needs a 'name'")
        if obj.primitive is not None and obj.primitive not in PRIMITIVES:
            raise ValueError(
                f"object {obj.name!r}: unknown primitive {obj.primitive!r} "
                f"(choose from {sorted(PRIMITIVES)})")
        obj.splines = [_coerce(sd, SplineRecipe) for sd in obj.splines or []]
        obj.bones = [_coerce(bd, BoneRecipe) for bd in obj.bones or []]
        recipe.objects.append(obj)

    for md in data.get("materials", []) or []:
        recipe.materials.append(_coerce(md, MaterialRecipe))

    for ad in data.get("actions", []) or []:
        act = _coerce(ad, ActionRecipe)
        if act.kind not in ACTION_KINDS:
            raise ValueError(
                f"action {act.name!r}: unknown kind {act.kind!r} "
                f"(choose from {sorted(ACTION_KINDS)})")
        act.channels = [_coerce(cd, ChannelRecipe)
                        for cd in act.channels or []]
        for ch in act.channels:
            ch.keys = [_coerce(kd, KeyframeRecipe) for kd in ch.keys or []]
        recipe.actions.append(act)

    for ed in data.get("exports", []) or []:
        ex = _coerce(ed, ExportRecipe)
        fmt = normalize_export_format(ex.format)
        if fmt not in EXPORT_FORMATS:
            raise ValueError(
                f"unknown export format {ex.format!r} "
                f"(choose from {sorted(EXPORT_FORMATS)})")
        ex.format = fmt
        recipe.exports.append(ex)

    return recipe


def validate_recipe(recipe: Recipe) -> list:
    """Human-readable problems with *recipe* ([] means it is good)."""
    problems = []
    seen_objects = set()
    for obj in recipe.objects:
        if obj.name in seen_objects:
            problems.append(f"duplicate object name {obj.name!r}")
        seen_objects.add(obj.name)
        if obj.primitive is None and not obj.splines and not obj.bones:
            problems.append(
                f"object {obj.name!r}: no primitive, splines or bones")
        bone_names = {b.name for b in obj.bones}
        for bone in obj.bones:
            if bone.parent and bone.parent not in bone_names:
                problems.append(
                    f"object {obj.name!r}: bone {bone.name!r} references "
                    f"unknown parent {bone.parent!r}")
    for act in recipe.actions:
        if act.character and act.character not in seen_objects:
            problems.append(
                f"action {act.name!r}: unknown character {act.character!r}")
    for ex in recipe.exports:
        if normalize_export_format(ex.format) not in EXPORT_FORMATS:
            problems.append(
                f"export {ex.path!r}: unknown format {ex.format!r} "
                f"(choose from {sorted(EXPORT_FORMATS)})")
    return problems