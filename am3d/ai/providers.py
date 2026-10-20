"""Cancellable OpenAI-compatible JSON HTTP provider adapter.

Only the provider boundary performs network IO. Responses are size-bounded and
strictly parsed before they cross into the headless generation pipeline.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import math
import re
import time
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit

from .credentials import (
    contains_percent_encoded_secret,
    contains_percent_encoded_secret_text,
    percent_decoded_representations,
)
from .contracts import (
    CancellationToken,
    DeadlineExceededError,
    GenerationCancelledError,
    GenerationRequest,
    MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL,
    MAX_PROVIDER_RESPONSE_BYTES,
    ProviderAuthenticationError,
    ProviderConfig,
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


_JSON_SYSTEM_INSTRUCTION = "Return exactly one JSON object and no Markdown or prose."
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_SAFE_FINISH_REASONS = frozenset({"stop", "length", "tool_calls", "function_call", "content_filter"})
_TRANSIENT_BACKOFF_SECONDS = 0.25
_MAX_RETRY_AFTER_SECONDS = 2.0
_CANCEL_POLL_SECONDS = 0.05


@dataclass(frozen=True, slots=True)
class TransportResponse:
    status_code: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    """Injectable synchronous transport; implementations must honor cancel/deadline."""

    def post(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        body: bytes,
        *,
        deadline: float,
        cancellation: CancellationToken,
        max_response_bytes: int,
    ) -> TransportResponse: ...


class _TransportFailure(Exception):
    pass


class HttpxTransport:
    """HTTPX async streaming transport run behind the synchronous provider API."""

    def __init__(self, transport: Any | None = None) -> None:
        # Optional httpx transport injection supports offline cancellation tests.
        self._httpx_transport = transport

    def post(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        body: bytes,
        *,
        deadline: float,
        cancellation: CancellationToken,
        max_response_bytes: int,
    ) -> TransportResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            # The interface is synchronous and intended for the app's worker
            # thread. Refuse to block an event-loop thread that owns cancellation.
            raise ProviderRequestError("Provider requests must run outside an asyncio event loop.")
        try:
            return asyncio.run(
                self._post_async(
                    endpoint,
                    headers,
                    body,
                    deadline=deadline,
                    cancellation=cancellation,
                    max_response_bytes=max_response_bytes,
                )
            )
        except (GenerationCancelledError, DeadlineExceededError, ProviderResponseTooLargeError, ProviderRequestError):
            raise
        except Exception:
            # Never expose an HTTPX exception: its representation may include
            # request details and should not enter diagnostics.
            raise _TransportFailure from None

    async def _post_async(
        self,
        endpoint: str,
        headers: Mapping[str, str],
        body: bytes,
        *,
        deadline: float,
        cancellation: CancellationToken,
        max_response_bytes: int,
    ) -> TransportResponse:
        try:
            import httpx
        except ImportError:
            raise ProviderRequestError("HTTP support is unavailable. Install the pinned httpx runtime dependency.") from None

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DeadlineExceededError("The generation deadline expired before the provider request.")
        timeout = httpx.Timeout(max(0.001, remaining))
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
        client_options = {
            "timeout": timeout,
            "limits": limits,
            "follow_redirects": False,
            "trust_env": False,
        }
        if self._httpx_transport is not None:
            client_options["transport"] = self._httpx_transport
        async with httpx.AsyncClient(**client_options) as client:
            operation = asyncio.create_task(
                self._read_response(
                    client,
                    endpoint,
                    headers,
                    body,
                    max_response_bytes=max_response_bytes,
                )
            )
            try:
                while True:
                    if cancellation.cancelled:
                        operation.cancel()
                        await _quietly_finish(operation)
                        raise GenerationCancelledError("Generation was cancelled during the provider request.")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        operation.cancel()
                        await _quietly_finish(operation)
                        raise DeadlineExceededError("The generation deadline expired during the provider request.")
                    done, _ = await asyncio.wait(
                        (operation,), timeout=min(_CANCEL_POLL_SECONDS, remaining)
                    )
                    if done:
                        # Cancellation/deadline may have fired while the
                        # response task was completing. Check before accepting
                        # its successful result.
                        _check_cancel_deadline(cancellation, deadline)
                        return operation.result()
            except asyncio.CancelledError:
                operation.cancel()
                await _quietly_finish(operation)
                raise GenerationCancelledError("Generation was cancelled during the provider request.") from None

    async def _read_response(
        self,
        client: Any,
        endpoint: str,
        headers: Mapping[str, str],
        body: bytes,
        *,
        max_response_bytes: int,
    ) -> TransportResponse:
        async with client.stream("POST", endpoint, headers=headers, content=body) as response:
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > max_response_bytes:
                    raise ProviderResponseTooLargeError("The provider response exceeded the 1 MiB limit.")
                chunks.append(chunk)
            selected_headers = {}
            for name in ("retry-after", "x-request-id"):
                value = response.headers.get(name)
                if value is not None:
                    selected_headers[name] = value
            return TransportResponse(response.status_code, selected_headers, b"".join(chunks))


class OpenAICompatibleProvider:
    """One JSON-only OpenAI Chat Completions HTTP adapter.

    ``credential_store`` must implement ``get(alias) -> str | None``. The key
    is fetched for each semantic call and is never cached on this object.
    ``transport`` can be replaced by deterministic test transports.
    """

    def __init__(
        self,
        config: ProviderConfig,
        credential_store: Any,
        transport: HttpTransport | None = None,
    ) -> None:
        self.config = config
        self.credential_store = credential_store
        self.transport = transport if transport is not None else HttpxTransport()
        _validate_endpoint(config.endpoint, config.allowed_hosts)

    def generate(
        self,
        request: GenerationRequest,
        deadline: float,
        cancellation: CancellationToken,
    ) -> ProviderResponse:
        _check_cancel_deadline(cancellation, deadline)
        try:
            api_key = self.credential_store.get(self.config.credential_alias)
        except Exception:
            raise ProviderCredentialError(
                "The saved provider credential is unavailable. Unlock the system credential store or enter a session-only key."
            ) from None
        if not isinstance(api_key, str) or not api_key.strip():
            raise ProviderCredentialError(
                "No provider credential is available. Save a key in the system credential store or enter a session-only key."
            )
        if len(api_key) > 4096 or any(ord(char) < 0x21 or ord(char) > 0x7E for char in api_key):
            raise ProviderCredentialError("The provider credential has an invalid format. Replace it.")

        try:
            payload = _build_payload(self.config.model, request)
            endpoint_path = urlsplit(self.config.endpoint).path
            if (
                api_key in self.config.endpoint
                or contains_percent_encoded_secret(endpoint_path, api_key)
                or _contains_string(payload, api_key)
            ):
                raise ProviderCredentialError(
                    "The provider credential matched endpoint or request content and was not sent."
                )
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8", errors="strict")
            if api_key.encode("ascii", errors="strict") in body:
                raise ProviderCredentialError(
                    "The provider credential matched endpoint or request content and was not sent."
                )
        except ProviderCredentialError:
            raise
        except Exception:
            raise ProviderRequestError("The provider request contains invalid text or could not be encoded.") from None
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        for attempt in range(1, MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL + 1):
            _check_cancel_deadline(cancellation, deadline)
            attempt_deadline = min(deadline, time.monotonic() + self.config.timeout_seconds)
            try:
                response = self.transport.post(
                    self.config.endpoint,
                    headers,
                    body,
                    deadline=attempt_deadline,
                    cancellation=cancellation,
                    max_response_bytes=MAX_PROVIDER_RESPONSE_BYTES,
                )
                # A transport may finish at the same time cancellation or the
                # per-attempt deadline fires. Never process a late success.
                _check_cancel_deadline(cancellation, attempt_deadline)
            except GenerationCancelledError:
                raise GenerationCancelledError("Generation was cancelled during the provider request.") from None
            except DeadlineExceededError:
                # The transport deadline is per attempt. Retry once when the
                # shared run deadline still has time remaining.
                if attempt < MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL and time.monotonic() < deadline:
                    _bounded_backoff(_TRANSIENT_BACKOFF_SECONDS, cancellation, deadline)
                    continue
                raise DeadlineExceededError("The provider attempt exceeded its deadline.") from None
            except ProviderResponseTooLargeError:
                raise ProviderResponseTooLargeError("The provider response exceeded the 1 MiB limit.") from None
            except ProviderRequestError:
                raise ProviderRequestError("Provider HTTP support is unavailable or cannot run in this context.") from None
            except ProviderError:
                if attempt < MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL:
                    _bounded_backoff(_TRANSIENT_BACKOFF_SECONDS, cancellation, deadline)
                    continue
                raise ProviderTransientError(
                    "The provider network request failed twice. Check the connection and try again."
                ) from None
            except Exception:
                if attempt < MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL:
                    _bounded_backoff(_TRANSIENT_BACKOFF_SECONDS, cancellation, deadline)
                    continue
                raise ProviderTransientError(
                    "The provider network request failed twice. Check the connection and try again."
                ) from None

            if not isinstance(response, TransportResponse):
                raise ProviderProtocolError("The HTTP transport returned an invalid response.")
            if len(response.body) > MAX_PROVIDER_RESPONSE_BYTES:
                raise ProviderResponseTooLargeError("The provider response exceeded the 1 MiB limit.")

            if response.status_code == 401 or response.status_code == 403:
                raise ProviderAuthenticationError(
                    "The provider rejected the credential. Check or replace the saved API key."
                )
            if response.status_code == 429:
                if attempt < MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL:
                    _bounded_backoff(_retry_after(response.headers), cancellation, deadline)
                    continue
                raise ProviderRateLimitError("The provider rate limit remained active after one retry.")
            if 500 <= response.status_code <= 599:
                if attempt < MAX_HTTP_ATTEMPTS_PER_SEMANTIC_CALL:
                    _bounded_backoff(_TRANSIENT_BACKOFF_SECONDS, cancellation, deadline)
                    continue
                raise ProviderTransientError(
                    "The provider server failed twice. Try again after the service recovers."
                )
            if not 200 <= response.status_code <= 299:
                _raise_deterministic_http_error(response)

            _reject_credential_reflection(response, api_key)
            result = _parse_success(response, self.config.model, request, api_key)
            _check_cancel_deadline(cancellation, deadline)
            return result

        raise ProviderTransientError("The provider request did not complete. Try again.")


def _validate_endpoint(endpoint: str, allowed_hosts: tuple[str, ...]) -> None:
    """Reject credential-bearing or untrusted URLs without echoing the URL."""
    invalid = ProviderConfigurationError(
        "Provider endpoint must use HTTPS on an explicitly allowlisted host, with no credentials, query, fragment, or custom port."
    )
    if not isinstance(endpoint, str) or not endpoint or any(ch.isspace() or ord(ch) < 32 for ch in endpoint):
        raise invalid
    try:
        parsed = urlsplit(endpoint)
        hostname = parsed.hostname
        port = parsed.port
    except (ValueError, UnicodeError):
        raise invalid from None
    if (
        parsed.scheme.lower() != "https"
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or "?" in endpoint
        or "#" in endpoint
        or parsed.query
        or parsed.fragment
        or (port is not None and port != 443)
        or parsed.netloc.endswith(":")
    ):
        raise invalid
    try:
        percent_decoded_representations(parsed.path)
    except ValueError:
        raise invalid from None
    try:
        normalized_host = hostname.rstrip(".").encode("idna").decode("ascii").lower()
        approved = {
            host.rstrip(".").encode("idna").decode("ascii").lower()
            for host in allowed_hosts
        }
    except (UnicodeError, AttributeError):
        raise invalid from None
    if normalized_host not in approved:
        raise invalid


def _build_payload(model: str, request: GenerationRequest) -> dict[str, Any]:
    messages = [{"role": "system", "content": _JSON_SYSTEM_INSTRUCTION}]
    messages.extend({"role": item.role, "content": item.content} for item in request.messages)
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "response_format": {"type": "json_object"},
        "store": False,
    }
    if request.output_token_limit is not None:
        payload["max_completion_tokens"] = request.output_token_limit
    return payload


def _parse_success(
    response: TransportResponse,
    configured_model: str,
    request: GenerationRequest,
    api_key: str,
) -> ProviderResponse:
    envelope = _strict_json_object(response.body)
    choices = envelope.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ProviderProtocolError("The provider response did not contain exactly one completion choice.")
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    if not isinstance(finish_reason, str) or finish_reason not in _SAFE_FINISH_REASONS:
        raise ProviderProtocolError("The provider response contained an unsupported completion state.")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ProviderProtocolError("The provider response did not contain an assistant message.")
    refusal = message.get("refusal")
    refused = (isinstance(refusal, str) and bool(refusal)) or finish_reason == "content_filter"
    request_id = _safe_request_id(response.headers.get("x-request-id"))
    if request_id is None:
        request_id = _safe_request_id(envelope.get("request_id")) or _safe_request_id(envelope.get("id"))
    usage = _parse_usage(envelope.get("usage"))
    if refused:
        return ProviderResponse(
            provider="openai-compatible",
            model=configured_model,
            request_id=request_id,
            json_text=None,
            json_data=None,
            usage=usage,
            finish_reason=finish_reason,
            refused=True,
        )
    if finish_reason == "length":
        raise ProviderTruncatedResponseError("The provider stopped before completing the JSON response.")
    content = message.get("content")
    if not isinstance(content, str):
        raise ProviderProtocolError("The provider assistant message did not contain JSON text.")
    try:
        encoded = content.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        raise ProviderProtocolError("The provider JSON contained invalid Unicode text.") from None
    if len(encoded) > request.max_output_bytes:
        raise ProviderResponseTooLargeError("The generated JSON exceeded this request's output limit.")
    data = _strict_json_object(encoded)
    if _contains_string(data, api_key):
        raise ProviderProtocolError("The provider response contained credential material and was discarded.")
    return ProviderResponse(
        provider="openai-compatible",
        model=configured_model,
        request_id=request_id,
        json_text=content,
        json_data=data,
        usage=usage,
        finish_reason=finish_reason,
        refused=False,
    )


def _reject_credential_reflection(response: TransportResponse, api_key: str) -> None:
    """Do not let a provider echo become persisted prompt or generation data."""
    try:
        secret = api_key.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        raise ProviderCredentialError("The provider credential has an invalid format. Replace it.") from None
    if secret in response.body or any(api_key in str(value) for value in response.headers.values()):
        raise ProviderProtocolError("The provider response contained credential material and was discarded.")
    try:
        envelope = _strict_json_object(response.body)
    except ProviderProtocolError:
        # Malformed bodies are rejected by the normal parser; they are never
        # returned. Raw-byte inspection above still catches direct echoes.
        return
    if _contains_string(envelope, api_key):
        raise ProviderProtocolError("The provider response contained credential material and was discarded.")


def _contains_string(value: Any, needle: str) -> bool:
    if isinstance(value, str):
        try:
            return contains_percent_encoded_secret_text(value, needle)
        except ValueError:
            # Ambiguous or over-budget text is not safe to send or retain.
            return True
    if isinstance(value, dict):
        return any(_contains_string(key, needle) or _contains_string(item, needle) for key, item in value.items())
    if isinstance(value, list):
        return any(_contains_string(item, needle) for item in value)
    return False


def _strict_json_object(raw: bytes) -> dict[str, Any]:
    try:
        text = raw.decode("utf-8", errors="strict")
        parsed = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite_constant,
            parse_float=_finite_float,
            parse_int=_bounded_int,
        )
    except ProviderProtocolError:
        raise
    except Exception:
        raise ProviderProtocolError("The provider returned malformed or truncated JSON.") from None
    if not isinstance(parsed, dict):
        raise ProviderProtocolError("The provider JSON response must be an object.")
    return parsed


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProviderProtocolError("The provider JSON contained a duplicate object key.")
        result[key] = value
    return result


def _reject_nonfinite_constant(value: str) -> None:
    raise ProviderProtocolError("The provider JSON contained a non-finite number.")


def _finite_float(value: str) -> float:
    if len(value) > 128:
        raise ProviderProtocolError("The provider JSON contained an oversized number.")
    number = float(value)
    if not math.isfinite(number):
        raise ProviderProtocolError("The provider JSON contained a non-finite number.")
    return number


def _bounded_int(value: str) -> int:
    if len(value.lstrip("-")) > 128:
        raise ProviderProtocolError("The provider JSON contained an oversized integer.")
    return int(value)


def _parse_usage(raw: Any) -> ProviderUsage:
    if not isinstance(raw, dict):
        return ProviderUsage()

    def count(name: str) -> int | None:
        value = raw.get(name)
        if type(value) is int and value >= 0:
            return value
        return None

    return ProviderUsage(
        prompt_tokens=count("prompt_tokens"),
        completion_tokens=count("completion_tokens"),
        total_tokens=count("total_tokens"),
        cost_usd=None,
    )


def _safe_request_id(value: Any) -> str | None:
    return value if isinstance(value, str) and _SAFE_ID.fullmatch(value) else None


def _raise_deterministic_http_error(response: TransportResponse) -> None:
    error_code = None
    try:
        body = _strict_json_object(response.body)
        error = body.get("error")
        if isinstance(error, dict):
            candidate = error.get("code")
            if isinstance(candidate, str):
                error_code = candidate.lower()
    except ProviderProtocolError:
        pass
    if error_code in {"model_not_found", "unsupported_model", "invalid_model"}:
        raise ProviderModelError("The configured model is unavailable for this provider account.")
    if response.status_code == 429:
        raise ProviderRateLimitError("The provider rate limit blocked the request.")
    raise ProviderRequestError(
        "The provider rejected the request. Check the configured model and JSON output support."
    )


def _retry_after(headers: Mapping[str, str]) -> float:
    raw = next((value for name, value in headers.items() if name.lower() == "retry-after"), None)
    if raw is None:
        return _TRANSIENT_BACKOFF_SECONDS
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return _TRANSIENT_BACKOFF_SECONDS
    if not math.isfinite(value) or value < 0:
        return _TRANSIENT_BACKOFF_SECONDS
    return min(value, _MAX_RETRY_AFTER_SECONDS)


def _bounded_backoff(
    seconds: float,
    cancellation: CancellationToken,
    deadline: float,
) -> None:
    delay = min(max(0.0, seconds), _MAX_RETRY_AFTER_SECONDS)
    remaining = deadline - time.monotonic()
    if remaining <= delay:
        raise DeadlineExceededError("The generation deadline expired before the provider retry.")
    if cancellation.wait(delay):
        raise GenerationCancelledError("Generation was cancelled before the provider retry.")
    _check_cancel_deadline(cancellation, deadline)


def _check_cancel_deadline(cancellation: CancellationToken, deadline: float) -> None:
    if cancellation.cancelled:
        raise GenerationCancelledError("Generation was cancelled.")
    if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or not math.isfinite(deadline):
        raise DeadlineExceededError("The generation deadline is invalid.")
    if time.monotonic() >= deadline:
        raise DeadlineExceededError("The generation deadline expired.")


async def _quietly_finish(task: asyncio.Task[Any]) -> None:
    try:
        await task
    except BaseException:
        pass
