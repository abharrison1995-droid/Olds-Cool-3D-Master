"""Compatibility, limits, and divergence tests for optional generation metadata."""

from __future__ import annotations

import hashlib
import json
import uuid

import msgpack
import pytest

from am3d.core.project import Material, Project
from am3d.core.script import Session
from am3d.core.serializer import (
    ProjectFormatError,
    _unpack_msgpack,
    dump_project,
    load_project_bytes,
    project_content_digest,
    validate_generation_envelope,
)


def _envelope():
    recipe = {"name": "bounded test", "objects": []}
    canonical = json.dumps(recipe, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {
        "version": 1,
        "run_id": str(uuid.uuid4()),
        "parent_generation_id": None,
        "accepted_brief": {"brief": "bounded provenance"},
        "recipe": recipe,
        "recipe_sha256": hashlib.sha256(canonical).hexdigest(),
        "application": {"version": "0.2.0b1", "build_id": "source-code-sha256:abc",
                        "capability_version": "recipe-v1-policy-v1-prompt-v1"},
        "warnings": [],
        "artifact_refs": [{"path": "preview.png", "sha256": "a" * 64}],
    }


def test_new_generation_field_roundtrips_and_old_format_one_two_load(tmp_path):
    project = Project("generation roundtrip")
    project.generation = _envelope()
    payload = dump_project(project)
    reopened = load_project_bytes(payload)
    assert reopened.generation["diverged"] is False
    assert reopened.generation["project_digest"] == project_content_digest(reopened)
    assert load_project_bytes(dump_project(reopened)).generation == reopened.generation

    body = _unpack_msgpack(dump_project(Project("legacy")))
    body.pop("generation", None)
    for version in (1, 2):
        legacy = dict(body, format_version=version)
        read = load_project_bytes(msgpack.packb(legacy, use_bin_type=True))
        assert read.generation is None


def test_explicit_legacy_root_field_allowlist_drops_optional_generation():
    """Pre-provenance reader schemas ignore this additive root field on save."""
    new_body = _unpack_msgpack(dump_project(Project("legacy downgrade")))
    new_body["generation"] = _envelope()
    assert "generation" in new_body

    # The old format-2 serializer explicitly emitted only these root fields.
    # Replaying that reader/writer boundary demonstrates its documented
    # downgrade behavior without importing or modifying repository history.
    legacy_root_fields = {
        "format_version", "name", "objects", "materials", "skeletons",
        "actions", "fps", "animation_settings", "render_settings", "mode",
        "frame", "session_state", "poses", "pose_offsets",
    }
    old_reader_project = {key: value for key, value in new_body.items()
                          if key in legacy_root_fields}
    legacy_saved = msgpack.packb(old_reader_project, use_bin_type=True)
    reopened = load_project_bytes(legacy_saved)
    assert reopened.generation is None


@pytest.mark.parametrize("sensitive_key", [
    "raw_http", "API-Key", "response_body", "r_a_w_h_t_t_p",
])
def test_sensitive_and_invalid_envelope_data_is_rejected(sensitive_key):
    envelope = _envelope()
    envelope["accepted_brief"][sensitive_key] = "SENTINEL"
    with pytest.raises(ProjectFormatError) as error:
        validate_generation_envelope(envelope)
    assert "SENTINEL" not in str(error.value)


def test_generation_validation_rejects_mixed_keys_nan_surrogates_and_unsafe_refs():
    base = _envelope()
    with pytest.raises(ProjectFormatError, match="keys must be strings"):
        validate_generation_envelope({**base, 3: "bad"})

    for key, value in (("accepted_brief", {"number": float("nan")}),
                       ("accepted_brief", "bad\ud800"),
                       ("artifact_refs", [{"path": "CON.txt", "sha256": "a" * 64}])):
        invalid = _envelope()
        invalid[key] = value
        with pytest.raises(ProjectFormatError):
            validate_generation_envelope(invalid)


def test_manual_edit_marks_divergence_and_save_as_preserves_provenance(tmp_path):
    session = Session()
    session.new_project("manual edit")
    session.create_object("body")
    session.project.generation = _envelope()
    first = tmp_path / "first.am3d"
    session.save_project(str(first))
    original = load_project_bytes(first.read_bytes())
    assert original.generation["diverged"] is False

    session.project.objects["body"].transform[0, 3] = 0.5
    second = tmp_path / "save-as.am3d"
    session.save_project(str(second))
    saved_as = load_project_bytes(second.read_bytes())
    assert saved_as.generation["diverged"] is True
    assert saved_as.generation["run_id"] == original.generation["run_id"]
    assert saved_as.objects["body"].transform[0, 3] == pytest.approx(0.5)


def test_project_digest_ignores_view_state_but_detects_material_changes():
    project = Project("digest")
    digest = project_content_digest(project)
    project.frame = 47.0
    assert project_content_digest(project) == digest
    project.materials["blue"] = Material(name="blue", color=(0.1, 0.2, 0.9))
    assert project_content_digest(project) != digest
