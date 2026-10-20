import asyncio
import json
import threading
import time
import traceback
from urllib.parse import quote

import httpx
import pytest

from am3d.ai.contracts import (
    AssetBrief,
    CancellationToken,
    DeadlineExceededError,
    GenerationCancelledError,
    GenerationRequest,
    ProviderAuthenticationError,
    ProviderConfig,
    ProviderConfigurationError,
    ProviderCredentialError,
    ProviderMessage,
    ProviderModelError,
    ProviderProtocolError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderResponseTooLargeError,
    ProviderTransientError,
    ProviderTruncatedResponseError,
)
from am3d.ai.credentials import SessionCredentialStore
from am3d.ai.providers import (
    HttpxTransport,
    OpenAICompatibleProvider,
    TransportResponse,
)


SECRET = "api-key-sentinel-8fa4"


class QueueTransport:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def post(self, endpoint, headers, body, *, deadline, cancellation, max_response_bytes):
        self.calls.append((endpoint, dict(headers), json.loads(body), deadline, max_response_bytes))
        result = self.results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result


def _provider(transport, *, model="explicit-test-model", endpoint=None, allowed_hosts=("api.openai.com",)):
    credentials = SessionCredentialStore()
    credentials.set("default", SECRET)
    config_args = {"model": model, "allowed_hosts": allowed_hosts}
    if endpoint is not None:
        config_args["endpoint"] = endpoint
    return OpenAICompatibleProvider(ProviderConfig(**config_args), credentials, transport)


def _request(*, max_output_bytes=1_048_576, output_token_limit=None):
    return GenerationRequest(
        AssetBrief("A stylized windmill"),
        (ProviderMessage("user", "Return a JSON object for this brief."),),
        output_token_limit=output_token_limit,
        max_output_bytes=max_output_bytes,
    )


def _chat_response(content='{"ok":true}', *, finish_reason="stop", usage=None, refusal=None, request_id="req_fake_1"):
    message = {"role": "assistant", "content": content}
    if refusal is not None:
        message["refusal"] = refusal
    envelope = {
        "id": "chatcmpl-test_1",
        "request_id": request_id,
        "model": "server-reported-alias",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }
    return TransportResponse(200, {"x-request-id": request_id}, json.dumps(envelope).encode("utf-8"))


def _run(provider, request=None, token=None, deadline=None):
    return provider.generate(
        request or _request(),
        deadline if deadline is not None else time.monotonic() + 30,
        token or CancellationToken(),
    )


def _encode_secret(secret, rounds=1):
    encoded = "".join(f"%{byte:02X}" for byte in secret.encode("utf-8"))
    for _ in range(rounds - 1):
        encoded = quote(encoded, safe="")
    return encoded


def test_fake_openai_shaped_json_roundtrip_and_request_contract():
    transport = QueueTransport(_chat_response(usage={"prompt_tokens": 18, "completion_tokens": 9, "total_tokens": 27}))
    provider = _provider(transport)

    response = _run(provider, _request(output_token_limit=2048))

    assert response.json_text == '{"ok":true}'
    assert response.json_data == {"ok": True}
    assert response.provider == "openai-compatible"
    assert response.model == "explicit-test-model"
    assert response.request_id == "req_fake_1"
    assert response.usage.prompt_tokens == 18
    assert response.usage.completion_tokens == 9
    assert response.usage.cost_usd is None
    endpoint, headers, payload, _, cap = transport.calls[0]
    assert endpoint == "https://api.openai.com/v1/chat/completions"
    assert headers["Authorization"] == f"Bearer {SECRET}"
    assert payload["model"] == "explicit-test-model"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["store"] is False
    assert payload["max_completion_tokens"] == 2048
    assert payload["messages"][0]["role"] == "system"
    assert "JSON object" in payload["messages"][0]["content"]
    assert cap == 1_048_576


@pytest.mark.parametrize("field", [
    "model", "message", "endpoint", "encoded-model", "encoded-message",
    "double-encoded-model", "double-encoded-message",
    "four-round-encoded-message", "overdeep-message",
])
def test_actual_api_key_in_request_configuration_or_content_is_rejected_before_transport(field):
    transport = QueueTransport(_chat_response())
    encoded = ""
    if field.startswith("encoded-"):
        encoded = _encode_secret(SECRET)
    elif field.startswith("double-encoded-"):
        encoded = _encode_secret(SECRET, rounds=2)
    elif field == "four-round-encoded-message":
        encoded = _encode_secret(SECRET, rounds=4)
    elif field == "overdeep-message":
        encoded = _encode_secret(SECRET, rounds=5)
    if field.endswith("model"):
        provider = _provider(transport, model=encoded or SECRET)
        request = _request()
    elif field.endswith("message"):
        provider = _provider(transport)
        request = GenerationRequest(
            AssetBrief("brief"),
            (ProviderMessage("user", f"include {encoded or SECRET}"),),
        )
    else:
        provider = _provider(
            transport,
            endpoint=f"https://api.openai.com/v1/{SECRET}/chat/completions",
        )
        request = _request()

    with pytest.raises(ProviderCredentialError) as caught:
        _run(provider, request)
    diagnostic = "".join(traceback.format_exception(caught.value))
    if SECRET in diagnostic or (encoded and encoded in diagnostic):
        raise AssertionError("provider error exposed credential material")
    if transport.calls:
        raise AssertionError("provider transport ran for credential-bearing request text")


@pytest.mark.parametrize("encoding", [
    "bytewise-utf8",
    "mixed-literal-and-escaped",
    "lowercase-hex",
    "double-encoded",
    "four-round-encoded",
])
def test_percent_encoded_active_api_key_in_endpoint_path_is_rejected_before_transport(encoding):
    if encoding == "mixed-literal-and-escaped":
        path_key = "".join(
            chr(byte) if index % 2 == 0 else f"%{byte:02X}"
            for index, byte in enumerate(SECRET.encode("utf-8"))
        )
    elif encoding == "lowercase-hex":
        path_key = _encode_secret(SECRET).lower()
    else:
        rounds = 2 if encoding == "double-encoded" else 4 if encoding == "four-round-encoded" else 1
        path_key = _encode_secret(SECRET, rounds=rounds)

    transport = QueueTransport(_chat_response())
    provider = _provider(
        transport,
        endpoint=f"https://api.openai.com/v1/{path_key}/chat/completions",
    )
    with pytest.raises(ProviderCredentialError) as caught:
        _run(provider)

    diagnostic = "".join(traceback.format_exception(caught.value))
    if SECRET in diagnostic or path_key in diagnostic:
        raise AssertionError("provider error exposed credential material")
    if transport.calls:
        raise AssertionError("provider transport ran for a credential-bearing endpoint")


def test_endpoint_with_encoding_beyond_the_bounded_depth_is_rejected_safely():
    path_key = _encode_secret(SECRET, rounds=5)
    with pytest.raises(ProviderConfigurationError) as caught:
        _provider(
            QueueTransport(),
            endpoint=f"https://api.openai.com/v1/{path_key}/chat/completions",
        )
    diagnostic = "".join(traceback.format_exception(caught.value))
    if SECRET in diagnostic or path_key in diagnostic:
        raise AssertionError("configuration error exposed credential material")


def test_endpoint_path_over_the_percent_decode_size_limit_is_rejected_safely():
    with pytest.raises(ProviderConfigurationError) as caught:
        _provider(
            QueueTransport(),
            endpoint="https://api.openai.com/" + ("a" * 16_385),
        )
    if "a" * 16_385 in "".join(traceback.format_exception(caught.value)):
        raise AssertionError("configuration error exposed endpoint path text")


def test_valid_percent_escaped_endpoint_path_without_key_reaches_transport():
    endpoint = "https://api.openai.com/v1/teams%2Fblue/chat/completions"
    transport = QueueTransport(_chat_response())
    provider = _provider(transport, endpoint=endpoint)

    result = _run(provider)

    assert result.json_data == {"ok": True}
    assert transport.calls[0][0] == endpoint


def test_large_provider_context_with_benign_percent_text_remains_usable():
    transport = QueueTransport(_chat_response())
    provider = _provider(transport)
    long_context = "ordinary context %2F " + ("x" * 24_000)
    request = GenerationRequest(
        AssetBrief("A large but valid local context"),
        (ProviderMessage("user", long_context),),
    )

    result = _run(provider, request)

    assert result.json_data == {"ok": True}
    assert len(transport.calls) == 1


def test_recipe_output_limit_is_applied_to_model_json():
    provider = _provider(QueueTransport(_chat_response('{"recipe":"12345"}')))
    with pytest.raises(ProviderResponseTooLargeError):
        _run(provider, _request(max_output_bytes=8))


@pytest.mark.parametrize("content", [
    '{"a":1,"a":2}',
    '{"number":NaN}',
    '{"number":Infinity}',
    '{"number":1e1000}',
    '{"a":',
])
def test_generated_json_rejects_duplicate_nonfinite_and_truncated_content(content):
    provider = _provider(QueueTransport(_chat_response(content)))
    with pytest.raises(ProviderProtocolError):
        _run(provider)


def test_generated_json_rejects_lone_surrogate_with_fixed_protocol_error():
    envelope = {
        "choices": [{
            "message": {"role": "assistant", "content": '{"text":"' + chr(0xD800) + '"}'},
            "finish_reason": "stop",
        }]
    }
    raw = json.dumps(envelope).encode("utf-8")
    provider = _provider(QueueTransport(TransportResponse(200, {}, raw)))
    with pytest.raises(ProviderProtocolError) as caught:
        _run(provider)
    assert "Unicode" in str(caught.value)


def test_http_envelope_rejects_duplicate_or_nonfinite_json_too():
    raw = b'{"choices":[],"choices":[],"value":NaN}'
    provider = _provider(QueueTransport(TransportResponse(200, {}, raw)))
    with pytest.raises(ProviderProtocolError):
        _run(provider)


def test_oversized_http_response_is_rejected():
    provider = _provider(QueueTransport(TransportResponse(200, {}, b" " * (1_048_577))))
    with pytest.raises(ProviderResponseTooLargeError):
        _run(provider)


def test_refusal_is_returned_as_state_and_never_retried():
    transport = QueueTransport(_chat_response(content=None, refusal="untrusted refusal text"))
    response = _run(_provider(transport))
    assert response.refused is True
    assert response.json_text is None
    assert response.json_data is None
    assert len(transport.calls) == 1


def test_truncated_finish_reason_is_not_retried():
    transport = QueueTransport(_chat_response('{"partial":', finish_reason="length"))
    with pytest.raises(ProviderTruncatedResponseError):
        _run(_provider(transport))
    assert len(transport.calls) == 1


def test_retries_429_once_then_reports_rate_limit():
    transport = QueueTransport(
        TransportResponse(429, {"retry-after": "0"}, b'{"error":{"code":"rate_limit"}}'),
        TransportResponse(429, {}, b"provider secret details are never echoed"),
    )
    with pytest.raises(ProviderRateLimitError):
        _run(_provider(transport))
    assert len(transport.calls) == 2


def test_retries_5xx_once_then_reports_fixed_transient_error():
    transport = QueueTransport(
        TransportResponse(503, {}, b"private server body"),
        TransportResponse(502, {}, b"more private body"),
    )
    with pytest.raises(ProviderTransientError) as caught:
        _run(_provider(transport))
    assert "private" not in str(caught.value)
    assert len(transport.calls) == 2


def test_retries_network_failure_once_and_can_then_succeed():
    transport = QueueTransport(TimeoutError(SECRET), _chat_response())
    response = _run(_provider(transport))
    assert response.json_data == {"ok": True}
    assert len(transport.calls) == 2


def test_per_attempt_deadline_can_retry_while_shared_run_deadline_remains():
    transport = QueueTransport(DeadlineExceededError("attempt elapsed"), _chat_response())
    response = _run(_provider(transport), deadline=time.monotonic() + 30)
    assert response.json_data == {"ok": True}
    assert len(transport.calls) == 2


@pytest.mark.parametrize(
    ("status", "exception"),
    [
        (401, ProviderAuthenticationError),
        (403, ProviderAuthenticationError),
    ],
)
def test_authentication_errors_do_not_retry_or_echo_body(status, exception):
    transport = QueueTransport(TransportResponse(status, {}, f"private {SECRET}".encode()))
    provider = _provider(transport)
    with pytest.raises(exception) as caught:
        _run(provider)
    diagnostic = "".join(traceback.format_exception(caught.value))
    assert SECRET not in diagnostic
    assert len(transport.calls) == 1


def test_model_error_is_classified_without_body_echo_and_does_not_retry():
    body = json.dumps({"error": {"code": "model_not_found", "message": SECRET}}).encode()
    transport = QueueTransport(TransportResponse(400, {}, body))
    with pytest.raises(ProviderModelError) as caught:
        _run(_provider(transport))
    assert SECRET not in "".join(traceback.format_exception(caught.value))
    assert len(transport.calls) == 1


@pytest.mark.parametrize("where", ["content", "metadata", "escaped-content", "request-id"])
def test_successful_response_that_reflects_active_credential_is_discarded(where):
    if where == "content":
        response = _chat_response(json.dumps({"description": SECRET}))
    elif where == "metadata":
        envelope = json.loads(_chat_response().body)
        envelope["provider_metadata"] = {"echo": SECRET}
        response = TransportResponse(200, {}, json.dumps(envelope).encode())
    elif where == "escaped-content":
        # A JSON unicode escape can hide the key from a raw byte substring scan.
        escaped = SECRET.replace("-", "\\u002d")
        response = _chat_response('{"description":"' + escaped + '"}')
    else:
        response = _chat_response(request_id=SECRET)

    provider = _provider(QueueTransport(response))
    with pytest.raises(ProviderProtocolError) as caught:
        _run(provider)
    diagnostic = "".join(traceback.format_exception(caught.value))
    if SECRET in diagnostic:
        raise AssertionError("provider response error exposed credential material")
    if "credential material" not in str(caught.value):
        raise AssertionError("provider response credential was not rejected")


@pytest.mark.parametrize("location", ["json-key", "json-value"])
def test_percent_encoded_credential_in_response_json_is_discarded(location):
    encoded = _encode_secret(SECRET)
    envelope = json.loads(_chat_response().body)
    envelope["provider_metadata"] = (
        {encoded: "metadata"}
        if location == "json-key"
        else {"metadata": encoded}
    )
    response = TransportResponse(200, {}, json.dumps(envelope).encode("utf-8"))
    provider = _provider(QueueTransport(response))

    with pytest.raises(ProviderProtocolError) as caught:
        _run(provider)

    diagnostic = "".join(traceback.format_exception(caught.value))
    if SECRET in diagnostic or encoded in diagnostic:
        raise AssertionError("provider response error exposed credential material")
    if "credential material" not in str(caught.value):
        raise AssertionError("encoded response credential was not rejected")


def test_other_deterministic_4xx_is_not_retried():
    transport = QueueTransport(TransportResponse(400, {}, b"bad request body"))
    with pytest.raises(ProviderRequestError):
        _run(_provider(transport))
    assert len(transport.calls) == 1


@pytest.mark.parametrize("endpoint", [
    "http://api.openai.com/v1/chat/completions",
    f"https://user:{SECRET}@api.openai.com/v1/chat/completions",
    f"https://api.openai.com/v1/chat/completions?key={SECRET}",
    "https://api.openai.com/v1/chat/completions#fragment",
    "https://api.openai.com:8443/v1/chat/completions",
    "https://evil.example/v1/chat/completions",
])
def test_endpoint_validation_is_https_allowlisted_and_sanitized(endpoint):
    with pytest.raises(ProviderConfigurationError) as caught:
        _provider(QueueTransport(), endpoint=endpoint)
    assert SECRET not in str(caught.value)
    assert "https" in str(caught.value).lower()


def test_explicit_custom_endpoint_requires_explicit_host_allowlist():
    provider = _provider(
        QueueTransport(_chat_response()),
        endpoint="https://gateway.example/v1/chat/completions",
        allowed_hosts=("gateway.example",),
    )
    assert _run(provider).json_data == {"ok": True}


def test_cancelled_request_acknowledges_within_three_seconds_and_closes_httpx_operation():
    cancelled_in_handler = threading.Event()

    async def slow_handler(request):
        try:
            await asyncio.sleep(30)
        except asyncio.CancelledError:
            cancelled_in_handler.set()
            raise

    token = CancellationToken()
    transport = HttpxTransport(httpx.MockTransport(slow_handler))
    provider = _provider(transport)
    timer = threading.Timer(0.1, token.cancel)
    started = time.monotonic()
    timer.start()
    try:
        with pytest.raises(GenerationCancelledError):
            _run(provider, token=token, deadline=time.monotonic() + 15)
    finally:
        timer.cancel()
    elapsed = time.monotonic() - started
    assert elapsed <= 3.0
    assert cancelled_in_handler.wait(1.0)


def test_httpx_completion_racing_with_cancellation_cannot_return_success():
    token = CancellationToken()

    async def cancel_then_return(request):
        token.cancel()
        return httpx.Response(200, content=_chat_response().body, request=request)

    transport = HttpxTransport(httpx.MockTransport(cancel_then_return))
    provider = _provider(transport)
    with pytest.raises(GenerationCancelledError):
        _run(provider, token=token)


def test_injected_transport_success_racing_with_cancellation_cannot_return_success():
    class CancelAndReturnTransport:
        def post(self, endpoint, headers, body, *, deadline, cancellation, max_response_bytes):
            cancellation.cancel()
            return _chat_response()

    provider = _provider(CancelAndReturnTransport())
    with pytest.raises(GenerationCancelledError):
        _run(provider)


def test_injected_transport_late_success_after_shared_deadline_is_rejected():
    class LateSuccessTransport:
        def post(self, endpoint, headers, body, *, deadline, cancellation, max_response_bytes):
            time.sleep(0.05)
            return _chat_response()

    provider = _provider(LateSuccessTransport())
    with pytest.raises(DeadlineExceededError):
        _run(provider, deadline=time.monotonic() + 0.01)


def test_cancel_before_call_and_expired_deadline_do_not_touch_transport():
    transport = QueueTransport(_chat_response())
    provider = _provider(transport)
    token = CancellationToken()
    token.cancel()
    with pytest.raises(GenerationCancelledError):
        _run(provider, token=token)
    with pytest.raises(Exception, match="deadline"):
        _run(provider, deadline=time.monotonic() - 1)
    assert transport.calls == []


def test_request_lone_surrogate_is_fixed_error_without_reflecting_text():
    with pytest.raises(ValueError, match="UTF-8"):
        _request_with_message("bad-" + chr(0xD800) + "-sentinel")


def _request_with_message(content):
    return GenerationRequest(AssetBrief("brief"), (ProviderMessage("user", content),))
