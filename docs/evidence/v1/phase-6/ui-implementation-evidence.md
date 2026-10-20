# Phase 6 desktop UI implementation evidence

Status: implementation evidence for the bounded desktop UI slice. The Phase 6 gate remains open pending independent review, profile-surface editing correction, and live/native/frozen checks.

## Baseline and environment

- Baseline HEAD: 3f6f7f03d32b4d1a3af06af4fdc0724bf0436945. HEAD remains at that commit; this work is uncommitted alongside previously authorized V1 edits.
- Host from task brief: Windows 10 IoT LTSC, build 19044, x64. Observed runtime: Windows-10-10.0.19044-SP0; Python 3.12.14 x64; PySide6 6.11.2; Qt 6.11.2.
- Qt tests used QT_QPA_PLATFORM=offscreen. This provides no physical display, DPI/scaling, GPU, Windows 11, or frozen executable qualification.
- Requested model configuration was GPT-6 Luna/xhigh per the task brief and accepted as requested; it was not independently introspected.

## Owned source snapshot

These SHA-256 values identify the seven Phase 6 UI files owned here. Other uncommitted repository files are shared V1 work and outside this snapshot.

| File | SHA-256 |
|---|---|
| am3d/ui/ai_controller.py | AFC2B2B64500222844C9E619CB527D0B30D406137DE0C3E0138B35F620617D33 |
| am3d/ui/ai_workspace.py | 5065A3005C03DD0ECAE2A8D85512BB1C0F9A5BF81805B03DE71D8951CF2D546B |
| am3d/ui/ai_settings.py | D909D131A857AB4AC0D22DE2F40D10E4EF9697EFD6F372EF58EA7D09BDFE4A5B |
| am3d/ui/test_ai_workspace.py | B1FE610D1F52EC6BD946502AF6D7F4972975701768C5EA5FB8FC89AE88113535 |
| am3d/ui/app.py | 81754CA352821BD45A82EBB2D87797E980302C213C62C55A5FFE5E5568792505 |
| am3d/ui/home.py | D3C89D1B08F1FFCE26A459539CFEBEC393280ADAAE8DE7E3AC5A09FEBCCB9F21 |
| am3d/ui/test_home.py | F1FADA2D5B1ED62E2E54C5C8A26D3F64A6262D758381EB60E043F14BBA6D0CE6 |

## Implementation

Home presents Create with AI as the primary focused action while preserving New, Open, editor, and CLI routes. The scrollable workspace collects a brief and explicit request confirmation, shows stage/attempt/elapsed status, checked preview and reports, limitations, and guarded editor handoff. Tab leaves natural-language entry for the actions. Model-derived text is plain text.

Provider settings require an explicit model and constrain the endpoint to HTTPS on api.openai.com. Startup does not inspect a credential backend. Keys use either system credential storage or explicitly selected session-only memory. Both newly entered and existing key values are checked against endpoint/model and saved preference fields before any key or settings persistence, including rotation. Focused tests redirect and restore both QSettings scopes/default format and verify the original INI filenames.

Owned QThreads run generation and the verified writable-copy operation. The UI allows one active job, filters stale run UUIDs and non-increasing event sequences, preserves Cancelling until terminal acknowledgement, and gives each retry a new UUID and transmission preflight. Copy cancellation/close waits for its worker and suppresses late adoption. Actual adoption runs the existing dirty-document guard on the GUI thread, then opens the writable copy and resets/refreshes editor state. Copy requires get_record verification; a missing history sidecar explains that manual File > Open remains available.

## Test evidence

Final focused UI, Home, and document-controller command:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py am3d/ui/test_home.py am3d/ui/test_document_controller.py -q --tb=short
```

```text
54 passed in 24.84s
```

The 54 checks cover offline startup without credential lookup, session-only key handling and cross-field sentinels, stale IDs/sequences, cancellation and retry preflight, safe worker exceptions and explicit-revision states, copy cancellation/close, missing-sidecar integrity, copied project resources, dirty-guard cancellation, failed-open preservation of the current Session/undo stack, and deferred close.

Actual source-pipeline manual-edit round trip, run separately to record its host UUID:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py::test_real_worker_checked_generation_adoption_and_manual_edit_round_trip -q -s --tb=short
```

```text
offline fixture generation id: 8ea57f73-12ab-40bb-b187-56e1ca827662
1 passed in 16.80s
```

The fixture sends a synthetic recipe through the actual source worker, deterministic checker, and record store using an in-process fake provider; creates a verified writable copy; edits a guide spline control point, the generated object's transform, and material; checks exact undo/redo; then saves, reopens, checks provenance divergence, and verifies the immutable artifact hash did not change. The guide-spline CP edit does not reshape the generated rendered surface. Existing recipe execution drops lathe/extrude source-generator metadata, so this fixture does not claim generated-surface CP editing. The read-only probe receipt is retained at docs/evidence/v1/phase-6/profile-gap-before.json; the parent task owns that correction.

Source smoke coverage also passed in this run:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py am3d/ui/test_home.py am3d/ui/test_document_controller.py am3d/ui/test_smoke.py -q --tb=short
```

```text
54 passed in 221.22s (0:03:41)
```

That smoke run preceded later test-only additions to test_ai_workspace.py; product implementation files did not change afterward. The final focused 54-test suite includes those additional cases.

No live provider, API key, telemetry, or network call was used. No personal prompt was used; the actual pipeline fixture uses a synthetic brief.

Additional static checks exited successfully with no stdout:

```powershell
git diff --check -- am3d/ui/app.py am3d/ui/home.py am3d/ui/test_home.py
.venv\Scripts\python.exe -m py_compile am3d/ui/ai_controller.py am3d/ui/ai_workspace.py am3d/ui/ai_settings.py am3d/ui/test_ai_workspace.py am3d/ui/app.py am3d/ui/home.py am3d/ui/test_home.py
```

## Remaining gates

- Independent Qt lifecycle/user-journey review is pending.
- Generated-profile rendered-surface CP correction and regression test remain pending in the parent task; the guide-spline check above does not satisfy that geometry gap.
- A configured live provider run was not supplied or attempted.
- Native display, keyboard flow at target logical sizes, scaling, GPU/software comparison, credential-backend availability, and frozen package qualification remain untested here.
- No Phase 6 acceptance or release gate is claimed passed.
