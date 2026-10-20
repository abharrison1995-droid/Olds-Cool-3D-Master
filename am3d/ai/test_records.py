"""Atomic provenance store, recovery, and immutable-copy tests."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import shutil
import uuid

from PIL import Image
import pytest

from am3d.ai import records
from am3d.ai.checks import check_artifacts
from am3d.ai.contracts import (
    CancellationToken,
    DeadlineExceededError,
    GenerationCancelledError,
)
from am3d.ai.records import GenerationRecordStore, application_identity
from am3d.core.paths import extended_io_path
from am3d.core.project import Material
from am3d.core.script import Session
from am3d.core.serializer import load_project
from am3d.recipes.executor import RecipeExecutor


def _candidate(attempt, number=1, *, texture=False):
    candidate = attempt.candidate_dir(number)
    session = Session()
    session.new_project("record fixture")
    session.create_object("body")
    if texture:
        session.project.materials["paint"] = Material(
            name="paint", color=(0.2, 0.3, 0.4), texture="atlas.png")
        session.project.objects["body"].material = "paint"
        Image.new("RGBA", (8, 8), (12, 64, 192, 255)).save(candidate / "atlas.png")
    session.save_project(str(candidate / "project.am3d"))
    Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(candidate / "preview.png")
    artifacts = []
    for path in sorted(candidate.iterdir()):
        artifacts.append({"path": path.name,
                          "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                          "bytes": path.stat().st_size})
    report = {"ok": True, "status": "passed", "checks": [],
              "artifacts": artifacts}
    record = {"accepted_recipe": {"name": "record fixture", "objects": []},
              "accepted_brief": {"brief": "A record fixture."},
              "provider": {"provider": "test", "model": "local fake"},
              "usage": {"tokens": None, "cost": None}}
    return candidate, record, report


def _publish(store, *, run_id=None, parent_id=None, texture=False):
    attempt = store.begin(run_id, parent_id)
    candidate, record, report = _candidate(attempt, texture=texture)
    final = attempt.publish(candidate, record, report)
    return attempt, final, store.get_record(attempt.run_id)


def test_publish_rebuilds_record_from_files_and_creates_verified_working_copy(tmp_path):
    store = GenerationRecordStore(tmp_path / "history")
    _attempt, final, record = _publish(store, texture=True)

    assert Path(record["run_root"]) == final
    assert record["status"] == "complete"
    assert {item["path"] for item in record["artifact_manifest"]} >= {
        "project.am3d", "preview.png", "atlas.png", "recipe.json",
        "brief.json", "check-report.json"}
    assert store.list_records()[0]["run_id"] == record["run_id"]

    copy = store.create_working_copy(record, tmp_path / "copies" / "working")
    assert Path(copy["project_path"]).is_file()
    assert Path(copy["run_root"]) == Path(extended_io_path(tmp_path / "copies" / "working"))
    assert Path(copy["run_root"], "atlas.png").read_bytes() == (final / "atlas.png").read_bytes()
    reopened = load_project(copy["project_path"])
    assert reopened.generation is None
    # This fixture was not generated, so native provenance is correctly absent.
    assert (final / "project.am3d").read_bytes() == Path(record["project_path"]).read_bytes()


def test_publication_requires_exact_checked_manifest_and_keeps_prior_success(tmp_path):
    store = GenerationRecordStore(tmp_path / "history")
    parent_attempt, parent_path, parent = _publish(store)
    parent_bytes = (parent_path / "project.am3d").read_bytes()
    parent_record = (parent_path / "record.json").read_bytes()

    child = store.begin(parent_generation_id=parent["run_id"])
    candidate, record, report = _candidate(child)
    report["ok"] = False
    report["status"] = "failed"
    with pytest.raises(ValueError, match="checker-passed"):
        child.publish(candidate, record, report)
    assert not child.final_dir.exists()
    assert (parent_path / "project.am3d").read_bytes() == parent_bytes
    assert (parent_path / "record.json").read_bytes() == parent_record

    candidate, record, report = _candidate(child, number=2)
    report["artifacts"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="hash changed"):
        child.publish(candidate, record, report)
    assert (parent_path / "record.json").read_bytes() == parent_record
    assert store.get_record(parent["run_id"])["run_id"] == parent["run_id"]


def test_interrupted_attempt_is_visible_but_never_successful(tmp_path):
    store = GenerationRecordStore(tmp_path / "history")
    attempt = store.begin()
    candidate = attempt.candidate_dir("failed-one")
    (candidate / "partial.obj").write_text("partial", encoding="utf-8")
    attempt.write_state("checking", {"candidates": 1})

    recovered = store.recover_interrupted()
    assert len(recovered) == 1
    assert recovered[0]["status"] == "interrupted"
    visible = store.list_records()
    assert len(visible) == 1
    assert visible[0]["status"] == "interrupted"
    assert visible[0]["successful"] is False
    assert visible[0]["retryable"] is True


def test_atomic_promotion_linearizes_cancel_and_postcommit_journal_failure(tmp_path, monkeypatch):
    store = GenerationRecordStore(tmp_path / "history")
    attempt = store.begin()
    candidate, record, report = _candidate(attempt)
    token = CancellationToken()
    assert token.cancel() is True
    with pytest.raises(GenerationCancelledError):
        attempt.publish(candidate, record, report, cancellation=token)
    assert not attempt.final_dir.exists()

    late = store.begin()
    candidate, record, report = _candidate(late)
    real_write_state = late.write_state

    def fail_after_commit(status, value=None):
        if status == "complete":
            raise OSError("injected journal write failure")
        return real_write_state(status, value)

    monkeypatch.setattr(late, "write_state", fail_after_commit)
    committed = late.publish(candidate, record, report)
    assert committed.is_dir()
    assert token.cancel() is True  # A previously cancelled token stays cancelled.
    committed_token = CancellationToken()
    # A successful commit makes a subsequent cancel a harmless stale signal.
    second = store.begin()
    second_candidate, second_record, second_report = _candidate(second)
    second.publish(second_candidate, second_record, second_report,
                   cancellation=committed_token)
    assert committed_token.cancel() is False

    # The first committed run has stale running state because its journal write
    # was injected to fail. Recovery repairs it from record.json and lists one
    # authoritative success, never a duplicate attempt failure.
    store.recover_interrupted()
    listed = [item for item in store.list_records()
              if item.get("run_id") == late.run_id]
    assert len(listed) == 1
    assert listed[0]["status"] == "complete"
    assert store.get_record(late.run_id)["run_id"] == late.run_id


def test_expired_deadline_fails_before_promotion_and_history_delete_warns_for_children(tmp_path):
    store = GenerationRecordStore(tmp_path / "history")
    parent_attempt, _parent_path, parent = _publish(store)

    child_attempt = store.begin(parent_generation_id=parent["run_id"])
    candidate, record, report = _candidate(child_attempt)
    with pytest.raises(DeadlineExceededError):
        child_attempt.publish(candidate, record, report, deadline=0.0)
    assert not child_attempt.final_dir.exists()

    child_attempt, _child_path, child = _publish(
        store, parent_id=parent["run_id"])
    warning = store.delete(parent["run_id"])
    assert warning["deleted"] is False
    assert warning["needs_parent_confirmation"] is True
    assert child["run_id"] in warning["child_generation_ids"]
    assert store.delete(parent["run_id"], confirm_parent=True)["deleted"] is True
    assert store.get_record(child["run_id"])["run_id"] == child["run_id"]


def test_publication_failure_before_commit_preserves_candidate_parent_and_history(tmp_path, monkeypatch):
    store = GenerationRecordStore(tmp_path / "history")
    _attempt, parent_path, parent = _publish(store)
    before_project = (parent_path / "project.am3d").read_bytes()
    before_record = (parent_path / "record.json").read_bytes()
    attempt = store.begin(parent_generation_id=parent["run_id"])
    candidate, record, report = _candidate(attempt)
    original = records._atomic_json

    def injected_disk_full(path, value, *, limit=records._MAX_RECORD_BYTES):
        if Path(path).name == "check-report.json":
            raise OSError("injected disk-full while staging")
        return original(path, value, limit=limit)

    monkeypatch.setattr(records, "_atomic_json", injected_disk_full)
    with pytest.raises(OSError, match="injected disk-full"):
        attempt.publish(candidate, record, report)
    assert not attempt.final_dir.exists()
    assert candidate.exists()
    assert (parent_path / "project.am3d").read_bytes() == before_project
    assert (parent_path / "record.json").read_bytes() == before_record
    assert store.get_record(parent["run_id"])["run_id"] == parent["run_id"]


def test_publication_rejects_artifact_changed_after_checker_hash(tmp_path, monkeypatch):
    store = GenerationRecordStore(tmp_path / "history")
    attempt = store.begin()
    candidate, record, report = _candidate(attempt)
    preview = candidate / "preview.png"
    original_manifest = records._artifact_manifest
    changed = False

    def mutate_before_full_scan(root, **kwargs):
        nonlocal changed
        if Path(root) == candidate and not changed:
            preview.write_bytes(preview.read_bytes() + b"changed after checked hash")
            changed = True
        return original_manifest(root, **kwargs)

    monkeypatch.setattr(records, "_artifact_manifest", mutate_before_full_scan)
    with pytest.raises(ValueError, match="checker-verified manifest"):
        attempt.publish(candidate, record, report)
    assert changed
    assert not attempt.final_dir.exists()


def test_publication_rechecks_private_snapshot_before_atomic_promotion(tmp_path, monkeypatch):
    store = GenerationRecordStore(tmp_path / "history")
    attempt = store.begin()
    candidate, record, report = _candidate(attempt)
    original_atomic_json = records._atomic_json
    mutated = False

    def mutate_staging_after_report(path, value, *, limit=records._MAX_RECORD_BYTES):
        nonlocal mutated
        result = original_atomic_json(path, value, limit=limit)
        path = Path(path)
        if path.name == "record.json" and not mutated:
            (path.parent / "preview.png").write_bytes(b"post-copy mutation")
            mutated = True
        return result

    monkeypatch.setattr(records, "_atomic_json", mutate_staging_after_report)
    with pytest.raises(OSError, match="final verification"):
        attempt.publish(candidate, record, report)
    assert mutated
    assert not attempt.final_dir.exists()
    assert candidate.exists()


def test_cancellation_is_polled_between_artifact_hash_chunks(tmp_path, monkeypatch):
    store = GenerationRecordStore(tmp_path / "history")
    attempt = store.begin()
    candidate, record, report = _candidate(attempt)
    large = candidate / "atlas.png"
    large.write_bytes(b"bounded test bytes" * (128 * 1024))
    report["artifacts"].append({"path": "atlas.png",
                                "sha256": hashlib.sha256(large.read_bytes()).hexdigest(),
                                "bytes": large.stat().st_size})
    token = CancellationToken()
    real_open = Path.open
    canceled = False

    class CancelAfterFirstChunk:
        def __init__(self, stream, path):
            self.stream = stream
            self.path = path

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def read(self, size=-1):
            nonlocal canceled
            chunk = self.stream.read(size)
            if self.path.name == "atlas.png" and chunk and not canceled:
                token.cancel()
                canceled = True
            return chunk

    def tracked_open(path, *args, **kwargs):
        stream = real_open(path, *args, **kwargs)
        if args and args[0] == "rb":
            return CancelAfterFirstChunk(stream, path)
        return stream

    monkeypatch.setattr(Path, "open", tracked_open)
    with pytest.raises(GenerationCancelledError):
        attempt.publish(candidate, record, report, cancellation=token)
    assert canceled
    assert not attempt.final_dir.exists()


def test_application_identity_is_stable_and_explicit_about_source_scope():
    first = application_identity()
    second = application_identity()
    assert first == second
    assert first["version"]
    assert first["capability_version"] == "recipe-v1-policy-v1-prompt-v1"
    if first["build_id"] != "unavailable":
        assert first["build_id"].startswith("source-code-sha256:")


def test_record_store_handles_windows_host_io_paths_longer_than_260(tmp_path):
    long_root = tmp_path / "long-run-root"
    for index in range(7):
        long_root = long_root / (f"segment-{index}-" + "x" * 35)
    try:
        os.makedirs(extended_io_path(long_root), exist_ok=False)
        store = GenerationRecordStore(long_root)
        attempt = store.begin()
        candidate = attempt.candidate_dir(1)
        recipe = {"name": "long path", "objects": [
            {"name": "body", "primitive": "box"}], "materials": [], "exports": []}
        session = Session()
        assert RecipeExecutor(session).execute(recipe).ok
        session.save_project(str(candidate / "project.am3d"))
        generation = {"run_id": attempt.run_id,
                      "accepted_brief": {"brief": "A bounded cube."}}
        report = check_artifacts(recipe, candidate,
                                 brief={"brief": "A bounded cube."},
                                 generation=generation)
        assert next(item for item in report["checks"]
                    if item["id"] == "native_roundtrip")["status"] == "passed"
        assert report["ok"] is True, report["checks"]
        final = attempt.publish(candidate,
                                {"accepted_recipe": recipe,
                                 "accepted_brief": {"brief": "A bounded cube."}},
                                report)
        assert store.get_record(attempt.run_id)["run_root"] == str(final)
        assert store.root.is_dir()
        assert len(str(final)) > 260
    finally:
        shutil.rmtree(extended_io_path(long_root), ignore_errors=True)
