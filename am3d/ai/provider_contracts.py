"""Strict, bounded data contracts for proposing recipe-v1 through providers."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
import json
import math
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, ValidationError as JSONSchemaValidationError


PROVIDER_RESPONSE_VERSION = 1
MAX_PROVIDER_RESPONSE_BYTES = 1024 * 1024
MAX_PROVIDER_JSON_DEPTH = 64
MAX_INTENT_CHARS = 512
MAX_ANNOTATION_ITEMS = 32
MAX_ANNOTATION_CHARS = 512
MAX_REQUIRED_COMPONENTS = 64
MAX_COMPONENT_CHARS = 256


class FailureCode(StrEnum):
    """Stable, serializable failure classifications for provider attempts."""

    UNAVAILABLE_PROVIDER = "unavailable_provider"
    UNSUPPORTED_ADAPTER = "unsupported_adapter"
    TIMEOUT = "timeout"
    TRANSPORT_FAILURE = "transport_failure"
    NONZERO_EXIT = "nonzero_cli_exit"
    RESPONSE_TOO_LARGE = "response_too_large"
    INVALID_UTF8 = "invalid_utf8"
    MALFORMED_JSON = "malformed_json"
    DUPLICATE_JSON_KEYS = "duplicate_json_keys"
    UNKNOWN_FIELDS = "unknown_fields"
    MISSING_FIELDS = "missing_fields"
    MISSING_RECIPE = "missing_recipe"
    INVALID_STRUCTURED_RESPONSE = "invalid_structured_response"
    POLICY_REJECTION = "policy_rejection"
    GENERATION_FAILURE = "generation_failure"
    CHECK_FAILURE = "check_failure"
    QUOTA_RATE_LIMIT = "quota_rate_limit"
    AUTHENTICATION_FAILURE = "authentication_failure"
    REFUSAL = "refusal"
    INVALID_BRIEF = "invalid_brief"
    PROMPT_TOO_LARGE = "prompt_too_large"


class ProviderResponseError(ValueError):
    def __init__(self, code: FailureCode, message: str):
        self.code = code
        super().__init__(message)


class _DuplicateKeyError(ValueError):
    pass


class _InvalidConstantError(ValueError):
    pass


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise _DuplicateKeyError("provider JSON contains a duplicate key")
        value[key] = item
    return value


def _reject_constant(value):
    raise _InvalidConstantError(f"invalid JSON constant {value}")


def _provider_schema_path() -> Path:
    # In the frozen app the repository root resolves to PyInstaller's _internal
    # directory, which receives this same docs/recipes asset in am3d.spec.
    root = Path(__file__).resolve().parents[2]
    return root / "docs" / "recipes" / "recipe-v1.provider.schema.json"


@lru_cache(maxsize=1)
def provider_response_schema() -> dict[str, Any]:
    """Compose the strict envelope with the generated model-facing recipe schema."""
    recipe_schema = json.loads(_provider_schema_path().read_text(encoding="utf-8"))
    recipe_definitions = recipe_schema.pop("$defs")
    recipe_schema.pop("$schema", None)
    recipe_schema.pop("$id", None)
    recipe_schema.pop("title", None)

    response_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://3d-master-2005.local/provider-response/v1",
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "intent", "assumptions",
                     "approximations", "required_components", "recipe"],
        "properties": {
            "schema_version": {"type": "integer", "const": PROVIDER_RESPONSE_VERSION},
            "intent": {"type": "string", "maxLength": MAX_INTENT_CHARS},
            "assumptions": {
                "type": "array", "maxItems": MAX_ANNOTATION_ITEMS,
                "items": {"type": "string", "minLength": 1,
                          "maxLength": MAX_ANNOTATION_CHARS}},
            "approximations": {
                "type": "array", "maxItems": MAX_ANNOTATION_ITEMS,
                "items": {"type": "string", "minLength": 1,
                          "maxLength": MAX_ANNOTATION_CHARS}},
            "required_components": {
                "type": "array", "maxItems": MAX_REQUIRED_COMPONENTS,
                "items": {"type": "string", "minLength": 1,
                          "maxLength": MAX_COMPONENT_CHARS}},
            "recipe": {"$ref": "#/$defs/recipe"},
        },
        "$defs": {**recipe_definitions, "recipe": recipe_schema},
    }
    Draft202012Validator.check_schema(response_schema)
    return response_schema


def provider_response_schema_json() -> str:
    return json.dumps(provider_response_schema(), ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"))


def _has_excessive_nesting(payload: bytes) -> bool:
    depth = 0
    in_string = False
    escaped = False
    for byte in payload:
        if in_string:
            if escaped:
                escaped = False
            elif byte == 0x5C:
                escaped = True
            elif byte == 0x22:
                in_string = False
            continue
        if byte == 0x22:
            in_string = True
        elif byte in (0x7B, 0x5B):
            depth += 1
            if depth > MAX_PROVIDER_JSON_DEPTH:
                return True
        elif byte in (0x7D, 0x5D) and depth:
            depth -= 1
    return False


def _validate_json_scalars(value) -> None:
    if isinstance(value, str):
        try:
            value.encode("utf-8", errors="strict")
        except UnicodeEncodeError as exc:
            raise ValueError("JSON contains an unpaired Unicode surrogate") from exc
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("JSON number is not finite")
    elif isinstance(value, list):
        for item in value:
            _validate_json_scalars(item)
    elif isinstance(value, dict):
        for key, item in value.items():
            _validate_json_scalars(key)
            _validate_json_scalars(item)


@dataclass(frozen=True)
class StructuredProviderResponse:
    schema_version: int
    intent: str
    assumptions: tuple[str, ...]
    approximations: tuple[str, ...]
    required_components: tuple[str, ...]
    recipe: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "intent": self.intent,
            "assumptions": list(self.assumptions),
            "approximations": list(self.approximations),
            "required_components": list(self.required_components),
            "recipe": deepcopy(self.recipe),
        }


def parse_provider_response(payload: bytes) -> StructuredProviderResponse:
    """Decode at most 1 MiB, rejecting ambiguous or non-contract JSON."""
    if not isinstance(payload, bytes):
        raise ProviderResponseError(
            FailureCode.INVALID_STRUCTURED_RESPONSE,
            "provider response must be raw UTF-8 bytes")
    if len(payload) > MAX_PROVIDER_RESPONSE_BYTES:
        raise ProviderResponseError(
            FailureCode.RESPONSE_TOO_LARGE,
            f"provider response exceeds {MAX_PROVIDER_RESPONSE_BYTES} bytes")
    if _has_excessive_nesting(payload):
        raise ProviderResponseError(
            FailureCode.INVALID_STRUCTURED_RESPONSE,
            f"provider JSON exceeds nesting limit {MAX_PROVIDER_JSON_DEPTH}")
    try:
        text = payload.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ProviderResponseError(
            FailureCode.INVALID_UTF8, "provider response is not valid UTF-8") from exc
    try:
        value = json.loads(text, object_pairs_hook=_unique_object,
                           parse_constant=_reject_constant)
    except _DuplicateKeyError as exc:
        raise ProviderResponseError(
            FailureCode.DUPLICATE_JSON_KEYS,
            "provider response contains duplicate JSON keys") from exc
    except (ValueError, RecursionError) as exc:
        raise ProviderResponseError(
            FailureCode.MALFORMED_JSON,
            "provider response is not strict JSON") from exc

    if not isinstance(value, dict):
        raise ProviderResponseError(
            FailureCode.INVALID_STRUCTURED_RESPONSE,
            "provider response root must be an object")
    try:
        _validate_json_scalars(value)
    except ValueError as exc:
        raise ProviderResponseError(
            FailureCode.INVALID_STRUCTURED_RESPONSE,
            "provider response contains an invalid Unicode or numeric value") from exc
    expected = {"schema_version", "intent", "assumptions", "approximations",
                "required_components", "recipe"}
    unknown = set(value) - expected
    if unknown:
        raise ProviderResponseError(
            FailureCode.UNKNOWN_FIELDS,
            "provider response contains unsupported fields")
    missing = expected - set(value)
    if "recipe" in missing:
        raise ProviderResponseError(
            FailureCode.MISSING_RECIPE,
            "provider response is missing its recipe")
    if missing:
        names = ", ".join(sorted(missing))
        raise ProviderResponseError(
            FailureCode.MISSING_FIELDS,
            f"provider response is missing fields: {names}")

    try:
        Draft202012Validator(provider_response_schema()).validate(value)
    except JSONSchemaValidationError as exc:
        # jsonschema's default messages include echoed input values. Keep the
        # user-facing failure bounded and independent of hostile model text.
        raise ProviderResponseError(
            FailureCode.INVALID_STRUCTURED_RESPONSE,
            "provider response does not match the versioned response schema") from exc

    return StructuredProviderResponse(
        schema_version=value["schema_version"],
        intent=value["intent"],
        assumptions=tuple(value["assumptions"]),
        approximations=tuple(value["approximations"]),
        required_components=tuple(value["required_components"]),
        recipe=deepcopy(value["recipe"]),
    )
