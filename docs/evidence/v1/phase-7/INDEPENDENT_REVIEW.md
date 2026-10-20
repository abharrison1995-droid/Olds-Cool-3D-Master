# Phase 7 independent preservation and refinement review

Date: 2026-10-13  
Repository: `C:\Users\Alex\Desktop\Olds-Cool-3D-Master`  
HEAD: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`  
Environment: Windows 10 IoT Enterprise LTSC build 19044 x64; Python 3.12.14; PySide6/Qt 6.11.2; `QT_QPA_PLATFORM=offscreen`.  
Requested reviewer settings: Luna/xhigh; recorded from task metadata, not independently introspected at runtime.

## Verdict

**Pass for the bounded local Phase 7 preservation/refinement review.** I found no reproduced preservation blocker. The independent history UI test and four measured refinement scenarios passed, and a long Unicode history-path probe passed through the store, native reopen, and Qt preview decode. This is not live-provider, native-display/GPU, frozen-package, or target-platform acceptance. The pre-existing Phase 6 close-cancel timeout remains an unexplained qualification limit; this review did not rerun that 58-test lifecycle suite or claim to diagnose it.

The checkout was already dirty with authorized V1 work. I changed no source, test, fixture, or product-document files; this review is the sole review-owned file. The master plan was concurrently updated elsewhere in the shared checkout during this review: its first observed SHA-256 was `ACC456207DDB4329B00045E633D8C1288EE0559262EC70E73B4A17618C3F97CA`, then I re-read the Phase 7/architecture passages at the final hash listed below. Those passages did not change.

## Evidence and checks

The exact Phase 7 implementation evidence at `docs/evidence/v1/phase-7/ui-history-evidence.md` identifies the five owned files listed below. Their hashes still match that evidence at the end of this review. The reported owner commands are useful context, not independent acceptance; I independently ran:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_history.py -q --maxfail=1 --tb=short
```

```text
.....                                                                    [100%]
5 passed in 20.86s
```

This exercises an actual offline source worker/orchestrator/check/store parent and child, immutable parent bytes, verified history and preview, guarded restore, manual-divergence choices, an unsaved Session action, restart reconstruction, failed/cancelled/interrupted rows, parent deletion confirmation without child cascade, stale selection, and history-worker deferred-close cancellation.

I separately ran the measured four-change geometry/material node once, without a retry:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ai/test_refinement.py::test_four_refinements_change_measured_reopened_native_geometry_and_material -q --maxfail=1 --tb=short
```

```text
.                                                                        [100%]
1 passed in 74.02s
```

The node measures flatter roof, longer arms, dark-green body material, and larger wheel radius after native reopen. It uses an offline fake provider.

For the Windows long-path concern, a disposable PowerShell here-string was piped to `.venv\Scripts\python.exe -`. It created a checked parent in a temporary store whose Unicode path produced a 286-character preview path, then called `GenerationRecordStore.get_record()` and `load_history_detail()`; the latter reopens the native project, recomputes its digest, and decodes the preview with `QImage`. The temporary directory was removed in `finally`. Result:

```json
{"root_chars": 221, "preview_path_chars": 286, "project_exists": true, "preview_decoded": true, "digest_present": true, "run_id_matches": true}
```

An initial version of that disposable probe reached the detail load but its final raw-Unicode print failed under the shell's cp1252 output encoding. The completed probe used UTF-8 output and ASCII-escaped JSON; no application source changed between the probe attempts.

## Preservation findings

**Store-authoritative refinement:** `AIController.start_generation()` accepts refinement only when the requested UUID is the currently selected, previously verified complete history record (`am3d/ui/ai_controller.py:327-362`). `GenerationOrchestrator` reloads the parent through `store.get_record()` and takes the accepted brief/recipe from that record (`am3d/ai/orchestrator.py:513`, `:984-1009`, with refinement selection at `:211-232`). The history detail worker independently verifies the completed check report and artifact manifest, reopens `project.am3d`, and requires its run ID, parent ID, and embedded recipe to match the record before making the row actionable (`am3d/ui/ai_history.py:53-78`). The actual worker test observed a new child UUID and unchanged parent project bytes/hash. Current Session data is not an input to the refinement request or a merge source.

**Manual divergence:** the guard compares the verified parent's reopened native-content digest with `project_content_digest(project, actions=self.session.actions)` (`am3d/ui/app.py:822-855`). It restores the provenance envelope after digest serialization, so the comparison and Cancel choice leave it unchanged. The test set the current envelope's `diverged` flag to false while retaining an unsaved Session action; the digest still differed from the saved parent's digest and the three user choices behaved as stated. The serializer's digest input includes authored objects/transforms/splines/patches/hooks, rigs, materials, actions and session animation state while excluding the provenance envelope and transient view state (`am3d/core/serializer.py:182-188`, `:525-624`, `:804-807`). The action mismatch is reproduced in the UI test; the other authored categories were source-inspected rather than individually mutated in this review.

**Save, restore, undo, and lifecycle:** Save Manual Copy delegates to the ordinary `DocumentController.do_save_as()` path; it does not swap Session or clear the undo stack. Refine Original leaves the edited Session in place. Cancel in the divergence dialog preserves Session identity, project identity, dirty state, undo count, and provenance in the executed test. A dirty-document adoption Cancel also preserves the live Session/project, dirty state, undo count, and parent snapshot bytes. Restores are copied to `working-projects` by the checked-copy path and are then opened only through the existing dirty guard; normal Save therefore addresses the writable copy, not the history snapshot. Restart/history reconstruction, parent-only deletion, failed-child retry with new run IDs, and stale/deferred history results passed in the focused history test.

The Phase 6 independent report records a successful missing-sidecar/manual-open test and prior guarded document lifecycle coverage; I read that evidence but did not rerun that separate test in this bounded Phase 7 pass.

**Long paths and displayed text:** `GenerationRecordStore` normalizes host-I/O roots through `extended_io_path()` (`am3d/core/paths.py:32-52`), and the 286-character Unicode store/detail probe passed with a valid preview. User/model-derived text in the AI workspace is passed through `QPlainTextEdit.setPlainText()` or labels/dialogs configured with `Qt.PlainText` (`am3d/ui/ai_workspace.py:143-157`, `:241`, `:298`, `:584-606`, `:825`; history details use `setPlainText()` at `:520-541`). The history list uses ordinary `QListWidgetItem` text. I found no rich-text interpretation path for model text in the reviewed history UI.

## Reproduced defects

None in the bounded local Phase 7 scope.

## Source-reasoned risks and suggestions

- **Known local-tamper limit; not a normal Save/restore defect.** `record.json` is excluded from its own artifact manifest (`am3d/ai/records.py:279-280`), and `get_record()` compares files against the manifest stored in that same sidecar (`:602-616`). This detects ordinary artifact corruption, but a same-account actor able to rewrite both the record/manifest and artifacts can construct a self-consistent replacement. The application does not write successful snapshots during Save/Save As, and restore always copies them first. This is not cryptographic immutability; it matches the master plan's explicit same-account rewrite limitation (Phase 8 status at `docs/V1_MASTER_IMPLEMENTATION_PLAN.md:346`).
- **Low-priority cleanup suggestion.** If the user cancels the normal dirty-document guard after a restore copy is ready, `_adopt_ai_project()` returns without removing that unused copy (`am3d/ui/app.py:802-806`). The current document and immutable generation remain intact, so this is not a preservation failure; repeated cancelled restores can leave extra disk files in `working-projects`.
- **False-positive concern resolved.** A `generation.diverged == false` field is not trusted as proof that current work matches the parent. The UI recomputes the authored digest and supplies `Session.actions`; the explicit unsaved-action/forged-flag test observed a mismatch while preserving the flag and session state on Cancel.

## Remaining qualification limits

`docs/evidence/v1/REGRESSION_FOLLOWUP.md` and the Phase 6 review record an initial 58-test close-cancel wait timeout with unknown cause, followed by an isolated pass and full rerun pass. The Phase 7 owner reports a current-tree 58-test pass, but it was not independently rerun here. My history close-cancel test passed; it covers a history worker and does not explain the earlier generation-close timeout. Preserve that first failure as an unresolved qualification note.

No live provider/key/network call, native display/DPI/GPU test, frozen executable, Windows 11, Linux Mint, model spend, commit, or push was performed. These gates remain open.

## Inspected identities

Repository HEAD was unchanged at `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`.

| File | SHA-256 |
|---|---|
| `docs/V1_MASTER_IMPLEMENTATION_PLAN.md` (re-read Phase 7 passages at end) | `9490C687C240598317D7DB74048961772E60034F6B8EBADDE2565E2100EF16B1` |
| `work/v1/phase7-task.md` | `F6013D4A7A34C97B1FA1F055C85A036AE22BA772AF767E4082218BF936D470F1` |
| `docs/evidence/v1/REGRESSION_FOLLOWUP.md` | `74EBF99B6173B2029591511DC080F6E930CB23E6D0BEB17DD4338B50C60D2324` |
| `docs/evidence/v1/phase-6/INDEPENDENT_REVIEW.md` | `3295723AC7E1967C01546249AABA1229CE0E3A2683DA93B07111EF985B0AB79D` |
| `docs/evidence/v1/phase-7/ui-history-evidence.md` | `EE94B708DC60C395B7D13FCF167C6F5A15901D884CCC29BBF375DA56B95B6FCA` |
| `am3d/ui/ai_history.py` | `E8F2193669EA72538297F9C3DE53B1A77E783774130DB2ADF682743B11E49275` |
| `am3d/ui/ai_controller.py` | `082408A848F239A604EC41D57B106D9B8FF9CA594D023F56EFD45F10FC7AC4FB` |
| `am3d/ui/ai_workspace.py` | `642C1C1D9D24B18D8E73FA80C01689ACBD886C01FDBF898A3DAEAA4614FDA24F` |
| `am3d/ui/app.py` | `0F0997543ED4EBAEA78586478277704025F357A14C186704D53595BC18CAA0D1` |
| `am3d/ui/test_ai_history.py` | `5EA33D68BB8922B71D61A04A2471FBEEF4B199476B0CBD05E0128615825EFFB9` |
| `am3d/ai/records.py` | `D11EB513B64A8C5A92F5271DC184BE919DDAB50390787336B2F5D085472ED2AE` |
| `am3d/ai/orchestrator.py` | `162C043DC2FC710AE5F7EAB75088336E82415E692F0D46EF487D53699C5623D0` |
| `am3d/core/serializer.py` | `C456F200B5681D807EC6D5FB81EBE7FF6B5D04910F90821642C0AD46BA143AB3` |
| `am3d/core/paths.py` | `C7287FC36C03A25D58E53640B0DE71D1443511E9D05D7F8F581974CAD4295F9D` |
| `am3d/ui/document_controller.py` | `0F60FCDEC2EB1550227AD3024D016CFB20A3E0AD5BB934CB8BC3BF6F7CE25094` |
| `am3d/ai/test_refinement.py` | `01EA4ADE8B5B613DE4D183E3710282D9A0C13165F77D94827E7D933580138AC5` |
