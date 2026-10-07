"""Codex strict-output projection of the canonical M3.1 response schema.

This is generated from the accepted provider schema at runtime. It only
narrows the contract to the strict JSON Schema dialect accepted by Codex;
``parse_provider_response`` remains the authoritative host parser.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from jsonschema import Draft202012Validator

from .provider_contracts import provider_response_schema


def codex_output_schema() -> dict[str, Any]:
    """Return a deterministic strict-schema subset of the M3.1 contract.

    Codex strict structured output requires every object property to be
    required, forbids additional properties, and supports ``anyOf`` rather
    than JSON Schema's general ``oneOf``. Open parameter maps are therefore
    narrowed to empty objects. This can reduce what the model can express, but
    cannot authorize data the canonical M3.1 parser would reject.
    """
    canonical = deepcopy(provider_response_schema())
    result = _project(canonical)
    result.pop("$schema", None)
    result.pop("$id", None)
    Draft202012Validator.check_schema(result)
    return result


def _project(schema: Any) -> Any:
    if isinstance(schema, list):
        return [_project(item) for item in schema]
    if not isinstance(schema, dict):
        return schema

    source = deepcopy(schema)
    if "oneOf" in source:
        branches = source.pop("oneOf")
        if not _branches_are_disjoint(branches):
            raise ValueError("Codex schema projection cannot safely narrow oneOf")
        source["anyOf"] = branches

    properties = source.get("properties")
    if source.get("type") == "object" or isinstance(properties, dict):
        properties = properties if isinstance(properties, dict) else {}
        source["properties"] = {
            name: _project(value) for name, value in properties.items()
        }
        # An object map with arbitrary keys cannot be represented safely in
        # Codex strict mode. Close it to the declared properties, or to {} when
        # the canonical schema permits only dynamic keys.
        source["additionalProperties"] = False
        source["required"] = list(properties)
        source.pop("propertyNames", None)

    if "items" in source:
        source["items"] = _project(source["items"])
    if "$defs" in source:
        source["$defs"] = {
            name: _project(value) for name, value in source["$defs"].items()
        }
    if "anyOf" in source:
        source["anyOf"] = [_project(value) for value in source["anyOf"]]

    # Strict Structured Outputs does not list const or JSON Schema string
    # length limits in its portable supported subset. An enum is equivalent
    # to const; a bounded regex preserves the canonical length interval.
    if "const" in source:
        constant = source.pop("const")
        if "enum" in source:
            source["enum"] = [value for value in source["enum"]
                              if value == constant]
        else:
            source["enum"] = [constant]
    minimum = source.pop("minLength", None)
    maximum = source.pop("maxLength", None)
    if minimum is not None or maximum is not None:
        if "pattern" in source:
            raise ValueError("Codex schema projection cannot combine string patterns")
        lower = 0 if minimum is None else minimum
        upper = "" if maximum is None else str(maximum)
        source["pattern"] = rf"^[\s\S]{{{lower},{upper}}}$"

    # These are documentation identifiers rather than instance constraints.
    source.pop("$schema", None)
    source.pop("$id", None)
    source.pop("title", None)
    return source


def _branches_are_disjoint(branches: Any) -> bool:
    """Prove the one current union is disjoint before replacing it by anyOf."""
    if not isinstance(branches, list) or len(branches) < 2:
        return False
    type_sets = [_top_level_types(branch) for branch in branches]
    if any(not types for types in type_sets):
        return False
    for index, left in enumerate(type_sets):
        for right_index in range(index + 1, len(type_sets)):
            overlap = left.intersection(type_sets[right_index])
            if not overlap:
                continue
            if overlap != {"array"}:
                return False
            left_signature = _array_signature(branches[index])
            right_signature = _array_signature(branches[right_index])
            if (not left_signature or not right_signature or
                    left_signature == right_signature):
                return False
    return True


def _array_signature(schema: Any) -> tuple[Any, ...] | None:
    if not isinstance(schema, dict) or schema.get("type") != "array":
        return None
    minimum = schema.get("minItems")
    maximum = schema.get("maxItems")
    items = schema.get("items")
    if minimum is None or minimum != maximum or not isinstance(items, dict):
        return None
    return minimum, tuple(sorted(_top_level_types(items)))


def _top_level_types(schema: Any) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    value = schema.get("type")
    if isinstance(value, str):
        return {value}
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return set(value)
    return set()
