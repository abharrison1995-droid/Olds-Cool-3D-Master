"""Typed, model-facing recipe capabilities.

This registry is the source of truth for the parameters that recipe validation
accepts.  Builder defaults are read from their callable signatures so a
changed default cannot silently leave the external recipe contract stale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import inspect
from typing import Any


_MISSING = object()


@dataclass(frozen=True)
class Parameter:
    """A recipe parameter's type and validation constraints."""

    type: str
    default: Any = _MISSING
    minimum: float | None = None
    maximum: float | None = None
    enum: tuple | None = None
    length: tuple[int, int] | None = None
    required: bool = False
    description: str = ""

    @property
    def has_default(self) -> bool:
        return self.default is not _MISSING


@dataclass(frozen=True)
class Capability:
    """One named feature a recipe may request."""

    category: str
    name: str
    params: dict[str, Parameter] = field(default_factory=dict)
    description: str = ""
    cost_hint: str = ""
    model_visible: bool = True


def _inferred_type(default: Any) -> str:
    if isinstance(default, bool):
        return "boolean"
    if isinstance(default, int):
        return "integer"
    if isinstance(default, float):
        return "number"
    if isinstance(default, str):
        return "string"
    if isinstance(default, (tuple, list)):
        return "color"
    return "object"


def _signature_params(function, overrides=None, *, required=(), exclude=()):
    """Read names/defaults from a builder signature and add declared limits."""
    overrides = overrides or {}
    result = {}
    for name, arg in inspect.signature(function).parameters.items():
        if name in {"self", "cls", *exclude}:
            continue
        opts = dict(overrides.get(name, {}))
        default = arg.default
        if name in required:
            default = _MISSING
        elif default is inspect.Parameter.empty:
            default = _MISSING
        result[name] = Parameter(
            type=opts.pop("type", _inferred_type(default)),
            default=default,
            required=(name in required or default is _MISSING),
            **opts,
        )
    return result


def _param(type_, default=_MISSING, **kwargs):
    return Parameter(type=type_, default=default, **kwargs)


def _cap(category, name, fn, description, cost_hint, overrides=None, *,
         required=(), exclude=(), model_visible=True):
    return Capability(
        category=category,
        name=name,
        params=_signature_params(fn, overrides, required=required,
                                 exclude=exclude),
        description=description,
        cost_hint=cost_hint,
        model_visible=model_visible,
    )


def _build_registry():
    from .primitives import BUILDERS
    from am3d.renderer.materials import PATTERNS
    from am3d.core.material_graph import NODE_TYPES
    from . import animation as action_builders

    positive = {"type": "number", "minimum": 0.0001}
    subdivisions = {"type": "integer", "minimum": 4, "maximum": 128}
    grid = {"type": "integer", "minimum": 3, "maximum": 128}
    vec_color = {"type": "color", "minimum": 0, "maximum": 1,
                 "length": (3, 4)}
    profile2 = {"type": "profile2", "length": (2, 4096)}
    profile3 = {"type": "profile3", "length": (2, 4096)}

    primitive_overrides = {
        "sphere": {
            "radius": positive,
            "sections": subdivisions,
            "rings": subdivisions,
        },
        "cylinder": {
            "radius": positive, "height": positive,
            "sections": subdivisions, "rings": subdivisions,
            "capped": {"type": "boolean"},
        },
        "cone": {
            "radius": positive, "height": positive,
            "sections": subdivisions, "rings": subdivisions,
        },
        "torus": {
            "major_radius": positive, "minor_radius": positive,
            "major_sections": subdivisions, "minor_sections": subdivisions,
        },
        "box": {
            "width": positive, "height": positive, "depth": positive,
            "n": grid,
        },
        "plane": {"width": positive, "height": positive, "n": grid},
        "lathe": {
            "profile": profile2,
            "axis": {"type": "string", "enum": ("x", "y", "z")},
            "sections": subdivisions,
        },
        "extrude": {
            "profile": profile3,
            "height": {"type": "number"},
            "twist_deg": {"type": "number"},
            "rings": {"type": "integer", "minimum": 2, "maximum": 128},
        },
    }
    primitive_descriptions = {
        "sphere": ("Create a UV sphere.", "Control-net cost grows with sections × rings."),
        "cylinder": ("Create a capped or open cylinder along +Y.", "Control-net cost grows with sections × rings."),
        "cone": ("Create a cone along +Y.", "Control-net cost grows with sections × rings."),
        "torus": ("Create a torus around the Y axis.", "Control-net cost grows with major_sections × minor_sections."),
        "box": ("Create a six-patch box.", "Six grids; each has n × n control points."),
        "plane": ("Create a flat XY plane.", "One grid with n × n control points."),
        "lathe": ("Revolve a 2D radius/height profile.", "Control-net cost grows with sections × profile points."),
        "extrude": ("Extrude a 3D profile along +Y.", "Control-net cost grows with rings × profile points."),
    }
    caps = []
    for name, function in BUILDERS.items():
        desc, cost = primitive_descriptions[name]
        caps.append(_cap("primitive", name, function, desc, cost,
                         primitive_overrides[name],
                         required=("profile",) if name in ("lathe", "extrude") else ()))

    color = _param("color", minimum=0, maximum=1, length=(3, 4))
    size = {"type": "integer", "minimum": 1, "maximum": 256}
    pattern_overrides = {
        "solid": {"color": {**vec_color}, "size": size},
        "checker": {"a": {**vec_color}, "b": {**vec_color},
                    "cells": {"type": "integer", "minimum": 1, "maximum": 128},
                    "size": size},
        "gradient": {"top": {**vec_color}, "bottom": {**vec_color}, "size": size},
        "noise": {"seed": {"type": "integer"}, "size": size,
                  "octaves": {"type": "integer", "minimum": 1, "maximum": 8},
                  "base": {**vec_color},
                  "contrast": {"type": "number", "minimum": 0, "maximum": 1}},
        "bricks": {"brick": {**vec_color}, "mortar": {**vec_color},
                   "rows": {"type": "integer", "minimum": 1, "maximum": 128},
                   "cols": {"type": "integer", "minimum": 1, "maximum": 128},
                   "mortar_px": {"type": "number", "minimum": 0, "maximum": 256},
                   "size": size},
    }
    pattern_descriptions = {
        "solid": "Fill a texture with one color.",
        "checker": "Create a two-color checker pattern.",
        "gradient": "Blend a bottom color into a top color.",
        "noise": "Create seeded value-noise color variation.",
        "bricks": "Create a running-bond brick pattern.",
    }
    for name, function in PATTERNS.items():
        caps.append(_cap("pattern", name, function, pattern_descriptions[name],
                         "Allocates one square RGBA texture at size × size.",
                         pattern_overrides[name]))

    # Material-graph generator nodes share their pattern generator parameters.
    pattern_by_name = {c.name: c for c in caps if c.category == "pattern"}
    graph_pattern_names = {"solid": "solid", "checker": "checker",
                           "gradient": "gradient", "noise": "noise",
                           "bricks": "bricks"}
    for node in NODE_TYPES:
        if node in graph_pattern_names:
            source = pattern_by_name[graph_pattern_names[node]]
            caps.append(Capability(
                "graph_node", node, source.params,
                f"Generate a {node} texture in a material graph.",
                source.cost_hint))
        elif node == "source":
            caps.append(Capability("graph_node", node, {},
                "Pass through an upstream material map.",
                "No texture allocation beyond the current graph map.",
                model_visible=False))
        elif node == "mix":
            caps.append(Capability("graph_node", node,
                {"factor": _param("number", 0.5, minimum=0, maximum=1)},
                "Blend two material maps.",
                "Allocates one square RGBA texture.", model_visible=False))
        elif node == "noise_overlay":
            caps.append(Capability("graph_node", node, {
                "amount": _param("number", 0.15, minimum=0, maximum=1),
                "seed": _param("integer", 7),
                "octaves": _param("integer", 3, minimum=1, maximum=8),
            }, "Modulate an upstream map with seeded grain.",
                "Allocates one square RGBA texture."))
        elif node == "tint":
            caps.append(Capability("graph_node", node,
                {"color": _param("color", (1, 1, 1), minimum=0,
                                  length=(3, 4))},
                "Multiply an upstream map by a color.",
                "Allocates one square RGBA texture."))

    action_overrides = {
        "walk": {"duration": {"type": "number", "minimum": 0.001,
                               "maximum": 3600},
                 "stride": {"type": "number"},
                 "amplitude_deg": {"type": "number"},
                 "bob": {"type": "number"}},
        "idle": {"duration": {"type": "number", "minimum": 0.001,
                               "maximum": 3600},
                 "sway_deg": {"type": "number"},
                 "breathe": {"type": "number"}},
        "jump": {"duration": {"type": "number", "minimum": 0.001,
                               "maximum": 3600},
                 "crouch": {"type": "number"},
                 "height": {"type": "number"}},
    }
    action_desc = {
        "walk": "Generate a looping walk cycle.",
        "idle": "Generate a subtle breathing idle loop.",
        "jump": "Generate a crouch, jump, and landing action.",
    }
    for name, function in action_builders._GENERATORS.items():
        caps.append(_cap("action_kind", name, function, action_desc[name],
                         "Key count scales with the skeleton bone count." ,
                         action_overrides[name],
                         exclude=("bones", "name", "duration")))
    caps.extend([
        Capability("action_kind", "custom", {},
                   "Use authored channels and keyframes.",
                   "Key count is the number of supplied channel keys."),
        Capability("action_kind", "retarget", {
            "source_character": _param("string"),
            "mapping": _param("mapping"),
        }, "Retarget an earlier action to another skeleton.",
            "Cost scales with source and target bone counts."),
    ])

    caps.extend([
        Capability("export_format", "obj", {}, "Write a Wavefront OBJ mesh.", "Cost scales with evaluated mesh size."),
        Capability("export_format", "glb", {}, "Write a binary glTF mesh.", "Cost scales with evaluated mesh size."),
        Capability("export_format", "am3d", {}, "Save an editable project.", "Cost scales with project size."),
        Capability("export_format", "spritesheet", {
            "views": _param("integer", 8, minimum=1, maximum=16),
            "size": _param("integer", 256, minimum=16, maximum=256),
            "color": _param("color", (0.72, 0.74, 0.82), minimum=0, maximum=1, length=(3, 4)),
            "silhouette": _param("boolean", False),
        }, "Render orbit views into per-object PNG sheets.", "Allocates views × size² pixels per object."),
        Capability("export_format", "toon_sheet", {
            "views": _param("integer", 8, minimum=1, maximum=16),
            "size": _param("integer", 256, minimum=16, maximum=256),
            "color": _param("color", (0.85, 0.78, 0.55), minimum=0, maximum=1, length=(3, 4)),
            "bands": _param("integer", 4, minimum=2, maximum=8),
            "ink": _param("boolean", True),
        }, "Render toon-shaded orbit views into per-object PNG sheets.", "Allocates views × size² pixels per object."),
        Capability("export_format", "animation_sheet", {
            "action": _param("nullable_string"),
            "frames": _param("integer", 8, minimum=1, maximum=16),
            "size": _param("integer", 256, minimum=16, maximum=256),
            "color": _param("color", (0.72, 0.74, 0.82), minimum=0, maximum=1, length=(3, 4)),
            "start": _param("number", 0.0),
            "end": _param("number"),
            "columns": _param("integer", minimum=1, maximum=16),
        }, "Render the scene across one action into a PNG frame sheet.", "Allocates frames × size² pixels."),
    ])

    caps.extend(Capability("channel_property", name, {}, desc,
                           "Each key stores a 3D vector, except weight which stores one scalar.")
                for name, desc in (
                    ("translate", "Animate a bone's translation."),
                    ("rotate", "Animate a bone's rotation."),
                    ("scale", "Animate a bone's scale."),
                    ("weight", "Animate a scalar influence weight.")))
    caps.extend([
        Capability("interpolation", "linear", {}, "Interpolate linearly between keys.", "No additional memory."),
        Capability("interpolation", "step", {}, "Hold each key until the next key.", "No additional memory."),
        Capability("interpolation", "smooth", {}, "Interpolate smoothly between keys.", "No additional memory."),
        Capability("object_metadata", "object", {
            "auto_weights": _param("boolean", False),
            "skeleton": _param("string"),
        }, "Bind geometry to a local or referenced skeleton.",
            "Cost scales with control points × bones."),
    ])

    return {(cap.category, cap.name): cap for cap in caps}


CAPABILITIES = _build_registry()


def get_capability(category: str, name: str) -> Capability | None:
    return CAPABILITIES.get((category, name))


def capabilities_for(category: str) -> tuple[Capability, ...]:
    return tuple(cap for (kind, _), cap in CAPABILITIES.items()
                 if kind == category)


def validate_parameters(category: str, name: str, values, path: str) -> list[dict]:
    """Validate a capability parameter object and return structured issues."""
    cap = get_capability(category, name)
    if cap is None:
        return []
    if not isinstance(values, dict):
        return [{
            "code": "invalid_type", "path": path,
            "message": f"expected object of parameters, received {type(values).__name__}",
        }]
    issues = []
    valid = sorted(cap.params)
    for key in sorted(values):
        p_path = f"{path}.{key}"
        if key not in cap.params:
            issues.append({
                "code": "unknown_parameter", "path": p_path,
                "message": (f"expected a parameter name in {valid}, received "
                            f"unknown key {key!r}"),
                "hint": (f"Use one of: {', '.join(valid)}." if valid
                         else "This capability accepts no parameters."),
            })
            continue
        spec = cap.params[key]
        problem = _parameter_problem(spec, values[key])
        if problem is not None:
            issues.append({
                "code": "invalid_parameter", "path": p_path,
                "message": problem,
                "hint": (f"Expected {spec.type}" +
                         (f" in {spec.enum}" if spec.enum else "") + "."),
            })
    for key, spec in cap.params.items():
        if spec.required and key not in values:
            issues.append({
                "code": "missing_parameter", "path": f"{path}.{key}",
                "message": f"missing required parameter {key!r}; expected {spec.type}",
                "hint": f"Valid keys: {sorted(cap.params)}",
            })
    return issues


def _received(value) -> str:
    return f"{type(value).__name__} {value!r}"


def _parameter_problem(spec: Parameter, value) -> str | None:
    import math

    kind = spec.type
    if kind == "nullable_string" and value is None:
        return None
    if kind in ("number", "integer"):
        valid_type = (isinstance(value, (int, float)) and
                      not isinstance(value, bool) and
                      (kind != "integer" or isinstance(value, int)))
        if not valid_type:
            return f"expected {kind}, received {_received(value)}"
        if not math.isfinite(value):
            return f"expected finite {kind}, received {_received(value)}"
        if spec.minimum is not None and value < spec.minimum:
            return f"expected {kind} >= {spec.minimum}, received {_received(value)}"
        if spec.maximum is not None and value > spec.maximum:
            return f"expected {kind} <= {spec.maximum}, received {_received(value)}"
    elif kind == "boolean":
        if not isinstance(value, bool):
            return f"expected boolean, received {_received(value)}"
    elif kind in ("string", "nullable_string"):
        if not isinstance(value, str):
            return f"expected string, received {_received(value)}"
    elif kind == "mapping":
        if (not isinstance(value, dict) or
                any(not isinstance(k, str) or not isinstance(v, str)
                    for k, v in value.items())):
            return f"expected object mapping strings to strings, received {_received(value)}"
    elif kind in ("color", "profile2", "profile3"):
        if not isinstance(value, (list, tuple)):
            return f"expected {kind} array, received {_received(value)}"
        if kind == "color":
            lo, hi = spec.length or (3, 3)
            if not lo <= len(value) <= hi:
                return f"expected {kind} with {lo} to {hi} values, received length {len(value)}"
            rows = [value]
        else:
            width = 2 if kind == "profile2" else 3
            lo, hi = spec.length or (2, 4096)
            if not lo <= len(value) <= hi:
                return f"expected {kind} with {lo} to {hi} points, received length {len(value)}"
            rows = value
        for row_index, row in enumerate(rows):
            if kind != "color" and (
                    not isinstance(row, (list, tuple)) or len(row) != width):
                return f"expected {kind} point {row_index} to contain {width} numbers, received {_received(row)}"
            for item_index, item in enumerate(row):
                if (not isinstance(item, (int, float)) or
                        isinstance(item, bool) or not math.isfinite(item)):
                    return f"expected finite number at [{row_index}][{item_index}], received {_received(item)}"
                if spec.minimum is not None and item < spec.minimum:
                    return f"expected values >= {spec.minimum}, received {_received(item)}"
                if spec.maximum is not None and item > spec.maximum:
                    return f"expected values <= {spec.maximum}, received {_received(item)}"
    elif kind == "object":
        if not isinstance(value, dict):
            return f"expected object, received {_received(value)}"
    else:  # pragma: no cover - registry metadata is covered by tests
        return f"registry uses unsupported parameter type {kind!r}"
    if spec.enum is not None and value not in spec.enum:
        return f"expected one of {list(spec.enum)}, received {_received(value)}"
    return None


def builder_default_snapshot() -> dict:
    """Return the live builder defaults for parity tests and docs tooling."""
    return {
        f"{category}.{name}": {
            key: value.default
            for key, value in cap.params.items()
            if value.has_default
        }
        for (category, name), cap in CAPABILITIES.items()
        if category in {"primitive", "pattern", "action_kind"}
    }
