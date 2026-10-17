"""One-call provider-to-recipe orchestration through the existing M2 boundary."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
import re
import time
import uuid

from am3d.recipes.schema import RecipeValidationError

from .policy import PolicyRejected, authorize_recipe
from .prompt import PromptBuildError, PromptCompiler
from .provider_contracts import (FailureCode, ProviderResponseError,
                                 StructuredProviderResponse,
                                 parse_provider_response)
from .providers import (AdapterKind, Provider, ProviderCallStatus,
                        ProviderRequest, ProviderResult, UsageMetadata)
from .runner import GenerationRunner
from .contracts import GenerationResult, GenerationStatus


class OrchestrationStatus(StrEnum):
    FAILED = "failed"
    RUNNING = "running"
    COMPLETE = "complete"


@dataclass(frozen=True)
class ProviderUsageRecord:
    """One host-attributed provider call; absent counters stay null."""

    attempt_id: str
    occurred_at: str
    provider_id: str
    model_id: str
    adapter_kind: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    latency_ms: float | None
    call_status: str
    failure_classification: str | None
    quota_or_rate_limited: bool | None

    def to_dict(self) -> dict:
        return {
            "attempt_id": self.attempt_id,
            "occurred_at": self.occurred_at,
            "provider_id": self.provider_id,
            "model_id": self.model_id,
            "adapter_kind": self.adapter_kind,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "latency_ms": self.latency_ms,
            "call_status": self.call_status,
            "failure_classification": self.failure_classification,
            "quota_or_rate_limited": self.quota_or_rate_limited,
        }


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    path: str
    stage: str
    message: str

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path,
                "stage": self.stage, "message": self.message}


@dataclass(frozen=True)
class OrchestrationOutcome:
    attempt_id: str
    status: OrchestrationStatus
    failure_code: FailureCode | None = None
    message: str = ""
    response: StructuredProviderResponse | None = None
    usage: ProviderUsageRecord | None = None
    generation_run_id: str | None = None
    generation_result: GenerationResult | None = None
    validation_issues: tuple[ValidationIssue, ...] = ()


_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_.])(?:[A-Za-z]:[\\/]|/)(?:[^\\/\s:'\"]+[\\/])*[^\\/\s:'\"]+")


def _safe_text(value, limit: int) -> str:
    return _ABSOLUTE_PATH.sub("<path>", str(value))[:limit]


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class GenerationOrchestrator:
    """Make one provider call, then use M1 policy and the existing M2 runner."""

    def __init__(self, provider: Provider, runner: GenerationRunner, *,
                 prompt_compiler: PromptCompiler | None = None):
        self.provider = provider
        self.runner = runner
        self.prompt_compiler = prompt_compiler or PromptCompiler()
        self._active_attempt_id: str | None = None
        self._active_run_id: str | None = None
        self._usage: ProviderUsageRecord | None = None
        self._response: StructuredProviderResponse | None = None
        self.last_outcome: OrchestrationOutcome | None = None

    def start(self, brief: str) -> OrchestrationOutcome:
        """Run the provider once and start M2 only after strict policy passes."""
        if self.runner.running:
            return OrchestrationOutcome(
                attempt_id=uuid.uuid4().hex,
                status=OrchestrationStatus.FAILED,
                failure_code=FailureCode.GENERATION_FAILURE,
                message="The local generation worker is busy.")

        self._active_attempt_id = uuid.uuid4().hex
        self._active_run_id = None
        self._response = None
        self._usage = None
        try:
            request = self.prompt_compiler.compile(brief)
        except PromptBuildError as exc:
            return self._finish_without_call(exc.code, str(exc))

        called_at = _iso_utc_now()
        started = time.monotonic()
        try:
            provider_result = self.provider.generate(request)
            if not isinstance(provider_result, ProviderResult):
                raise TypeError("provider returned an invalid result object")
        except TimeoutError:
            provider_result = self._synthetic_provider_failure(
                FailureCode.TIMEOUT, time.monotonic() - started)
        except Exception:
            # Do not echo exception text; subprocess and transport exceptions
            # often contain environment or filesystem paths.
            provider_result = self._synthetic_provider_failure(
                FailureCode.TRANSPORT_FAILURE, time.monotonic() - started)

        self._usage = self._usage_record(provider_result, called_at)
        if provider_result.status is ProviderCallStatus.FAILED:
            failure = provider_result.failure_code or FailureCode.TRANSPORT_FAILURE
            return self._finish(failure, self._message_for(failure))
        if provider_result.response_bytes is None:
            return self._finish(
                FailureCode.INVALID_STRUCTURED_RESPONSE,
                "Provider returned no structured response.")

        try:
            response = parse_provider_response(provider_result.response_bytes)
        except ProviderResponseError as exc:
            return self._finish(exc.code, str(exc))
        self._response = response

        # M1/M2 policy remains the only recipe policy. This host-selected
        # preflight root is never read from or supplied by the provider.
        preflight_root = self.runner.store.private / "provider-preflight" / "exports"
        try:
            authorize_recipe(response.recipe, preflight_root)
        except PolicyRejected as exc:
            issues = tuple(self._policy_issue(item) for item in exc.errors[:100])
            return self._finish(
                FailureCode.POLICY_REJECTION,
                "Recipe was rejected by the existing AI policy.",
                issues=issues)
        except (RecipeValidationError, TypeError, ValueError):
            return self._finish(
                FailureCode.POLICY_REJECTION,
                "Recipe was rejected by the existing AI policy.")

        # The M2 runner repeats policy validation with its actual private output
        # root, creates the run ID/root on the host, and owns worker/checks/
        # publication. No provider field can configure that call.
        try:
            run_id = self.runner.start(response.recipe)
        except Exception:
            return self._finish(
                FailureCode.GENERATION_FAILURE,
                "The validated recipe could not be started by the local worker.")
        self._active_run_id = run_id

        if not self.runner.running:
            result = self.runner.poll() or self.runner.last_result
            if result is not None and result.run_id == run_id:
                return self._finish_generation(result)
            return self._finish(
                FailureCode.GENERATION_FAILURE,
                "The local worker did not return a result for this run.")

        self.last_outcome = OrchestrationOutcome(
            attempt_id=self._active_attempt_id,
            status=OrchestrationStatus.RUNNING,
            response=response,
            usage=self._usage,
            generation_run_id=run_id)
        return self.last_outcome

    def poll(self) -> OrchestrationOutcome | None:
        """Advance M2's nonblocking worker and return its terminal outcome."""
        if self._active_run_id is None or self._active_attempt_id is None:
            return self.last_outcome
        result = self.runner.poll()
        if result is None:
            if (not self.runner.running and self.runner.last_result is not None and
                    self.runner.last_result.run_id == self._active_run_id):
                result = self.runner.last_result
            else:
                return self.last_outcome
        if result.run_id != self._active_run_id:
            return self._finish(
                FailureCode.GENERATION_FAILURE,
                "The local worker returned a result for a different run.")
        return self._finish_generation(result)

    def cancel(self) -> bool:
        """Delegate cancellation to M2; provider calls are not retried."""
        return self.runner.cancel()

    def _finish_generation(self, result: GenerationResult) -> OrchestrationOutcome:
        if result.status is GenerationStatus.COMPLETE:
            if self._usage is not None:
                self._usage = replace(self._usage, failure_classification=None)
            self.last_outcome = OrchestrationOutcome(
                attempt_id=self._active_attempt_id or "",
                status=OrchestrationStatus.COMPLETE,
                response=self._response,
                usage=self._usage,
                generation_run_id=result.run_id,
                generation_result=result)
            self._active_run_id = None
            return self.last_outcome

        failed_checks = [check for check in result.checks if not check.ok]
        code = (FailureCode.CHECK_FAILURE if failed_checks
                else FailureCode.GENERATION_FAILURE)
        return self._finish(code, self._message_for(code),
                            generation_result=result)

    def _finish(self, code: FailureCode, message: str, *,
                issues: tuple[ValidationIssue, ...] = (),
                generation_result: GenerationResult | None = None
                ) -> OrchestrationOutcome:
        if self._usage is not None:
            self._usage = replace(self._usage,
                                  failure_classification=code.value)
        self.last_outcome = OrchestrationOutcome(
            attempt_id=self._active_attempt_id or uuid.uuid4().hex,
            status=OrchestrationStatus.FAILED,
            failure_code=code,
            message=_safe_text(message, 600),
            response=self._response,
            usage=self._usage,
            generation_run_id=self._active_run_id,
            generation_result=generation_result,
            validation_issues=issues)
        self._active_run_id = None
        return self.last_outcome

    def _finish_without_call(self, code: FailureCode,
                             message: str) -> OrchestrationOutcome:
        self._active_attempt_id = uuid.uuid4().hex
        self._active_run_id = None
        self._response = None
        self._usage = None
        return self._finish(code, message)

    def _synthetic_provider_failure(self, code: FailureCode,
                                    latency_seconds: float) -> ProviderResult:
        provider_id = _safe_text(getattr(self.provider, "provider_id", "provider"), 80) or "provider"
        model_id = _safe_text(getattr(self.provider, "model_id", "unknown"), 120) or "unknown"
        kind = getattr(self.provider, "adapter_kind", None)
        if not isinstance(kind, AdapterKind):
            kind = AdapterKind.FAKE
        return ProviderResult(
            provider_id, model_id, kind, ProviderCallStatus.FAILED,
            latency_ms=max(0.0, latency_seconds * 1000),
            failure_code=code, usage=UsageMetadata(),
            transport_status=("deadline_expired" if code is FailureCode.TIMEOUT
                              else "transport_error"))

    def _usage_record(self, result: ProviderResult,
                      occurred_at: str) -> ProviderUsageRecord:
        quota = result.quota_or_rate_limited
        if quota is None and result.failure_code is FailureCode.QUOTA_RATE_LIMIT:
            quota = True
        return ProviderUsageRecord(
            attempt_id=self._active_attempt_id or "",
            occurred_at=occurred_at,
            provider_id=_safe_text(result.provider_id, 80),
            model_id=_safe_text(result.model_id, 120),
            adapter_kind=result.adapter_kind.value,
            input_tokens=result.usage.input_tokens,
            output_tokens=result.usage.output_tokens,
            total_tokens=result.usage.total_tokens,
            latency_ms=(float(result.latency_ms)
                        if result.latency_ms is not None else None),
            call_status=result.status.value,
            failure_classification=(result.failure_code.value
                                    if result.failure_code is not None else None),
            quota_or_rate_limited=quota)

    @staticmethod
    def _policy_issue(issue) -> ValidationIssue:
        return ValidationIssue(
            code=_safe_text(issue.code, 80),
            path=_safe_text(issue.path, 200),
            stage=_safe_text(issue.stage, 40),
            message=_safe_text(issue.message, 500))

    @staticmethod
    def _message_for(code: FailureCode) -> str:
        messages = {
            FailureCode.UNAVAILABLE_PROVIDER: "Selected provider is unavailable.",
            FailureCode.UNSUPPORTED_ADAPTER: "Selected provider adapter is unsupported.",
            FailureCode.TIMEOUT: "Provider request exceeded its deadline.",
            FailureCode.TRANSPORT_FAILURE: "Provider request failed in transport.",
            FailureCode.NONZERO_EXIT: "Provider CLI exited unsuccessfully.",
            FailureCode.RESPONSE_TOO_LARGE: "Provider response exceeded its size limit.",
            FailureCode.INVALID_UTF8: "Provider response was not valid UTF-8.",
            FailureCode.MALFORMED_JSON: "Provider response was not strict JSON.",
            FailureCode.DUPLICATE_JSON_KEYS: "Provider response contained duplicate JSON keys.",
            FailureCode.UNKNOWN_FIELDS: "Provider response contained unsupported fields.",
            FailureCode.MISSING_FIELDS: "Provider response omitted required fields.",
            FailureCode.MISSING_RECIPE: "Provider response omitted its recipe.",
            FailureCode.INVALID_STRUCTURED_RESPONSE: "Provider response did not match its contract.",
            FailureCode.POLICY_REJECTION: "Recipe was rejected by the existing AI policy.",
            FailureCode.GENERATION_FAILURE: "The local generation worker failed.",
            FailureCode.CHECK_FAILURE: "A deterministic generation check failed.",
            FailureCode.QUOTA_RATE_LIMIT: "Provider quota or rate limit was reached.",
            FailureCode.AUTHENTICATION_FAILURE: "Provider authentication failed.",
            FailureCode.REFUSAL: "Provider declined the request.",
            FailureCode.INVALID_BRIEF: "Brief must be non-empty valid text.",
            FailureCode.PROMPT_TOO_LARGE: "Brief or compiled prompt exceeded its size limit.",
        }
        return messages.get(code, "Provider generation failed.")
