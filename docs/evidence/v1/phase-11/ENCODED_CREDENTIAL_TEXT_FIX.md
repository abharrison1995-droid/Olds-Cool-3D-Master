# Phase 11 — encoded credentials in request, settings, and response text

Status: **bounded source extension and focused checks complete; the single independent extension verification is pending.** This extends the endpoint-path fix in [`ENCODED_CREDENTIAL_FIX.md`](ENCODED_CREDENTIAL_FIX.md). That earlier receipt and its original pre/post hashes remain unchanged.

The extension followed an adjacent offline source review finding: percent-encoded active credential text in the configured model or request message could pass literal checks into request JSON, and a percent-encoded reflection in response JSON could pass literal response checks. The settings scan also searched literal strings only. No real credential, network request, OS credential backend, build, lock capture, or release action was used.

## Change and bounds

`am3d/ai/credentials.py` now also provides a general text scanner. It first checks the literal credential and then looks for valid `%HH` escapes. Text without either takes a fast path without decoding. Text requiring decoding is checked through at most four standard percent-decoding rounds, with a 1 MiB UTF-8 byte ceiling at each layer. A fifth valid escape layer or over-budget decoded text raises a generic `ValueError`; the calling provider/settings boundary converts it to its existing fixed safe rejection. There is no recursive decoding or alternate-codec handling.

The earlier URL-path helper retains its separate 16,384-character limit and four-round depth check. `OpenAICompatibleProvider` uses the general scanner over all request JSON string keys and values before transport, and over parsed response JSON string keys and values before returning a response. Over-budget or excessively encoded text is rejected. `AISettingsDialog._secret_leaks` scans all preference keys/values and the pending endpoint/model text for both current and newly entered credentials, while the strict URL-path check remains in place. A failed save leaves settings and the selected session store unchanged.

Large valid request text can exceed the URI path limit: a 24,000-character context containing an ordinary escaped slash remained usable. The remaining boundary is standard percent decoding only; this is not a claim against other encodings, nonstandard intermediary transformations, compromised application code, or same-account rewriting.

## Verification

Windows isolated interpreter, `QT_QPA_PLATFORM=offscreen`:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\windows\venv\Scripts\python.exe -m pytest am3d/ai/test_providers.py am3d/ai/test_credentials.py -q --maxfail=1 --tb=short
```

Final result: **64 passed in 2.46s**. Coverage includes encoded and double-encoded model/message values, the four-round and over-depth text boundary, zero transport on rejection, a benign large context, and encoded JSON response keys/values discarded with fixed diagnostics.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\windows\venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py -k settings -q --maxfail=1 --tb=short
```

Result: **11 passed, 16 deselected in 1.70s**. The UI cases cover endpoint and model fields with current, old-rotation, and new-rotation keys, plus an encoded key in an existing preference value. They compare preferences/store state without printing the values. The module fixture uses temporary INI settings and restores QSettings format and user/system paths. Credentials are in-memory; no system store or network was used.

One earlier focused attempt failed in test setup, not product code: the four-round case was first placed in the model field, whose existing `ProviderConfig` contract limits models to 128 bytes. The first run stopped at `am3d/ai/test_providers.py:144`, then `ProviderConfig.__post_init__` / `_short_text` at `am3d/ai/contracts.py:222` raised `ValueError: model exceeds its 128-byte limit` after 8 passes. The regression was moved to the request-message field, which exercises the same scanner within the existing 1 MiB message limit; the final provider/credential run above passed.

The earlier endpoint-only independent verification passed its single focused round (provider/credential: 55 passed; settings selection: 7 passed, 16 deselected). The independent reviewer has been asked to verify this text extension once; no further independent round is requested.

## File identities for this extension

These are SHA-256 identities immediately before and after the text-scan extension, with the endpoint-only fix already present. They do not replace or rewrite the source-freeze manifest.

| File | Before this extension | After this extension |
|---|---|---|
| `am3d/ai/credentials.py` | `C08FD39C5FD20A4C0CFC84669C26E33B572B6E5374D2A78FA8191A82857288AA` | `AF019CEDB840EAE9B5CFDE00073AF07EF00D1F058A690273F8F2996E233A40F2` |
| `am3d/ai/providers.py` | `C8E53A351326A0BFCB56E27C250E89C1EB13CB841679AA8F4240162F670C05D9` | `BF1ACC782ECADE0DE4D585A47E1E3FB73C04520E52B52118271E745270887BA4` |
| `am3d/ui/ai_settings.py` | `6A0F2ED266FA0ED19F0DB45D4E609C1EA56E1DC2F4E5755200837C5B70D9BA0B` | `571F9653583500D00516527CB2C8E5A4E5476F110DE6648182B1B6038AE4B076` |
| `am3d/ai/test_providers.py` | `7E67106E271A4208DAFBDBB4EFE0DD41BC139DB75B2ABC16B83D06E010332A08` | `973448B1173E4E6E9C7D06EC4301D1B04382B3E52D4B60D7696FF12180DDB146` |
| `am3d/ui/test_ai_workspace.py` | `E442AACB176908A58DE2F647696D9AD3407FE3E68B21D2B5BE568389278AC310` | `A230EEC3F6999423F670BD6F8FF7461A4921C61705F2B0F3440F684475CCD61E` |

`am3d/ai/test_credentials.py` was not edited and remained `331F62AD879E4DAFA33AF46BD1E1592EC4A85E001876978F5D3F0499F56F7FAE`.

## Independent extension verification

The independent focused reviewer completed the single requested verification round after this extension. The reviewed production and test source hashes matched the identities above; the reviewer did not edit source. In the isolated Windows interpreter with `QT_QPA_PLATFORM=offscreen`, the reviewer reran:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\windows\venv\Scripts\python.exe -m pytest am3d/ai/test_providers.py am3d/ai/test_credentials.py -q --maxfail=1 --tb=short
```

Result: **64 passed in 2.66s**.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\windows\venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py -k settings -q --maxfail=1 --tb=short
```

Result: **11 passed, 16 deselected in 1.20s**.

The reviewer also independently reran the preflight/native privacy selection:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\windows\venv\Scripts\python.exe -m pytest am3d/ai/test_checks.py::test_output_tree_byte_preflight_stops_native_loading am3d/ai/test_checks.py::test_native_failure_report_does_not_persist_untrusted_exception_text -q --maxfail=1 --tb=short
```

Result: **2 passed in 0.57s**. The focused review is complete; no additional independent round was requested.
