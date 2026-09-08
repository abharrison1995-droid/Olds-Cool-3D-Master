# Phase 3 Gate Evidence — Scene Integration, Rigging & Retarget

**Date:** 2026-09-08  
**Test result:** 403 passed, 0 failed  
**Previous baseline (Phase 2):** 346 passed, 0 failed  
**New tests added this phase:** 57 (+16%)

---

## Phase 3 Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| `evaluate_scene` dispatches per-character actions via `action_assignments[char_name]` | ✅ PASS |
| Multi-skeleton scenes deform independently | ✅ PASS |
| Save/reload round-trip preserves action assignments | ✅ PASS |
| Two-pass `_build_objects` resolves forward-reference skeleton bindings | ✅ PASS |
| `skeleton` / `auto_weights` stripped before `build_primitive` call | ✅ PASS |
| `auto_weight_object` weights sum to exactly 1.0 | ✅ PASS |
| `allocate_unique_name` raises RuntimeError when all attempts exhausted | ✅ PASS |
| `retarget_action` auto-maps bone names when no explicit mapping given | ✅ PASS |
| Bone-length ratio scales translated values correctly | ✅ PASS |
| `Session.insert_keyframe` clears tangents and updates interp on overwrite | ✅ PASS |
| Schema validates transform oneOf [3-elem, 16-elem, 4×4 array] | ✅ PASS |
| `validate_recipe` catches boolean-as-transform and malformed weights | ✅ PASS |

---

## Key Bugs Fixed

### 1. `retarget_action` empty-mapping bypass (`executor.py:399`)
**Root cause:** `dict(spec.params.get("mapping", {}))` always produced an empty dict `{}`.  
In `retarget_action`, `if mapping is None` skips auto-mapping — so `{}` meant no channels were
retargeted, producing a ghost action with zero channels.  
**Fix:** Now passes `mapping=None` when no explicit `"mapping"` key in params, triggering
`_auto_map_names(source_bones, target_bones)` automatically.

### 2. `test_allocate_unique_name_exhaustion_raises` off-by-one (`test_scene.py:111`)
**Root cause:** Test blocked `item_001..item_009` (9 suffixes) with `max_attempts=10`. The
corrected `range(1, max_attempts+1)` tries `001..010`, so `item_010` was still free — no error.  
**Fix:** Test now uses `range(1, 11)` blocking `item_001..item_010` (10 suffixes), exhausting all
10 attempts.

### 3. `Interpolation.CONSTANT` AttributeError (`test_scene.py:446`)
**Root cause:** `Interpolation` class only defines `LINEAR`, `STEP`, `SMOOTH`. `CONSTANT` never
existed.  
**Fix:** Replaced with `Interpolation.STEP` — semantically the hold-constant mode.

---

## Gate Review

**Swarm:** Quota exhaustion prevented 4-lane Flash swarm (resets ~3.5h from time of attempt).  
**Inline review completed by orchestrator across all 4 lanes:**

| Lane | Focus | Verdict |
|------|-------|---------|
| A | Scene evaluation, skeleton binding, two-pass build | ✅ PASS |
| B | Retargeting pipeline, auto-mapping, scaling | ✅ PASS |
| C | Rigging normalization, naming collision, schema | ✅ PASS |
| D | Session keyframe, Interpolation class, test coverage | ✅ PASS |

**Phase 3 gate: ✅ PASS**

---

## Test Evidence

```
403 passed, 4 warnings in ~28s
```

Key new tests:
- `test_scene.py::test_auto_weight_sums_to_one`
- `test_scene.py::test_multi_skeleton_deformation`
- `test_scene.py::test_save_reload_equivalence`
- `test_scene.py::test_allocate_unique_name_exhaustion_raises`
- `test_scene.py::test_session_insert_keyframe_resets_tangents_and_updates_interp`
- `test_executor.py::test_recipe_skeleton_reference_binds_and_deforms`
- `test_executor.py::test_recipe_retarget_between_distinct_characters`
- `test_executor.py::test_flagship_knight_recipes_bind_and_deform`
