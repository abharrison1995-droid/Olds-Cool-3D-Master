# Phase 11 — bounded encoded-credential guard

Status: **source fix and focused offline checks complete; independent fix verification pending.**

Baseline checkout: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`. The initial architecture finding is recorded in [`ARCHITECTURE_REVIEW.md`](ARCHITECTURE_REVIEW.md). No provider network, OS credential backend, actual credential, application package, lock capture, or release action was used for this fix.

## Change

The provider and settings flow now share a Qt-free percent-decoding guard in `am3d/ai/credentials.py`. Existing literal comparisons remain. The helper checks the original text and up to four standard `urllib.parse.unquote` rounds, which covers mixed literal and `%HH` bytes, either hex case, UTF-8 percent bytes for the provider's supported ASCII credentials, and up to four nested percent-encoding layers. Endpoint validation rejects a path longer than 16,384 characters at any decoded layer, or one that still contains a valid `%HH` escape after the fourth round. These bounds prevent recursive decoding and unbounded intermediate allocation; rejection uses the existing fixed endpoint configuration error.

`OpenAICompatibleProvider.generate` applies the shared comparison to the parsed endpoint path before constructing or sending the request. `AISettingsDialog._secret_leaks` applies the same comparison to HTTP(S) preference URLs and the pending endpoint while checking both the entered key and the current stored key. Thus failed saves leave QSettings and the credential store unchanged during rotation. Host allowlisting, HTTPS, model choice, default endpoint, key storage selection, and the settings layout are unchanged.

The guard covers standard percent decoding only. It does not claim protection against arbitrary nonstandard server/intermediary transformations, alternate encodings, compromised application code, or a same-account actor rewriting the application and preferences. Encoding deeper than the fixed bound is rejected whenever a valid percent escape remains after round four.

## Reproduction and diagnosis

Before the fix, the independent reviewer used an in-memory `SessionCredentialStore` and `httpx.MockTransport` with a fake credential. An allowlisted endpoint containing that key bytewise percent-encoded reached the mock request target; the raw key was absent from the target, but its encoded form was present. The settings literal scan returned false. The reviewer’s safe summary was:

```json
{"authorization_header_present":true,"encoded_secret_in_request_target":true,"hostname_allowlisted":true,"mock_request_completed":true,"raw_secret_in_request_target":false,"settings_literal_secret_scan_would_detect":false}
```

After the fix, focused tests reject literal, mixed, upper/lower hex, double-encoded, and four-round encodings before transport. A fifth nested layer is rejected during endpoint validation. A normal API endpoint and a common escaped path without a credential remain usable. Settings tests cover an entered key, the old key during rotation, and the new key during rotation; each rejection occurs before preference or credential mutation. Error checks inspect only sanitized diagnostics and do not print credential text.

The earlier Phase 10 bootstrap failure is separate from this privacy fix. Its exact first failure remains in [`bootstrap-build.log`](../phase-10/bootstrap-build.log), SHA-256 `db67006d79221da3308f6e8a777ada3175171fb74059b7f40d12bedff8bf9b20`: after 27 passes in 96.01 seconds, `test_native_failure_report_does_not_persist_untrusted_exception_text` failed at `am3d/ai/test_checks.py:554` with `KeyError: 'reason'` while indexing `checks[0]`. The diagnosis was a stale test selection: `output_tree_preflight` had become the first check. The root-owned test-only correction was separate; this fix did not change `test_checks.py` or runtime checking. No PyInstaller/archive or lock-capture stage was reached in that bootstrap.

## Verification

Windows isolated interpreter, with `QT_QPA_PLATFORM=offscreen`:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\windows\venv\Scripts\python.exe -m pytest am3d/ai/test_providers.py am3d/ai/test_credentials.py -q --maxfail=1 --tb=short
```

Result: **55 passed in 3.09s**.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
& .\build\windows\venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py -k settings -q --maxfail=1 --tb=short
```

Result: **7 passed, 16 deselected in 0.91s**. The UI module's autouse fixture uses temporary INI preferences and restores the prior QSettings format and user/system paths. All credential cases use in-memory or fake stores. No full application suite or build was run.

## File identity

These SHA-256 values identify the owned files immediately before and after this bounded edit. The worktree already contained other V1 changes; these are file identities, not a source-freeze manifest.

| File | Before | After |
|---|---|---|
| `am3d/ai/credentials.py` | `BCAEE82E8DB9F0BBCF6D01455477572C50CD890195E41BADF5E5F9300D5D2141` | `C08FD39C5FD20A4C0CFC84669C26E33B572B6E5374D2A78FA8191A82857288AA` |
| `am3d/ai/providers.py` | `BD883900F4B33B054E289F95723B330ED658BFBD21CC3DFF598C978340243439` | `C8E53A351326A0BFCB56E27C250E89C1EB13CB841679AA8F4240162F670C05D9` |
| `am3d/ui/ai_settings.py` | `41B1B9F7CFDBF299AE6FD999F9DFC7A23D238A8BE04D20918339B089FD350AEA` | `6A0F2ED266FA0ED19F0DB45D4E609C1EA56E1DC2F4E5755200837C5B70D9BA0B` |
| `am3d/ai/test_providers.py` | `663E322DFFAE665AA8A489562D905DAB0A8FCD7AA1B59D24AFEF090010649AC0` | `7E67106E271A4208DAFBDBB4EFE0DD41BC139DB75B2ABC16B83D06E010332A08` |
| `am3d/ui/test_ai_workspace.py` | `18376373AE5455B76218D2EFF5EBF1C61F45887BA0C833A9177D0962FF91E6DC` | `E442AACB176908A58DE2F647696D9AD3407FE3E68B21D2B5BE568389278AC310` |

`am3d/ai/test_credentials.py` was not edited; its SHA-256 remained `331F62AD879E4DAFA33AF46BD1E1592EC4A85E001876978F5D3F0499F56F7FAE`.
