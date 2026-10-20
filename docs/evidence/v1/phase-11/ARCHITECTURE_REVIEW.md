# Phase 11 integrated architecture and data-security review

Review date: 2026-10-14  
Review type: independent source review; bounded offline mock-transport reproductions and focused verification  
Repository: `C:\Users\Alex\Desktop\Olds-Cool-3D-Master`  
Baseline: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`  
Approved plan: `docs/V1_MASTER_IMPLEMENTATION_PLAN.md`  

## Disposition

The integrated implementation generally follows the approved V1 architecture: it composes the existing session/schema/serializer, provider and worker boundaries, immutable generation records, strict export validation, scene preview, and guarded `DocumentController` adoption flow. It does not introduce an independent scene model or execute provider-supplied code. The worker provides resource and lifecycle isolation; it is not an operating-system security sandbox. Existing records and local files are protected against ordinary application mutation, but same-account rewriting is outside the documented authenticity promise.

The local credential-handling gate was initially blocked by the reproduced P2 findings below. The first was an encoded key in an allowlisted endpoint path; the focused follow-up exposed the same common encoding in configured model or message text. The root accepted this as one credential-boundary issue and delegated a bounded extension. Independent source inspection and focused offline verification now confirm the standard percent-encoded forms covered below are rejected from endpoint paths, settings text, provider request JSON, and parsed response JSON before persistence, transport, or result retention. No further defect was reproduced within that bounded encoding scope. This review does not certify the full V1 suite or target-machine acceptance. I did not change production source.

## Initial reproduced finding: percent-encoded key bypasses endpoint and settings checks

Relevant pre-fix source at the initial finding:

- `am3d/ai/providers.py:247–257` checks whether the literal key occurs in the endpoint or request payload, then puts the key in the Authorization header.
- `am3d/ai/providers.py:343–378` validates HTTPS, host allowlisting, and URL authority/query/fragment constraints, but permits percent-encoded data in the path.
- `am3d/ui/ai_settings.py:137–148, 173–201` checks settings and endpoint/model text for literal key strings, then persists the endpoint unchanged.
- `am3d/ai/test_providers.py:119–139` covers a literal key in the endpoint, but not a percent-encoded representation.

I configured an allowlisted `api.openai.com` endpoint with a fake test key percent-encoded byte-by-byte in its path. An in-memory `SessionCredentialStore` supplied the same fake value, and an `httpx.MockTransport` inspected the outgoing request. The handler returned a fixed success response. No external request, OS credential store, GUI, or real credential was used. The provider accepted the endpoint; the outgoing raw request path contained the encoded fake key, while the raw fake key was absent from that path. The settings literal-secret scan also returned false for the endpoint. Safe output from the harness was:

```json
{"authorization_header_present":true,"encoded_secret_in_request_target":true,"hostname_allowlisted":true,"mock_request_completed":true,"raw_secret_in_request_target":false,"settings_literal_secret_scan_would_detect":false}
```

Reproduction shape, from the repository root (the harness was run with the isolated project Python and did not print either the fake key or its encoded form):

```text
PowerShell stdin harness | .venv\Scripts\python.exe -
```

The harness creates a fake sentinel, percent-encodes each UTF-8/ASCII byte as `%XX`, constructs `https://api.openai.com/v1/<encoded>/chat/completions`, uses `SessionCredentialStore` plus `OpenAICompatibleProvider(HttpxTransport(httpx.MockTransport(handler)))`, and emits only the six boolean fields above. The handler records `request.url.host`, `request.url.raw_path`, and whether the Authorization header exists. This demonstrates an accepted allowlisted endpoint and request-target exposure; it does not send network traffic or claim to address arbitrary malicious provider behavior.

## Bounded fix and independent verification

The first bounded URL-path correction passed an independent `55`-test provider/credential selection and a `7`-test settings selection. During that check, a second offline mock-transport reproduction showed that the same fake credential, bytewise percent-encoded in the configured model or a user message, passed the then-literal payload/settings scan and appeared in the outgoing JSON body. Safe output from that reproduction (no fake key or encoded value printed) was:

```json
{"encoded_secret_in_message_body":true,"encoded_secret_in_model_body":true,"mock_message_request_completed":true,"mock_model_request_completed":true,"raw_secret_in_message_body":false,"raw_secret_in_model_body":false,"settings_literal_scan_detects_encoded_model":false}

A PowerShell stdin harness piped to `build/windows/venv/Scripts/python.exe -` generated a random synthetic key at runtime, percent-encoded its ASCII bytes, then made separate provider calls with that value in the model field and message content. Both calls used an in-memory SessionCredentialStore and HttpxTransport(httpx.MockTransport(handler)); the handler captured request bytes without network access. The harness called the same settings string-check helper on the model value and emitted only the boolean fields shown above.
```

The bounded extension adds `contains_percent_encoded_secret_text` in `am3d/ai/credentials.py:60–104`; provider recursive JSON-string traversal uses it at `am3d/ai/providers.py:487–498` for request and parsed response dictionaries, keys, lists, and values. The settings scan applies it to every current or retained preference string at `am3d/ui/ai_settings.py:18–47`, before `_save` writes settings or rotates the credential at lines 174–205. The separate URL-path checker remains capped at 16,384 characters and four decoding rounds; the generic request/response/settings string scan is capped at 1 MiB per layer and four rounds, so it does not apply the URL path cap to a large valid context. Excessive or over-budget encoded text fails closed with fixed errors.

I independently inspected those gates and ran only these offline selections in the isolated Windows interpreter with `QT_QPA_PLATFORM=offscreen`:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\windows\venv\Scripts\python.exe -m pytest am3d/ai/test_providers.py am3d/ai/test_credentials.py -q --maxfail=1 --tb=short
```

Result after the extension: **64 passed in 2.66s**. The parameterized cases assert zero transport calls for encoded model/message text, including nested and overdeep forms, and reject encoded credential strings in both response JSON keys and values. They also retain a benign 24 KB context containing `%2F` and accept it.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\windows\venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py -k settings -q --maxfail=1 --tb=short
```

Result after the extension: **11 passed, 16 deselected in 1.20s**. The encoded current, old-during-rotation, and new-during-rotation cases cover both endpoint and model fields; they assert that QSettings and the in-memory session store are unchanged and that diagnostics omit both raw and encoded fake values. An encoded retained preference is rejected before mutation, while a valid escaped endpoint path remains accepted.

I also independently checked the test-selection/preflight pair separately:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\windows\venv\Scripts\python.exe -m pytest am3d/ai/test_checks.py::test_output_tree_byte_preflight_stops_native_loading am3d/ai/test_checks.py::test_native_failure_report_does_not_persist_untrusted_exception_text -q --maxfail=1 --tb=short
```

Result: **2 passed in 0.57s**. This confirms the preflight test still exercises the pre-load stop and the native privacy test selects `native_roundtrip` by name rather than indexing the first check.

Final focused source hashes at this verification point were: `credentials.py` `AF019CEDB840EAE9B5CFDE00073AF07EF00D1F058A690273F8F2996E233A40F2`; `providers.py` `BF1ACC782ECADE0DE4D585A47E1E3FB73C04520E52B52118271E745270887BA4`; `ai_settings.py` `571F9653583500D00516527CB2C8E5A4E5476F110DE6648182B1B6038AE4B076`; `test_providers.py` `973448B1173E4E6E9C7D06EC4301D1B04382B3E52D4B60D7696FF12180DDB146`; `test_credentials.py` `331F62AD879E4DAFA33AF46BD1E1592EC4A85E001876978F5D3F0499F56F7FAE`; `test_ai_workspace.py` `A230EEC3F6999423F670BD6F8FF7461A4921C61705F2B0F3440F684475CCD61E`; and `test_checks.py` `EB837EAED63FF3E1F18FF89FB70395CF36AB90023EE37E68A472F88902A5D687`. They match the files inspected after the final test runs.

## Integrated boundary review and qualifications

The reviewed flow keeps model output within the typed recipe/document boundary, applies strict schema and serializer checks, and promotes only validated artifacts through the existing project/session/document-controller route. Cancellation and stale-job/adoption checks are represented at the controller/worker boundary. Export parsing keeps a strict project-root boundary, and retained generated profile workflows use the existing profile/serializer route. Fixed pre-Qt startup and bundle identity checks occur before the UI import path. These are source-review observations, not claims of completed target-machine acceptance.

The following limits remain material to the V1 evidence and are not resolved by this review:

- A worker process boundary does not provide an OS sandbox.
- Same-account rewriting of application files cannot be treated as an authenticity guarantee.
- A missing history entry may require manual file opening; stale job output is not silently adopted.
- The frozen-key service reviewed here supports current credential CRUD but is not evidence of target-machine secret-store acceptance.
- The offline benchmark retains its fixed 30-case denominator and two runs; the existing two human-original scores remain unknown, so this does not qualify as live/provider or human acceptance.
- No target Windows 10 IoT device, live provider, native GPU path, or independent human reviewer was exercised here. The prior 8-second close-wait observation remains unexplained, and the earlier interrupted broad AI-suite status remains unknown.

## Evidence identity and test/build status

At the start of source review, the Phase 10 frozen-source manifest `docs/evidence/v1/phase-10/BOOTSTRAP_SOURCE_INPUTS.json` had digest `6c570bdd18102fb51f76e3e74626e8ecfd78c05e6d043c3ac47972089579aa9b`. A read-only check at that point checked all 187 listed files and found zero hash mismatches. That digest binds only the pre-correction snapshot. Subsequent root-owned test-selection edits and the encoded-credential provider/settings changes invalidate it for both test and runtime inputs. The hashes above bind the files used for this independent focused verification; a fresh complete manifest and digest are still required before final test/artifact binding. This review file is a Phase 11 evidence artifact and is not part of the source-freeze input set.

At initial bootstrap, root reported that the isolated Windows run stopped at its first failing named unit after 27 passed tests in 96.01 seconds. The assertion selected `checks[0]` for a native-privacy failure, although `output_tree_preflight` is now first. Root subsequently reported that the bounded test-only correction in `am3d/ai/test_checks.py` passed two targeted tests in 0.80 seconds and a 16-module run in 78.99 seconds; the runtime-check source snapshot was unchanged. The earlier 187-file source manifest does not bind this edited test input and must be recomputed. No resumed full-suite result, PyInstaller build, final lock, or frozen archive had been reported at this review cutoff. Do not treat the earlier full-suite or packaging gates as complete based on this review.

I ran only the focused offline tests and the in-process mock transports described above. I did not access the OS credential store, launch the application GUI, invoke a live provider, or alter runtime source, tests, locks, bundles, or existing evidence. The sole file authored for this task is this Phase 11 review.
