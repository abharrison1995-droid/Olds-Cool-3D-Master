"""Headless bounded generation, repair, checking, and publication."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import math
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping

from am3d.recipes.schema import RecipeValidationError

from .contracts import (
    AssetBrief,
    CancellationToken,
    DeadlineExceededError,
    GenerationCancelledError,
    GenerationEvent,
    MAX_GENERATION_SECONDS,
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderCredentialError,
    ProviderError,
    ProviderModelError,
    ProviderProtocolError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderRequestError,
    ProviderResponse,
    ProviderResponseTooLargeError,
    ProviderTransientError,
    ProviderTruncatedResponseError,
    ProviderUsage,
)
from .policy import PolicyError, prepare_recipe
from .prompts import (
    BriefRequiresUserChoiceError,
    _known_user_choice_limitations,
    build_candidate,
    interpret_brief,
    prompt_context_metadata,
)
from .worker import MAX_WORKER_SECONDS, run_worker


MAX_CANDIDATES = 4
MAX_SEMANTIC_CALLS = 5
MAX_VALIDATION_REPAIRS = 2
MAX_RUNTIME_CHECK_REPAIRS = 1
MAX_ERROR_RECORDS = 32
MAX_ERROR_TEXT = 256
_SAFE_FIELD = re.compile(r"^[A-Za-z0-9_.\[\]]{1,192}$")
_SAFE_CODE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


@dataclass(slots=True)
class GenerationOutcome:
    run_id: str
    status: str
    record: dict[str, Any]
    record_path: str | None = None
    check_report: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    published_path: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"


@dataclass(slots=True)
class _Usage:
    responses: int = 0
    prompt: list[int | None] = field(default_factory=list)
    completion: list[int | None] = field(default_factory=list)
    total: list[int | None] = field(default_factory=list)
    cost: list[float | None] = field(default_factory=list)
    provider_metadata: list[dict[str, str | None]] = field(default_factory=list)

    def add(self, response: Any) -> None:
        if not isinstance(response, ProviderResponse):
            return
        usage = response.usage if isinstance(response.usage, ProviderUsage) else ProviderUsage()
        self.responses += 1
        self.prompt.append(usage.prompt_tokens)
        self.completion.append(usage.completion_tokens)
        self.total.append(usage.total_tokens)
        self.cost.append(usage.cost_usd)
        self.provider_metadata.append({
            "provider": _short_optional(response.provider, 128),
            "model": _short_optional(response.model, 128),
            "request_id": _short_optional(response.request_id, 128),
        })

    def _sum(self, values: list[int | float | None]) -> int | float | None:
        if not values or any(value is None for value in values):
            return None
        return sum(values)  # type: ignore[arg-type]

    def as_record(self, semantic_calls: int) -> dict[str, Any]:
        return {
            "semantic_calls": semantic_calls,
            # Provider adapters may retry transport internally; the current
            # provider contract does not expose that count.
            "http_attempts": None,
            "prompt_tokens": self._sum(self.prompt),
            "completion_tokens": self._sum(self.completion),
            "total_tokens": self._sum(self.total),
            "cost_usd": self._sum(self.cost),
            "provider_responses": self.responses,
        }


class _MeteredProvider:
    """Count only actual semantic calls and retain response metadata, not bodies."""

    def __init__(self, provider: Any, usage: _Usage, deadline: float,
                 cancellation: CancellationToken,
                 clock: Callable[[], float]) -> None:
        self._provider = provider
        self._usage = usage
        self._deadline = deadline
        self._cancellation = cancellation
        self._clock = clock
        self.semantic_calls = 0

    def generate(self, request: Any, deadline: float, cancellation: CancellationToken) -> Any:
        if self.semantic_calls >= MAX_SEMANTIC_CALLS:
            raise _BudgetExceeded("semantic_call_limit")
        if self._cancellation.cancelled or cancellation.cancelled:
            raise GenerationCancelledError("Generation was cancelled.")
        effective_deadline = min(deadline, self._deadline)
        if self._clock() >= effective_deadline:
            raise DeadlineExceededError("The generation deadline expired.")
        self.semantic_calls += 1
        response = self._provider.generate(request, effective_deadline, self._cancellation)
        self._usage.add(response)
        return response


class _BudgetExceeded(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class GenerationOrchestrator:
    """Run one isolated generation using shared deadlines and finite repairs."""

    def __init__(self, provider: Any, store: Any, *,
                 worker_runner: Callable[..., dict] = run_worker,
                 clock: Callable[[], float] = time.monotonic,
                 total_seconds: float = MAX_GENERATION_SECONDS,
                 worker_seconds: float = MAX_WORKER_SECONDS) -> None:
        """Create the host-side coordinator.

        ``clock`` is injectable for deterministic tests, but must use the
        same absolute monotonic time base as provider, worker, and publication
        deadline checks.
        """
        self.provider = provider
        self.store = store
        self.worker_runner = worker_runner
        self.clock = clock
        self.total_seconds = _bounded_seconds(total_seconds, MAX_GENERATION_SECONDS,
                                              "total_seconds")
        self.worker_seconds = _bounded_seconds(worker_seconds, MAX_WORKER_SECONDS,
                                               "worker_seconds")

    def generate(self, user_request: str, *,
                 cancellation: CancellationToken | None = None,
                 on_event: Callable[[GenerationEvent], Any] | None = None,
                 requirements: dict | None = None,
                 run_id: str | None = None,
                 parent_generation_id: str | None = None,
                 refinement_request: str | None = None) -> GenerationOutcome:
        """Generate, check, and atomically publish a child run.

        ``requirements`` is caller-authored deterministic check evidence. A
        refinement always reloads a successful parent record and interprets
        the parent's original brief together with the new instruction.
        """
        token = cancellation or CancellationToken()
        try:
            canonical_run_id = _canonical_uuid(run_id) if run_id else str(uuid.uuid4())
            parent_id = _canonical_uuid(parent_generation_id) if parent_generation_id else None
        except (ValueError, TypeError, AttributeError):
            return self._unrecorded(str(uuid.uuid4()), "invalid_request", "invalid_generation_id")
        started = self.clock()
        deadline = started + self.total_seconds
        try:
            attempt = self.store.begin(run_id=canonical_run_id,
                                      parent_generation_id=parent_id)
        except Exception:
            return self._unrecorded(canonical_run_id, "record_error", "record_store_error")
        canonical_run_id = attempt.run_id
        if canonical_run_id != (run_id or canonical_run_id):
            # The store must honor a caller-provided ID exactly.
            return self._finish(attempt, canonical_run_id, "record_error",
                                _base_record(canonical_run_id, parent_id),
                                _safe_error("record_id_mismatch", "record"), None)

        record = _base_record(canonical_run_id, parent_id)
        usage = _Usage()
        metered = _MeteredProvider(self.provider, usage, deadline, token, self.clock)
        state = _RunState(canonical_run_id, attempt, on_event, token,
                          self.clock, deadline, parent_id, requirements,
                          metered, usage)
        state.snapshot(record)
        try:
            state.emit("starting", "Preparing an isolated generation run.", 0)
            state.write("running", record)
            if token.cancelled:
                return self._finish(attempt, canonical_run_id, "cancelled", record,
                                    _safe_error("cancelled", "orchestrator"), state)
            if self.clock() >= deadline:
                return self._finish(attempt, canonical_run_id, "timed_out", record,
                                    _safe_error("deadline_exceeded", "orchestrator"), state)

            parent_record = None
            raw_request = user_request
            previous_recipe = None
            if refinement_request is not None:
                if not parent_id:
                    return self._finish(attempt, canonical_run_id, "failed", record,
                                        _safe_error("refinement_parent_required", "refinement"), state)
                parent_record = self._load_parent(parent_id)
                if parent_record is None:
                    return self._finish(attempt, canonical_run_id, "failed", record,
                                        _safe_error("parent_record_unavailable", "refinement"), state)
                parent_brief = _parent_brief_text(parent_record)
                previous_recipe = _parent_recipe(parent_record)
                if not parent_brief or previous_recipe is None:
                    return self._finish(attempt, canonical_run_id, "failed", record,
                                        _safe_error("parent_record_invalid", "refinement"), state)
                if not _parent_is_checked(parent_record):
                    return self._finish(attempt, canonical_run_id, "failed", record,
                                        _safe_error("parent_not_successful", "refinement"), state)
                raw_request = parent_brief + "\n\nRequested refinement: " + str(refinement_request)

            state.emit("interpreting", "Interpreting the brief within the shared time limit.", 0)
            try:
                brief = interpret_brief(metered, raw_request, deadline, token)
            except GenerationCancelledError:
                return self._finish(attempt, canonical_run_id, "cancelled", record,
                                    _safe_error("cancelled", "provider"), state)
            except DeadlineExceededError:
                return self._finish(attempt, canonical_run_id, "timed_out", record,
                                    _safe_error("deadline_exceeded", "provider"), state)
            except Exception as exc:
                if isinstance(exc, BriefRequiresUserChoiceError):
                    error = _brief_choice_error(exc, raw_request)
                    return self._finish(attempt, canonical_run_id,
                                        "user_choice_required", record, error, state)
                status, error = _classify_exception(exc, stage="brief")
                return self._finish(attempt, canonical_run_id, status, record, error, state)

            # Dataclass tuples are valid Python but the policy, checker, and
            # sidecar contracts require ordinary JSON lists.
            brief_data = json.loads(json.dumps(asdict(brief),
                                               ensure_ascii=False,
                                               allow_nan=False))
            application = _application_identity()
            record["accepted_brief"] = brief_data
            record["application"] = application
            record["prompt_context"] = _prompt_metadata()
            state.write("running", record)
            state.emit("brief_ready", "Brief interpretation is ready.", 0)
            if token.cancelled:
                return self._finish(attempt, canonical_run_id, "cancelled", record,
                                    _safe_error("cancelled", "orchestrator"), state)

            candidate_recipe = None
            accepted_recipe = None
            check_report = None
            repair_errors = None
            runtime_repair_pending = False
            last_status = "failed"
            last_error = _safe_error("generation_failed", "orchestrator")

            while state.candidate_count < MAX_CANDIDATES:
                if token.cancelled:
                    return self._finish(attempt, canonical_run_id, "cancelled", record,
                                        _safe_error("cancelled", "orchestrator"), state,
                                        check_report)
                if self.clock() >= deadline:
                    return self._finish(attempt, canonical_run_id, "timed_out", record,
                                        _safe_error("deadline_exceeded", "orchestrator"), state,
                                        check_report)
                if metered.semantic_calls >= MAX_SEMANTIC_CALLS:
                    break
                candidate_number = state.candidate_count + 1
                state.emit("candidate", "Requesting a bounded recipe candidate.",
                           candidate_number)
                if token.cancelled:
                    return self._finish(attempt, canonical_run_id, "cancelled", record,
                                        _safe_error("cancelled", "orchestrator"), state,
                                        check_report)
                candidate_dir = Path(attempt.candidate_dir(candidate_number))
                state.candidate_count = candidate_number
                state.attempt = candidate_number
                state.active_candidate_dir = candidate_dir
                state.write("running", record)
                try:
                    candidate_recipe = build_candidate(
                        metered, brief, deadline, token,
                        previous_recipe=previous_recipe,
                        repair_errors=repair_errors,
                        refinement_request=refinement_request,
                    )
                    try:
                        canonical_recipe = prepare_recipe(candidate_recipe,
                                                          brief=brief_data)
                    except PolicyError as exc:
                        return self._finish(attempt, canonical_run_id, "policy_error",
                                            record, _policy_error(exc), state,
                                            check_report)
                    except RecipeValidationError as exc:
                        if state.validation_repairs >= MAX_VALIDATION_REPAIRS:
                            last_status, last_error = "validation_failed", _validation_error(exc)
                            break
                        state.validation_repairs += 1
                        repair_errors = [_validation_error(exc)]
                        last_error = repair_errors[0]
                        record["errors"] = [last_error]
                        state.write("running", record)
                        state.emit("validation_repair",
                                   "Repairing a structured recipe validation error.",
                                   state.candidate_count)
                        continue
                    # Retain the bounded provider candidate separately from
                    # the host-normalized executable recipe. Only policy-safe,
                    # JSON-bounded candidates are kept in local history.
                    original_candidate = _bounded_candidate(candidate_recipe)
                    if original_candidate is not None:
                        record["candidate_recipe"] = original_candidate
                    state.write("running", record)
                except GenerationCancelledError:
                    return self._finish(attempt, canonical_run_id, "cancelled", record,
                                        _safe_error("cancelled", "provider"), state,
                                        check_report)
                except DeadlineExceededError:
                    return self._finish(attempt, canonical_run_id, "timed_out", record,
                                        _safe_error("deadline_exceeded", "provider"), state,
                                        check_report)
                except (ProviderProtocolError, ProviderResponseTooLargeError,
                        ProviderTruncatedResponseError) as exc:
                    if state.validation_repairs >= MAX_VALIDATION_REPAIRS:
                        last_status, last_error = "provider_protocol_error", _safe_error("provider_protocol", "candidate")
                        break
                    state.validation_repairs += 1
                    repair_errors = [_safe_error("provider_protocol", "candidate")]
                    last_error = repair_errors[0]
                    record["errors"] = [last_error]
                    state.write("running", record)
                    state.emit("validation_repair",
                               "Repairing a malformed structured candidate response.",
                               state.candidate_count)
                    continue
                except Exception as exc:
                    if isinstance(exc, BriefRequiresUserChoiceError):
                        error = _brief_choice_error(exc, raw_request)
                        return self._finish(attempt, canonical_run_id,
                                            "user_choice_required", record,
                                            error, state, check_report)
                    last_status, last_error = _classify_exception(exc, stage="candidate")
                    return self._finish(attempt, canonical_run_id, last_status,
                                        record, last_error, state, check_report)

                if token.cancelled:
                    return self._finish(attempt, canonical_run_id, "cancelled", record,
                                        _safe_error("cancelled", "orchestrator"), state,
                                        check_report)
                worker_deadline = min(deadline, self.clock() + self.worker_seconds)
                check_options = {
                    "brief": brief_data,
                    "generation": {
                        "run_id": canonical_run_id,
                        "parent_generation_id": parent_id,
                        "application": {key: application[key]
                                        for key in ("version", "build_id",
                                                    "capability_version")},
                    },
                    "requirements": requirements or {},
                }
                state.emit("checking", "Building and independently checking the recipe in a private worker.",
                           state.candidate_count)
                if token.cancelled:
                    return self._finish(attempt, canonical_run_id, "cancelled",
                                        record, _safe_error("cancelled", "orchestrator"),
                                        state, check_report)
                state.write("checking", record)
                try:
                    result = self.worker_runner(canonical_recipe, candidate_dir,
                                                worker_deadline, token,
                                                check_options=check_options)
                except Exception:
                    result = {"status": "worker_error", "error_records": [
                        _safe_error("worker_error", "worker")],
                        "manifest": [], "check_report": None}
                if token.cancelled:
                    return self._finish(attempt, canonical_run_id, "cancelled",
                                        record, _safe_error("cancelled", "orchestrator"),
                                        state, result.get("check_report")
                                        if isinstance(result, dict) else None)
                status = result.get("status") if isinstance(result, dict) else None
                check_report = result.get("check_report") if isinstance(result, dict) else None
                record["check_report"] = _bounded_check_report(check_report)
                record["worker"] = _safe_worker_summary(result)
                if (isinstance(check_report, dict)
                        and check_report.get("resource_limit") is True):
                    return self._finish(
                        attempt, canonical_run_id, "resource_limit", record,
                        _safe_error("resource_limit", "check"), state,
                        check_report)
                if status == "checked_ok" and _checks_passed(result):
                    record["accepted_recipe"] = canonical_recipe
                    record["check_report"] = _bounded_check_report(check_report)
                    record["manifest"] = _safe_manifest(
                        check_report.get("artifacts") if isinstance(check_report, dict) else None)
                    state.write("checking", record)
                    if token.cancelled:
                        return self._finish(attempt, canonical_run_id, "cancelled",
                                            record, _safe_error("cancelled", "orchestrator"),
                                            state, check_report)
                    state.emit("publishing", "Publishing the checked candidate atomically.",
                               state.candidate_count)
                    if token.cancelled:
                        return self._finish(attempt, canonical_run_id, "cancelled",
                                            record, _safe_error("cancelled", "orchestrator"),
                                            state, check_report)
                    inner_root = candidate_dir / f"attempt-{result.get('attempt_id')}"
                    if not _candidate_inner_root(candidate_dir, inner_root):
                        return self._finish(attempt, canonical_run_id, "publication_failed",
                                            record, _safe_error("worker_output_missing", "publication"),
                                            state, check_report)
                    try:
                        published = attempt.publish(inner_root, record, check_report,
                                                    cancellation=token,
                                                    deadline=deadline)
                    except GenerationCancelledError:
                        return self._finish(attempt, canonical_run_id, "cancelled",
                                            record, _safe_error("cancelled", "publication"),
                                            state, check_report)
                    except DeadlineExceededError:
                        return self._finish(attempt, canonical_run_id, "timed_out",
                                            record, _safe_error("deadline_exceeded", "publication"),
                                            state, check_report)
                    except Exception:
                        return self._finish(attempt, canonical_run_id, "publication_failed",
                                            record, _safe_error("publication_failed", "publication"),
                                            state, check_report)
                    record["status"] = "completed"
                    record["published_path"] = str(published)
                    state.emit("completed", "The checked project is published and recoverable.",
                               state.candidate_count)
                    # cancel() returns false once commit() completed the atomic
                    # promotion, so late UI requests cannot relabel this run.
                    final_dir = Path(getattr(attempt, "final_dir", published))
                    return GenerationOutcome(canonical_run_id, "completed", record,
                                             str(final_dir / "record.json"),
                                             check_report, None, str(published))
                if status in {"cancelled", "timed_out", "policy_error", "validation_error",
                              "worker_error", "resource_limit"}:
                    terminal, err = _worker_terminal(status, result)
                    return self._finish(attempt, canonical_run_id, terminal, record,
                                        err, state, check_report)
                if status not in {"execution_failed", "check_failed"}:
                    return self._finish(attempt, canonical_run_id, "worker_error", record,
                                        _safe_error("worker_protocol", "worker"),
                                        state, check_report)
                if state.runtime_check_repairs >= MAX_RUNTIME_CHECK_REPAIRS:
                    last_status = "check_failed" if status == "check_failed" else "execution_failed"
                    last_error = _result_error(result, status)
                    break
                state.runtime_check_repairs += 1
                runtime_repair_pending = True
                repair_errors = _result_repair_errors(result, status)
                last_error = repair_errors[0] if repair_errors else _safe_error("execution_error", "runtime")
                previous_recipe = canonical_recipe
                record["errors"] = repair_errors
                state.write("running", record)
                state.emit("runtime_repair" if status == "execution_failed" else "check_repair",
                           "Repairing the bounded worker or deterministic check report.",
                           state.candidate_count)

            if token.cancelled:
                return self._finish(attempt, canonical_run_id, "cancelled", record,
                                    _safe_error("cancelled", "orchestrator"), state,
                                    check_report)
            if self.clock() >= deadline:
                return self._finish(attempt, canonical_run_id, "timed_out", record,
                                    _safe_error("deadline_exceeded", "orchestrator"),
                                    state, check_report)
            record["errors"] = [last_error]
            return self._finish(attempt, canonical_run_id, last_status, record,
                                last_error, state, check_report)
        except GenerationCancelledError:
            return self._finish(attempt, canonical_run_id, "cancelled", record,
                                _safe_error("cancelled", "orchestrator"), state)
        except DeadlineExceededError:
            return self._finish(attempt, canonical_run_id, "timed_out", record,
                                _safe_error("deadline_exceeded", "orchestrator"), state)
        except Exception:
            # All unexpected host/store failures are represented with fixed
            # text; exception strings can contain paths or provider data.
            return self._finish(attempt, canonical_run_id, "failed", record,
                                _safe_error("orchestrator_error", "orchestrator"), state)

    def _load_parent(self, run_id: str) -> dict | None:
        try:
            value = self.store.get_record(run_id)
        except Exception:
            return None
        return value if isinstance(value, dict) else None

    def _finish(self, attempt: Any, run_id: str, status: str, record: dict,
                error: dict | None, state: "_RunState | None",
                check_report: dict | None = None) -> GenerationOutcome:
        if state is not None:
            state.snapshot(record)
        record["status"] = status
        record["error"] = error
        if error:
            record["errors"] = record.get("errors", [])[-(MAX_ERROR_RECORDS - 1):] + [error]
        bounded_report = _bounded_check_report(check_report)
        if bounded_report is not None:
            record["check_report"] = bounded_report
        if state is not None:
            record["event_sequence"] = state.sequence
            try:
                state.write("cancelled" if status == "cancelled" else "failed", record)
                state.emit(status, _status_message(status), state.attempt)
            except Exception:
                # Keep the caller's outcome useful even if the record store
                # cannot persist a terminal state.
                pass
        attempt_dir = getattr(attempt, "attempt_dir", None)
        state_path = Path(attempt_dir) / "state.json" if attempt_dir is not None else None
        record_path = str(state_path) if state_path is not None and state_path.is_file() else None
        return GenerationOutcome(run_id, status, record, record_path,
                                 bounded_report, error, None)

    def _unrecorded(self, run_id: str, status: str, code: str) -> GenerationOutcome:
        error = _safe_error(code, "record")
        record = _base_record(run_id, None)
        record.update(status=status, error=error, errors=[error])
        return GenerationOutcome(run_id, status, record, None, None, error, None)


class _RunState:
    def __init__(self, run_id: str, attempt: Any,
                 callback: Callable[[GenerationEvent], Any] | None,
                 cancellation: CancellationToken, clock: Callable[[], float],
                 deadline: float, parent_id: str | None,
                 requirements: dict | None, metered: _MeteredProvider,
                 usage: _Usage) -> None:
        self.run_id = run_id
        self.attempt_obj = attempt
        self.callback = callback
        self.cancellation = cancellation
        self.clock = clock
        self.deadline = deadline
        self.parent_id = parent_id
        self.requirements = requirements
        self.metered = metered
        self.usage = usage
        self.sequence = 0
        self.attempt = 0
        self.candidate_count = 0
        self.validation_repairs = 0
        self.runtime_check_repairs = 0
        self.active_candidate_dir: Path | None = None

    def emit(self, stage: str, message: str, attempt: int) -> None:
        event = GenerationEvent(self.run_id, self.sequence, stage, attempt,
                                message[:256], None)
        self.sequence += 1
        if self.callback is None:
            return
        try:
            self.callback(event)
        except Exception:
            # UI observers are never allowed to break the headless run.
            pass

    def write(self, status: str, record: dict) -> None:
        self.snapshot(record)
        record["event_sequence"] = self.sequence
        self.attempt_obj.write_state(status, record)

    def snapshot(self, record: dict) -> None:
        """Refresh all auditable counters from their single live sources."""
        record["usage"] = self.usage.as_record(self.metered.semantic_calls)
        record["provider"] = _provider_metadata(self.usage)
        record["candidate_count"] = self.candidate_count
        record["validation_repairs"] = self.validation_repairs
        record["runtime_check_repairs"] = self.runtime_check_repairs


def _canonical_uuid(value: str) -> str:
    parsed = uuid.UUID(value)
    canonical = str(parsed)
    if value != canonical:
        raise ValueError("generation identifiers must be canonical UUIDs")
    return canonical


def _bounded_seconds(value: Any, maximum: float, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive finite number")
    try:
        seconds = float(value)
    except (OverflowError, ValueError):
        raise ValueError(f"{name} must be a positive finite number") from None
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError(f"{name} must be a positive finite number")
    return min(seconds, maximum)


def _base_record(run_id: str, parent_id: str | None) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "parent_generation_id": parent_id,
        "status": "running",
        "accepted_brief": None,
        "candidate_recipe": None,
        "accepted_recipe": None,
        "check_report": None,
        "provider": {"provider": None, "model": None, "request_id": None},
        "application": {"version": None, "build_id": None,
                        "source_sha256": None},
        "errors": [],
        "candidate_count": 0,
        "validation_repairs": 0,
        "runtime_check_repairs": 0,
        "usage": {"semantic_calls": 0, "http_attempts": None,
                  "prompt_tokens": None, "completion_tokens": None,
                  "total_tokens": None, "cost_usd": None,
                  "provider_responses": 0},
    }


def _short_optional(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    safe = "".join(c for c in value if c.isalnum() or c in "_-.")[:limit]
    return safe or None


def _provider_metadata(usage: _Usage) -> dict[str, str | None]:
    if not usage.provider_metadata:
        return {"provider": None, "model": None, "request_id": None}
    return dict(usage.provider_metadata[-1])


def _application_identity() -> dict[str, str | None]:
    try:
        from .records import application_identity
        value = application_identity()
    except Exception:
        value = {}
    version = _identity_text(value.get("version")) if isinstance(value, dict) else None
    build_id = _identity_text(value.get("build_id")) if isinstance(value, dict) else None
    capability = (_identity_text(value.get("capability_version"))
                  if isinstance(value, dict) else None)
    source_sha256 = None
    if isinstance(build_id, str) and build_id.startswith("source-code-sha256:"):
        candidate = build_id.removeprefix("source-code-sha256:")
        if re.fullmatch(r"[0-9a-f]{64}", candidate):
            source_sha256 = candidate
    return {"version": version, "build_id": build_id,
            "capability_version": capability, "source_sha256": source_sha256}


def _identity_text(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", value):
        return value
    return None


def _prompt_metadata() -> dict[str, Any]:
    try:
        value = prompt_context_metadata()
        return {key: str(item)[:128] for key, item in value.items()
                if isinstance(item, str)}
    except Exception:
        return {}


def _safe_error(code: str, stage: str, path: str = "recipe",
                hint: str | None = None) -> dict[str, str]:
    match = _SAFE_CODE.fullmatch(str(code))
    safe_code = match.group(0) if match else "generation_error"
    allowed_stages = {"record", "brief", "candidate", "policy", "worker",
                      "runtime", "check", "publication", "provider",
                      "orchestrator", "refinement", "resource", "schema",
                      "write", "policy-preflight"}
    safe_stage = stage if stage in allowed_stages else "orchestrator"
    safe_path = path if isinstance(path, str) and _SAFE_FIELD.fullmatch(path) else "recipe"
    result = {"code": safe_code, "stage": safe_stage, "path": safe_path,
              "message": _message(safe_code, safe_stage)}
    if isinstance(hint, str):
        clean_hint = "".join(c for c in hint if c.isprintable() and c not in "\\/")[:MAX_ERROR_TEXT]
        if clean_hint:
            result["hint"] = clean_hint
    return result


def _brief_choice_error(exc: BriefRequiresUserChoiceError,
                        raw_request: str) -> dict[str, str]:
    """Map only host-recognized limitations to fixed, actionable UI copy.

    Model-authored limitation strings are deliberately never copied into the
    error record. Known categories are accepted only when the prompt layer's
    deterministic scanner independently found the same marker in the caller's
    original text. Everything else receives a fixed generic edit-or-cancel
    instruction.
    """
    known = set(_known_user_choice_limitations(raw_request))
    matched = [item for item in getattr(exc, "limitations", ())
               if isinstance(item, str) and item in known]
    mappings = (
        ("Would a native editable project and animation sheet meet your need, or do you need an animated interchange file?",
         "animated_glb_unsupported",
         "V1 GLB exports are static pose snapshots and cannot carry animation.",
         "Choose a native AM3D project plus animation sheet, revise the request for a static GLB, or cancel."),
        ("Are opaque tinted panels acceptable, or do you require physically transparent glass?",
         "physical_glass_unsupported",
         "V1 supports stylized opaque or tinted glass-like panels, not physically accurate transparent glass.",
         "Choose stylized opaque or tinted panels, revise the brief for another supported material, or cancel."),
        ("Would you like a new asset built from supported recipe geometry, or do you need an import workflow?",
         "external_import_unsupported",
         "The V1 recipe workflow creates assets from supported geometry and does not import external models.",
         "Choose a new asset built from supported geometry, revise the brief, or cancel."),
        ("Would a composition made from supported primitives and profiles work, or do you need another modeling workflow?",
         "advanced_topology_unsupported",
         "V1 recipe generation does not provide arbitrary sculpting, topology, or Boolean/CSG operations.",
         "Choose a composition from supported primitives and profiles, revise the brief, or cancel."),
        ("Would a simplified head with a basic supported body action work, or do you need facial animation?",
         "facial_animation_unsupported",
         "V1 does not provide expressive facial topology or lip-sync workflows.",
         "Choose a simplified head with a supported body action, revise the brief, or cancel."),
        ("Would explicit positive-scale mirrored parts be acceptable, or should this wait for a verified negative-scale workflow?",
         "negative_scale_unqualified",
         "Negative-scale mirrored texture and export behavior is not qualified for V1.",
         "Choose explicit positive-scale mirrored parts, revise the brief, or cancel."),
        ("Would placing the geometry in the shared rig frame be acceptable, or do you need independent object transforms?",
         "rig_frame_required",
         "V1 requires skinned geometry to share the rig coordinate frame with identity object transforms.",
         "Choose geometry in the shared rig frame, revise the brief, or cancel."),
        ("What smaller maximum count or supported grouped approximation would you accept?",
         "part_count_limit",
         "The requested count of separate parts may exceed configured V1 recipe or execution limits.",
         "Choose a smaller maximum count or a supported grouped approximation, revise the brief, or cancel."),
    )
    for signature, code, _message_text, hint in mappings:
        if any(signature in item for item in matched):
            return _safe_error(code, "brief", hint=hint)

    if _has_unsupported_export_request(raw_request):
        return _safe_error(
            "unsupported_export_format", "brief",
            hint="Supported choices are OBJ, static GLB, native AM3D, spritesheet, toon sheet, and animation sheet; revise the brief or cancel.")
    return _safe_error(
        "unsupported_requirement", "brief",
        hint="Review or revise the brief to choose a supported alternative, or cancel. Unsupported requirements are never silently dropped.")


def _has_unsupported_export_request(text: str) -> bool:
    """Recognize an unsupported export category without retaining its name."""
    matches = re.finditer(
        r"\bexport(?:\s+[A-Za-z][A-Za-z0-9_-]*){0,4}\s+(?:as|to|in)\s+([A-Za-z0-9_.+-]{1,32})\b",
        text, flags=re.IGNORECASE)
    supported = {"obj", "glb", "gltf", "spritesheet", "toon_sheet",
                 "am3d", "animation_sheet"}
    return any(match.group(1).casefold() not in supported for match in matches)


def _message(code: str, stage: str) -> str:
    messages = {
        "cancelled": "Generation was cancelled.",
        "deadline_exceeded": "The shared generation time limit expired.",
        "provider_authentication": "The provider rejected the configured credential.",
        "provider_credential": "The provider credential is unavailable or invalid.",
        "provider_configuration": "The provider configuration is invalid.",
        "provider_model": "The explicitly configured model is unavailable.",
        "provider_refusal": "The provider refused the generation request.",
        "provider_protocol": "The provider response did not match the structured response contract.",
        "provider_transient": "The bounded provider request failed after its retry.",
        "provider_request": "The provider request could not be completed.",
        "unsupported_choice": "The request needs a user choice before generation can continue.",
        "animated_glb_unsupported": "Animated GLB is unsupported; choose a native project and animation sheet or revise the request.",
        "physical_glass_unsupported": "Physical transparent glass is unsupported; choose a stylized material or revise the request.",
        "external_import_unsupported": "External model import is outside the V1 recipe workflow.",
        "advanced_topology_unsupported": "Arbitrary topology and Boolean/CSG operations are outside the V1 recipe workflow.",
        "facial_animation_unsupported": "Expressive facial animation is outside the V1 recipe workflow.",
        "negative_scale_unqualified": "Negative-scale mirrored export behavior is not qualified for V1.",
        "rig_frame_required": "Skinned geometry must use the shared rig coordinate frame in V1.",
        "part_count_limit": "The requested separate-part count may exceed configured V1 limits.",
        "unsupported_export_format": "The requested export format is outside the supported V1 choices.",
        "unsupported_requirement": "The request includes an unsupported capability that needs a user decision.",
        "policy_denied": "The candidate violates the host recipe policy.",
        "validation_failed": "The recipe remained invalid after bounded repair.",
        "check_failed": "The deterministic checks did not pass after bounded repair.",
        "execution_failed": "The recipe could not be executed after bounded repair.",
        "resource_limit": "The host checker stopped the candidate at a configured resource limit.",
        "publication_failed": "The checked output could not be published atomically.",
        "parent_not_successful": "The selected parent run has no checked successful recipe.",
        "parent_record_unavailable": "The selected parent run record is unavailable.",
        "parent_record_invalid": "The selected parent run record is incomplete.",
    }
    return messages.get(code, "The generation run failed at the " + stage + " stage.")


def _classify_exception(exc: BaseException, *, stage: str) -> tuple[str, dict]:
    if isinstance(exc, GenerationCancelledError):
        return "cancelled", _safe_error("cancelled", "provider")
    if isinstance(exc, DeadlineExceededError):
        return "timed_out", _safe_error("deadline_exceeded", "provider")
    if isinstance(exc, ProviderAuthenticationError):
        return "provider_error", _safe_error("provider_authentication", "provider")
    if isinstance(exc, ProviderCredentialError):
        return "provider_error", _safe_error("provider_credential", "provider")
    if isinstance(exc, ProviderConfigurationError):
        return "provider_error", _safe_error("provider_configuration", "provider")
    if isinstance(exc, ProviderModelError):
        return "provider_error", _safe_error("provider_model", "provider")
    if isinstance(exc, ProviderRefusalError):
        return "provider_refused", _safe_error("provider_refusal", "provider")
    if isinstance(exc, (ProviderRateLimitError, ProviderTransientError)):
        return "provider_error", _safe_error("provider_transient", "provider")
    if isinstance(exc, ProviderRequestError):
        return "provider_error", _safe_error("provider_request", "provider")
    if isinstance(exc, BriefRequiresUserChoiceError):
        return "user_choice_required", _safe_error("unsupported_requirement", "brief")
    if isinstance(exc, PolicyError):
        return "policy_error", _policy_error(exc)
    if isinstance(exc, RecipeValidationError):
        return "validation_failed", _validation_error(exc)
    if isinstance(exc, _BudgetExceeded):
        return "budget_exhausted", _safe_error(exc.code, "orchestrator")
    if isinstance(exc, ProviderError):
        return "provider_error", _safe_error("provider_request", "provider")
    return "failed", _safe_error("generation_error", stage)


def _policy_error(exc: PolicyError) -> dict[str, str]:
    return _safe_error(getattr(exc, "code", "policy_denied"), "policy",
                        getattr(exc, "path", "recipe"))


def _validation_error(exc: RecipeValidationError) -> dict[str, str]:
    return _safe_error(getattr(exc, "code", "validation_error"), "candidate",
                        getattr(exc, "path", "recipe"),
                        getattr(exc, "hint", None))


def _checks_passed(result: Any) -> bool:
    return (isinstance(result, dict)
            and result.get("checks_status") == "passed"
            and isinstance(result.get("check_report"), dict)
            and result["check_report"].get("ok") is True
            and result["check_report"].get("status") == "passed")


def _worker_terminal(status: str, result: dict) -> tuple[str, dict]:
    if status == "cancelled":
        return "cancelled", _safe_error("cancelled", "worker")
    if status == "timed_out":
        return "timed_out", _safe_error("deadline_exceeded", "worker")
    if status == "policy_error":
        return "policy_error", _result_error(result, status)
    if status == "validation_error":
        return "validation_failed", _result_error(result, status)
    if status == "resource_limit":
        return "resource_limit", _result_error(result, status)
    return "worker_error", _result_error(result, status)


def _result_error(result: dict, status: str) -> dict[str, str]:
    errors = result.get("error_records") if isinstance(result, dict) else None
    first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    code = first.get("code", {
        "check_failed": "check_failed", "execution_failed": "execution_failed",
        "policy_error": "policy_denied", "validation_error": "validation_failed",
    }.get(status, "worker_error"))
    stage = first.get("stage", "check" if status == "check_failed" else
                      "runtime" if status == "execution_failed" else "worker")
    path = first.get("path", "recipe")
    return _safe_error(code, stage, path, first.get("hint"))


def _result_repair_errors(result: dict, status: str) -> list[dict[str, str]]:
    errors = result.get("error_records") if isinstance(result, dict) else None
    safe = []
    for item in errors[:MAX_ERROR_RECORDS] if isinstance(errors, list) else []:
        if isinstance(item, dict):
            safe.append(_safe_error(item.get("code", "execution_error"),
                                    item.get("stage", "check" if status == "check_failed" else "runtime"),
                                    item.get("path", "recipe"), item.get("hint")))
    if status == "check_failed" and isinstance(result.get("check_report"), dict):
        report = result["check_report"]
        for check in report.get("checks", [])[:MAX_ERROR_RECORDS]:
            if isinstance(check, dict) and check.get("status") == "failed":
                check_id = _short_optional(check.get("id"), 64) or "check_failed"
                safe.append(_safe_error(check_id, "check"))
    return safe[:MAX_ERROR_RECORDS] or [_safe_error("execution_error", "runtime")]


def _safe_worker_summary(result: Any) -> dict:
    if not isinstance(result, dict):
        return {"status": "worker_error", "attempt_id": None,
                "checks_status": "not_run", "manifest": []}
    status = result.get("status")
    statuses = {"checked_ok", "check_failed", "execution_failed", "execution_ok",
                "policy_error", "validation_error", "worker_error", "cancelled",
                "timed_out", "resource_limit"}
    return {"status": status if status in statuses else "worker_error",
            "attempt_id": _short_optional(result.get("attempt_id"), 64),
            "checks_status": result.get("checks_status") if result.get("checks_status") in
            {"not_run", "not_requested", "unavailable", "passed", "failed"} else "not_run",
            "artifact_count": len(result.get("manifest", []))
            if isinstance(result.get("manifest"), list) else 0}


def _safe_manifest(value: Any) -> list[dict[str, Any]]:
    result = []
    for item in value[:256] if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        digest = item.get("sha256")
        size = item.get("bytes")
        if (isinstance(path, str) and len(path) <= 512 and not Path(path).is_absolute()
                and ".." not in Path(path).parts and isinstance(digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", digest)
                and type(size) is int and size >= 0):
            result.append({"path": path.replace("\\", "/"),
                           "sha256": digest, "bytes": size})
    return result


def _bounded_check_report(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) <= 256 * 1024:
            return value
    except (TypeError, ValueError, UnicodeEncodeError):
        pass
    return {"ok": False, "status": "failed", "checks": [],
            "artifacts": [], "measurements": {},
            "limitations": ["check report exceeded its record size limit"]}


def _bounded_candidate(value: Any) -> dict | None:
    """Copy a policy-approved candidate without retaining arbitrary objects."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
        if len(encoded) > 512 * 1024:
            return None
        copied = json.loads(encoded.decode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        return None
    return copied if isinstance(copied, dict) else None


def _candidate_inner_root(candidate_dir: Path, inner_root: Path) -> bool:
    try:
        candidate = candidate_dir.resolve(strict=True)
        inner = inner_root.resolve(strict=True)
        return inner.parent == candidate and inner.is_dir()
    except (OSError, RuntimeError):
        return False


def _parent_brief_text(record: dict) -> str | None:
    value = record.get("accepted_brief")
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and isinstance(value.get("brief"), str):
        return value["brief"]
    return None


def _parent_recipe(record: dict) -> dict | None:
    for key in ("accepted_recipe", "recipe"):
        value = record.get(key)
        if isinstance(value, dict):
            return value
    return None


def _parent_is_checked(record: dict) -> bool:
    if record.get("status") != "complete":
        return False
    report = record.get("check_report")
    if not isinstance(report, dict) or report.get("ok") is not True or report.get("status") != "passed":
        return False
    return bool(_parent_recipe(record))


def _status_message(status: str) -> str:
    return {
        "completed": "The checked project is published.",
        "cancelled": "Generation was cancelled.",
        "timed_out": "The generation time limit expired.",
        "policy_error": "The candidate was blocked by recipe policy.",
        "check_failed": "The candidate did not pass deterministic checks.",
        "execution_failed": "The candidate could not be executed.",
        "publication_failed": "The checked candidate could not be published.",
    }.get(status, "Generation finished with a recorded failure.")


__all__ = ["GenerationOrchestrator", "GenerationOutcome", "MAX_CANDIDATES",
           "MAX_SEMANTIC_CALLS", "MAX_VALIDATION_REPAIRS",
           "MAX_RUNTIME_CHECK_REPAIRS"]
