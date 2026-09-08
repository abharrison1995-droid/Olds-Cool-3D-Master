# Phase 1 Gate Closure & Verification Evidence

**Date**: 2026-09-08  
**Phase**: Phase 1 — Reliable External LLM Recipe Contract  
**Gate Verdict**: **PASS (Unanimous 4/4 Swarm Approval)**  

---

## 1. Test Suite Verification

- **Command**: `$env:QT_QPA_PLATFORM="offscreen"; python -m pytest am3d`
- **Interpreter**: Python 3.14.6 (Windows 64-bit)
- **Result**: **347 passed, 4 warnings in 24.53s**
- **Regressions**: 0
- **New Tests Added for Phase 1**: 23 tests (from 324 baseline to 347)
  - Strict Draft 2020-12 schema validation & enum parity
  - Unknown field rejection with indexed JSON pointer paths
  - Subprocess CLI execution across 6 real modes:
    1. Plain recipe file (`--recipe file.json`)
    2. Stdin plain JSON (`--recipe -`)
    3. Stdin UTF-8 BOM (`b"\xef\xbb\xbf"`)
    4. File with UTF-8 BOM
    5. Missing file error handling
    6. `--validate-only` zero-side-effect mode
    7. Malformed JSON stdin error handling
  - Path confinement & directory traversal escape rejection (`os.path.realpath`, splitdrive checks, `.` / `./` rejection)
  - Staging isolation (`tempfile.TemporaryDirectory`) ensuring atomic publication and preservation of pre-existing files on failure
  - Cyclic bone hierarchy detection (`a -> b -> a`)
  - Rich manifest tracking per physical artifact (`format`, `path`, `status="written"`, `size_bytes`, metadata)

---

## 2. Review Swarm Verdicts (Gemini Flash Swarm)

| Lane | Focus | Initial Verdict | Recheck Verdict | Final Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **Lane A** | Logic, Correctness & State Transitions | FAIL (4 defects) | PASS | **PASS** |
| **Lane B** | Contracts, Schema Conformance & CLI Ergonomics | FAIL (3 defects) | PASS | **PASS** |
| **Lane C** | Data Integrity, Path Confinement & Staging Atomicity | FAIL (2 defects) | PASS | **PASS** |
| **Lane D** | Integration, Regressions & Acceptance Criteria | FAIL (1 gap) | PASS | **PASS** |

---

## 3. Finding Ledger & Resolution Summary

| ID | Lane | Defect / Gap | Resolution |
| :--- | :--- | :--- | :--- |
| 1 | A | Ghost success on `spritesheet`/`toon_sheet` when recipe contains no mesh geometry. | Added explicit check in `_run_exports` raising `code="missing_geometry"`, `stage="write"`. Tested in `test_spritesheet_on_rig_only_fails_loudly`. |
| 2 | A | Procedural atlas baking ran on rig-only / patchless objects. | Added check `if not obj or not obj.patches: continue` in `_bake_atlases`. |
| 3 | A | Action channels targeting non-existent bones on characters were unvalidated. | Added bone lookup check in `validate_recipe` raising `code="unknown_bone"`, `stage="schema"`. |
| 4 | A/B | Diagnostic error paths lacked indexed notation for arrays. | Updated all loops to format paths as `recipe.actions[{i}].*` and `recipe.exports[{i}].*`. |
| 5 | B | Missing `primitive` enum and required export fields in `recipe-v1.schema.json`. | Updated schema with `PRIMITIVES` enum and `required: ["format", "path"]`. Added `test_schema_json_conformance`. |
| 6 | B | External agent guide lacked coordinate system, unit documentation, and sample links. | Updated `docs/recipes/EXTERNAL_AGENT_GUIDE.md` with coordinate conventions, units, primitive parameters, error correction loop, and sample links. |
| 7 | C | Output path confinement used lexical `abspath`, vulnerable to `.` and Windows drive escapes. | Upgraded `_resolve_output_path` to `os.path.realpath`, checking `os.path.splitdrive` and rejecting `.`/`./` targets. |
| 8 | C | Exports were written directly, corrupting existing destination files on midway failures. | Wrapped export & atlas pipeline in `tempfile.TemporaryDirectory`, copying files via `shutil.copy2` only if all staged items succeed. |
| 9 | C | Bone hierarchy circular references (`a -> b -> a`) caused recursion issues. | Added DFS cycle detection in `validate_recipe` raising `code="cyclic_bone_hierarchy"`. |
| 10 | D | Missing real subprocess test for files encoded with UTF-8 BOM. | Added `test_subprocess_cli_file_with_bom` to `am3d/recipes/test_executor.py`. |

---

## 4. Phase 1 Gate Sign-off

With all 10 findings resolved, zero open defects, 347 tests passing, and unanimous PASS from all 4 Gemini Flash review lanes, Phase 1 is officially declared **PASS**.
