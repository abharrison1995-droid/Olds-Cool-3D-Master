"""Offline tests for frozen V1 benchmark ledgers and score import."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import uuid

import pytest

from . import benchmark
from . import orchestrator as orchestrator_module
from .contracts import AssetBrief, ProviderResponse, ProviderUsage
from .records import GenerationRecordStore


REPO_ROOT = Path(__file__).resolve().parents[2]
_RUNNER_SPEC = importlib.util.spec_from_file_location(
    "v1_benchmark_runner_test", REPO_ROOT / "scripts" / "run_ai_benchmark.py")
RUNNER = importlib.util.module_from_spec(_RUNNER_SPEC)
assert _RUNNER_SPEC is not None and _RUNNER_SPEC.loader is not None
_RUNNER_SPEC.loader.exec_module(RUNNER)


def _manifest(scope="release", mode="fake"):
    _document, fixtures = benchmark.load_fixture_set(REPO_ROOT, scope)
    fixture_ids = ([item["id"] for item in fixtures])
    provider_id = {"live": "openai-compatible", "fake": "offline-fake",
                   "replay": "offline-replay"}[mode]
    return {
        "schema_version": benchmark.RUN_SCHEMA_VERSION,
        "run_uuid": str(uuid.uuid4()),
        "created_utc": "2026-10-13T00:00:00Z",
        "scope": scope,
        "fixture_set": "v1-release" if scope == "release" else "v1-discovery",
        "mode": mode,
        "qualifying_mode": False,
        "qualification_label": "NONQUALIFYING",
        "denominator": len(fixture_ids),
        "fixture_ids": fixture_ids,
        "provider": {"provider_id": provider_id,
                     "model": "offline-test-model",
                     "endpoint_host": None, "endpoint_path": None,
                     "credential_source": None, "credential_alias": None},
        "limits": {
            "max_semantic_calls": 150 if scope == "release" else 40,
            "completion_output_token_reservation": 1_228_800 if scope == "release" else 327_680,
            "max_http_attempts_per_semantic_call": 0,
            "http_attempts_conservative_upper_bound": 0,
        },
        "frozen_inputs": {
            "source": {"baseline_head": "3f6f7f03d32b4d1a3af06af4fdc0724bf0436945",
                       "dirty_diff_sha256": "a" * 64},
            "fixture_files": {},
            "fixture_item_sha256": benchmark._fixture_hashes(fixtures),
            "prompt_context": {},
        },
    }


def _write_run(run_root: Path, manifest: dict, *, statuses=None) -> dict:
    fixtures = benchmark.load_fixture_set(REPO_ROOT, manifest["scope"])[1]
    journal = benchmark.new_journal(manifest, fixtures)
    journal["status"] = "complete"
    journal["started_utc"] = "2026-10-13T00:00:00Z"
    journal["completed_utc"] = "2026-10-13T00:01:00Z"
    if statuses is None:
        statuses = ["failed"] * manifest["denominator"]
    for item, status in zip(journal["items"], statuses):
        item["status"] = status
        item["completed_utc"] = "2026-10-13T00:01:00Z"
        item["failure_class"] = "provider_or_infrastructure" if status == "failed" else None
        item["failure_code"] = "provider_transient" if status == "failed" else None
    run_root.mkdir(parents=True)
    benchmark.atomic_write_json(run_root / "manifest.json", manifest)
    benchmark.persist_journal(run_root, journal)
    return journal


def _score_template(manifest: dict, reviewer_id: str) -> dict:
    return {
        "schema_version": benchmark.HUMAN_SCHEMA_VERSION,
        "review_kind": "v1_visual_native_review",
        "run_uuid": manifest["run_uuid"],
        "manifest_sha256": benchmark.manifest_sha256(manifest),
        "reviewer_id": reviewer_id,
        "items": [
            {"id": item_id, "preview": None, "native_project": None,
             "scores": {"recognizable_silhouette": 2,
                        "essential_components": 2,
                        "proportions_and_appearance": 2,
                        "editability": 2}}
            for item_id in benchmark.RELEASE_IDS
        ],
    }


def test_fixture_id_hash_revision_and_independent_requirements_are_unchanged():
    document, fixtures = benchmark.load_fixture_set(REPO_ROOT, "release")
    assert document["frozen"] is True
    assert tuple(item["id"] for item in fixtures) == benchmark.RELEASE_IDS
    assert [item["tier"] for item in fixtures].count("static") == 25
    assert [item["tier"] for item in fixtures].count("rig") == 5
    assert benchmark.sha256_file(REPO_ROOT / "benchmarks/v1/prompts.json") == (
        "0ef3291a7cb5818091a1a22ebdbfe75dc9cb4118274f32fe6395c478e119e560")
    fixture = fixtures[22]
    expected = {key: deepcopy(value) for key, value in fixture.items()
                if key not in {"id", "tier", "prompt"}}
    assert benchmark.fixture_requirements(fixture) == expected
    assert benchmark.fixture_requirements(fixture)["component_count_checks"] == fixture["component_count_checks"]
    fixture_with_disclosure = next(item for item in fixtures
                                   if "requirements" in item)
    assert benchmark.fixture_requirements(fixture_with_disclosure)["requirements"] == fixture_with_disclosure["requirements"]


def test_manifest_freezes_denominator_source_build_inputs_and_provider_disclosure():
    manifest = benchmark.build_manifest(
        REPO_ROOT, scope="release", mode="fake",
        provider={"provider_id": "offline-fake", "model": "offline-refusal-v1"},
        limits={"max_semantic_calls": 150,
                "completion_output_tokens": 150 * 8192},
    )
    assert manifest["fixture_ids"] == list(benchmark.RELEASE_IDS)
    assert manifest["denominator"] == 30
    assert manifest["mode"] == "fake"
    assert manifest["qualification_label"] == "NONQUALIFYING"
    assert manifest["provider"]["provider_id"] == "offline-fake"
    assert manifest["frozen_inputs"]["source"]["baseline_head"]
    assert manifest["frozen_inputs"]["source"]["dirty_diff_sha256"]
    files = manifest["frozen_inputs"]["source"]["runtime_build_inputs"]
    assert "am3d/ai/orchestrator.py" in files
    assert "pyproject.toml" in files
    assert manifest["frozen_inputs"]["fixture_files"]["benchmarks/v1/prompts.json"] == (
        "0ef3291a7cb5818091a1a22ebdbfe75dc9cb4118274f32fe6395c478e119e560")
    assert manifest["frozen_inputs"]["prompt_context"]["prompt_template_sha256"]
    assert manifest["frozen_inputs"]["prompt_context"]["capability_context_sha256"]
    assert manifest["frozen_inputs"]["prompt_context"]["recipe_schema_sha256"]
    assert manifest["model_drift_disclosure"] == manifest["provider"]["drift_disclosure"]
    assert "cannot qualify" in manifest["model_drift_disclosure"]
    assert manifest["limits"]["actual_cost_usd"] is None
    assert manifest["limits"]["http_attempts_actual"] is None


def _real_offline_generation(tmp_path, monkeypatch):
    fixtures = benchmark.load_fixture_set(REPO_ROOT, "release")[1]
    fixture = fixtures[7]
    manifest = _manifest()
    run_root = tmp_path / "run"
    run_root.mkdir()
    journal = benchmark.new_journal(manifest, fixtures)
    journal["status"] = "running"
    journal["started_utc"] = "2026-10-13T00:00:00Z"
    item = journal["items"][7]
    item["status"] = "running"
    item["started_utc"] = "2026-10-13T00:00:00Z"
    benchmark.atomic_write_json(run_root / "manifest.json", manifest)
    benchmark.persist_journal(run_root, journal)

    class OfflineFixtureProvider:
        calls = 0

        def generate(self, _request, _deadline, _cancellation):
            self.calls += 1
            return ProviderResponse(
                provider="offline-fake", model="offline-test-model",
                request_id=f"offline-{self.calls}", json_text="{}", json_data={},
                usage=ProviderUsage(prompt_tokens=2, completion_tokens=3,
                                    total_tokens=5, cost_usd=None),
                finish_reason="stop")

    recipe = {"version": 1, "name": "benchmark receipt cube",
              "objects": [{"name": "cube", "primitive": "box",
                           "params": {"width": 1.0, "height": 1.0,
                                      "depth": 1.0}}], "exports": []}

    def interpret(provider, request, deadline, cancellation):
        provider.generate(None, deadline, cancellation)
        return AssetBrief(brief=request)

    def candidate(provider, _brief, deadline, cancellation, **_kwargs):
        provider.generate(None, deadline, cancellation)
        return deepcopy(recipe)

    monkeypatch.setattr(orchestrator_module, "interpret_brief", interpret)
    monkeypatch.setattr(orchestrator_module, "build_candidate", candidate)
    store = GenerationRecordStore(run_root / "store")
    provider = OfflineFixtureProvider()
    outcome = orchestrator_module.GenerationOrchestrator(provider, store).generate(
        fixture["prompt"], requirements={}, run_id=str(uuid.uuid4()))
    assert outcome.status == "completed", outcome.error
    return run_root, journal, item, fixture, outcome


def test_real_offline_worker_store_receipt_is_anchored_once_and_rechecked(tmp_path, monkeypatch):
    run_root, journal, item, fixture, outcome = _real_offline_generation(tmp_path, monkeypatch)
    generation_root = run_root / "store" / "generations" / outcome.run_id
    record_path = generation_root / "record.json"
    record_original = record_path.read_bytes()
    receipt_dir = run_root / "generation-receipts"
    receipt_path = receipt_dir / f"{outcome.run_id}.json"
    assert not receipt_path.exists()

    # Returned in-memory identity must match the committed generation before
    # the trusted host captures a receipt.
    original_provider = deepcopy(outcome.record["provider"])
    item["generation_id"] = outcome.run_id
    outcome.record["provider"]["model"] = "tampered-before-capture"
    with pytest.raises(benchmark.BenchmarkError, match="returned generation identity"):
        benchmark._capture_generation_receipt(run_root, item, journal["manifest"],
                                              outcome, fixture)
    assert not receipt_path.exists()
    outcome.record["provider"] = original_provider

    benchmark.apply_outcome(
        journal, item["id"], outcome,
        provider_stats={"semantic_calls_forwarded": 2,
                        "semantic_call_attempts": 2,
                        "output_tokens_reserved": 20},
        wall_seconds=1.0, run_root=run_root, fixture=fixture)
    benchmark.persist_journal(run_root, journal)
    assert item["status"] == "completed"
    assert item["deterministic_pass"] is True
    assert item["generation_receipt"]["path"] == f"generation-receipts/{outcome.run_id}.json"
    assert benchmark.verify_success_artifacts(run_root, item, journal["manifest"])["valid"]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["fixture"] == fixture
    assert receipt["fixture_assertions"] == benchmark.fixture_requirements(fixture)
    assert receipt["fixture_assertions"].get("requirements") == fixture.get("requirements")
    assert receipt["source_run_manifest_sha256"] == journal["manifest_sha256"]
    assert receipt["provider"]["provider"] == "offline-fake"
    assert receipt["provider"]["model"] == "offline-test-model"
    assert receipt["record_sha256"] == benchmark.sha256_bytes(record_original)
    for relative in ("project.am3d", "preview.png"):
        entry = next(entry for entry in receipt["artifact_manifest"]
                     if entry["path"] == relative)
        assert benchmark.sha256_file(generation_root / relative) == entry["sha256"]

    # Metadata edits are rejected even when the byte artifacts remain valid.
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["provider"] = {"provider": "openai-compatible", "model": "live-model"}
    record["check_report"]["checks"] = [
        {"id": "native_roundtrip", "status": "passed"},
        {"id": "whole_scene_preview", "status": "passed"}]
    record_path.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
    assert benchmark.verify_success_artifacts(run_root, item, journal["manifest"])["valid"] is False
    record_path.write_bytes(record_original)
    assert benchmark.verify_success_artifacts(run_root, item, journal["manifest"])["valid"]

    # Rewriting a self-consistent record/receipt cannot make arbitrary bytes
    # pass the independent physical PNG decode and native load/save/reopen.
    preview_path = generation_root / "preview.png"
    native_path = generation_root / "project.am3d"
    preview_original, native_original = preview_path.read_bytes(), native_path.read_bytes()
    check_report_path = generation_root / "check-report.json"
    saved_report = check_report_path.read_bytes()
    preview_path.write_bytes(b"not-a-png")
    native_path.write_bytes(b"not-a-native-project")
    record = json.loads(record_original.decode("utf-8"))
    report = json.loads(saved_report.decode("utf-8"))
    first_manifest, _ = __import__("am3d.ai.records", fromlist=["_artifact_manifest"])._artifact_manifest(generation_root)
    current_by_path = {entry["path"]: entry for entry in first_manifest}
    for entry in report["artifacts"]:
        if entry["path"] in {"preview.png", "project.am3d"}:
            entry.update({key: current_by_path[entry["path"]][key]
                          for key in ("sha256", "bytes")})
    report_raw = json.dumps(report, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"), allow_nan=False).encode("utf-8")
    check_report_path.write_bytes(report_raw)
    artifact_manifest, _ = __import__("am3d.ai.records", fromlist=["_artifact_manifest"])._artifact_manifest(generation_root)
    record["artifact_manifest"] = artifact_manifest
    record["check_report"] = report
    record_raw = json.dumps(record, sort_keys=True, ensure_ascii=False,
                            separators=(",", ":"), allow_nan=False).encode("utf-8")
    record_path.write_bytes(record_raw)
    forged_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    forged_receipt["record_sha256"] = benchmark.sha256_bytes(record_raw)
    forged_receipt["artifact_manifest"] = artifact_manifest
    forged_receipt["check_report"] = report
    forged_receipt["check_report_sha256"] = benchmark.sha256_bytes(benchmark.canonical_json(report))
    forged_receipt["check_report_sidecar_sha256"] = benchmark.sha256_bytes(report_raw)
    forged_receipt["artifact_hashes"] = {
        entry["path"]: {"sha256": entry["sha256"], "bytes": entry["bytes"]}
        for entry in artifact_manifest}
    receipt_raw = benchmark.canonical_json(forged_receipt) + b"\n"
    receipt_path.write_bytes(receipt_raw)
    item["generation_receipt"]["sha256"] = benchmark.sha256_bytes(
        benchmark.canonical_json(forged_receipt))
    integrity = benchmark.verify_success_artifacts(run_root, item, journal["manifest"])
    assert integrity["valid"] is False
    assert integrity["preview_verified"] is False
    assert integrity["native_roundtrip"] is False
    preview_path.write_bytes(preview_original)
    native_path.write_bytes(native_original)
    (generation_root / "check-report.json").write_bytes(saved_report)
    record_path.write_bytes(record_original)
    receipt_path.write_bytes(benchmark.canonical_json(receipt) + b"\n")
    item["generation_receipt"]["sha256"] = benchmark.sha256_bytes(
        benchmark.canonical_json(receipt))
    assert benchmark.verify_success_artifacts(run_root, item, journal["manifest"])["valid"]

    # Missing/changed anchors fail closed and report-time verification never
    # creates a replacement receipt.
    original_anchor = deepcopy(item["generation_receipt"])
    item["generation_receipt"] = None
    assert not benchmark.verify_success_artifacts(run_root, item, journal["manifest"])["valid"]
    assert receipt_path.exists()
    benchmark.persist_journal(run_root, journal)
    report_without_anchor = benchmark.single_run_report(run_root, REPO_ROOT)
    assert report_without_anchor["qualification"] == "NONQUALIFYING"
    persisted_after_report = benchmark.load_journal(run_root)
    assert persisted_after_report["items"][7]["generation_receipt"] is None
    assert receipt_path.exists()
    item["generation_receipt"] = original_anchor
    changed_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    changed_receipt["provider"]["model"] = "edited-receipt"
    receipt_path.write_bytes(benchmark.canonical_json(changed_receipt) + b"\n")
    assert not benchmark.verify_success_artifacts(run_root, item, journal["manifest"])["valid"]
    assert benchmark.deterministic_result(journal)["denominator"] == 30
    assert benchmark.single_run_report(run_root, REPO_ROOT)["qualification"] == "NONQUALIFYING"


def test_changed_frozen_inputs_are_rejected(monkeypatch):
    manifest = _manifest()
    frozen_source = manifest["frozen_inputs"]["source"]
    files = {"one": "1" * 64}
    monkeypatch.setattr(benchmark, "source_snapshot", lambda _root: frozen_source)
    monkeypatch.setattr(benchmark, "_file_hashes", lambda _root: files)
    manifest["frozen_inputs"]["fixture_files"] = files
    assert benchmark.frozen_inputs_match(REPO_ROOT, manifest)
    monkeypatch.setattr(benchmark, "source_snapshot",
                        lambda _root: {**frozen_source, "dirty_diff_sha256": "b" * 64})
    assert not benchmark.frozen_inputs_match(REPO_ROOT, manifest)


def test_interrupted_item_and_failed_items_remain_denominator_and_cannot_be_overwritten(tmp_path):
    manifest = _manifest()
    journal = benchmark.new_journal(
        manifest, benchmark.load_fixture_set(REPO_ROOT, "release")[1])
    journal["items"][0]["status"] = "running"
    journal["items"][1]["status"] = "failed"
    journal["items"][1]["failure_code"] = "provider_transient"
    assert benchmark.mark_interrupted_items(journal)
    assert journal["items"][0]["status"] == "interrupted"
    assert journal["items"][1]["status"] == "failed"
    assert len(journal["items"]) == 30

    class Outcome:
        status = "completed"
        ok = True
        run_id = str(uuid.uuid4())
        record = {}
        check_report = None

    with pytest.raises(benchmark.BenchmarkError, match="cannot be overwritten"):
        benchmark.apply_outcome(journal, "02", Outcome(),
                                provider_stats={}, wall_seconds=1.0,
                                run_root=tmp_path)
    benchmark.refresh_totals(journal)
    assert journal["totals"]["cost_usd"] is None
    assert journal["totals"]["http_attempts_actual"] is None
    assert benchmark.deterministic_result(journal)["denominator"] == 30
    assert benchmark.deterministic_result(journal)["status"] == "INCOMPLETE"


def test_deterministic_tier_floors_keep_failures_in_the_fixed_denominator():
    manifest = _manifest()
    journal = benchmark.new_journal(
        manifest, benchmark.load_fixture_set(REPO_ROOT, "release")[1])
    journal["status"] = "complete"
    passing_ids = set(benchmark.RELEASE_STATIC_IDS[:23] + benchmark.RELEASE_RIG_IDS[:4])
    for item in journal["items"]:
        passed = item["id"] in passing_ids
        item["status"] = "completed" if passed else "failed"
        item["deterministic_pass"] = passed
        item["record_integrity"] = ({"valid": True, "native_roundtrip": True,
                                     "preview_verified": True,
                                     "whole_scene_preview_verified": True,
                                     "record_manifest_verified": True,
                                     "provider_matches_manifest": True}
                                    if passed else None)
    result = benchmark.deterministic_result(journal)
    assert result["status"] == "PASS"
    assert result["passes"] == 27
    assert result["static_passes"] == 23
    assert result["rig_passes"] == 4
    assert result["denominator"] == 30

    for item_id in benchmark.RELEASE_RIG_IDS[:2]:
        item = next(row for row in journal["items"] if row["id"] == item_id)
        item["status"] = "failed"
        item["deterministic_pass"] = False
        item["record_integrity"] = None
    result = benchmark.deterministic_result(journal)
    assert result["status"] == "FAIL"
    assert result["passes"] == 25


def test_offline_gate_is_always_nonqualifying_even_with_two_ledgers(tmp_path):
    roots = []
    for _ in range(2):
        manifest = _manifest()
        root = tmp_path / manifest["run_uuid"]
        _write_run(root, manifest)
        roots.append(root)
    result = benchmark.two_run_gate(roots[0], roots[1], REPO_ROOT)
    assert result["qualification"] == "NONQUALIFYING"
    assert result["release_gate"] == "FAIL_OR_PENDING"
    assert result["live_release_runs"] is False
    assert all(run["qualification"] == "NONQUALIFYING" for run in result["runs"])


def test_human_import_requires_two_original_independent_files_and_separate_resolution(tmp_path):
    manifest = _manifest()
    run_root = tmp_path / "run"
    journal = _write_run(run_root, manifest)
    template_path = tmp_path / "blank-review.json"
    template = benchmark.export_human_template(run_root, template_path)
    assert template["items"][0]["preview"] is None
    assert template["items"][0]["native_project"] is None

    originals = []
    for reviewer, silhouette in (("reviewer-a", 2), ("reviewer-b", 1)):
        score = _score_template(manifest, reviewer)
        score["items"][0]["scores"]["recognizable_silhouette"] = silhouette
        path = tmp_path / f"{reviewer}.json"
        raw = json.dumps(score, ensure_ascii=False, indent=2).encode("utf-8")
        path.write_bytes(raw)
        result = benchmark.import_human_scores(run_root, path)
        assert result["counts"]["human_acceptable"] == 30
        originals.append((raw, result["original_file"]))
    for raw, preserved_path in originals:
        assert Path(preserved_path).read_bytes() == raw

    derived_files = list((run_root / "human-review" / "derived").glob("*.json"))
    assert len(derived_files) == 2
    derived = json.loads(derived_files[0].read_text(encoding="utf-8"))
    derived["reviewer_id"] = "forged-derived-reviewer"
    derived["counts"]["human_acceptable"] = 0
    derived_files[0].write_text(json.dumps(derived), encoding="utf-8")
    before_resolution = benchmark._human_result(run_root, benchmark.load_journal(run_root))
    assert set(before_resolution["reviewers"]) == {"reviewer-a", "reviewer-b"}
    assert before_resolution["human_acceptable"] == 30
    assert before_resolution["status"] == "PENDING_RESOLUTION"
    with pytest.raises(benchmark.BenchmarkError, match="already exists"):
        benchmark.import_human_scores(run_root, tmp_path / "reviewer-a.json")

    resolution_template = benchmark.export_human_resolution_template(
        run_root, tmp_path / "resolution-blank.json")
    assert [item["id"] for item in resolution_template["items"]] == ["01"]
    resolution_template["items"][0]["resolution"] = "accepted"
    resolution_template["items"][0]["note"] = "The preview and native project were compared."
    resolution_file = tmp_path / "resolution.json"
    resolution_raw = json.dumps(resolution_template, indent=2).encode("utf-8")
    resolution_file.write_bytes(resolution_raw)
    stored_resolution = benchmark.import_human_resolution(run_root, resolution_file)
    assert Path(stored_resolution["original_file"]).read_bytes() == resolution_raw
    derived_resolution = Path(stored_resolution["analysis_path"])
    forged_resolution = json.loads(derived_resolution.read_text(encoding="utf-8"))
    forged_resolution["items"][0]["resolution"] = "unresolved"
    derived_resolution.write_text(json.dumps(forged_resolution), encoding="utf-8")
    human = benchmark._human_result(run_root, benchmark.load_journal(run_root))
    assert human["status"] == "PASS"
    assert human["human_acceptable"] == 30
    assert human["agreement"]["score_comparisons"] == 120
    assert human["agreement"]["exact_score_matches"] == 119
    assert human["agreement"]["disagreement_item_ids"] == ["01"]
    assert human["resolution"]["status"] == "RECORDED"


def test_human_import_rejects_self_asserted_qualification_duplicate_ids_and_bad_scores(tmp_path):
    manifest = _manifest()
    run_root = tmp_path / "run"
    _write_run(run_root, manifest)
    valid = _score_template(manifest, "reviewer-a")
    bad_cases = []
    self_asserted = deepcopy(valid)
    self_asserted["qualification"] = "PASS"
    bad_cases.append(self_asserted)
    duplicate = deepcopy(valid)
    duplicate["items"][1]["id"] = duplicate["items"][0]["id"]
    bad_cases.append(duplicate)
    out_of_range = deepcopy(valid)
    out_of_range["items"][0]["scores"]["essential_components"] = 3
    bad_cases.append(out_of_range)
    bool_score = deepcopy(valid)
    bool_score["items"][0]["scores"]["essential_components"] = True
    bad_cases.append(bool_score)
    for index, case in enumerate(bad_cases):
        path = tmp_path / f"invalid-{index}.json"
        path.write_text(json.dumps(case), encoding="utf-8")
        with pytest.raises(benchmark.BenchmarkError):
            benchmark.import_human_scores(run_root, path)
    assert not list((run_root / "human-review").rglob("*.json")) if (run_root / "human-review").exists() else True


def test_budget_reservation_is_journaled_before_provider_and_not_reused_after_restart(tmp_path):
    manifest = _manifest()
    journal = benchmark.new_journal(
        manifest, benchmark.load_fixture_set(REPO_ROOT, "release")[1])
    journal["status"] = "running"
    journal["items"][0]["status"] = "running"
    run_root = tmp_path / "run"
    run_root.mkdir()
    benchmark.atomic_write_json(run_root / "manifest.json", manifest)
    benchmark.persist_journal(run_root, journal)
    journal = benchmark.load_journal(run_root)

    class FailingProvider:
        calls = 0

        def generate(self, _request, _deadline, _cancellation):
            self.calls += 1
            raise RuntimeError("credential-sentinel-must-not-be-logged")

    provider = FailingProvider()
    wrapper = RUNNER.BudgetedProvider(provider, max_calls=1,
                                      output_token_budget=20)
    item = journal["items"][0]
    wrapper.set_case(item["id"], on_progress=RUNNER._item_progress_callback(
        journal, item, run_root))
    request = SimpleNamespace(output_token_limit=20)
    with pytest.raises(RuntimeError):
        wrapper.generate(request, 10.0, SimpleNamespace(cancelled=False))
    assert provider.calls == 1
    durable = benchmark.load_journal(run_root)
    assert durable["totals"]["semantic_calls"] == 1
    assert durable["totals"]["completion_output_tokens_reserved"] == 20
    assert durable["items"][0]["provider_calls"]["http_attempts_actual"] is None
    assert durable["items"][0]["usage"]["cost_usd"] is None

    resumed = RUNNER.BudgetedProvider(provider, max_calls=1,
                                      output_token_budget=20,
                                      initial_calls=durable["totals"]["semantic_calls"],
                                      initial_output_tokens=durable["totals"]["completion_output_tokens_reserved"])
    resumed.set_case("02")
    with pytest.raises(Exception):
        resumed.generate(request, 10.0, SimpleNamespace(cancelled=False))
    assert provider.calls == 1
    assert resumed.snapshot()["semantic_calls_forwarded"] == 1


def test_provider_completion_usage_cannot_silently_exceed_its_reserved_request_limit():
    class OverBudgetProvider:
        def generate(self, _request, _deadline, _cancellation):
            return SimpleNamespace(usage=SimpleNamespace(
                prompt_tokens=7, completion_tokens=21, total_tokens=28,
                cost_usd=None))

    wrapper = RUNNER.BudgetedProvider(
        OverBudgetProvider(), max_calls=1, output_token_budget=20)
    wrapper.set_case("01")
    with pytest.raises(Exception, match="reported completion usage above"):
        wrapper.generate(SimpleNamespace(output_token_limit=20), 10.0,
                         SimpleNamespace(cancelled=False))
    progress = wrapper._progress_snapshot()
    assert progress["output_tokens_reserved"] == 20
    assert progress["usage"]["completion_tokens"] == 21
    assert progress["budget_stop_reason"] == "provider_output_exceeded_reserved_completion_limit"


def test_cli_output_parent_stays_inside_per_user_benchmark_directory(tmp_path, monkeypatch):
    local_data = tmp_path / "per-user-local-data"
    monkeypatch.setenv("LOCALAPPDATA", str(local_data))
    default_parent = RUNNER._default_output_parent()
    allowed = default_parent / "test-run-output"
    assert RUNNER._validated_output_parent(str(allowed)) == allowed
    with pytest.raises(RUNNER.RunInputError, match="per-user benchmark directory"):
        RUNNER._validated_output_parent(str(tmp_path / "shared-output"))


def test_provider_error_projection_and_fake_provider_do_not_expose_secrets_or_network():
    secret = "credential-sentinel-0123456789"
    safe = benchmark.safe_provider_error({
        "code": "provider_credential", "stage": "provider",
        "message": f"provider body echoed {secret}",
    })
    assert safe == {"code": "provider_credential", "stage": "provider"}
    assert secret not in repr(safe)
    provider = RUNNER.ReplayProvider(model="offline-refusal-v1")
    provider.set_case("01")
    response = provider.generate(
        SimpleNamespace(purpose="brief_interpretation"), 10.0,
        SimpleNamespace(cancelled=False),
    )
    assert response.provider == "offline-fake"
    assert response.refused is True
    assert response.usage.cost_usd is None
