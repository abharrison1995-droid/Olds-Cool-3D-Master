"""Small provider boundary and deterministic offline fake implementation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import math
import time
from typing import Any, Protocol

from .provider_contracts import (FailureCode, MAX_PROVIDER_RESPONSE_BYTES,
                                 provider_response_schema)


class AdapterKind(StrEnum):
    FAKE = "fake"
    AGENT_CLI = "agent_cli"
    LOCAL_OPENAI_COMPATIBLE = "local_openai_compatible"
    REMOTE_API = "remote_api"


class ProviderCallStatus(StrEnum):
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True)
class UsageMetadata:
    """Provider-reported usage. Unknown counters remain ``None``."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None

    def __post_init__(self):
        for name in ("input_tokens", "output_tokens", "total_tokens"):
            value = getattr(self, name)
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError(f"{name} must be a non-negative integer or None")


@dataclass(frozen=True)
class ProviderRequest:
    """Only prompt data, output contract and call bounds cross the provider API."""

    system_prompt: str
    user_prompt: str
    response_schema: dict[str, Any]
    deadline_seconds: float = 600.0
    max_response_bytes: int = MAX_PROVIDER_RESPONSE_BYTES

    def __post_init__(self):
        if not isinstance(self.system_prompt, str) or not isinstance(self.user_prompt, str):
            raise TypeError("provider prompts must be strings")
        if not isinstance(self.response_schema, dict):
            raise TypeError("provider response schema must be an object")
        if (isinstance(self.deadline_seconds, bool) or
                not isinstance(self.deadline_seconds, (int, float)) or
                not math.isfinite(self.deadline_seconds) or
                not 0.1 <= self.deadline_seconds <= 1200):
            raise ValueError("provider deadline must be between 0.1 and 1200 seconds")
        if type(self.max_response_bytes) is not int or self.max_response_bytes != MAX_PROVIDER_RESPONSE_BYTES:
            raise ValueError("provider response limit must use the canonical 1 MiB bound")


@dataclass(frozen=True)
class ProviderResult:
    provider_id: str
    model_id: str
    adapter_kind: AdapterKind
    status: ProviderCallStatus
    response_bytes: bytes | None = None
    latency_ms: float | None = None
    usage: UsageMetadata = field(default_factory=UsageMetadata)
    failure_code: FailureCode | None = None
    quota_or_rate_limited: bool | None = None
    transport_status: str | None = None
    transport_code: int | None = None

    def __post_init__(self):
        if not isinstance(self.provider_id, str) or not self.provider_id or len(self.provider_id) > 80:
            raise ValueError("provider identity is invalid")
        if not isinstance(self.model_id, str) or not self.model_id or len(self.model_id) > 120:
            raise ValueError("model identity is invalid")
        if not isinstance(self.adapter_kind, AdapterKind):
            raise TypeError("adapter kind must be host-selected")
        if not isinstance(self.status, ProviderCallStatus):
            raise TypeError("provider status is invalid")
        if self.latency_ms is not None and (
                isinstance(self.latency_ms, bool) or
                not isinstance(self.latency_ms, (int, float)) or
                not math.isfinite(self.latency_ms) or self.latency_ms < 0):
            raise ValueError("provider latency must be finite and non-negative or None")
        if self.response_bytes is not None and not isinstance(self.response_bytes, bytes):
            raise TypeError("provider response must be raw bytes")
        if (self.response_bytes is not None and
                len(self.response_bytes) > MAX_PROVIDER_RESPONSE_BYTES + 1):
            raise ValueError("provider adapter exceeded the bounded response read")
        if not isinstance(self.usage, UsageMetadata):
            raise TypeError("provider usage must use UsageMetadata")
        if self.quota_or_rate_limited is not None and not isinstance(
                self.quota_or_rate_limited, bool):
            raise TypeError("quota/rate-limit metadata must be bool or None")
        if (self.transport_status is not None and
                (not isinstance(self.transport_status, str) or
                 not self.transport_status or len(self.transport_status) > 80 or
                 "\n" in self.transport_status or "\r" in self.transport_status)):
            raise ValueError("provider transport status is invalid")
        if self.transport_code is not None and (
                type(self.transport_code) is not int or
                not -(2**31) <= self.transport_code < 2**31):
            raise ValueError("provider transport code is invalid")
        if self.status is ProviderCallStatus.FAILED and not isinstance(
                self.failure_code, FailureCode):
            raise ValueError("failed provider call requires a typed failure code")
        if self.status is ProviderCallStatus.SUCCEEDED and self.failure_code is not None:
            raise ValueError("successful provider call cannot carry a failure code")


class Provider(Protocol):
    """Host-selected provider. No method accepts a command or output path."""

    provider_id: str
    model_id: str
    adapter_kind: AdapterKind

    def generate(self, request: ProviderRequest) -> ProviderResult:
        """Return provider output as data, never execute it.

        Implementations must enforce ``request.deadline_seconds`` and, when
        reading streams, stop after ``request.max_response_bytes + 1`` bytes so
        the orchestrator can classify an over-limit response without buffering
        an unbounded body.
        """


class FakeBehavior(StrEnum):
    VALID = "valid"
    MALFORMED_JSON = "malformed_json"
    DUPLICATE_KEYS = "duplicate_keys"
    INVALID_UTF8 = "invalid_utf8"
    OVERSIZED = "oversized"
    TRANSPORT_FAILURE = "transport_failure"
    NONZERO_EXIT = "nonzero_exit"
    TIMEOUT = "timeout"
    HANG = "hang"
    INVALID_RECIPE = "invalid_recipe"
    POLICY_DENIED = "policy_denied"
    RESOURCE_LIMIT = "resource_limit"
    TEXTURE_PATH = "texture_path"
    COMMAND_FIELD = "command_field"
    OUTPUT_ROOT_FIELD = "output_root_field"
    QUOTA_LIMIT = "quota_limit"
    AUTHENTICATION_FAILURE = "authentication_failure"
    REFUSAL = "refusal"
    UNAVAILABLE_PROVIDER = "unavailable_provider"
    UNSUPPORTED_ADAPTER = "unsupported_adapter"


def _valid_response(recipe: dict[str, Any] | None = None) -> bytes:
    import json

    payload = {
        "schema_version": 1,
        "intent": "A simple block model.",
        "assumptions": [],
        "approximations": [],
        "required_components": ["body"],
        "recipe": recipe or {
            "version": 1,
            "name": "fake_box",
            "objects": [{"name": "body", "primitive": "box"}],
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


class FakeProvider:
    """Canned offline provider for provider/orchestrator contract tests."""

    provider_id = "fake"
    model_id = "canned-v1"
    adapter_kind = AdapterKind.FAKE

    def __init__(self, behavior: FakeBehavior = FakeBehavior.VALID, *,
                 known_usage: bool = False, hang_seconds: float = 0.11):
        if not isinstance(behavior, FakeBehavior):
            raise TypeError("fake provider behavior must be selected by the test host")
        if (isinstance(hang_seconds, bool) or
                not isinstance(hang_seconds, (int, float)) or
                not math.isfinite(hang_seconds) or not 0 < hang_seconds <= 5):
            raise ValueError("fake hang duration must be between zero and five seconds")
        self.behavior = behavior
        self.known_usage = known_usage
        self.hang_seconds = float(hang_seconds)
        self.calls = 0
        self.last_request: ProviderRequest | None = None

    def generate(self, request: ProviderRequest) -> ProviderResult:
        started = time.perf_counter()
        self.calls += 1
        self.last_request = request
        usage = (UsageMetadata(input_tokens=41, output_tokens=29, total_tokens=70)
                 if self.known_usage else UsageMetadata())
        behavior = self.behavior
        if behavior is FakeBehavior.VALID:
            return self._success(_valid_response(), usage, started)
        if behavior is FakeBehavior.INVALID_RECIPE:
            return self._success(_valid_response({
                "version": 1, "name": "invalid_params",
                "objects": [{"name": "body", "primitive": "box",
                             "params": {"unsupported_parameter": 1}}],
            }), usage, started)
        if behavior is FakeBehavior.POLICY_DENIED:
            return self._success(_valid_response({
                "version": 1, "name": "escape_attempt",
                "objects": [{"name": "body", "primitive": "box"}],
                "exports": [{"format": "obj", "path": "../escape.obj"}],
            }), usage, started)
        if behavior is FakeBehavior.RESOURCE_LIMIT:
            return self._success(_valid_response({
                "version": 1, "name": "too_many_sections",
                "objects": [{"name": "body", "primitive": "sphere",
                             "params": {"sections": 129, "rings": 8}}],
            }), usage, started)
        if behavior is FakeBehavior.TEXTURE_PATH:
            return self._success(_valid_response({
                "version": 1, "name": "texture_attempt",
                "materials": [{"name": "surface", "texture": "/tmp/private.png"}],
            }), usage, started)
        if behavior in {FakeBehavior.COMMAND_FIELD, FakeBehavior.OUTPUT_ROOT_FIELD}:
            import json
            payload = json.loads(_valid_response())
            key = ("command" if behavior is FakeBehavior.COMMAND_FIELD
                   else "output_root")
            payload[key] = "must-not-be-used"
            return self._success(
                json.dumps(payload, separators=(",", ":")).encode("utf-8"), usage,
                started)
        if behavior is FakeBehavior.MALFORMED_JSON:
            return self._success(b"{", usage, started)
        if behavior is FakeBehavior.DUPLICATE_KEYS:
            return self._success(
                b'{"schema_version":1,"schema_version":1}', usage, started)
        if behavior is FakeBehavior.INVALID_UTF8:
            return self._success(b"\xff\xfe", usage, started)
        if behavior is FakeBehavior.OVERSIZED:
            return self._success(b" " * (MAX_PROVIDER_RESPONSE_BYTES + 1),
                                 usage, started)
        if behavior is FakeBehavior.HANG:
            # Simulate a provider that stops responding. Keep tests bounded by
            # the request deadline plus a small scheduling allowance.
            time.sleep(min(self.hang_seconds, request.deadline_seconds + 0.01))
            failure = FailureCode.TIMEOUT
            return ProviderResult(
                self.provider_id, self.model_id, self.adapter_kind,
                ProviderCallStatus.FAILED,
                latency_ms=(time.perf_counter() - started) * 1000,
                usage=usage, failure_code=failure,
                transport_status="deadline_expired")

        failures = {
            FakeBehavior.TRANSPORT_FAILURE: FailureCode.TRANSPORT_FAILURE,
            FakeBehavior.NONZERO_EXIT: FailureCode.NONZERO_EXIT,
            FakeBehavior.TIMEOUT: FailureCode.TIMEOUT,
            FakeBehavior.QUOTA_LIMIT: FailureCode.QUOTA_RATE_LIMIT,
            FakeBehavior.AUTHENTICATION_FAILURE: FailureCode.AUTHENTICATION_FAILURE,
            FakeBehavior.REFUSAL: FailureCode.REFUSAL,
            FakeBehavior.UNAVAILABLE_PROVIDER: FailureCode.UNAVAILABLE_PROVIDER,
            FakeBehavior.UNSUPPORTED_ADAPTER: FailureCode.UNSUPPORTED_ADAPTER,
        }
        failure = failures[behavior]
        return ProviderResult(
            self.provider_id, self.model_id, self.adapter_kind,
            ProviderCallStatus.FAILED,
            latency_ms=(time.perf_counter() - started) * 1000, usage=usage,
            failure_code=failure,
            quota_or_rate_limited=(True if failure is FailureCode.QUOTA_RATE_LIMIT else None),
            transport_status={
                FailureCode.TRANSPORT_FAILURE: "transport_error",
                FailureCode.NONZERO_EXIT: "process_exit_nonzero",
                FailureCode.TIMEOUT: "deadline_expired",
                FailureCode.QUOTA_RATE_LIMIT: "quota_or_rate_limit",
                FailureCode.AUTHENTICATION_FAILURE: "authentication_failure",
                FailureCode.REFUSAL: "provider_refusal",
                FailureCode.UNAVAILABLE_PROVIDER: "provider_unavailable",
                FailureCode.UNSUPPORTED_ADAPTER: "adapter_unsupported",
            }[failure],
            transport_code=(23 if failure is FailureCode.NONZERO_EXIT else None))

    def _success(self, response: bytes, usage: UsageMetadata,
                 started: float) -> ProviderResult:
        return ProviderResult(
            self.provider_id, self.model_id, self.adapter_kind,
            ProviderCallStatus.SUCCEEDED, response_bytes=response,
            latency_ms=(time.perf_counter() - started) * 1000,
            usage=usage, transport_status="response_received")
