"""Small immutable contracts shared by headless AI generation stages."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import threading
import time
from typing import Any, Mapping


MAX_PROVIDER_RESPONSE_BYTES = 1_048_576
MAX_RECIPE_RESPONSE_BYTES = 524_288
MAX_PROVIDER_ATTEMPT_SECONDS = 90.0
MAX_GENERATION_SECONDS = 600.0
MAX_CANCEL_ACK_SECONDS = 3.0
MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL = 2


class ProviderError(Exception):
    """Base class for fixed, sanitized provider and credential failures."""


class ProviderConfigurationError(ProviderError):
    """Provider settings are invalid or outside the explicit trust boundary."""


class ProviderCredentialError(ProviderError):
    """A credential could not be retrieved or saved in an approved backend."""


class ProviderAuthenticationError(ProviderError):
    """The configured credential was rejected."""


class ProviderModelError(ProviderError):
    """The explicitly configured model is unavailable or unsupported."""


class ProviderRequestError(ProviderError):
    """The provider rejected a deterministic request."""


class ProviderProtocolError(ProviderError):
    """The endpoint did not return a valid OpenAI-compatible JSON response."""


class ProviderResponseTooLargeError(ProviderProtocolError):
    """The HTTP response or generated JSON exceeded its configured cap."""


class ProviderTruncatedResponseError(ProviderProtocolError):
    """The provider stopped before returning a complete structured response."""


class ProviderRefusalError(ProviderError):
    """The provider returned a refusal instead of the requested JSON object."""


class ProviderRateLimitError(ProviderError):
    """The endpoint kept returning rate-limit responses after one retry."""


class ProviderTransientError(ProviderError):
    """A retryable network/server failure persisted after one retry."""


class GenerationCancelledError(ProviderError):
    """The current generation request was cancelled by its owner."""


class DeadlineExceededError(ProviderError):
    """The shared generation deadline expired."""


@dataclass(frozen=True, slots=True)
class Dimensions:
    """Requested overall dimensions in a declared physical or abstract unit."""

    width: float
    height: float
    depth: float
    units: str = "m"

    def __post_init__(self) -> None:
        _positive_finite(self.width, "width")
        _positive_finite(self.height, "height")
        _positive_finite(self.depth, "depth")
        _short_text(self.units, "units", max_bytes=32)


@dataclass(frozen=True, slots=True)
class ComponentRequirement:
    name: str
    description: str = ""
    required: bool = True

    def __post_init__(self) -> None:
        _short_text(self.name, "component name", max_bytes=256)
        _short_text(self.description, "component description", max_bytes=2048, allow_empty=True)
        if type(self.required) is not bool:
            raise ValueError("component required must be a boolean")


@dataclass(frozen=True, slots=True)
class MaterialIntent:
    name: str
    appearance: str
    color_srgb: tuple[float, float, float] | None = None

    def __post_init__(self) -> None:
        _short_text(self.name, "material name", max_bytes=256)
        _short_text(self.appearance, "material appearance", max_bytes=2048)
        if self.color_srgb is not None:
            if len(self.color_srgb) != 3:
                raise ValueError("material color must have three sRGB channels")
            for channel in self.color_srgb:
                _finite_number(channel, "material color")
                if not 0.0 <= channel <= 1.0:
                    raise ValueError("material color channels must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class AnimationIntent:
    actions: tuple[str, ...]
    duration_seconds: float | None = None
    looping: bool | None = None

    def __post_init__(self) -> None:
        if not self.actions:
            raise ValueError("animation intent needs at least one action")
        for action in self.actions:
            _short_text(action, "animation action", max_bytes=256)
        if self.duration_seconds is not None:
            _positive_finite(self.duration_seconds, "animation duration")
        if self.looping is not None and type(self.looping) is not bool:
            raise ValueError("animation looping must be a boolean or null")


@dataclass(frozen=True, slots=True)
class AssetBrief:
    """User intent that remains independent from executable recipe-v1 data."""

    brief: str
    required_components: tuple[ComponentRequirement, ...] = ()
    dimensions: Dimensions | None = None
    materials: tuple[MaterialIntent, ...] = ()
    animation: AnimationIntent | None = None
    exports: tuple[str, ...] = ()
    style: str = ""
    intended_use: str = ""
    approximations: tuple[str, ...] = ()
    schema_version: int = 1

    def __post_init__(self) -> None:
        _short_text(self.brief, "brief", max_bytes=32_768)
        _short_text(self.style, "style", max_bytes=2048, allow_empty=True)
        _short_text(self.intended_use, "intended use", max_bytes=2048, allow_empty=True)
        if self.schema_version != 1:
            raise ValueError("unsupported AssetBrief schema version")
        for export in self.exports:
            _short_text(export, "export format", max_bytes=64)
        for approximation in self.approximations:
            _short_text(approximation, "approximation", max_bytes=1024)
        if len(self.required_components) > 128 or len(self.materials) > 32:
            raise ValueError("asset brief exceeds its component or material limit")
        if len(self.exports) > 16 or len(self.approximations) > 32:
            raise ValueError("asset brief exceeds its export or approximation limit")


@dataclass(frozen=True, slots=True)
class ProviderMessage:
    role: str
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "developer", "user", "assistant"}:
            raise ValueError("unsupported provider message role")
        if not isinstance(self.content, str):
            raise ValueError("provider message content must be text")


@dataclass(frozen=True, slots=True)
class GenerationRequest:
    brief: AssetBrief
    messages: tuple[ProviderMessage, ...]
    output_token_limit: int | None = None
    max_output_bytes: int = MAX_PROVIDER_RESPONSE_BYTES
    purpose: str = "generation"

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("generation request requires provider messages")
        if self.output_token_limit is not None and (
            type(self.output_token_limit) is not int or self.output_token_limit < 1
        ):
            raise ValueError("output token limit must be a positive integer")
        if type(self.max_output_bytes) is not int or not (
            1 <= self.max_output_bytes <= MAX_PROVIDER_RESPONSE_BYTES
        ):
            raise ValueError("output byte limit must be between 1 byte and 1 MiB")
        _short_text(self.purpose, "request purpose", max_bytes=64)
        try:
            message_bytes = sum(len(message.content.encode("utf-8", errors="strict")) for message in self.messages)
        except UnicodeEncodeError:
            raise ValueError("provider request messages must be valid UTF-8 text") from None
        if message_bytes > MAX_PROVIDER_RESPONSE_BYTES:
            raise ValueError("provider request messages exceed 1 MiB")


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """Non-secret settings for the single OpenAI-compatible adapter."""

    model: str
    endpoint: str = "https://api.openai.com/v1/chat/completions"
    credential_alias: str = "default"
    timeout_seconds: float = MAX_PROVIDER_ATTEMPT_SECONDS
    allowed_hosts: tuple[str, ...] = ("api.openai.com",)

    def __post_init__(self) -> None:
        _short_text(self.model, "model", max_bytes=128)
        _short_text(self.credential_alias, "credential alias", max_bytes=128)
        if not math.isfinite(self.timeout_seconds) or not (0 < self.timeout_seconds <= MAX_PROVIDER_ATTEMPT_SECONDS):
            raise ValueError("provider timeout must be between 0 and 90 seconds")
        if not self.allowed_hosts:
            raise ValueError("provider endpoint host must be explicitly allowlisted")
        for host in self.allowed_hosts:
            _short_text(host, "allowlisted host", max_bytes=253)


@dataclass(frozen=True, slots=True)
class ProviderUsage:
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None

    def __post_init__(self) -> None:
        for value in (self.prompt_tokens, self.completion_tokens, self.total_tokens):
            if value is not None and (type(value) is not int or value < 0):
                raise ValueError("token usage values must be non-negative integers or null")
        if self.cost_usd is not None and (not math.isfinite(self.cost_usd) or self.cost_usd < 0):
            raise ValueError("usage cost must be a non-negative finite number or null")


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    provider: str
    model: str
    request_id: str | None
    json_text: str | None
    json_data: Mapping[str, Any] | None
    usage: ProviderUsage = field(default_factory=ProviderUsage)
    finish_reason: str | None = None
    refused: bool = False


@dataclass(frozen=True, slots=True)
class GenerationEvent:
    run_id: str
    sequence: int
    stage: str
    attempt: int
    message: str
    progress: float | None = None

    def __post_init__(self) -> None:
        if self.sequence < 0 or self.attempt < 0:
            raise ValueError("event sequence and attempt must be non-negative")
        if self.progress is not None and (
            not math.isfinite(self.progress) or not 0.0 <= self.progress <= 1.0
        ):
            raise ValueError("event progress must be between 0 and 1")


class CancellationToken:
    """Thread-safe cancellation signal with an atomic completion boundary.

    Normal generation checks are lock-free reads of the event. ``commit``
    takes the lock only around the final host-controlled atomic promotion so
    a late cancel cannot make an already-published run appear cancelled.
    """

    __slots__ = ("_event", "_lock", "_committed")

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._committed = False

    def cancel(self) -> bool:
        """Request cancellation; return false once completion committed."""
        with self._lock:
            if self._committed:
                return False
            self._event.set()
            return True

    def commit(self, action, *, deadline: float | None = None):
        """Linearize a small irreversible host action against cancellation.

        The action should be the final atomic rename only. Network, checking,
        hashing, staging, and other slow work must happen before this call.
        """
        if not callable(action):
            raise TypeError("completion action must be callable")
        checked_deadline = None
        if deadline is not None:
            if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
                raise ValueError("deadline must be a finite monotonic timestamp")
            try:
                checked_deadline = float(deadline)
            except (OverflowError, ValueError):
                raise ValueError("deadline must be a finite monotonic timestamp") from None
            if not math.isfinite(checked_deadline):
                raise ValueError("deadline must be a finite monotonic timestamp")
        with self._lock:
            if self._committed:
                raise RuntimeError("completion has already been committed")
            if self._event.is_set():
                raise GenerationCancelledError("Generation was cancelled before publication.")
            if checked_deadline is not None and time.monotonic() >= checked_deadline:
                raise DeadlineExceededError("The generation deadline expired before publication.")
            result = action()
            self._committed = True
            return result

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def wait(self, timeout: float) -> bool:
        return self._event.wait(max(0.0, timeout))


def _finite_number(value: Any, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"{name} must be a finite number")


def _positive_finite(value: Any, name: str) -> None:
    _finite_number(value, name)
    if value <= 0:
        raise ValueError(f"{name} must be greater than zero")


def _short_text(value: Any, name: str, max_bytes: int, allow_empty: bool = False) -> None:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"{name} must be non-empty text")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must be valid UTF-8 text") from exc
    if size > max_bytes:
        raise ValueError(f"{name} exceeds its {max_bytes}-byte limit")
