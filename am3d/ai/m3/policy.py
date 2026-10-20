"""Strict local-generation policy layered on recipe-v1 validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from am3d.core.paths import classify_portable_relative_path
from am3d.recipes.resources import LIMITS, estimate_recipe_resources, resource_limit_issues
from am3d.recipes.schema import (Recipe, RecipeValidationError,
                                recipe_from_dict, validate_recipe)


POLICY_VERSION = 1
MAX_RECIPE_BYTES = 128 * 1024


@dataclass(frozen=True)
class PolicyError:
    code: str
    path: str
    message: str
    stage: str = "policy"
    hint: str | None = None

    def to_dict(self) -> dict[str, str]:
        result = asdict(self)
        return {key: value for key, value in result.items() if value is not None}


class PolicyRejected(ValueError):
    def __init__(self, errors: list[PolicyError]):
        self.errors = tuple(errors)
        super().__init__(errors[0].message if errors else "recipe rejected by AI policy")


@dataclass(frozen=True)
class PolicyDecision:
    recipe: Recipe
    recipe_json: str
    output_root: str
    snapshot: dict[str, Any]
    resource_estimate: dict[str, int]


def _reject_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def _snapshot_payload() -> dict[str, Any]:
    limits = {key: value for key, value in sorted(LIMITS.items())}
    return {
        "policy_version": POLICY_VERSION,
        "max_recipe_bytes": MAX_RECIPE_BYTES,
        "resource_limits": limits,
        "forbidden_texture_path_keys": [
            "texture", "bump_map", "transparency_map", "specular_map"],
        "output_path_mode": "host-root-confined-relative",
    }


def policy_snapshot() -> dict[str, Any]:
    """Return a stable, digest-bound snapshot safe to pass to the worker."""
    payload = _snapshot_payload()
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return {**payload, "sha256": hashlib.sha256(encoded.encode()).hexdigest()}


def _encode_recipe(recipe: str | bytes | dict | Recipe) -> tuple[bytes, Any]:
    if isinstance(recipe, bytes):
        raw = recipe
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys,
                               parse_constant=lambda item: (_ for _ in ()).throw(
                                   ValueError(f"invalid JSON constant {item}")))
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            raise PolicyRejected([PolicyError(
                "invalid_json", "recipe", f"recipe JSON is invalid: {exc}")]) from exc
        return raw, value
    if isinstance(recipe, str):
        return _encode_recipe(recipe.encode("utf-8"))
    if isinstance(recipe, Recipe):
        value = recipe.to_dict()
    elif isinstance(recipe, dict):
        value = recipe
    else:
        raise PolicyRejected([PolicyError(
            "invalid_recipe_type", "recipe",
            f"expected JSON text or object, received {type(recipe).__name__}")])
    try:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise PolicyRejected([PolicyError(
            "invalid_json", "recipe", f"recipe cannot be serialized as strict JSON: {exc}")]) from exc
    return raw, value


def _walk_texture_paths(value, path="recipe"):
    """Find any authored texture path, including hidden/unknown JSON fields."""
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if key in {"texture", "bump_map", "transparency_map", "specular_map"} and child:
                yield child_path
            yield from _walk_texture_paths(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_texture_paths(child, f"{path}[{index}]")


def _validate_output_paths(value) -> list[PolicyError]:
    errors = []
    exports = value.get("exports", []) if isinstance(value, dict) else []
    if not isinstance(exports, list):
        return errors  # recipe-v1 validation returns the more precise type error
    for index, export in enumerate(exports):
        if not isinstance(export, dict) or "path" not in export:
            continue
        path = export["path"]
        if not isinstance(path, str):
            continue  # schema validation owns the type diagnostic
        issue = classify_portable_relative_path(path)
        if issue:
            reason, hint = issue
            errors.append(PolicyError(
                "output_path_rejected", f"recipe.exports[{index}].path",
                reason, hint=hint))
    return errors


def authorize_recipe(recipe_input: str | bytes | dict | Recipe,
                     output_root: str | os.PathLike) -> PolicyDecision:
    """Apply M1 AI validation and M2's bounded local policy before spawning."""
    raw, value = _encode_recipe(recipe_input)
    if len(raw) > MAX_RECIPE_BYTES:
        raise PolicyRejected([PolicyError(
            "recipe_too_large", "recipe",
            f"serialized recipe is {len(raw)} bytes; AI-mode limit is {MAX_RECIPE_BYTES}",
            hint="Reduce recipe JSON size and retry.")])
    if not isinstance(value, dict):
        raise PolicyRejected([PolicyError(
            "invalid_recipe_type", "recipe", "recipe JSON root must be an object")])

    errors = [PolicyError(
        "texture_path_forbidden", path,
        "AI-mode recipes cannot select texture file paths",
        hint="Use a registered procedural material pattern or graph node.")
        for path in _walk_texture_paths(value)]
    errors.extend(_validate_output_paths(value))

    try:
        recipe = recipe_from_dict(value)
    except RecipeValidationError as exc:
        errors.append(PolicyError(exc.code, exc.path, str(exc), stage=exc.stage,
                                  hint=exc.hint))
        raise PolicyRejected(errors) from exc
    except (TypeError, ValueError) as exc:
        errors.append(PolicyError("invalid_recipe", "recipe", str(exc)))
        raise PolicyRejected(errors) from exc

    validation = validate_recipe(recipe, ai_mode=True)
    errors.extend(PolicyError(issue.code, issue.path, issue.message,
                              hint=issue.hint)
                  for issue in validation)
    if errors:
        raise PolicyRejected(errors)

    try:
        estimate = estimate_recipe_resources(recipe)
        resource_errors = resource_limit_issues(estimate)
    except (MemoryError, TypeError, ValueError, OverflowError) as exc:
        raise PolicyRejected([PolicyError(
            "resource_estimate_failed", "recipe",
            "recipe resource estimate could not be completed",
            hint="Check recipe parameter types and resource dimensions.")]) from exc
    if resource_errors:
        raise PolicyRejected([PolicyError(
            item["code"], item["path"], item["message"], item["stage"],
            item.get("hint")) for item in resource_errors])

    if not isinstance(output_root, (str, os.PathLike)) or not os.fspath(output_root):
        raise PolicyRejected([PolicyError(
            "host_output_root_required", "output_root",
            "local generation requires a host-selected private output root")])
    root_path = Path(output_root).expanduser()
    if not root_path.is_absolute():
        raise PolicyRejected([PolicyError(
            "host_output_root_required", "output_root",
            "host-selected output root must be absolute")])
    root = str(root_path.resolve(strict=False))
    if not os.path.isabs(root):
        raise PolicyRejected([PolicyError(
            "host_output_root_required", "output_root",
            "host-selected output root must resolve to an absolute path")])

    return PolicyDecision(recipe, raw.decode("utf-8"), root,
                          policy_snapshot(), estimate)
