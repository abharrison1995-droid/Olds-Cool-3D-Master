"""Focused state-machine tests for the headless bounded orchestrator."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from am3d.ai import orchestrator as orch
from am3d.ai.contracts import (
    AssetBrief,
    CancellationToken,
    ProviderAuthenticationError,
    ProviderProtocolError,
    ProviderRefusalError,
    ProviderResponse,
    ProviderUsage,
)
from am3d.ai.policy import PolicyError
from am3d.recipes.schema import RecipeValidationError


def _recipe(name="cube"):
    return {
        "version": 1,
        "name": name,
        "objects": [{"name": "cube", "primitive": "box",
                     "params": {"width": 1.0, "height": 1.0, "depth": 1.0}}],
        "exports": [],
    }


class FakeProvider:
    def __init__(self):
        self.calls = 0

    def generate(self, _request, _deadline, _cancellation):
        self.calls += 1
        return ProviderResponse(
            provider="fake", model="fixed-test-model", request_id=f"req-{self.calls}",
            json_text="{}", json_data={},
            usage=ProviderUsage(prompt_tokens=2, completion_tokens=3,
                                total_tokens=5, cost_usd=None),
            finish_reason="stop",
        )


class MemoryStore:
    def __init__(self, root: Path, *, fail_publish=False):
        self.root = root
        self.fail_publish = fail_publish
        self.attempts = []
        self.published = {}
        self.parents = {}

    def begin(self, run_id=None, parent_generation_id=None):
        attempt = MemoryAttempt(self, run_id, parent_generation_id)
        self.attempts.append(attempt)
        return attempt

    def get_record(self, run_id):
        return copy.deepcopy(self.parents[run_id])


class MemoryAttempt:
    def __init__(self, store, run_id, parent_id):
        self.store = store
        self.run_id = run_id
        self.parent_generation_id = parent_id
        self.attempt_dir = store.root / "attempts" / run_id
        self.attempt_dir.mkdir(parents=True)
        self.final_dir = store.root / "generations" / run_id
        self.states = []

    def candidate_dir(self, number):
        result = self.attempt_dir / f"candidate-{number:02d}"
        result.mkdir()
        return result

    def write_state(self, status, record=None):
        assert status in {"running", "checking", "failed", "cancelled"}
        self.states.append((status, copy.deepcopy(record or {})))

    def publish(self, candidate_dir, record, check_report, *,
                cancellation=None, deadline=None):
        if self.store.fail_publish:
            raise OSError("secret path detail should never escape")
        assert check_report["ok"] is True and check_report["status"] == "passed"
        self.final_dir.parent.mkdir(parents=True, exist_ok=True)
        published = copy.deepcopy(record)
        published.update(status="complete", run_id=self.run_id,
                         parent_generation_id=self.parent_generation_id)
        def promote():
            self.store.published[self.run_id] = published
            return self.final_dir
        return cancellation.commit(promote, deadline=deadline)


def _fake_worker(sequence, calls=None):
    calls = calls if calls is not None else []

    def run(recipe, output_dir, deadline, cancellation, *, check_options=None):
        calls.append((copy.deepcopy(recipe), Path(output_dir), check_options))
        attempt_id = "worker-attempt"
        inner = Path(output_dir) / f"attempt-{attempt_id}"
        inner.mkdir()
        native = inner / "project.am3d"
        native.write_bytes(b"fake native project")
        status = sequence.pop(0)
        passed = status == "checked_ok"
        report = {
            "ok": passed,
            "status": "passed" if passed else "failed",
            "checks": ([{"id": "native_roundtrip", "status": "passed"}]
                       if passed else [{"id": "surface_geometry", "status": "failed"}]),
            "artifacts": ([{"path": "project.am3d",
                             "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                             "bytes": native.stat().st_size}]
                          if passed else []),
            "measurements": {},
            "limitations": [],
        }
        errors = [] if passed else [
            {"code": "checks_failed" if status == "check_failed" else "execution_error",
             "stage": "check" if status == "check_failed" else "runtime",
             "path": "recipe"}
        ]
        return {
            "status": status,
            "attempt_id": attempt_id,
            "checks_status": "passed" if passed else "failed",
            "check_report": report,
            "error_records": errors,
            "manifest": ([{"path": f"{inner.name}/project.am3d",
                           "sha256": hashlib.sha256(native.read_bytes()).hexdigest(),
                           "bytes": native.stat().st_size}]),
        }

    return run


def _patch_prompts(monkeypatch, candidates, *, brief_error=None, seen=None):
    provider_calls = []
    seen = seen if seen is not None else {}

    def interpret(provider, request, deadline, cancellation):
        provider.generate(None, deadline, cancellation)
        seen["interpreted"] = request
        if brief_error:
            raise brief_error
        return AssetBrief(brief=request)

    def build(provider, brief, deadline, cancellation, previous_recipe=None,
              repair_errors=None, refinement_request=None):
        provider.generate(None, deadline, cancellation)
        provider_calls.append({
            "previous_recipe": copy.deepcopy(previous_recipe),
            "repair_errors": copy.deepcopy(repair_errors),
            "refinement_request": refinement_request,
        })
        value = candidates.pop(0)
        if isinstance(value, BaseException):
            raise value
        return copy.deepcopy(value)

    monkeypatch.setattr(orch, "interpret_brief", interpret)
    monkeypatch.setattr(orch, "build_candidate", build)
    return provider_calls, seen


def _orchestrator(tmp_path, monkeypatch, candidate_results,
                  worker_results, *, fail_publish=False, brief_error=None,
                  seen=None, provider=None):
    calls, seen = _patch_prompts(monkeypatch, candidate_results,
                                 brief_error=brief_error, seen=seen)
    store = MemoryStore(tmp_path / "store", fail_publish=fail_publish)
    worker_calls = []
    worker = _fake_worker(worker_results, worker_calls)
    subject = orch.GenerationOrchestrator(provider or FakeProvider(), store,
                                          worker_runner=worker)
    return subject, store, calls, worker_calls, seen


def test_repairs_share_exact_candidate_and_semantic_call_ceilings(tmp_path, monkeypatch):
    subject, store, build_calls, workers, _ = _orchestrator(
        tmp_path, monkeypatch,
        [{"objects": [{"name": "bad"}]},
         {"objects": [{"name": "bad"}]},
         _recipe("runtime-fails"), _recipe("check-fails")],
        ["execution_failed", "check_failed"],
    )

    outcome = subject.generate("Make a cube")

    assert outcome.status == "check_failed"
    assert outcome.record["candidate_count"] == orch.MAX_CANDIDATES == 4
    assert outcome.record["validation_repairs"] == orch.MAX_VALIDATION_REPAIRS == 2
    assert outcome.record["runtime_check_repairs"] == orch.MAX_RUNTIME_CHECK_REPAIRS == 1
    assert outcome.record["usage"]["semantic_calls"] == orch.MAX_SEMANTIC_CALLS == 5
    assert len(build_calls) == 4
    assert len(workers) == 2
    assert store.published == {}
    assert store.attempts[0].states[-1][0] == "failed"


def test_first_checked_candidate_is_the_only_publishable_result(tmp_path, monkeypatch):
    subject, store, _build_calls, workers, _ = _orchestrator(
        tmp_path, monkeypatch, [_recipe()], ["checked_ok"])
    events = []

    outcome = subject.generate("Make a cube", on_event=events.append)

    assert outcome.status == "completed"
    assert outcome.record["accepted_recipe"]["name"] == "cube"
    assert outcome.record["candidate_recipe"] == _recipe()
    assert outcome.record["accepted_recipe"]["exports"] != []
    assert len(workers) == 1
    assert store.published[outcome.run_id]["status"] == "complete"
    assert events and [event.sequence for event in events] == list(range(len(events)))
    assert all(event.run_id == outcome.run_id and event.progress is None for event in events)
    assert outcome.record["usage"]["prompt_tokens"] == 4
    assert outcome.record["usage"]["total_tokens"] == 10
    assert outcome.record["usage"]["cost_usd"] is None
    assert "http_attempts" in outcome.record["usage"]


def test_check_failure_gets_one_shared_repair_then_publishes(tmp_path, monkeypatch):
    subject, _store, build_calls, workers, _ = _orchestrator(
        tmp_path, monkeypatch,
        [_recipe("first"), _recipe("repaired")],
        ["check_failed", "checked_ok"],
    )

    outcome = subject.generate("Make a cube")

    assert outcome.status == "completed"
    assert len(workers) == len(build_calls) == 2
    assert build_calls[1]["previous_recipe"]["name"] == "first"
    assert build_calls[1]["repair_errors"][0]["stage"] == "check"
    assert outcome.record["accepted_recipe"]["name"] == "repaired"


@pytest.mark.parametrize("worker_status", ["check_failed", "checked_ok"])
def test_host_resource_limit_is_terminal_before_repair_or_promotion(
        tmp_path, monkeypatch, worker_status):
    subject, store, build_calls, worker_calls, _ = _orchestrator(
        tmp_path, monkeypatch, [_recipe()], [worker_status])
    ordinary_runner = subject.worker_runner

    def mark_host_resource_limit(*args, **kwargs):
        result = ordinary_runner(*args, **kwargs)
        result["check_report"]["resource_limit"] = True
        return result

    subject.worker_runner = mark_host_resource_limit

    outcome = subject.generate("Make a cube")

    assert outcome.status == "resource_limit"
    assert outcome.error["code"] == "resource_limit"
    assert outcome.error["stage"] == "check"
    assert outcome.record["check_report"]["resource_limit"] is True
    assert outcome.record["candidate_count"] == 1
    assert outcome.record["validation_repairs"] == 0
    assert outcome.record["runtime_check_repairs"] == 0
    assert outcome.record["usage"]["semantic_calls"] == 2
    assert len(build_calls) == len(worker_calls) == 1
    assert store.published == {}
    terminal_status, terminal_record = store.attempts[0].states[-1]
    assert terminal_status == "failed"
    assert terminal_record["runtime_check_repairs"] == 0
    assert terminal_record["error"]["code"] == "resource_limit"


def test_truthy_nonboolean_resource_limit_does_not_suppress_ordinary_repair(
        tmp_path, monkeypatch):
    subject, store, build_calls, worker_calls, _ = _orchestrator(
        tmp_path, monkeypatch, [_recipe("first"), _recipe("repaired")],
        ["check_failed", "checked_ok"])
    ordinary_runner = subject.worker_runner

    def mark_nonboolean_resource_value(*args, **kwargs):
        result = ordinary_runner(*args, **kwargs)
        result["check_report"]["resource_limit"] = 1
        return result

    subject.worker_runner = mark_nonboolean_resource_value

    outcome = subject.generate("Make a cube")

    assert outcome.status == "completed"
    assert outcome.record["candidate_count"] == 2
    assert outcome.record["runtime_check_repairs"] == 1
    assert len(build_calls) == len(worker_calls) == 2
    assert outcome.run_id in store.published


def test_policy_denial_is_terminal_and_never_sent_as_repair(tmp_path, monkeypatch):
    subject, _store, build_calls, workers, _ = _orchestrator(
        tmp_path, monkeypatch, [_recipe()], [])
    monkeypatch.setattr(orch, "prepare_recipe",
                        lambda *_args, **_kwargs: (_ for _ in ()).throw(
                            PolicyError("output_path_denied", "unsafe path")))

    outcome = subject.generate("Make a cube")

    assert outcome.status == "policy_error"
    assert len(build_calls) == 1
    assert workers == []
    assert outcome.error["code"] == "output_path_denied"


def test_provider_refusal_and_authentication_are_terminal(tmp_path, monkeypatch):
    for error, expected in ((ProviderRefusalError("private provider body"), "provider_refused"),
                            (ProviderAuthenticationError("private auth detail"), "provider_error")):
        subject, _store, build_calls, workers, _ = _orchestrator(
            tmp_path / expected, monkeypatch, [], [], brief_error=error)
        outcome = subject.generate("Make a cube")
        assert outcome.status == expected
        assert build_calls == [] and workers == []
        assert "private" not in str(outcome.record)


def test_terminal_user_choice_snapshots_completed_interpret_provider_call(
        tmp_path, monkeypatch):
    from am3d.ai.prompts import BriefRequiresUserChoiceError

    raw = "Make a model with an unsupported feature."
    error = BriefRequiresUserChoiceError(["model supplied unsupported detail"])
    subject, store, build_calls, workers, _ = _orchestrator(
        tmp_path, monkeypatch, [], [], brief_error=error)

    outcome = subject.generate(raw)

    assert outcome.status == "user_choice_required"
    assert build_calls == [] and workers == []
    assert outcome.record["usage"] == {
        "semantic_calls": 1, "http_attempts": None,
        "prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5,
        "cost_usd": None, "provider_responses": 1,
    }
    assert outcome.record["provider"] == {
        "provider": "fake", "model": "fixed-test-model", "request_id": "req-1"}
    assert store.attempts[0].states[-1][1]["usage"] == outcome.record["usage"]


def test_protocol_repair_cancel_snapshots_call_and_consumed_repair(
        tmp_path, monkeypatch):
    provider = FakeProvider()

    def interpret(metered, request, deadline, cancellation):
        metered.generate(None, deadline, cancellation)
        return AssetBrief(brief=request)

    def build(metered, brief, deadline, cancellation, **_kwargs):
        metered.generate(None, deadline, cancellation)
        raise ProviderProtocolError("candidate response schema is malformed")

    monkeypatch.setattr(orch, "interpret_brief", interpret)
    monkeypatch.setattr(orch, "build_candidate", build)
    store = MemoryStore(tmp_path / "store")
    subject = orch.GenerationOrchestrator(provider, store, worker_runner=_fake_worker([]))
    token = CancellationToken()

    def cancel_on_repair(event):
        if event.stage == "validation_repair":
            token.cancel()

    outcome = subject.generate("Make a cube", cancellation=token,
                               on_event=cancel_on_repair)

    assert outcome.status == "cancelled"
    assert outcome.record["candidate_count"] == 1
    assert outcome.record["validation_repairs"] == 1
    assert outcome.record["runtime_check_repairs"] == 0
    assert outcome.record["usage"] == {
        "semantic_calls": 2, "http_attempts": None,
        "prompt_tokens": 4, "completion_tokens": 6, "total_tokens": 10,
        "cost_usd": None, "provider_responses": 2,
    }
    assert outcome.record["provider"]["request_id"] == "req-2"
    failed_state = store.attempts[0].states[-1]
    assert failed_state[0] == "cancelled"
    assert failed_state[1]["candidate_count"] == 1
    assert failed_state[1]["validation_repairs"] == 1
    assert failed_state[1]["usage"] == outcome.record["usage"]


@pytest.mark.parametrize("fail_on,expected_calls,expected_responses,expected_candidate_count", [
    (1, 1, 0, 0),
    (2, 2, 1, 1),
])
def test_provider_error_snapshots_attempted_calls_without_unreturned_metadata(
        tmp_path, monkeypatch, fail_on, expected_calls, expected_responses,
        expected_candidate_count):
    class FailAtCallProvider:
        def __init__(self):
            self.calls = 0

        def generate(self, _request, _deadline, _cancellation):
            self.calls += 1
            if self.calls == fail_on:
                raise ProviderAuthenticationError("credential detail must not persist")
            return ProviderResponse(
                provider="fake", model="validated-model", request_id=f"validated-{self.calls}",
                json_text="{}", json_data={},
                usage=ProviderUsage(prompt_tokens=7, completion_tokens=4,
                                    total_tokens=11, cost_usd=None),
                finish_reason="stop")

    subject, store, build_calls, workers, _ = _orchestrator(
        tmp_path, monkeypatch, [_recipe()], [], provider=FailAtCallProvider())

    outcome = subject.generate("Make a cube")

    assert outcome.status == "provider_error"
    assert outcome.record["usage"]["semantic_calls"] == expected_calls
    assert outcome.record["usage"]["provider_responses"] == expected_responses
    assert outcome.record["candidate_count"] == expected_candidate_count
    assert outcome.record["validation_repairs"] == 0
    assert outcome.record["runtime_check_repairs"] == 0
    assert "credential detail" not in str(outcome.record)
    if expected_responses:
        assert outcome.record["usage"]["prompt_tokens"] == 7
        assert outcome.record["provider"]["request_id"] == "validated-1"
    else:
        assert outcome.record["usage"]["prompt_tokens"] is None
        assert outcome.record["provider"] == {
            "provider": None, "model": None, "request_id": None}
    assert not workers
    if fail_on == 1:
        assert build_calls == []


@pytest.mark.parametrize("raw_request,known_part,code,hint_fragment", [
    ("Animate the character and export the animation as GLB.", "animated glb",
     "animated_glb_unsupported", "animation sheet"),
    ("Make the windows physically transparent glass.", "transparent glass",
     "physical_glass_unsupported", "stylized opaque or tinted"),
    ("Export the vehicle as FBX.", None,
     "unsupported_export_format", "Supported choices are OBJ"),
])
def test_user_choice_error_surfaces_only_fixed_known_limitation_choices(
        tmp_path, monkeypatch, raw_request, known_part, code, hint_fragment):
    from am3d.ai.prompts import BriefRequiresUserChoiceError

    if known_part:
        limitations = orch._known_user_choice_limitations(raw_request)
        assert limitations and known_part in limitations[0].lower()
        limitations = [*limitations, "MODEL SECRET: C:\\private\\secret"]
    else:
        # A model-authored unsupported-requirement marker cannot supply UI copy.
        limitations = ["MODEL SECRET: C:\\private\\secret"]
    subject, store, build_calls, workers, _ = _orchestrator(
        tmp_path, monkeypatch, [], [], brief_error=BriefRequiresUserChoiceError(limitations))

    outcome = subject.generate(raw_request)

    assert outcome.status == "user_choice_required"
    assert outcome.error["code"] == code
    assert hint_fragment.lower() in outcome.error["hint"].lower()
    assert "MODEL SECRET" not in str(outcome.error)
    assert "C:\\private" not in str(outcome.record)
    assert not build_calls and not workers and not store.published


def test_publication_failure_is_terminal_and_keeps_checked_evidence(tmp_path, monkeypatch):
    subject, _store, build_calls, workers, _ = _orchestrator(
        tmp_path, monkeypatch, [_recipe()], ["checked_ok"], fail_publish=True)

    outcome = subject.generate("Make a cube")

    assert outcome.status == "publication_failed"
    assert len(build_calls) == len(workers) == 1
    assert outcome.record["check_report"]["ok"] is True
    assert "secret path detail" not in str(outcome.record)


@pytest.mark.parametrize("stage", ["starting", "interpreting", "candidate",
                                    "checking", "publishing"])
def test_cancellation_is_rechecked_at_each_boundary(tmp_path, monkeypatch, stage):
    worker_states = ["checked_ok"] if stage == "publishing" else []
    subject, store, _build_calls, workers, _ = _orchestrator(
        tmp_path, monkeypatch, [_recipe()], worker_states)
    token = CancellationToken()

    def cancel_on_boundary(event):
        if event.stage == stage:
            token.cancel()

    outcome = subject.generate("Make a cube", cancellation=token,
                               on_event=cancel_on_boundary)

    assert outcome.status == "cancelled"
    assert not store.published
    expected_semantic_calls = {
        "starting": 0, "interpreting": 0, "candidate": 1,
        "checking": 2, "publishing": 2,
    }
    expected_candidates = {"starting": 0, "interpreting": 0,
                           "candidate": 0, "checking": 1,
                           "publishing": 1}
    assert outcome.record["usage"]["semantic_calls"] == expected_semantic_calls[stage]
    assert outcome.record["usage"]["provider_responses"] == expected_semantic_calls[stage]
    assert outcome.record["candidate_count"] == expected_candidates[stage]
    assert outcome.record["validation_repairs"] == 0
    assert outcome.record["runtime_check_repairs"] == 0
    persisted = store.attempts[0].states[-1][1]
    assert persisted["usage"] == outcome.record["usage"]
    assert persisted["candidate_count"] == outcome.record["candidate_count"]
    if stage in {"starting", "interpreting", "candidate", "checking"}:
        assert workers == []
    else:
        assert len(workers) == 1
    assert store.attempts[0].states[-1][0] == "cancelled"


def test_observer_exception_and_late_cancellation_do_not_corrupt_run(tmp_path, monkeypatch):
    subject, _store, _build_calls, _workers, _ = _orchestrator(
        tmp_path, monkeypatch, [_recipe()], ["checked_ok"])

    def bad_observer(_event):
        raise RuntimeError("observer failure")

    outcome = subject.generate("Make a cube", on_event=bad_observer)
    assert outcome.status == "completed"


def test_cancel_after_atomic_commit_cannot_relabel_success(tmp_path, monkeypatch):
    subject, store, _build_calls, _workers, _ = _orchestrator(
        tmp_path, monkeypatch, [_recipe()], ["checked_ok"])
    token = CancellationToken()
    cancel_result = []

    def cancel_after_commit(event):
        if event.stage == "completed":
            cancel_result.append(token.cancel())

    outcome = subject.generate("Make a cube", cancellation=token,
                               on_event=cancel_after_commit)

    assert outcome.status == "completed"
    assert cancel_result == [False]
    assert outcome.run_id in store.published


def test_cancellation_token_commit_linearizes_cancel_requests():
    token = CancellationToken()
    assert token.commit(lambda: "published") == "published"
    assert token.cancel() is False
    assert token.cancelled is False
    actions = []
    with pytest.raises(RuntimeError, match="already been committed"):
        token.commit(lambda: actions.append("must not run"))
    assert actions == []


@pytest.mark.parametrize("deadline", [True, float("nan"), float("inf"), "later"])
def test_cancellation_token_rejects_invalid_commit_deadlines(deadline):
    token = CancellationToken()
    actions = []
    with pytest.raises(ValueError, match="finite monotonic timestamp"):
        token.commit(lambda: actions.append("must not run"), deadline=deadline)
    assert actions == []


@pytest.mark.parametrize("name,value", [
    ("total_seconds", 0), ("total_seconds", float("nan")),
    ("total_seconds", float("inf")), ("total_seconds", True),
    ("worker_seconds", -1), ("worker_seconds", float("nan")),
])
def test_nonfinite_or_nonpositive_deadline_configuration_is_rejected(tmp_path, name, value):
    kwargs = {name: value}
    with pytest.raises(ValueError, match="positive finite"):
        orch.GenerationOrchestrator(FakeProvider(), MemoryStore(tmp_path), **kwargs)


def test_validation_repairs_receive_only_sanitized_structured_errors(tmp_path, monkeypatch):
    secret = "C:\\private\\provider-key"
    bad = {"objects": [{"name": "bad"}]}
    subject, _store, build_calls, workers, _ = _orchestrator(
        tmp_path, monkeypatch, [bad, _recipe()], ["checked_ok"])
    monkeypatch.setattr(orch, "prepare_recipe", lambda raw, **_kw: (
        (_ for _ in ()).throw(RecipeValidationError(
            "invalid_value", f"do not retain {secret}", path="recipe.objects[0].params.radius",
            hint="Set a finite radius.")) if raw == bad else _recipe("cube")))

    outcome = subject.generate("Make a cube")

    assert outcome.status == "completed"
    assert build_calls[1]["repair_errors"][0]["path"] == "recipe.objects[0].params.radius"
    assert secret not in str(build_calls[1]["repair_errors"])
    assert workers and secret not in str(outcome.record)


def test_valid_recipe_runs_through_real_worker_checks_and_immutable_publish(
        tmp_path, monkeypatch):
    from am3d.ai.records import GenerationRecordStore

    def interpret(provider, raw_request, deadline, cancellation):
        provider.generate(None, deadline, cancellation)
        return AssetBrief(brief=raw_request)

    def build(provider, brief, deadline, cancellation, **_kwargs):
        provider.generate(None, deadline, cancellation)
        return _recipe("worker-checked-cube")

    monkeypatch.setattr(orch, "interpret_brief", interpret)
    monkeypatch.setattr(orch, "build_candidate", build)
    store = GenerationRecordStore(tmp_path / "real-record-store")
    worker_results = []

    def real_worker(*args, **kwargs):
        result = orch.run_worker(*args, **kwargs)
        worker_results.append(result)
        return result

    subject = orch.GenerationOrchestrator(FakeProvider(), store,
                                          worker_runner=real_worker)

    outcome = subject.generate("Create one simple cube")

    assert outcome.status == "completed", (
        outcome.error,
        [(item.get("status"), item.get("error_records"), item.get("checks_status"))
         for item in worker_results],
    )
    assert outcome.check_report["ok"] is True
    assert outcome.check_report["status"] == "passed"
    assert Path(outcome.record_path).is_file()
    saved = store.get_record(outcome.run_id)
    assert saved["status"] == "complete"
    assert Path(saved["project_path"]).is_file()
    assert saved["candidate_recipe"] == _recipe("worker-checked-cube")
    assert saved["accepted_recipe"]["name"] == "worker-checked-cube"
    assert saved["accepted_brief"]["brief"] == "Create one simple cube"
    assert saved["parent_generation_id"] is None
    assert saved["candidate_count"] == 1
    assert saved["validation_repairs"] == 0
    assert saved["runtime_check_repairs"] == 0


def test_worker_audit_diagnostics_persist_only_fixed_categories():
    from am3d.ai._generation_reports import _safe_worker_summary
    result = {"status": "worker_error", "error_records": [{
        "audit_reason": "unexpected_file", "audit_phase": "live", "message": "private sentinel"}]}
    summary = _safe_worker_summary(result)
    assert summary["audit_reason"] == "unexpected_file"
    assert summary["audit_phase"] == "live"
    assert "sentinel" not in str(summary)
    result["error_records"][0]["audit_reason"] = "private sentinel"
    assert "audit_reason" not in _safe_worker_summary(result)
    result["error_records"][0]["audit_reason"] = []
    assert "audit_reason" not in _safe_worker_summary(result)
