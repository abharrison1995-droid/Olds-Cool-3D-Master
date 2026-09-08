# Phase 2 Gate Closure & Verification Evidence

**Date**: 2026-09-08  
**Phase**: Phase 2 — Complete Project State and Material Persistence  
**Gate Verdict**: **PASS (Unanimous 4/4 Swarm Approval)**  

---

## 1. Test Suite Verification

- **Command**: `$env:QT_QPA_PLATFORM="offscreen"; python -m pytest am3d`
- **Interpreter**: Python 3.14.6 (Windows 64-bit)
- **Result**: **374 passed, 4 warnings in 25.31s**
- **Regressions**: 0
- **New Tests Added for Phase 2**: 27 tests (from 347 Phase 1 count to 374)
  - Full material properties roundtrip (`roughness`, `metalness`, `texture`, `pattern`, `params`, `graph`, `objects`, `bump_map`, `transparency_map`, `specular_map`)
  - Session authored poses roundtrip distinguishing authored poses/offsets from derived `posed_transforms` cache
  - Preservation of explicit `active_action = None` across save/load
  - Strict payload bounds before memory allocation (`_MAX_CONTAINER_DEPTH`, `_MAX_ARRAY_ELEMENTS`, `_MAX_CHANNELS = 2000`, `_ALLOWED_DTYPES`)
  - Prevention of 32-bit integer overflow in `_unpack_ndarray` via arbitrary-precision `math.prod`
  - Rejection of spline point/weight count mismatches and non-positive weights with `ProjectFormatError`
  - Atomic write failure safety via same-directory tempfile, flush, `os.fsync`, atomic `os.replace`, and guaranteed cleanup in `finally` block
  - Candidate session FK pre-validation in `Session.load_project` preventing state corruption on bad candidate files
  - Restoration of `posed_transforms` on rest-pose rigs in `DeleteObjectCommand.undo`
  - Recalculation of `apply_pose` on redo/undo in `SetBoneEndpointsCommand`
  - Restoration of `active_action = None` in `CreateActionCommand.undo`
  - Dictionary key insertion order preservation across `rename_object`, `rename_action`, and delete undos
  - Normalization of missing action queries in `Session.save_action_file` to `ScriptingError`
  - Duplicate patch name handling with 1:1 UV cell alignment in atlas baking and direct patch material priority
  - Legacy `.am3d` format v1 and `.am3a` action migration tests

---

## 2. Review Swarm Verdicts (Gemini Flash Swarm)

| Lane | Focus | Initial Verdict | Recheck Verdict | Final Verdict |
| :--- | :--- | :--- | :--- | :--- |
| **Lane A** | Logic, Undo/Redo & State Atomicity | FAIL (6 defects) | PASS | **PASS** |
| **Lane B** | API Contracts, Material Ergonomics & Error Normalization | PASS | PASS | **PASS** |
| **Lane C** | Data Integrity, Safety Bounds & Atomic Persistence | FAIL (5 defects) | PASS | **PASS** |
| **Lane D** | Full Integration, Test Suite Verification & Regressions | PASS | PASS | **PASS** |

---

## 3. Finding Ledger & Resolution Summary

| ID | Lane | Defect / Gap | Resolution |
| :--- | :--- | :--- | :--- |
| 1 | A | `Session.load_project` mutated `self` before candidate validation completed. | Validates candidate on temporary isolated `Session(cand)` including forward kinematics before committing to `self`. |
| 2 | A | `DeleteObjectCommand.undo` only re-evaluated poses if `poses` or `pose_offsets` were non-empty, leaving rest rigs with unpopulated `posed_transforms`. | Updated check to `if self._skeleton is not None or self.session.poses or self.session.pose_offsets:` ensuring rest-rig bone transforms are immediately populated. |
| 3 | A | `SetBoneEndpointsCommand` modified endpoints but did not recalculate FK. | Added `self.session.apply_pose(self.object_name)` to both `redo()` and `undo()`. |
| 4 | A | `CreateActionCommand.undo` did not restore `active_action = None` if there was no active action prior to creation. | Recorded `_prev_active` and calls `set_active_action(_prev_active)` on undo. |
| 5 | A | `rename_object` and `rename_action` did not preserve exact dictionary key insertion order. | Replaced dict mutations with order-preserving dictionary comprehensions. |
| 6 | A | Duplicate patch names collapsed into single dict keys in `bake_atlas`, misaligning UV cells with `tessellate_object`. | Updated `bake_atlas` to support sequential lists of patch materials for 1:1 UV cell alignment with `tessellate_object`. |
| 7 | B | `Session.save_action_file` raised raw unhandled `KeyError` on missing actions. | Added action existence check raising `ScriptingError(f"no such action: {name!r}")`. |
| 8 | B | Missing texture paths raised generic `FileNotFoundError` escaping recipe error handling. | Structured error handling in `RecipeExecutor.execute` catching `FileNotFoundError` and emitting `code="missing_resource"`, `stage="resource"`. |
| 9 | C | `_MAX_CHANNELS = 2000` was declared but unenforced during deserialization. | Enforced check in both `validate_project_data` and action deserialization `_decode`. |
| 10 | C | `_unpack_ndarray` used `int(np.prod(raw_shape))`, vulnerable to 32-bit integer overflow. | Switched to `math.prod(raw_shape)` before safety limit comparison. |
| 11 | C | `_atomic_write` tempfile could leak if an exception was raised during replace. | Added `try...finally` block to guarantee tempfile unlinking on any failure before replace. |

---

## 4. Phase 2 Gate Sign-off

With all 11 findings verified and resolved, zero open defects, 374 automated tests passing, and unanimous PASS from all 4 Gemini Flash review lanes, Phase 2 is officially declared **PASS**.
