# V1 Phase 1 — AI contracts and provider transport

Status: **implementation and fake-transport checks complete; live-provider qualification pending**.

This phase adds headless typed contracts, one bounded OpenAI-compatible Chat Completions adapter, and explicit OS credential stores. It does not implement prompts, recipe validation, geometry, orchestration, UI settings, or a release qualification claim.

## Frozen interfaces

`am3d.ai` is Qt-free. The user-intent contract is `AssetBrief`, with separate component requirements, optional overall dimensions, material intents, optional animation intent, requested exports, style, use, and declared approximations. It describes the request; recipe-v1 remains the only executable asset description.

The provider call is:

```python
provider = OpenAICompatibleProvider(config, credential_store, transport=None)
response = provider.generate(request, deadline, cancellation)
```

The deadline is an absolute `time.monotonic()` value. `CancellationToken` can be signalled from another thread. `ProviderResponse.json_data` is a strictly parsed JSON object; `json_text` preserves its JSON text. A refusal has `refused=True` and no content. Provider usage fields remain null when unavailable, and cost is always null until there is a dated tariff configuration.

`ProviderConfig` requires an explicit model string. Its default endpoint is the documented OpenAI Chat Completions URL; custom endpoints must use HTTPS, have no embedded user information, query or fragment, use the default TLS port, and match an explicit host allowlist. Redirects and environment proxy discovery are disabled for the HTTP request.

## Verified HTTP contract

The configured endpoint is `POST https://api.openai.com/v1/chat/completions`. The request carries the configured model, messages, JSON mode, and `store: false`; `max_completion_tokens` is sent only when the caller provides a model-appropriate output-token cap. The adapter prepends a short JSON-only system instruction.

The documented Chat Completions contract accepts `response_format: {"type":"json_object"}` and returns choices containing an assistant message and finish reason, with usage data when available. The implementation requires exactly one choice and a JSON object in `choices[0].message.content`. It handles refusal state, truncation, request IDs, and optional token counts. It does not use strict `json_schema` mode: the existing recipe schema contains open-ended parameter dictionaries and references that do not automatically satisfy the provider's strict schema subset. Phase 2 must apply the local recipe validator to the returned object.

The current official contract was checked against the [Create chat completion API reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create). OpenAI documents JSON mode as producing valid JSON and recommends Structured Outputs where the selected model and schema support it; JSON mode still requires a prompt that requests JSON. That is why the adapter supplies a JSON instruction and parses/validates the response locally.

## Bounds and error behavior

- HTTP envelope: at most 1 MiB; generated recipe requests set `max_output_bytes` to 512 KiB.
- Request messages: at most 1 MiB total.
- Provider attempt: at most 90 seconds; the caller owns the shared run deadline (up to 600 seconds).
- Cancellation is checked during HTTPX streaming, when the response task finishes, immediately after an injected or real transport returns, before retries, and before success is returned. The adapter makes no more than two HTTP attempts per semantic call. A completion that races with cancellation or deadline expiry is discarded.
- One retry is allowed for network failures/timeouts, HTTP 429, or HTTP 5xx while the shared deadline permits it. Authentication, model, refusal, deterministic 4xx, malformed JSON, and policy errors are not retried.
- HTTP and generated JSON reject duplicate keys, non-finite values, oversized numeric tokens, malformed UTF-8, and truncated content. JSON output must be an object.
- Error messages are fixed and sanitized. Response bodies and exception strings are never included. Before sending, the adapter checks endpoint/model/message fields and serialized request bytes for the active API key. Before returning a successful result, it checks raw response bytes, parsed envelope/content, and response headers for that key and discards a reflected credential.
- Endpoint, model, request ID and usage metadata are limited to what Phase 1 can establish. No tariff is inferred and no cost is reported as zero.

## Credential boundary

`SystemCredentialStore` explicitly constructs Windows Credential Manager (`WinVaultKeyring`) on Windows or the keyring Secret Service backend on Linux. It does not call keyring auto-selection and never selects a plaintext backend. Alias values are constrained; backend errors are replaced with fixed messages. `SessionCredentialStore` is an explicit memory-only fallback and has no disk serialization method. The provider fetches a credential for each call and does not cache it.

Tests use injected fake backends to cover rotation, deletion, missing entries, locked/unavailable behavior, and sentinel redaction. A separate orchestrator check exercised real Windows 10 Credential Manager store/retrieve/rotation/delete and removed its sentinel entry; see windows-credential-check.json. Windows 11 target qualification and Linux Secret Service checks remain pending.

Runtime dependency pins are owned by the parent phase coordinator: `httpx==0.28.1` and `keyring==25.7.0`. Keyring declares platform-specific credential backend dependencies, including SecretStorage on Linux; the Linux lock must resolve those dependencies. The adapter imports HTTPX only when making a request.

## Verification

Command:

```powershell
.venv\Scripts\python.exe -m pytest am3d/ai/test_contracts.py am3d/ai/test_credentials.py am3d/ai/test_providers.py -q
```

Result: **54 passed**; full stdout is in [`tests.txt`](tests.txt). Coverage includes a real-shaped fake Chat Completions response, request envelope, usage with unknown cost, recipe response cap, malformed/duplicate/non-finite/truncated JSON, refusal, 429/5xx/network retry ceiling, authentication/model errors, endpoint allowlisting, credential-in-request rejection before transport, reflected-secret rejection, cancellation races for HTTPX and injected transports, late-deadline rejection, and credential lifecycle. The HTTPX cancellation test uses an in-process mock transport and confirms cancellation propagation in less than three seconds without a network call.

No live API call was made. A model ID, user account, spend ceiling, tariff and selected live model support have not been provided, so live endpoint/model/refusal qualification remains pending. No release or platform-support claim follows from these tests.
