"""Tests for the versioned local-generation IPC contract."""

from __future__ import annotations

import pytest

from .contracts import (
    GenerationArtifact,
    GenerationCheckResult,
    GenerationRequest,
    GenerationResult,
    GenerationStatus,
)


def _request(**changes):
    values = {
        "run_id": "0" * 32,
        "recipe_json": '{"version":1,"name":"one"}',
        "output_root": "/private/run",
        "policy_snapshot": {"policy_version": 1},
        "check_config": {},
    }
    values.update(changes)
    return GenerationRequest(**values)


def test_request_round_trips_through_bounded_json():
    original = _request()
    restored = GenerationRequest.from_json(original.to_json())
    assert restored == original


@pytest.mark.parametrize("run_id", ["../x", "A" * 32, "0" * 31])
def test_request_rejects_nonopaque_run_ids(run_id):
    with pytest.raises(ValueError, match="run_id"):
        _request(run_id=run_id).to_json()


def test_request_rejects_unknown_and_missing_fields():
    value = _request().to_dict()
    value["provider"] = "must-not-cross-worker-boundary"
    with pytest.raises(ValueError, match="unknown or missing"):
        GenerationRequest.from_dict(value)
    del value["provider"]
    del value["check_config"]
    with pytest.raises(ValueError, match="unknown or missing"):
        GenerationRequest.from_dict(value)


def test_request_enforces_recipe_and_contract_size_bounds():
    with pytest.raises(ValueError, match="AI policy limit"):
        GenerationRequest.from_dict(_request(
            recipe_json=" " * (128 * 1024 + 1)).to_dict())


def test_contract_json_rejects_duplicate_keys_and_nonfinite_constants():
    with pytest.raises(ValueError, match="duplicate"):
        GenerationRequest.from_json(
            '{"schema_version":1,"schema_version":1}')
    raw = ('{"schema_version":1,"run_id":"' + "0" * 32 +
           '","status":"failed","artifacts":[],"checks":[],"warnings":[],'
           '"error_records":[],"elapsed_seconds":NaN,"record_path":null}')
    with pytest.raises(ValueError, match="invalid JSON constant"):
        GenerationResult.from_json(raw)


def test_result_round_trips_structured_artifacts_and_checks():
    result = GenerationResult(
        run_id="a" * 32,
        status=GenerationStatus.COMPLETE,
        artifacts=(GenerationArtifact("preview.png", "preview", 12,
                                      "0" * 64, "image/png"),),
        checks=(GenerationCheckResult("preview_decodes", True),),
        elapsed_seconds=1.25,
        record_path="record.json",
    )
    restored = GenerationResult.from_json(result.to_json())
    assert restored == result
    assert restored.ok


def test_failed_result_never_reports_success():
    result = GenerationResult("b" * 32, GenerationStatus.FAILED)
    assert not result.ok
