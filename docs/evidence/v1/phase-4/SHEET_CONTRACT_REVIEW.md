# Phase 4 requested-export contract: independent review

Date: 2026-10-13  
Local verdict: **PASS for the bounded reopened requested-export contract**. The focused source and worker checks below pass. This does not qualify a frozen build, close the full Phase 4 gate, or qualify packaging/release.

## Source reviewed

The preserved Phase 10 receipt is still byte-identical to the fix record: `docs/evidence/v1/phase-10/spritesheet-contract-pending.json`, SHA-256 `b80dd21bbbdd85679e81d5a1425c3996890dc17a77b5298503f6f16fa8bcb1cc`. It records the original public failure: accepted exports included `spritesheet`, the checker expected `ignored-sheet.png`, and the worker produced `export_03_object_000_bcd1dec4.png` plus `preview.png`.

Checked source identities:

- `am3d/ai/checks.py` — `2c610c348e71d1311854ee9e3618db2e62164067c87fec2a84ca011708f27421`
- `am3d/ai/test_sheet_contract.py` — `0216adba98804d9bf1fbf5ee29d2969667c48152ac237fbfe4beefe48c0976b7`
- `am3d/recipes/executor.py` — `cc902232491f570dd8975cc44047b53e20106f685e1ca57d765bad91c4742a2b`
- `am3d/ai/policy.py` — `9d80cf3174b491191e577811b97e5a2389d90796319065cce4978e08c0ae962e`
- `am3d/ai/worker.py` — `184df9bf7555ee9496120e30ae4aab3bb1a9e3807326721e092b2313ced7fae7`
- `am3d/ai/orchestrator.py` — `162c043dc2fc710ae5f7eab75088336e82415e692f0d46ef487d53699c5623d0`
- Fix evidence `SHEET_CONTRACT_FIX.md` — `23a4c0d28eacc166f0dd5e402a8a584f6441af4cdc44ed8611b06577b4de721e`

Relevant lines: object path identity comes from `_artifact_object_name` at `am3d/recipes/executor.py:100`; executor mesh filtering and per-object suffixing are at `:635-638` and `:753-793`. The checker mirrors the suffix at `am3d/ai/checks.py:870-878`, enumerates the reopened scene's nonempty meshes and verifies each exact path at `:933-980`, and resolves the reopened scene at `:1186`. No glob, preview, atlas, or renamed-file fallback participates in that lookup. The per-object check uses `_safe_file` (`checks.py:129`) and the normal tree preflight/manifest (`:149-224`).

`_expected_export_formats` unions caller `required_exports` and accepted brief `exports`, maps `gltf` to `glb`, and returns a fixed malformed/unsupported error at `checks.py:832-868`; missing recipe formats are rejected at `:907-921`. The mandatory `project.am3d` check is at `:1058-1064`. The report still bounds output to 64 file entries and 16 issue entries (`:1066-1068`). PNG dimension/pixel limits and their resource-flag registration remain in the exact per-sheet path (`:954-980`) and generic PNG path (`:997-1056`); the fixed worker caps the serialized check report as before (`worker.py:391-394`).

The actual source route normalizes through `prepare_recipe` (`policy.py:880-884`, normalized host paths at `:863-878`), runs `RecipeExecutor(..., safe_artifact_names=True)` in the worker (`worker.py:342-344`), and calls `check_artifacts` with the host brief and requirements (`worker.py:379-390`). The orchestrator puts accepted `brief_data` and caller requirements into check options (`orchestrator.py:378-388`). Thus the checker sees the accepted brief even when the candidate recipe omits a requested sheet.

`animation_sheet` remains one base PNG: the executor composes all live meshes into each frame (`executor.py:833-835`) and stages one `base.png` (`:848-854`). The checker uses its generic single-file path for that format (`checks.py:983-1056`); it does not derive per-object sheet suffixes for animation.

## Verification

Windows 10 source environment, `.venv`, `QT_QPA_PLATFORM=offscreen`; all runs were local and used no provider, credentials, key, or network.

Commands rerun independently:

```powershell
.\.venv\Scripts\python.exe -m pytest am3d/ai/test_sheet_contract.py -q --maxfail=1 --tb=short
```

Result: **12 passed in 75.11s**.

```powershell
.\.venv\Scripts\python.exe -m pytest am3d/ai/test_checks.py::test_export_preflight_stops_glb_parser_reads am3d/ai/test_checks.py::test_checker_marks_strict_obj_byte_guard_as_terminal_resource_limit am3d/ai/test_checks.py::test_missing_requested_export_fails_independent_export_check am3d/ai/test_checks.py::test_checker_validates_baked_glb_png_mime_crc_and_header_bounds -q --maxfail=1 --tb=short
```

Result: **4 passed in 26.63s**.

I also invoked `worker.run_worker` as a real local child-process run with a two-object recipe (`body/骨`, `arm .. / 翼`), a normalized `spritesheet` request, the accepted brief declaring the sheet, and independent required exports. It returned `checked_ok`; `requested_exports` passed with exactly `export_01_object_000_877f8137.png` and `export_01_object_001_d00d7faa.png` plus `project.am3d`, with no issues. The manifest also had `preview.png`, but it was not used as a requested sheet. This covers the actual worker, reopened-native checker path, and mesh order together.

A paired real-worker omission reproduction used the same accepted intent (`exports: [am3d, spritesheet]`) with a recipe that contained no sheet. It returned `check_failed`, `requested_exports: failed`, issue `missing required export formats: spritesheet`, and `resource_limit: false`. This confirms recipe omissions cannot erase accepted intent.

A separate actual `check_artifacts` negative reproduction used two expected object sheets, removed one, and added valid `preview.png`, `atlas.png`, and `renamed.png`. The check failed with `required spritesheet object sheet is missing` and `resource_limit: false`; none of those unrelated PNGs filled the missing object slot.

The GLTF alias reproduction ran `prepare_recipe` on a `gltf` request and called `check_artifacts` with both accepted brief and independent requirements using `gltf`. The host normalized the recipe to `glb`; the check passed with `project.am3d` and `export_01.glb`, no issues, and `resource_limit: false`.

The focused tests additionally cover one/two mesh sprite and toon sheets, opaque names, exact missing sheet, malformed PNG as an ordinary failure, image caps before pixel loading with `resource_limit: true`, the required-export union, fixed unknown-format diagnostics, native/OBJ/GLB/sheet together, and the single unsuffixed animation sheet.

## Findings and limits

No reproducible defect or false acceptance was found in the reopened export contract. The focused contract fix is suitable for the packaging owner's next fixed-self-test attempt, subject to that result; the failed receipt remains preserved and the frozen acceptance case has not been rerun here.

One non-blocking coverage suggestion: `test_animation_sheet_keeps_single_unsuffixed_composited_output` verifies a single base PNG, no object-suffixed outputs, and checker acceptance, while source lines `executor.py:833-854` show the all-mesh composite operation. The test does not assert that both meshes contribute pixels or that animated frames differ. This is a test-strengthening opportunity, not a defect in the reviewed naming/checker contract.

No source or test files were changed during this review. Only this review report is added.
