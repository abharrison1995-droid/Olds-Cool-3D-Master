"""Strict response-envelope and provider schema boundary regressions."""

from __future__ import annotations

import json

import pytest

from . import provider_contracts
from .provider_contracts import (
    FailureCode, MAX_PROVIDER_JSON_DEPTH, MAX_PROVIDER_RESPONSE_BYTES,
    ProviderResponseError, parse_provider_response, provider_response_schema,
)
from .providers import FakeProvider, ProviderCallStatus, UsageMetadata


def _payload(recipe=None):
    return {
        "schema_version": 1,
        "intent": "A block.",
        "assumptions": [],
        "approximations": [],
        "required_components": ["body"],
        "recipe": recipe or {
            "version": 1,
            "name": "block",
            "objects": [{"name": "body", "primitive": "box"}],
        },
    }


def _encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def test_valid_structured_response_parses_and_preserves_recipe_v1():
    response = parse_provider_response(_encode(_payload()))
    assert response.schema_version == 1
    assert response.intent == "A block."
    assert response.assumptions == ()
    assert response.approximations == ()
    assert response.required_components == ("body",)
    assert response.recipe["version"] == 1
    assert response.recipe["objects"][0]["primitive"] == "box"


@pytest.mark.parametrize("extra", ["command", "output_root", "imports", "callback"])
def test_unknown_authority_fields_are_rejected(extra):
    value = _payload()
    value[extra] = "must-not-be-used"
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(_encode(value))
    assert caught.value.code is FailureCode.UNKNOWN_FIELDS


def test_missing_fields_and_missing_recipe_have_distinct_failures():
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(b'{"schema_version":1}')
    assert caught.value.code is FailureCode.MISSING_RECIPE

    value = _payload()
    del value["assumptions"]
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(_encode(value))
    assert caught.value.code is FailureCode.MISSING_FIELDS


@pytest.mark.parametrize(("raw", "code"), [
    (b'{"schema_version":1,"schema_version":1}', FailureCode.DUPLICATE_JSON_KEYS),
    (b'{', FailureCode.MALFORMED_JSON),
    (b'{"x":NaN}', FailureCode.MALFORMED_JSON),
    (b"\xff", FailureCode.INVALID_UTF8),
])
def test_strict_json_failures_are_typed(raw, code):
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(raw)
    assert caught.value.code is code


def test_extremely_long_json_integer_is_a_typed_malformed_response():
    raw = b'{"n":' + b"9" * 5000 + b"}"
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(raw)
    assert caught.value.code is FailureCode.MALFORMED_JSON


def test_response_limit_is_checked_before_decode_or_json_parse(monkeypatch):
    def no_json(*_args, **_kwargs):
        raise AssertionError("oversized response reached JSON parsing")

    monkeypatch.setattr(provider_contracts.json, "loads", no_json)
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(b" " * (MAX_PROVIDER_RESPONSE_BYTES + 1))
    assert caught.value.code is FailureCode.RESPONSE_TOO_LARGE


def test_json_nesting_is_bounded_before_parser_recursion():
    raw = b"[" * (MAX_PROVIDER_JSON_DEPTH + 1) + b"0" + b"]" * (
        MAX_PROVIDER_JSON_DEPTH + 1)
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(raw)
    assert caught.value.code is FailureCode.INVALID_STRUCTURED_RESPONSE


def test_contract_rejects_invalid_version_and_bounded_annotations():
    value = _payload()
    value["schema_version"] = True
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(_encode(value))
    assert caught.value.code is FailureCode.INVALID_STRUCTURED_RESPONSE

    value = _payload()
    value["approximations"] = ["a"] * 33
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(_encode(value))
    assert caught.value.code is FailureCode.INVALID_STRUCTURED_RESPONSE


def test_nonfinite_overflow_and_unpaired_surrogates_are_rejected():
    value = _payload({
        "version": 1, "name": "block", "objects": [{
            "name": "body", "primitive": "box",
            "transform": {"translate": [0.0, 0.0, 0.0]},
        }],
    })
    raw = _encode(value).replace(b"[0.0,0.0,0.0]", b"[1e9999,0,0]")
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(raw)
    assert caught.value.code is FailureCode.INVALID_STRUCTURED_RESPONSE

    raw = (b'{"schema_version":1,"intent":"\\ud800","assumptions":[], '
           b'"approximations":[],"required_components":[],"recipe":{"version":1}}')
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(raw)
    assert caught.value.code is FailureCode.INVALID_STRUCTURED_RESPONSE


def test_model_facing_recipe_contract_is_embedded_and_texture_path_is_absent():
    schema = provider_response_schema()
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "schema_version", "intent", "assumptions", "approximations",
        "required_components", "recipe"}
    assert "texture" not in schema["$defs"]["material"]["properties"]

    texture_recipe = _payload({
        "version": 1,
        "name": "texture_attempt",
        "materials": [{"name": "surface", "texture": "/tmp/private.png"}],
    })
    with pytest.raises(ProviderResponseError) as caught:
        parse_provider_response(_encode(texture_recipe))
    assert caught.value.code is FailureCode.INVALID_STRUCTURED_RESPONSE


def test_fake_provider_exposes_only_bounded_data_and_unknown_usage_is_null():
    from .prompt import PromptCompiler

    request = PromptCompiler().compile("A block")
    result = FakeProvider().generate(request)
    assert result.status is ProviderCallStatus.SUCCEEDED
    assert result.response_bytes is not None
    assert result.usage == UsageMetadata()
    assert result.usage.input_tokens is None
    assert result.usage.output_tokens is None
    assert result.usage.total_tokens is None

    known = FakeProvider(known_usage=True).generate(request)
    assert known.usage == UsageMetadata(input_tokens=41, output_tokens=29,
                                        total_tokens=70)


def test_provider_adapter_result_cannot_buffer_more_than_limit_plus_one():
    from .providers import (AdapterKind, ProviderCallStatus, ProviderResult)

    with pytest.raises(ValueError, match="bounded response read"):
        ProviderResult(
            "fake", "fake-v1", AdapterKind.FAKE,
            ProviderCallStatus.SUCCEEDED,
            response_bytes=b"x" * (MAX_PROVIDER_RESPONSE_BYTES + 2))


def test_unknown_provider_latency_remains_unknown():
    from .providers import AdapterKind, ProviderResult

    result = ProviderResult(
        "fake", "fake-v1", AdapterKind.FAKE, ProviderCallStatus.SUCCEEDED)
    assert result.latency_ms is None
