# Phase 7 bounded history and refinement UI evidence

Date: 2026-10-13  
Repository HEAD: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`  
Mode: owner implementation evidence; this is not an independent review or a Phase 7 acceptance decision.  
Requested model/settings: Luna/xhigh, accepted as requested metadata; runtime model and reasoning effort were not independently introspected.  
Platform: Windows 10 IoT Enterprise LTSC, build 19044, x64; Python 3.12.14; PySide6/Qt 6.11.2; `QT_QPA_PLATFORM=offscreen`.

## Scope and implementation

The work adds a local history list with explicit refresh, fixed terminal statuses, timestamps and brief summaries. Selecting a successful row loads its immutable record, verifies the full artifact manifest, reopens the native project, recomputes its authored-content digest, and decodes the checked preview in the controller-owned background worker. The UI displays parent/child references, limitations, checked files, and a deterministic recipe change summary. Failed, cancelled, and interrupted attempts remain visible and can be deleted only after the user confirms.

Refinement accepts only a selected history record that passed the detail verification. It starts a new UUID run with the verified parent ID and an explicit bounded request; the orchestrator reloads the saved parent and supplies its accepted recipe. No current project data is sent or merged. Refinement retry keeps the selected original parent and instruction while creating another run ID. Manual divergence compares the current authored Session digest (including `Session.actions`) against the digest recomputed from the verified parent native file. The comparison restores the serializer-mutated provenance dictionary before returning, so Cancel leaves project metadata unchanged. Save manual copy uses the existing `DocumentController.do_save_as()` path. Restore creates a separate writable working copy in the background and reaches the existing `maybe_abandon_document()` / `do_open()` adoption path.

History, verification, preview decoding, deletion and restore-copy work share the controller's single owned Qt worker slot. Request UUIDs and history selection tokens gate late results. Close requests wait for the owned worker and defer its terminal history state until the close decision is final. No `DocumentController`, AI transport/worker/orchestrator, record-store, recipe, renderer, benchmark, packaging, or global product-document source was changed. The existing missing-sidecar manual `File > Open` behavior remains covered by Phase 6's `test_missing_history_sidecar_keeps_copy_integrity_and_manual_open_message`.

## Verification

Compilation command:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m py_compile am3d\ui\ai_history.py am3d\ui\ai_controller.py am3d\ui\ai_workspace.py am3d\ui\app.py am3d\ui\test_ai_history.py
```

Result: exit code 0; no diagnostics.

Phase 7 UI/history command:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_history.py -q --tb=short
```

```text
.....                                                                    [100%]
5 passed in 23.68s
```

The offline UI fixture runs the actual source orchestrator, worker, checker and store for a parent and successful child; verifies the checked preview/manifest; checks the parent's project bytes remain unchanged; restores the parent through the guarded writable-copy path; checks exact Session/undo preservation on adoption cancel; and exercises Cancel, Refine original, and Save manual copy choices with an unsaved action whose `Session.actions` is not synchronized into `Project.actions`. The same module covers delete-parent confirmation with no child cascade, fresh-controller restart reconstruction of parent/child plus failed/cancelled/interrupted records, stale history selection, deferred-close cancellation, and retry UUID/parent preservation.

The four existing measured offline refinement fixtures were also rerun with the UI history tests:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ai/test_refinement.py::test_four_refinements_change_measured_reopened_native_geometry_and_material am3d/ui/test_ai_history.py -q --tb=short
```

```text
......                                                                   [100%]
6 passed in 83.15s (0:01:23)
```

That source-pipeline fixture measures flatter roof, longer arms, dark-green body material, and larger wheel radius after native reopen. The fake provider is offline; these results do not represent live-provider qualification.

The Phase 6 lifecycle/Home/document suite was rerun against this dirty checkout after the UI/controller changes:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py am3d/ui/test_home.py am3d/ui/test_document_controller.py -q --tb=long
```

```text
..........................................................               [100%]
58 passed in 32.83s
```

The Phase 6 historical close/cancel evidence remains unchanged. Its first full 58-test run had one 8-second close-cancel wait timeout of unknown cause; the isolated case and immediate full rerun passed, with the full rerun at 52.00 seconds. This current-tree pass is additional evidence and does not explain or erase that recorded qualification limit. Final stable-build suite remains pending.

## Identity and limits

Baseline HEAD remained `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`. This checkout already had the authorized, uncommitted Phase 6/V1 files. In particular, `am3d/ui/app.py` already contained the Phase 6 UI integration before the Phase 7 refinement hookup; the dirty tree was preserved.

Owned-file SHA-256 at this evidence revision:

| File | SHA-256 |
|---|---|
| `am3d/ui/ai_history.py` | `E8F2193669EA72538297F9C3DE53B1A77E783774130DB2ADF682743B11E49275` |
| `am3d/ui/ai_controller.py` | `082408A848F239A604EC41D57B106D9B8FF9CA594D023F56EFD45F10FC7AC4FB` |
| `am3d/ui/ai_workspace.py` | `642C1C1D9D24B18D8E73FA80C01689ACBD886C01FDBF898A3DAEAA4614FDA24F` |
| `am3d/ui/app.py` | `0F0997543ED4EBAEA78586478277704025F357A14C186704D53595BC18CAA0D1` |
| `am3d/ui/test_ai_history.py` | `5EA33D68BB8922B71D61A04A2471FBEEF4B199476B0CBD05E0128615825EFFB9` |

Fixture identity is the listed pytest node ID; runtime generation UUIDs are intentionally newly generated on every run and are not fixed acceptance data. No live request, credential lookup for a provider call, model spend, commit, push, release, native-display/DPI/GPU test, frozen-package test, or target-platform qualification occurred. Independent preservation/refinement review and final stable-build qualification remain pending.
