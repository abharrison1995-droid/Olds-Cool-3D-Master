# Phase 4 independent integrity review

Date: 2026-10-13  
Baseline: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`  
Scope: approved plan sections 4–10, Phase 4, and review policy 12; principally `am3d/ai/checks.py`, `am3d/ai/records.py`, `am3d/core/project.py`, `am3d/core/serializer.py`, and `am3d/renderer/sprite.py`, with focused tests and the Phase 3 worker boundary.  
Working tree: shared, uncommitted. This review changed no source or test files; it writes only this report.

## Verdict

**Phase 4 local integrity gate: blocked.** Four focused reproductions show that a run can be published with bytes different from the checked bytes, an OBJ can pass while depending on an MTL outside its run directory, an OBJ export can pass with the wrong material assignment, and animation can pass when the requested component has no action assignment. These findings are limited to the local integrity gate; they do not assess artistic quality or release qualification.

## Reproduced defects

### High — Publication can promote bytes that differ from the checked manifest

In `am3d/ai/records.py:331–340`, publication compares candidate files with the checker’s hashes. It then rebuilds the manifest at lines 356–359 but compares only path sets. The record is written from this new manifest at lines 381–390, so the subsequent integrity check proves only that the new record matches the new bytes.

Reproduction: prepare a normal record candidate and passing check report; after the initial claimed-hash loop, change `preview.png` while allowing `_artifact_manifest` to run. `publish()` returned a completed directory. The committed `preview.png` hash differed from the checker report’s hash, while `get_record()` accepted the completed record. The same repro reported `publish_succeeded=true`, `claimed_hash_matches_committed=false`, `embedded_check_report_matches_committed=false`, and `get_record_accepts_committed_record=true`.

This defeats the completion guarantee: the immutable generation can contain an artifact the checker never approved. Rehash and compare exact `(path, bytes, sha256)` entries against the checker manifest before recording completion, and ensure the final staging snapshot cannot change between that comparison and promotion.

### Medium — OBJ validation follows `mtllib` outside the candidate and omits it from the manifest

`am3d/ai/checks.py:533–546` confines the OBJ path, then passes the file to `validate_obj`. In `am3d/export/validate.py:226–227, 301–309`, the parser reads the OBJ’s `mtllib` token, joins it to the OBJ directory without a containment check, and opens the result.

Reproduction: execute the normal box recipe exporting `mesh.obj`; copy its valid `mesh.mtl` beside the candidate directory, change the OBJ’s `mtllib` to that absolute path, and remove the in-directory MTL. `check_artifacts()` returned `ok=true`; `requested_exports` passed; the manifest contained `mesh.obj`, `preview.png`, and `project.am3d` but no MTL. Thus the published OBJ can depend on a file outside the run and that dependency is neither confined nor included in its manifest.

The same parser’s malformed-MTL path returns exception text containing the referenced MTL path (`validate.py:306–313`), and `_verify_exports` copies that text into report issues. A direct `_verify_exports` reproduction with an invalid-UTF-8 external MTL included both its outside filename and decoder exception text in the report. The checker should reject nonportable or escaping MTL and texture references before opening them, and keep report errors free of raw paths and exception text.

### Medium — OBJ material checks do not compare exported assignments with required intent

The native project’s material intent is checked separately, but the export path at `am3d/ai/checks.py:541–555` verifies only that the OBJ/GLB parses and that referenced material entries or indices exist. It never compares exported face or primitive assignments to the caller-authored required material/component mapping.

Reproduction: generate the normal blue-body OBJ, change its `usemtl mat_body` to `usemtl wrong_material`, and add a valid red `wrong_material` entry to the MTL. With the original native project and a blue material requirement, `check_artifacts()` still returned `ok=true`; both `requested_exports` and `material_assignments_and_color` passed. The output manifest included the changed OBJ and MTL. This leaves the independently checked export free to contradict the accepted material requirement.

### Medium — Animation assignment is checked on any one rig, not the intended part

At `am3d/ai/checks.py:918–925`, `assigned_ok` checks the first skeleton with any action assignment, while deformation is measured for `intended` components. It does not require the requested action to be assigned to each intended component. The scene evaluator also reuses a sole sampled rig pose for other rigs (`am3d/core/scene.py:140–141`), so a second rig with matching bone names can appear to move despite having no assignment of its own.

Reproduction: create two box rigs with a shared `root` bone, assign the `wave` action only to `driver`, and set `target` as the sole `must_deform_components` requirement. The report returned `ok=true` and `animation_and_deformation=passed` with `assignments={"driver":"wave"}` and target displacement `0.798525`, above the reported `0.004243` threshold. The check therefore does not enforce the plan’s requested-action assignment for the intended component.

## Source-reasoned risk

### Publication hashing/staging does not poll cancellation or deadline

`GenerationAttempt.publish()` accepts a cancellation token and deadline but does not inspect either during claimed-file hashing, tree rehashing, sidecar staging, or verification (`records.py:331–405`). The only cancellation/deadline check is `CancellationToken.commit()` at the final rename (`contracts.py:300–325`).

A bounded fixture reproduction cancelled while `_sha256` was delayed: publication continued through all 14 hash calls, then returned `GenerationCancelledError` after 0.828 seconds and did not commit. This preserves the no-late-success property, but a slow disk or the allowed 256 MiB output can keep publication work running after cancellation or beyond the shared deadline. The reproduction did not exceed the three-second acknowledgement target; this is a source-reasoned responsiveness/deadline risk, not a measured threshold breach.

## Verified behavior and evidence limits

- Native format 2 has an optional generation envelope capped at 1 MiB, recursive JSON-value limits, canonical run IDs, recipe SHA-256 validation, selected sensitive-key rejection, portable artifact-reference validation, and project-content divergence tracking. The semantic digest excludes view/transient state and includes authored content. New-reader roundtrip, format 1/2 without provenance, Save As divergence, and provenance preservation tests passed. The old-writer downgrade test emulates the explicit root-field set; the baseline serializer confirms its writer constructs that root body explicitly and returns it without unknown fields.
- Record creation uses same-volume directory promotion. Recovery treats a verified promoted record as authoritative after a failed journal update. `get_record()` verifies the full artifact manifest; working-copy creation rechecks the source and copied native project/resources; parent deletion reports children and requires explicit confirmation. The associated focused tests passed, subject to the publication hash mismatch above.
- The preview uses one camera and shared depth buffer for flat material colors. The two-material occlusion fixture passed. Texture and procedural-pattern fidelity is clearly reported as a preview limitation.
- The native-roundtrip failure boundary suppresses unchecked exception details, and its existing sentinel test passed. That result does not cover export-parser errors; the external-MTL reproduction above shows those can include a referenced path and decoder exception text.
- The fixed checker runs in the Phase 3 worker child. Current Phase 3 source hashes match its recorded identity; its evidence reports five successful worker → checker → immutable-publish integrations. The worker is explicitly a fixed-code lifecycle/resource boundary for data-only recipes, not an OS sandbox or compromised-code containment claim. Two Windows symlink tests were skipped because this account lacked symlink privilege; the Windows junction rejection test passed.
- All 15 source/evidence hashes in the Phase 4 hash file match current files. The Phase 3 identity hashes also match current listed files.
- Independently rerun focused command:

  ```powershell
  .venv\Scripts\python.exe -m pytest am3d/core/test_generation_provenance.py am3d/ai/test_records.py am3d/ai/test_checks.py am3d/renderer/test_color_scene_preview.py -q -k "roundtrip or downgrade or sensitive or invalid_envelope or divergence or digest or publication_requires_exact or atomic_promotion or expired_deadline or rebuilds_record or native_failure_report or missing_requested_export or basic_bound_rig or material_preview"
  ```

  Result: **16 passed, 9 deselected in 23.30s**. The separate modified-output reproductions above were run as inline PowerShell here-string Python harnesses; no test or source file was added.
- Phase 4 evidence records 127 focused tests passing in 95.96s, and an earlier broader AI run of 166 passed / 2 skipped. These are recorded results, not reruns in this review. No live-provider prompt run, frozen Windows 11 or Mint qualification, native desktop acceptance, or physical GPU check is claimed. The workstation evidence is Windows 10 IoT LTSC 19044 x64.
- The review request recorded `gpt-6-luna` at `xhigh` as the requested configuration and says the tool accepted it; runtime model/reasoning effort cannot be independently introspected here, so this report treats it as requested configuration only.

No fixes were applied by the reviewer. After the owner addresses the reproduced defects, the review policy calls for one focused verification round; this report is the independent review round.

## Focused verification after source fixes

Date: 2026-10-13. This is the single focused follow-up to the initial independent review. The original blocked verdict above describes the pre-fix source. This addendum records the final local dispositions; it does not claim live-provider, artistic, frozen-build, platform, native-GUI, or GPU acceptance.

### Disposition

The four reproduced defects from the initial review are fixed in the reviewed source and their targeted regressions pass: publication preserves the exact checker-approved artifact tuples through a private staging snapshot and atomic promotion; strict checker-mode OBJ validation confines and budgets OBJ/MTL/texture dependencies before reading text sidecars and returns root-relative dependencies; requested OBJ/GLB materials are compared with the freshly reopened native component assignments and colors; and each intended deforming part needs its own requested action or an explicit matching shared skeleton. Publication polls cancellation/deadline through tree walks, hash chunks, copies, and staging checks before its atomic commit point.

The additional GLB diagnostic sentinel defect found during this follow-up is also fixed. `_safe_export_parser_issues()` reduces parser text to fixed issue categories and counts before it reaches the checker report (`am3d/ai/checks.py:743–771`). A valid requested GLB still passes; a parseable GLB with the injected mesh-name sentinel and missing POSITION fails without echoing that string (`test_checks.py:247–289`).

The embedded-image boundary is now checked independently: only embedded `image/png` images are accepted; each buffer view must fit the declared single BIN buffer and actual GLB bytes; Pillow verifies PNG CRC and decodes pixels; width/height are bounded before pixel allocation; aggregate image count, encoded bytes, and pixels use existing limits (`MAX_OBJECTS=128`, `MAX_OUTPUT_BYTES=256 MiB`, `MAX_ATLAS_PIXELS=64,000,000`; per-side dimension 8,192). See `am3d/ai/checks.py:41–43,578–692`. Regression coverage accepts a valid baked-texture GLB and rejects wrong MIME, corrupted PNG bytes, and an oversized IHDR before decode (`test_checks.py:312–351`).

The OBJ strict parser now stats the OBJ before parsing and preflights the combined OBJ/MTL size before reading any MTL (`am3d/export/validate.py:308–368, 396–408`). The checker also preflights the full output tree before loading native or exported files (`am3d/ai/checks.py:197–219, 944–959`); the worker’s independent final output audit returns terminal `resource_limit` when the total exceeds 256 MiB (`am3d/ai/worker.py:853`). The legacy public `validate_obj(path)` default remains covered by its existing clean/missing-sidecar/reference tests.

### Focused commands and results

The first focused regression command exercised the exact checked-byte and staged-snapshot mutation races, commit/cancel/deadline handling, per-chunk cancellation, OBJ/GLB material corruption, GLB texture references, two-rig assignment, legacy OBJ defaults, and strict external MTL/texture references:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ai/test_records.py::test_publication_requires_exact_checked_manifest_and_keeps_prior_success am3d/ai/test_records.py::test_atomic_promotion_linearizes_cancel_and_postcommit_journal_failure am3d/ai/test_records.py::test_expired_deadline_fails_before_promotion_and_history_delete_warns_for_children am3d/ai/test_records.py::test_publication_rejects_artifact_changed_after_checker_hash am3d/ai/test_records.py::test_publication_rechecks_private_snapshot_before_atomic_promotion am3d/ai/test_records.py::test_cancellation_is_polled_between_artifact_hash_chunks am3d/ai/test_checks.py::test_requested_obj_material_must_match_reopened_native_material am3d/ai/test_checks.py::test_requested_glb_material_must_match_reopened_native_material am3d/ai/test_checks.py::test_glb_checker_rejects_external_or_out_of_range_texture_references am3d/ai/test_checks.py::test_action_must_be_assigned_per_intended_geometry_or_explicit_shared_rig am3d/export/test_validate.py::test_validate_obj_accepts_a_clean_export am3d/export/test_validate.py::test_validate_obj_flags_missing_mtl_sidecar am3d/export/test_validate.py::test_validate_obj_flags_usemtl_with_no_matching_newmtl am3d/export/test_validate.py::test_strict_obj_rejects_external_mtl_before_opening_it am3d/export/test_validate.py::test_strict_obj_rejects_external_texture_and_collects_safe_dependencies -q
```

Result: **15 passed in 77.72s**. This run preceded the final diagnostic, image-decode, and pre-read budget additions below; the records and animation sources it exercised were unchanged afterward.

After those final additions, the bounded final command covered the new whole-tree/export preflights and pre-read OBJ size guards, embedded PNG validity/MIME/dimension bounds, the malformed-GLB sentinel, external/out-of-range GLB and OBJ resource references, and OBJ/GLB material mismatch:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ai/test_checks.py::test_output_tree_byte_preflight_stops_native_loading am3d/ai/test_checks.py::test_export_preflight_stops_glb_parser_reads am3d/export/test_validate.py::test_strict_obj_stat_bounds_main_input_before_parsing am3d/export/test_validate.py::test_strict_obj_bounds_aggregate_sidecars_before_reading_any_mtl am3d/ai/test_checks.py::test_checker_validates_baked_glb_png_mime_crc_and_header_bounds am3d/ai/test_checks.py::test_checker_sanitizes_untrusted_glb_parser_names_but_valid_export_passes am3d/ai/test_checks.py::test_glb_checker_rejects_external_or_out_of_range_texture_references am3d/export/test_validate.py::test_strict_obj_rejects_external_mtl_before_opening_it am3d/export/test_validate.py::test_strict_obj_rejects_external_texture_and_collects_safe_dependencies am3d/ai/test_checks.py::test_requested_obj_material_must_match_reopened_native_material am3d/ai/test_checks.py::test_requested_glb_material_must_match_reopened_native_material -q
```

Result: **11 passed in 21.56s**. In a separate earlier focused run, the GLB MIME/decode/dimension plus sentinel subset also passed **3 tests in 14.48s** before it was included in this final 11-test command. The final listed file hashes in `SOURCE_HASHES.txt` were independently recomputed and all matched current files; the file retains baseline `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945` and records final SHA-256 values for the reviewed runtime, tests, schema, and evidence inputs.

### Final local verdict and limit

**The reviewed Phase 4 local integrity findings are clear after the fixes.** No checked-byte substitution, outside OBJ dependency, wrong requested export material, unbound intended animation, parser-sentinel echo, malformed embedded PNG, or over-budget-before-parse case reproduced after the final focused checks. Failed checks remain unpublishable. This is a local integrity verdict for the reviewed source tree only, not Phase 4 release qualification; live-provider and artist benchmarks, frozen Windows 11 and Mint acceptance, native desktop, and GPU gates remain open.

One source-reasoned workflow note remains: a GLB embedded-image pixel-limit failure under the overall 256 MiB output cap is currently reported as a failed `requested_exports` check and can enter bounded candidate repair (`checks.py:665–692`; `worker.py:421`; `orchestrator.py:461–476, 899–905`). It cannot be published while failing checks. By contrast, the overall output-byte limit is terminal at the worker’s independent final audit. This is a resource-failure classification/repair-efficiency question, not a checked-artifact integrity bypass, and is not counted as a remaining local integrity blocker here.

## Final focused follow-up — numeric resource terminal contract

The earlier source-reasoned note about an embedded GLB pixel-limit failure entering candidate repair is superseded by the final resource-report/orchestrator fix. This follow-up was limited to that known seam. In `am3d/ai/checks.py`, host-owned numeric guards register bounded measurements with explicit kind, actual, limit, and unit (`_register_resource_limit`, lines 54–76); the GLB image count/byte/dimension/pixel checks supply those details at lines 628–706, and strict OBJ resource measurements propagate at lines 900–905. Ordinary MIME, PNG corruption, and material/export failures leave the top-level flag false, as asserted in `test_checks.py:414–432`; the over-limit header and pixel fixtures assert true at lines 463–476.

The orchestrator checks `check_report.get("resource_limit") is True` at `am3d/ai/orchestrator.py:414–418`, before the checked-success publication branch and before ordinary check repair. The parametrized regression at `test_orchestrator.py:246–275` covers both `check_failed` and contradictory `checked_ok`: it expects terminal `resource_limit`, one candidate/worker call, zero repairs, and no published generation. `test_orchestrator.py:277–295` confirms truthy integer `1` does not suppress ordinary repair, while `test_orchestrator.py:229–243` confirms an ordinary check failure still gets one repair and can publish after passing.

I ran the focused checker and orchestrator cases on the Windows source environment:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv\Scripts\python.exe -m pytest -q am3d/ai/test_checks.py::test_checker_marks_strict_obj_byte_guard_as_terminal_resource_limit am3d/ai/test_checks.py::test_checker_validates_baked_glb_png_mime_crc_and_header_bounds am3d/ai/test_orchestrator.py::test_check_failure_gets_one_shared_repair_then_publishes am3d/ai/test_orchestrator.py::test_host_resource_limit_is_terminal_before_repair_or_promotion am3d/ai/test_orchestrator.py::test_truthy_nonboolean_resource_limit_does_not_suppress_ordinary_repair
```

```text
6 passed in 16.61s
```

The Phase 4 resource-report contract set also records 12 passing tests in `review-resource-flag-tests.txt`. The Phase 5 terminal-seam set records 13 passing tests (23 deselected, 4.95s) in `phase-5/IMPLEMENTATION.md`; it includes the identity-boolean guard, contradictory `checked_ok`, ordinary repair, and accounting/cancellation regressions. Independently recomputed source hashes match the current evidence: `checks.py` `15951983dedf353149eccb112727024621c2875219fa919e59d38bfcf2579374`, `test_checks.py` `7246329b5dd72373b9d3895b18f56bf2fdfb74886fb6e6318f68f7df7638e17c`, `orchestrator.py` `162c043dc2fc710ae5f7eab75088336e82415e692f0d46ef487d53699c5623d0`, and `test_orchestrator.py` `55708e6c2a013976ee81813b5329c3a3d956b9c12d9d5196a87f3bd10efc5483`.

**Disposition:** the numeric resource-limit repair-classification risk is verified fixed for this local source state. Explicit host bounds stop before candidate repair or publication, including when the worker status says `checked_ok`; ordinary check failures retain bounded repair behavior. This closes the remaining local integrity note from this review. It does not change the review’s qualification boundary: live-provider and artist benchmarks, frozen Windows 11 and Mint, native desktop/GPU behavior, and release acceptance remain unpassed. No source or test files were modified by this reviewer.
