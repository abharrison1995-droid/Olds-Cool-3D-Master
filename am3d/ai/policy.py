"""Typed, bounded preflight for AI-authored recipe-v1 data.

This is application policy for untrusted *data*, not an OS sandbox.  It runs
before the recipe executor allocates geometry or decodes/bakes textures.
"""

from __future__ import annotations

import math
import re
import unicodedata
import json
from typing import Any

from am3d.core.paths import classify_portable_relative_path
from am3d.recipes.schema import (
    EXPORT_FORMATS,
    RecipeValidationError,
    normalize_export_format,
    recipe_from_dict,
    validate_recipe,
)


MAX_RECIPE_BYTES = 512 * 1024
MAX_OBJECTS = 128
MAX_PATCHES = 1024
MAX_BONES_PER_RIG = 64
MAX_TOTAL_BONES = 256
MAX_ACTIONS = 16
MAX_CHANNELS = 256
MAX_KEYS = 4096
MAX_AUTHORED_POINTS = 4096
MAX_SUBDIVISIONS = 128
MAX_MATERIALS = 32
MAX_GRAPH_NODES = 32
MAX_EVALUATED_TRIANGLES = 250_000
TESS_U = 16
TESS_V = 16
MAX_PREVIEW_PIXELS = 512 * 512
MAX_SHEETS = 16
MAX_SHEET_CELL_SIZE = 256
MAX_SHEET_PIXELS = 16_000_000
MAX_ATLAS_PIXELS = 64_000_000
MAX_ESTIMATED_MEMORY = 1024 * 1024 * 1024
MAX_OUTPUT_BYTES = 256 * 1024 * 1024
MAX_WORKER_SECONDS = 180.0

_MAX_NESTING = 24
_MAX_JSON_NODES = 100_000
_MAX_SCALAR_BYTES = MAX_RECIPE_BYTES
_MAX_COORDINATE = 1_000_000.0
_CONTROL_POINT_BYTES = 128
_TRIANGLE_BYTES = 160
_TEXTURE_FLOAT_BYTES = 8

_RESOURCE_KEYS = {
    "path", "filepath", "file_path", "filename", "file", "uri", "url",
    "resource", "resource_path", "image", "image_path", "texture",
    "texture_path", "texture_file", "normal_map", "bump_map",
    "transparency_map", "specular_map", "albedo_map", "environment_map",
}
_UNTRUSTED_CODE_KEYS = {
    "code", "python", "script", "shell", "command", "callback", "module",
    "import", "imports", "exec", "eval",
}
_UNTRUSTED_VERBS = {
    "python", "script", "shell", "command", "exec", "eval", "import",
    "fetch", "http", "https", "download", "callback", "file_read",
    "file_write",
}


class PolicyError(ValueError):
    """A terminal AI policy denial with stable, path-safe diagnostics."""

    def __init__(self, code: str, message: str, *, path: str = "recipe"):
        self.code = code
        self.stage = "policy"
        self.path = path
        self.hint = None
        super().__init__(message)

    def to_record(self) -> dict[str, str]:
        return {"code": self.code, "stage": self.stage, "path": self.path,
                "message": str(self)}


def _invalid(code: str, message: str, path: str) -> None:
    raise RecipeValidationError(code, message, path=path, stage="policy-preflight")


def _finite(value: Any, path: str, *, positive: bool = False,
            minimum: float | None = None, maximum: float = _MAX_COORDINATE) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        _invalid("invalid_type", f"{path} must be a finite number", path)
    try:
        number = float(value)
    except OverflowError:
        _invalid("invalid_value", f"{path} is outside the finite numeric range", path)
    if not math.isfinite(number) or abs(number) > maximum:
        _invalid("invalid_value", f"{path} is outside the finite numeric range", path)
    if positive and number <= 0:
        _invalid("invalid_value", f"{path} must be greater than zero", path)
    if minimum is not None and number < minimum:
        _invalid("invalid_value", f"{path} must be at least {minimum:g}", path)
    return number


def _integer(value: Any, path: str, low: int, high: int) -> int:
    if type(value) is not int:
        _invalid("invalid_type", f"{path} must be an integer", path)
    if value < low or value > high:
        _invalid("resource_limit", f"{path} must be between {low} and {high}", path)
    return value


def _list(value: Any, path: str, *, maximum: int, minimum: int = 0) -> list:
    if not isinstance(value, list):
        _invalid("invalid_type", f"{path} must be a list", path)
    if len(value) < minimum:
        _invalid("invalid_length", f"{path} needs at least {minimum} items", path)
    if len(value) > maximum:
        raise PolicyError("resource_limit", f"{path} exceeds its item limit", path=path)
    return value


def _optional_list(value: Any, path: str, *, maximum: int,
                   minimum: int = 0) -> list:
    if value is None:
        return []
    return _list(value, path, maximum=maximum, minimum=minimum)


def _mapping(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        _invalid("invalid_type", f"{path} must be an object", path)
    return value


def _check_data_tree(root: Any) -> None:
    """Bound a plain-JSON object tree without serializing/copying it first."""
    stack = [(root, "recipe", 0, False)]
    active: set[int] = set()
    nodes = 0
    scalar_bytes = 0
    while stack:
        value, path, depth, leaving = stack.pop()
        if leaving:
            active.remove(id(value))
            continue
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise PolicyError("resource_limit", "recipe structure exceeds its item limit")
        if depth > _MAX_NESTING:
            raise PolicyError("resource_limit", "recipe nesting exceeds its depth limit", path=path)
        if value is None or type(value) is bool:
            continue
        if type(value) is int:
            if value.bit_length() > 1024:
                _invalid("invalid_value", f"{path} integer is too large", path)
            scalar_bytes += max(1, (value.bit_length() + 7) // 8) + 2
            continue
        if type(value) is float:
            if not math.isfinite(value):
                _invalid("invalid_value", f"{path} must be finite", path)
            scalar_bytes += 16
            continue
        if isinstance(value, str):
            try:
                scalar_bytes += len(value.encode("utf-8", errors="strict"))
            except UnicodeEncodeError:
                _invalid("invalid_value", f"{path} must be valid UTF-8 text", path)
            scalar_bytes += 2
            if scalar_bytes > _MAX_SCALAR_BYTES:
                raise PolicyError("response_too_large", "recipe exceeds the 512 KiB policy limit")
            continue
        if isinstance(value, list) or isinstance(value, dict):
            identity = id(value)
            if identity in active:
                _invalid("invalid_type", f"{path} contains a cyclic value", path)
            active.add(identity)
            stack.append((value, path, depth, True))
            if isinstance(value, list):
                if len(value) > _MAX_JSON_NODES:
                    raise PolicyError("resource_limit", f"{path} exceeds its item limit", path=path)
                for index in range(len(value) - 1, -1, -1):
                    stack.append((value[index], f"{path}[{index}]", depth + 1, False))
            else:
                if len(value) > _MAX_JSON_NODES:
                    raise PolicyError("resource_limit", f"{path} exceeds its item limit", path=path)
                for key, item in reversed(tuple(value.items())):
                    if not isinstance(key, str):
                        _invalid("invalid_type", f"{path} object keys must be strings", path)
                    try:
                        scalar_bytes += len(key.encode("utf-8", errors="strict")) + 4
                        if scalar_bytes > _MAX_SCALAR_BYTES:
                            raise PolicyError("response_too_large", "recipe exceeds the 512 KiB policy limit")
                    except UnicodeEncodeError:
                        _invalid("invalid_value", f"{path} keys must be valid UTF-8", path)
                    stack.append((item, f"{path}.{key}", depth + 1, False))
            continue
        _invalid("invalid_type", f"{path} must contain only JSON values", path)

    if scalar_bytes > _MAX_SCALAR_BYTES:
        raise PolicyError("response_too_large", "recipe exceeds the 512 KiB policy limit")


def _inspect_hostile_fields(value: Any, path: str = "recipe") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            low = key.casefold().replace("-", "_")
            child = f"{path}.{key}"
            if low in _UNTRUSTED_CODE_KEYS and item not in (None, "", [], {}):
                raise PolicyError("unsupported_code", "executable code and commands are not accepted", path=child)
            resource_name = (low in _RESOURCE_KEYS or
                             (low.endswith(("_path", "_file", "_map")) and low != "mapping"))
            if resource_name and item not in (None, "", [], {}):
                # Export paths are checked separately below so an escape is
                # reported before any normalization or host path is created.
                if not (re.fullmatch(r"recipe\.exports\[\d+\]", path) and low == "path"):
                    raise PolicyError("resource_access_denied", "file and URL resources are disabled for AI recipes", path=child)
            _inspect_hostile_fields(item, child)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _inspect_hostile_fields(item, f"{path}[{index}]")


def _check_export_paths(raw: dict) -> None:
    exports = raw.get("exports", [])
    if exports is None:
        return
    if not isinstance(exports, list):
        _invalid("invalid_type", "recipe.exports must be a list", "recipe.exports")
    if len(exports) > MAX_SHEETS:
        raise PolicyError("resource_limit", "recipe has more than 16 export entries", path="recipe.exports")
    for index, export in enumerate(exports):
        if not isinstance(export, dict):
            continue  # schema error, not a path policy decision
        path = export.get("path")
        if path is None and "path" not in export:
            continue
        if not isinstance(path, str):
            _invalid("invalid_type", f"recipe.exports[{index}].path must be text", f"recipe.exports[{index}].path")
        if any(unicodedata.category(char) == "Cc" for char in path):
            raise PolicyError("output_path_denied", "model export path contains control characters", path=f"recipe.exports[{index}].path")
        verdict = classify_portable_relative_path(path)
        if verdict is not None:
            raise PolicyError("output_path_denied", "model export path is unsafe; outputs are assigned by the host", path=f"recipe.exports[{index}].path")


def _check_verb(value: Any, path: str) -> None:
    if isinstance(value, str) and value.casefold() in _UNTRUSTED_VERBS:
        raise PolicyError("unsupported_verb", "recipe requests an unsupported command or resource verb", path=path)


def _vec(value: Any, path: str, sizes: tuple[int, ...] = (3,), *,
         minimum: float | None = None, maximum: float = _MAX_COORDINATE) -> int:
    if not isinstance(value, list) or len(value) not in sizes:
        expected = " or ".join(str(n) for n in sizes)
        _invalid("invalid_shape", f"{path} must be a list of {expected} numbers", path)
    for i, item in enumerate(value):
        number = _finite(item, f"{path}[{i}]", maximum=maximum)
        if minimum is not None and number < minimum:
            _invalid("invalid_value", f"{path}[{i}] is below its allowed range", f"{path}[{i}]")
    return len(value)


def _primitive_preflight(primitive: Any, params: Any, path: str) -> tuple[int, int, int]:
    """Return (patches, generated control points, authored profile points)."""
    if primitive is None:
        primitive = ""
    if not isinstance(primitive, str):
        _invalid("invalid_type", f"{path}.primitive must be a string or null", f"{path}.primitive")
    _check_verb(primitive, f"{path}.primitive")
    params = _mapping(params, f"{path}.params")
    name = primitive.casefold()
    defaults = {
        "sphere": {"radius": 1.0, "sections": 16, "rings": 8},
        "box": {"width": 1.0, "height": 1.0, "depth": 1.0, "n": 4},
        "cylinder": {"radius": .5, "height": 1.0, "sections": 16, "capped": True, "rings": 4},
        "cone": {"radius": .5, "height": 1.0, "sections": 16, "rings": 5},
        "torus": {"major_radius": 1.0, "minor_radius": .3, "major_sections": 24, "minor_sections": 12},
        "plane": {"width": 1.0, "height": 1.0, "n": 4},
        "lathe": {"axis": "y", "sections": 24},
        "extrude": {"height": 1.0, "twist_deg": 0.0, "rings": 4},
    }
    if not name:
        allowed = {"skeleton", "auto_weights"}
        if set(params) - allowed:
            key = sorted(set(params) - allowed)[0]
            _invalid("invalid_field", f"{path}.params.{key} is not used by an object without a primitive", f"{path}.params.{key}")
        return 0, 0, 0
    if name not in defaults:
        _invalid("unsupported_primitive", f"{path}.primitive is not supported", f"{path}.primitive")

    allowed = set(defaults[name])
    if name == "lathe":
        allowed |= {"profile"}
    if name == "extrude":
        allowed |= {"profile"}
    # Rig convenience values are interpreted by the fixed executor, never by
    # the geometry builder.
    allowed |= {"skeleton", "auto_weights"}
    extra = set(params) - allowed
    if extra:
        key = sorted(extra)[0]
        _invalid("unknown_parameter", f"{path}.params.{key} is unsupported", f"{path}.params.{key}")
    values = dict(defaults[name])
    values.update(params)
    for field_name in ("skeleton",):
        if field_name in values and values[field_name] is not None and not isinstance(values[field_name], str):
            _invalid("invalid_type", f"{path}.params.{field_name} must be a name", f"{path}.params.{field_name}")
    if "auto_weights" in values and type(values["auto_weights"]) is not bool:
        _invalid("invalid_type", f"{path}.params.auto_weights must be boolean", f"{path}.params.auto_weights")

    def positive(field_name: str) -> float:
        return _finite(values[field_name], f"{path}.params.{field_name}", positive=True)

    authored = 0
    if name in {"sphere", "cylinder", "cone", "torus"}:
        for field_name in ({"sphere": ("radius",), "cylinder": ("radius", "height"), "cone": ("radius", "height"), "torus": ("major_radius", "minor_radius")}[name]):
            positive(field_name)
    elif name == "box":
        for field_name in ("width", "height", "depth"):
            positive(field_name)
    elif name == "plane":
        for field_name in ("width", "height"):
            positive(field_name)
    if name == "cylinder" and type(values["capped"]) is not bool:
        _invalid("invalid_type", f"{path}.params.capped must be boolean", f"{path}.params.capped")
    if name in {"sphere", "cylinder", "cone", "torus", "lathe"}:
        section_names = {
            "sphere": ("sections",), "cylinder": ("sections",),
            "cone": ("sections",), "torus": ("major_sections", "minor_sections"),
            "lathe": ("sections",),
        }[name]
        for field_name in section_names:
            _integer(values[field_name], f"{path}.params.{field_name}", 4, MAX_SUBDIVISIONS)
    if name in {"sphere", "cylinder", "cone"}:
        _integer(values["rings"], f"{path}.params.rings", 4, MAX_SUBDIVISIONS)
    if name == "torus":
        _integer(values["minor_sections"], f"{path}.params.minor_sections", 4, MAX_SUBDIVISIONS)
    if name in {"box", "plane"}:
        _integer(values["n"], f"{path}.params.n", 3, MAX_SUBDIVISIONS)
    if name == "lathe":
        if values["axis"] not in ("x", "y", "z"):
            _invalid("invalid_value", f"{path}.params.axis must be x, y or z", f"{path}.params.axis")
        profile = _list(values.get("profile"), f"{path}.params.profile", maximum=MAX_AUTHORED_POINTS, minimum=2)
        for i, point in enumerate(profile):
            _vec(point, f"{path}.params.profile[{i}]", sizes=(2,))
        authored = len(profile)
    if name == "extrude":
        profile = _list(values.get("profile"), f"{path}.params.profile", maximum=MAX_AUTHORED_POINTS, minimum=2)
        for i, point in enumerate(profile):
            _vec(point, f"{path}.params.profile[{i}]", sizes=(3,))
        _finite(values["height"], f"{path}.params.height")
        _finite(values["twist_deg"], f"{path}.params.twist_deg")
        _integer(values["rings"], f"{path}.params.rings", 2, MAX_SUBDIVISIONS)
        authored = len(profile)

    if name == "sphere":
        pts = (values["sections"] + 1) * values["rings"]
    elif name == "cylinder":
        pts = (values["sections"] + 1) * (values["rings"] + (2 if values["capped"] else 0))
    elif name == "cone":
        pts = (values["sections"] + 1) * values["rings"]
    elif name == "torus":
        pts = (values["major_sections"] + 1) * (values["minor_sections"] + 1)
    elif name == "box":
        pts = 6 * values["n"] * values["n"]
    elif name == "plane":
        pts = values["n"] * values["n"]
    elif name == "lathe":
        pts = (values["sections"] + 1) * len(values["profile"])
    else:  # extrude
        pts = values["rings"] * len(values["profile"])
    return (6 if name == "box" else 1), pts, authored


def _pattern_params(pattern: str, params: Any, path: str) -> int:
    params = _mapping(params, path)
    signatures = {
        "solid": {"color", "size"},
        "checker": {"a", "b", "cells", "size"},
        "gradient": {"top", "bottom", "size"},
        "noise": {"seed", "size", "octaves", "base", "contrast"},
        "bricks": {"brick", "mortar", "rows", "cols", "mortar_px", "size"},
    }
    if pattern not in signatures:
        _invalid("unsupported_pattern", f"{path} uses an unsupported pattern", path)
    extra = set(params) - signatures[pattern]
    if extra:
        key = sorted(extra)[0]
        _invalid("unknown_parameter", f"{path}.{key} is unsupported", f"{path}.{key}")
    pixels = params.get("size", MAX_SHEET_CELL_SIZE)
    _integer(pixels, f"{path}.size", 1, MAX_SHEET_CELL_SIZE)
    if pattern == "checker":
        _integer(params.get("cells", 8), f"{path}.cells", 1, 256)
        for key in ("a", "b"):
            if key in params:
                _vec(params[key], f"{path}.{key}", sizes=(3, 4), minimum=0, maximum=1)
    if pattern == "gradient":
        for key in ("top", "bottom"):
            if key in params:
                _vec(params[key], f"{path}.{key}", sizes=(3, 4), minimum=0, maximum=1)
    if pattern == "solid" and "color" in params:
        _vec(params["color"], f"{path}.color", sizes=(3, 4), minimum=0, maximum=1)
    if pattern == "noise":
        if "seed" in params:
            _integer(params["seed"], f"{path}.seed", 0, 2**31 - 1)
        _integer(params.get("octaves", 4), f"{path}.octaves", 1, 8)
        if "base" in params:
            _vec(params["base"], f"{path}.base", sizes=(3, 4), minimum=0, maximum=1)
        if "contrast" in params:
            _finite(params["contrast"], f"{path}.contrast", minimum=0, maximum=1)
    if pattern == "bricks":
        _integer(params.get("rows", 8), f"{path}.rows", 1, 256)
        _integer(params.get("cols", 4), f"{path}.cols", 1, 256)
        if "mortar_px" in params:
            _finite(params["mortar_px"], f"{path}.mortar_px", minimum=0, maximum=256)
        for key in ("brick", "mortar"):
            if key in params:
                _vec(params[key], f"{path}.{key}", sizes=(3, 4), minimum=0, maximum=1)
    return pixels * pixels


def _material_preflight(material: dict, index: int) -> tuple[bool, int]:
    path = f"recipe.materials[{index}]"
    if not isinstance(material, dict):
        _invalid("invalid_type", f"{path} must be an object", path)
    texture = material.get("texture")
    if texture not in (None, ""):
        raise PolicyError("resource_access_denied", "file and image textures are disabled for AI recipes", path=f"{path}.texture")
    pattern = material.get("pattern")
    params = material.get("params", {})
    total_tex_px = 0
    if pattern is not None:
        if not isinstance(pattern, str):
            _invalid("invalid_type", f"{path}.pattern must be a string or null", f"{path}.pattern")
        _check_verb(pattern, f"{path}.pattern")
        total_tex_px += _pattern_params(pattern.casefold(), params, f"{path}.params")
    elif params not in ({}, None):
        # Inert material params are easy to misread as active appearance.
        _invalid("invalid_field", f"{path}.params requires a supported pattern", f"{path}.params")
    graph = _optional_list(material.get("graph", []), f"{path}.graph",
                           maximum=MAX_GRAPH_NODES)
    if len(graph) > MAX_GRAPH_NODES:
        raise PolicyError("resource_limit", f"{path}.graph exceeds 32 nodes", path=f"{path}.graph")
    graph_types = {"source", "solid", "checker", "gradient", "noise", "bricks", "mix", "noise_overlay", "tint"}
    graph_params = {
        "source": set(), "solid": {"color", "size"},
        "checker": {"a", "b", "cells", "size"},
        "gradient": {"top", "bottom", "size"},
        "noise": {"seed", "size", "octaves", "base", "contrast"},
        "bricks": {"brick", "mortar", "rows", "cols", "mortar_px", "size"},
        "mix": {"factor"}, "noise_overlay": {"amount", "seed", "octaves"},
        "tint": {"color"},
    }
    for node_index, node in enumerate(graph):
        npath = f"{path}.graph[{node_index}]"
        if not isinstance(node, dict):
            _invalid("invalid_type", f"{npath} must be an object", npath)
        kind = node.get("type", "source")
        if not isinstance(kind, str):
            _invalid("invalid_type", f"{npath}.type must be text", f"{npath}.type")
        _check_verb(kind, f"{npath}.type")
        kind = kind.casefold()
        if kind not in graph_types:
            _invalid("unsupported_graph_node", f"{npath}.type is unsupported", f"{npath}.type")
        params_node = node.get("params", {})
        if not isinstance(params_node, dict):
            _invalid("invalid_type", f"{npath}.params must be an object", f"{npath}.params")
        extra = set(params_node) - graph_params[kind]
        if extra:
            key = sorted(extra)[0]
            _invalid("unknown_parameter", f"{npath}.params.{key} is unsupported", f"{npath}.params.{key}")
        if kind in {"solid", "checker", "gradient", "noise", "bricks"}:
            _pattern_params(kind, params_node, f"{npath}.params")
            total_tex_px += MAX_SHEET_CELL_SIZE * MAX_SHEET_CELL_SIZE
        elif kind == "noise_overlay":
            _finite(params_node.get("amount", .15), f"{npath}.params.amount", minimum=0, maximum=1)
            _integer(params_node.get("seed", 7), f"{npath}.params.seed", 0, 2**31 - 1)
            _integer(params_node.get("octaves", 3), f"{npath}.params.octaves", 1, 8)
            total_tex_px += MAX_SHEET_CELL_SIZE * MAX_SHEET_CELL_SIZE
        elif kind == "mix":
            _finite(params_node.get("factor", .5), f"{npath}.params.factor", minimum=0, maximum=1)
        elif kind == "tint" and "color" in params_node:
            _vec(params_node["color"], f"{npath}.params.color", sizes=(3, 4), minimum=0, maximum=1)
    graph_enabled = bool(graph)
    return pattern is not None or graph_enabled, total_tex_px


def _export_preflight(export: dict, index: int) -> tuple[str, dict, int]:
    path = f"recipe.exports[{index}]"
    if not isinstance(export, dict):
        _invalid("invalid_type", f"{path} must be an object", path)
    fmt = export.get("format", "obj")
    if not isinstance(fmt, str):
        _invalid("invalid_type", f"{path}.format must be text", f"{path}.format")
    _check_verb(fmt, f"{path}.format")
    fmt = normalize_export_format(fmt)
    if fmt not in EXPORT_FORMATS:
        _invalid("unsupported_export_format", f"{path}.format is unsupported", f"{path}.format")
    params = _mapping(export.get("params", {}), f"{path}.params")
    pixels = 0
    if fmt in {"spritesheet", "toon_sheet"}:
        allowed = {"views", "size", "color", "silhouette"}
        if fmt == "toon_sheet":
            allowed |= {"bands", "ink"}
        extra = set(params) - allowed
        if extra:
            key = sorted(extra)[0]
            _invalid("unknown_parameter", f"{path}.params.{key} is unsupported", f"{path}.params.{key}")
        views = _integer(params.get("views", 8), f"{path}.params.views", 1, MAX_SHEETS)
        size = _integer(params.get("size", 256), f"{path}.params.size", 1, MAX_SHEET_CELL_SIZE)
        pixels = views * size * size
        if "color" in params:
            _vec(params["color"], f"{path}.params.color", sizes=(3, 4), minimum=0, maximum=1)
        if "silhouette" in params and type(params["silhouette"]) is not bool:
            _invalid("invalid_type", f"{path}.params.silhouette must be boolean", f"{path}.params.silhouette")
        if fmt == "toon_sheet":
            _integer(params.get("bands", 4), f"{path}.params.bands", 1, 16)
            if "ink" in params and type(params["ink"]) is not bool:
                _invalid("invalid_type", f"{path}.params.ink must be boolean", f"{path}.params.ink")
    elif fmt == "animation_sheet":
        allowed = {"action", "frames", "size", "color", "columns", "start", "end"}
        extra = set(params) - allowed
        if extra:
            key = sorted(extra)[0]
            _invalid("unknown_parameter", f"{path}.params.{key} is unsupported", f"{path}.params.{key}")
        frames = _integer(params.get("frames", 8), f"{path}.params.frames", 1, MAX_SHEETS)
        size = _integer(params.get("size", 256), f"{path}.params.size", 1, MAX_SHEET_CELL_SIZE)
        _integer(params.get("columns", frames), f"{path}.params.columns", 1, frames)
        pixels = frames * size * size
        if "action" in params and params["action"] is not None and not isinstance(params["action"], str):
            _invalid("invalid_type", f"{path}.params.action must be an action name", f"{path}.params.action")
        if "color" in params:
            _vec(params["color"], f"{path}.params.color", sizes=(3, 4), minimum=0, maximum=1)
        if "start" in params:
            _finite(params["start"], f"{path}.params.start", minimum=0)
        if "end" in params:
            _finite(params["end"], f"{path}.params.end", minimum=0)
        if "start" in params and "end" in params and params["end"] < params["start"]:
            _invalid("invalid_value", f"{path}.params.end must be at least start", f"{path}.params.end")
    elif params:
        _invalid("unknown_parameter", f"{path}.params are unsupported for {fmt}", f"{path}.params")
    return fmt, params, pixels


def _check_name(value: Any, path: str) -> None:
    if not isinstance(value, str) or not value.strip():
        _invalid("invalid_type", f"{path} must be non-empty text", path)
    try:
        size = len(value.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        _invalid("invalid_value", f"{path} must be valid UTF-8 text", path)
    if size > 256:
        _invalid("invalid_length", f"{path} exceeds 256 UTF-8 bytes", path)
    if any(unicodedata.category(char) == "Cc" for char in value):
        _invalid("invalid_value", f"{path} may not contain control characters", path)


def _preflight_body(raw: dict) -> dict:
    if not isinstance(raw, dict):
        _invalid("invalid_type", "recipe must be a JSON object", "recipe")
    _check_data_tree(raw)
    # The tree walk bounds this temporary serialization to a few MiB even for
    # escape-heavy strings; this exact check enforces the wire-sized cap.
    try:
        encoded_size = len(json.dumps(raw, ensure_ascii=False, separators=(",", ":"),
                                      allow_nan=False).encode("utf-8", errors="strict"))
    except (TypeError, ValueError, UnicodeError):
        _invalid("invalid_type", "recipe must contain only valid JSON values", "recipe")
    if encoded_size > MAX_RECIPE_BYTES:
        raise PolicyError("response_too_large", "recipe exceeds the 512 KiB policy limit")
    _check_export_paths(raw)
    _inspect_hostile_fields(raw)
    if "version" in raw and type(raw["version"]) is not int:
        _invalid("invalid_type", "recipe.version must be an integer", "recipe.version")
    if "name" in raw:
        _check_name(raw["name"], "recipe.name")
    objects = _list(raw.get("objects", []), "recipe.objects", maximum=MAX_OBJECTS)
    materials = _list(raw.get("materials", []), "recipe.materials", maximum=MAX_MATERIALS)
    actions = _list(raw.get("actions", []), "recipe.actions", maximum=MAX_ACTIONS)
    raw_exports = _optional_list(raw.get("exports", []), "recipe.exports",
                                 maximum=MAX_SHEETS)

    total_patches = 0
    estimated_control_points = 0
    authored_points = 0
    predicted_triangles = 0
    explicit_bone_counts: dict[str, int] = {}
    object_names: set[str] = set()
    object_by_name: dict[str, dict] = {}
    for index, obj in enumerate(objects):
        path = f"recipe.objects[{index}]"
        obj = _mapping(obj, path)
        _check_name(obj.get("name"), f"{path}.name")
        name = obj["name"]
        if name in object_names:
            _invalid("duplicate_name", f"{path}.name is duplicated", f"{path}.name")
        object_names.add(name)
        object_by_name[name] = obj
        patches, points, profile_points = _primitive_preflight(
            obj.get("primitive"), obj.get("params", {}), path)
        splines = _optional_list(obj.get("splines", []), f"{path}.splines", maximum=MAX_AUTHORED_POINTS)
        bones = _optional_list(obj.get("bones", []), f"{path}.bones", maximum=MAX_BONES_PER_RIG)
        if len(bones) > MAX_BONES_PER_RIG:
            raise PolicyError("resource_limit", f"{path} exceeds 64 bones", path=f"{path}.bones")
        explicit_bone_counts[name] = len(bones)
        total_patches += patches
        estimated_control_points += points
        authored_points += profile_points
        for spline_index, spline in enumerate(splines):
            spath = f"{path}.splines[{spline_index}]"
            spline = _mapping(spline, spath)
            points_raw = _list(spline.get("points"), f"{spath}.points", maximum=MAX_AUTHORED_POINTS, minimum=2)
            for point_index, point in enumerate(points_raw):
                _vec(point, f"{spath}.points[{point_index}]")
            authored_points += len(points_raw)
            estimated_control_points += len(points_raw)
            closed = spline.get("closed", False)
            if type(closed) is not bool:
                _invalid("invalid_type", f"{spath}.closed must be boolean", f"{spath}.closed")
            degree = _integer(spline.get("degree", 3), f"{spath}.degree", 1, 3)
            if degree >= len(points_raw):
                _invalid("invalid_value", f"{spath}.degree must be smaller than the point count", f"{spath}.degree")
            if closed:
                predicted_triangles += 64
        transform = obj.get("transform", [])
        if transform not in (None, []):
            nested_matrix = (isinstance(transform, list) and len(transform) == 4
                             and all(isinstance(row, list) and len(row) == 4
                                     for row in transform))
            if not isinstance(transform, list) or (len(transform) not in (3, 16)
                                                   and not nested_matrix):
                _invalid("invalid_shape", f"{path}.transform must contain 3 translation values or a 4x4 matrix", f"{path}.transform")
            for i, item in enumerate(transform):
                if isinstance(item, list):
                    for j, cell in enumerate(item):
                        _finite(cell, f"{path}.transform[{i}][{j}]")
                else:
                    _finite(item, f"{path}.transform[{i}]")
        for bone_index, bone in enumerate(bones):
            bpath = f"{path}.bones[{bone_index}]"
            bone = _mapping(bone, bpath)
            _check_name(bone.get("name"), f"{bpath}.name")
            _vec(bone.get("head"), f"{bpath}.head")
            _vec(bone.get("tail"), f"{bpath}.tail")
            for weight_field in ("weights", "cp_weights"):
                weights = bone.get(weight_field, {})
                if weights is None:
                    weights = {}
                weights = _mapping(weights, f"{bpath}.{weight_field}")
                for key, weight in weights.items():
                    if not re.fullmatch(r"0|[1-9][0-9]*", key):
                        _invalid("invalid_index", f"{bpath}.{weight_field} keys must be non-negative integer indices", f"{bpath}.{weight_field}")
                    _finite(weight, f"{bpath}.{weight_field}.{key}", minimum=0, maximum=1)
    if total_patches > MAX_PATCHES:
        raise PolicyError("resource_limit", "recipe exceeds 1024 generated patches", path="recipe.objects")
    if authored_points > MAX_AUTHORED_POINTS:
        raise PolicyError("resource_limit", "recipe exceeds 4096 authored control/profile points", path="recipe.objects")

    copied_bones = 0
    effective_bone_counts: dict[str, int] = {}
    for index, obj in enumerate(objects):
        params = obj.get("params", {})
        skeleton = params.get("skeleton") if isinstance(params, dict) else None
        effective_bone_counts[obj["name"]] = explicit_bone_counts[obj["name"]]
        if skeleton is not None:
            if not isinstance(skeleton, str):
                _invalid("invalid_type", f"recipe.objects[{index}].params.skeleton must be a name", f"recipe.objects[{index}].params.skeleton")
            source_count = explicit_bone_counts.get(skeleton, 0)
            if explicit_bone_counts.get(obj["name"], 0) == 0:
                if source_count > MAX_BONES_PER_RIG:
                    raise PolicyError("resource_limit", "a copied skeleton exceeds 64 bones", path=f"recipe.objects[{index}].params.skeleton")
                copied_bones += source_count
                effective_bone_counts[obj["name"]] = source_count
        copied_bones += explicit_bone_counts[obj["name"]]
    if copied_bones > MAX_TOTAL_BONES:
        raise PolicyError("resource_limit", "recipe exceeds 256 explicit and copied bones", path="recipe.objects")

    material_names: set[str] = set()
    material_enabled = []
    max_texture_work_pixels = 0
    for index, material in enumerate(materials):
        path = f"recipe.materials[{index}]"
        material = _mapping(material, path)
        _check_name(material.get("name"), f"{path}.name")
        if material["name"] in material_names:
            _invalid("duplicate_material_name", f"{path}.name is duplicated", f"{path}.name")
        material_names.add(material["name"])
        color = material.get("color", [0.8, 0.8, 0.8])
        if color is not None:
            _vec(color, f"{path}.color", sizes=(3, 4), minimum=0, maximum=1)
        _finite(material.get("roughness", .5), f"{path}.roughness", minimum=0, maximum=1)
        _finite(material.get("metalness", 0), f"{path}.metalness", minimum=0, maximum=1)
        enabled, px = _material_preflight(material, index)
        material_enabled.append(enabled)
        max_texture_work_pixels = max(max_texture_work_pixels, px)
        targets = _optional_list(material.get("objects", []), f"{path}.objects", maximum=MAX_OBJECTS)
        for target_index, target in enumerate(targets):
            if not isinstance(target, str):
                _invalid("invalid_type", f"{path}.objects[{target_index}] must be an object name", f"{path}.objects[{target_index}]")

    action_names: set[str] = set()
    total_channels = 0
    total_keys = 0
    action_channels: dict[str, int] = {}
    action_keys: dict[str, int] = {}
    for index, action in enumerate(actions):
        path = f"recipe.actions[{index}]"
        action = _mapping(action, path)
        _check_name(action.get("name"), f"{path}.name")
        if action["name"] in action_names:
            _invalid("duplicate_action_name", f"{path}.name is duplicated", f"{path}.name")
        action_names.add(action["name"])
        kind = action.get("kind", "custom")
        if not isinstance(kind, str):
            _invalid("invalid_type", f"{path}.kind must be text", f"{path}.kind")
        _check_verb(kind, f"{path}.kind")
        kind = kind.casefold()
        params = _mapping(action.get("params", {}), f"{path}.params")
        if kind in {"walk", "idle", "jump"}:
            allowed = {"walk": {"stride", "amplitude_deg", "bob"}, "idle": {"sway_deg", "breathe"}, "jump": {"crouch", "height"}}[kind]
            extra = set(params) - allowed
            if extra:
                key = sorted(extra)[0]
                _invalid("unknown_parameter", f"{path}.params.{key} is unsupported", f"{path}.params.{key}")
            for key, val in params.items():
                _finite(val, f"{path}.params.{key}")
        elif kind == "custom":
            if params:
                _invalid("unknown_parameter", f"{path}.params are unsupported for custom keyframe actions", f"{path}.params")
        elif kind == "retarget":
            extra = set(params) - {"source_character", "mapping"}
            if extra:
                key = sorted(extra)[0]
                _invalid("unknown_parameter", f"{path}.params.{key} is unsupported", f"{path}.params.{key}")
            if "source_character" in params and not isinstance(params["source_character"], str):
                _invalid("invalid_type", f"{path}.params.source_character must be a name", f"{path}.params.source_character")
            if "mapping" in params:
                mapping = _mapping(params["mapping"], f"{path}.params.mapping")
                if len(mapping) > MAX_BONES_PER_RIG:
                    raise PolicyError("resource_limit", f"{path}.params.mapping exceeds 64 entries", path=f"{path}.params.mapping")
                for key, value in mapping.items():
                    if not isinstance(value, str):
                        _invalid("invalid_type", f"{path}.params.mapping values must be names", f"{path}.params.mapping.{key}")
        elif kind != "retarget":
            from am3d.recipes.schema import ACTION_KINDS
            if kind not in ACTION_KINDS:
                _invalid("unsupported_action_kind", f"{path}.kind is unsupported", f"{path}.kind")
        if kind not in {"custom", "retarget", "walk", "idle", "jump"}:
            _invalid("unsupported_action_kind", f"{path}.kind is unsupported", f"{path}.kind")
        if "duration" in action:
            _finite(action["duration"], f"{path}.duration", positive=True, maximum=600.0)
        channels = _optional_list(action.get("channels", []), f"{path}.channels", maximum=MAX_CHANNELS)
        this_channels = len(channels)
        this_keys = 0
        for channel_index, channel in enumerate(channels):
            cpath = f"{path}.channels[{channel_index}]"
            channel = _mapping(channel, cpath)
            if not isinstance(channel.get("bone"), str):
                _invalid("invalid_type", f"{cpath}.bone must be a bone name", f"{cpath}.bone")
            prop = channel.get("property", "translate")
            if not isinstance(prop, str) or prop not in {"translate", "rotate", "scale", "weight"}:
                _invalid("unsupported_action_property", f"{cpath}.property is unsupported", f"{cpath}.property")
            keys = _optional_list(channel.get("keys", []), f"{cpath}.keys", maximum=MAX_KEYS)
            this_keys += len(keys)
            for key_index, key in enumerate(keys):
                kpath = f"{cpath}.keys[{key_index}]"
                key = _mapping(key, kpath)
                _finite(key.get("time"), f"{kpath}.time", minimum=0, maximum=600)
                _vec(key.get("value"), f"{kpath}.value", sizes=(1, 2, 3))
                interpolation = key.get("interp", "smooth")
                if not isinstance(interpolation, str) or interpolation not in {"smooth", "linear", "constant"}:
                    _invalid("unsupported_interpolation", f"{kpath}.interp is unsupported", f"{kpath}.interp")
        char = action.get("character")
        if char is not None and not isinstance(char, str):
            _invalid("invalid_type", f"{path}.character must be an object name", f"{path}.character")
        if char and kind in {"walk", "idle", "jump"}:
            bone_count = effective_bone_counts.get(char, 0)
            this_channels = max(this_channels, bone_count)
            this_keys = max(this_keys, (bone_count - 1) * 13 + (13 if bone_count else 0))
        action_channels[action["name"]] = this_channels
        action_keys[action["name"]] = this_keys
        total_channels += this_channels
        total_keys += this_keys
    if total_channels > MAX_CHANNELS:
        raise PolicyError("resource_limit", "recipe exceeds 256 total action channels", path="recipe.actions")
    if total_keys > MAX_KEYS:
        raise PolicyError("resource_limit", "recipe exceeds 4096 total action keys", path="recipe.actions")

    export_info = [_export_preflight(item, index) for index, item in enumerate(raw_exports)]
    total_sheets = sum(fmt in {"spritesheet", "toon_sheet", "animation_sheet"} for fmt, _, _ in export_info)
    total_sheet_pixels = 0
    for (fmt, _, pixels) in export_info:
        if fmt in {"spritesheet", "toon_sheet"}:
            renderables = sum(bool(obj.get("primitive") or obj.get("splines")) for obj in objects)
            total_sheet_pixels += pixels * renderables
        else:
            total_sheet_pixels += pixels
    if total_sheets > MAX_SHEETS or total_sheet_pixels > MAX_SHEET_PIXELS:
        raise PolicyError("resource_limit", "sheet exports exceed 16 sheets or 16 million total pixels", path="recipe.exports")

    # Conservative fixed tessellation estimate for every generated surface.
    predicted_triangles += total_patches * 2 * TESS_U * TESS_V
    if predicted_triangles > MAX_EVALUATED_TRIANGLES:
        raise PolicyError("resource_limit", "recipe exceeds 250,000 evaluated triangles at 16x16 tessellation", path="recipe.objects")

    atlas_pixels = 0
    textured_objects = set()
    for index, obj in enumerate(objects):
        name = obj["name"]
        active_materials = []
        for material_index, material in enumerate(materials):
            if not material_enabled[material_index]:
                continue
            targets = material.get("objects", []) or []
            if not targets or name in targets:
                active_materials.append(material)
        if active_materials and obj.get("primitive"):
            patch_count = 6 if obj.get("primitive") == "box" else 1
            cell_count = patch_count
            columns = max(int(math.ceil(math.sqrt(cell_count))), 1)
            rows = max(int(math.ceil(cell_count / columns)), 1)
            atlas_pixels += rows * columns * MAX_SHEET_CELL_SIZE * MAX_SHEET_CELL_SIZE
            textured_objects.add(name)
    if atlas_pixels > MAX_ATLAS_PIXELS:
        raise PolicyError("resource_limit", "baked atlases exceed 64 million total pixels", path="recipe.materials")

    estimated_bytes = (
        estimated_control_points * _CONTROL_POINT_BYTES
        + predicted_triangles * _TRIANGLE_BYTES
        + (atlas_pixels + max_texture_work_pixels) * 4 * _TEXTURE_FLOAT_BYTES * 3
        + total_sheet_pixels * 4
    )
    if estimated_bytes > MAX_ESTIMATED_MEMORY:
        raise PolicyError("resource_limit", "estimated worker memory exceeds 1 GiB", path="recipe")
    output_estimate = (
        estimated_control_points * 48
        + predicted_triangles * 256
        + (atlas_pixels + total_sheet_pixels) * 4
    )
    if output_estimate > MAX_OUTPUT_BYTES:
        raise PolicyError("resource_limit", "estimated output exceeds 256 MiB", path="recipe.exports")

    # Normalize through the existing schema only after all counts and raw
    # values have been bounded, then assign every path in the host.
    try:
        candidate = recipe_from_dict(raw)
    except RecipeValidationError:
        raise
    problems = validate_recipe(candidate)
    if problems:
        problem = problems[0]
        if hasattr(problem, "to_record"):
            raise RecipeValidationError(problem.code, str(problem), path=problem.path,
                                        hint=problem.hint, stage=problem.stage)
        raise RecipeValidationError("validation_error", str(problem), stage="policy-preflight")

    normalized_exports = [{"format": "am3d", "path": "project.am3d", "params": {}}]
    export_index = 1
    for fmt, params, _ in export_info:
        if fmt == "am3d":
            continue
        normalized_exports.append({
            "format": fmt,
            "path": f"export_{export_index:02d}",
            "params": params,
        })
        export_index += 1
    # Host owns all destinations, including the required native project.
    canonical = candidate.to_dict()
    canonical["exports"] = normalized_exports
    return canonical


def prepare_recipe(raw_recipe: Any, brief: Any = None) -> dict:
    """Return a canonical, host-safe recipe-v1 dictionary.

    Unsafe path/resource/code requests raise :class:`PolicyError` and are
    terminal. Safe malformed values raise :class:`RecipeValidationError` and
    can be repaired by the bounded generation loop.
    """
    if isinstance(brief, dict):
        # A brief is evidence for later checks only; never trust it to loosen
        # resource policy. Bound its JSON form before retaining any details.
        _check_data_tree(brief)
    return _preflight_body(raw_recipe)
