# Phase 4 Gate Evidence — Rendering and Exported Artifact Correctness

**Date:** 2026-09-08
**Test result:** 431 passed, 0 failed
**Previous baseline (Phase 3):** 403 passed, 0 failed (see `docs/evidence/v3/phase-3/gate_evidence.md`)
**New tests added this phase:** 28

---

## Phase 4 Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| Viewport, software fallback, recipe rendering, and GUI export route through shared evaluated scenes | ✅ PASS |
| Software rendering shares one z-buffer/depth handling across every visible mesh (viewport, GUI export, recipe OBJ/GLB, `animation_sheet`) | ✅ PASS (after gate fix, see below) |
| Renderer availability (actual backend, forced-software fallback reason) is reported separately from image correctness | ✅ PASS |
| Material assignments and flat colors carry into OBJ (`.mtl` sidecar) and GLB (`materials`/`pbrMetallicRoughness.baseColorFactor`) | ✅ PASS |
| No dangling material references (`usemtl` always resolves; GLB material index always in range) | ✅ PASS |
| Approximation of procedural/PBR/texture support is declared explicitly in docs, not implied | ✅ PASS |
| Bind/current pose and action/frame selection are exposed; static OBJ/GLB reopen at the selected pose | ✅ PASS |
| `animation_sheet` (time-sampled) is distinguishable from `spritesheet`/`toon_sheet` (multi-view) in schema, code, and docs | ✅ PASS |
| `animation_sheet` frame count/timing/columns/rows/action are deterministic and carried as manifest metadata | ✅ PASS |
| GLB manifest never implies embedded skeletal animation | ✅ PASS |
| Exported OBJ/GLB files validated with an independent reader (index ranges, bounds, normal direction, material references, selected pose) — not the writer or string matching | ✅ PASS |
| Original vs. reopened scene renders match under fixed settings: empty, occluding two-object, invisible, translated, rotated, non-uniformly scaled | ✅ PASS |

---

## Key Bugs Fixed

### 1. `.mtl` sidecar staged/published under the wrong filename (`executor.py`)
**Root cause:** The OBJ export branch staged the `.obj` under a generic `export_{index}.obj` name; `write_obj`'s internal `_write_mtl` call wrote the sidecar next to *that* name, which was never registered in `staged_items`, so the stage → publish copy never moved it to the final output directory — and the `mtllib` directive inside the `.obj` text referenced a filename that would never exist at the destination either way.
**Fix:** Stage the `.obj` under its final basename, and explicitly stage+publish the `.mtl` alongside it.
**Caught by:** `test_recipe_material_color_carries_into_obj_and_glb`, an end-to-end integration test — a writer-only unit test could not have caught this, since the writer's own inputs were self-consistent.

### 2. GUI export bypassed the shared scene evaluation boundary (`app.py`)
**Root cause:** `MainWindow._file_export_obj`/`_file_export_glb` called `tessellate_project()` directly on raw bind-pose geometry, ignoring object transforms, pose, visibility, and material color — so a GUI export did not match what was on screen.
**Fix:** Added `MainWindow._export_scene()`, calling `session.evaluate_scene(apply_transforms=True, visible_only=True)` plus `scene_material_colors()` — the same boundary the viewport and recipe exporter already used.

### 3. Inverted (inward-facing) normals on `sphere` and `box`/`plane` primitives (`primitives.py`)
**Root cause:** `build_patch_grid`'s fixed triangulation only produces an outward-facing normal when a patch's control grid has its *second* axis following `du` and first following `dv`; `_face_grid` (used by `box`/`plane`) had these transposed. `make_sphere`'s profile walked pole-to-pole in the direction that made the axial coordinate *decrease* with row index, the opposite of `make_cylinder`'s convention.
**Fix:** Transposed `_face_grid`'s axis assignment; reversed `make_sphere`'s `theta` traversal. `cylinder`/`cone`/`lathe` were already correct and untouched.
**Caught by:** building an independent `outward_normal_fraction` validator check — a genuine pre-existing geometry bug affecting primitives likely used throughout demos and tests, found as a byproduct of building export validation, not while looking for it.

### 4. `animation_sheet` export composited per-mesh renders instead of sharing a z-buffer (`executor.py`)
**Root cause:** The time-stepped `animation_sheet` branch rendered each visible mesh independently via `render_view()` and combined frames with `np.maximum()` — a per-pixel "brightest wins" composite, not real depth-based occlusion. A nearer but darker surface could be overwritten by a farther but brighter one.
**Fix:** Switched to `render_scene()`, which merges every visible mesh into one shared-index mesh (`merge_meshes()` — the same merge the viewport and GUI export already used) before a single z-buffered render pass.
**Caught by:** the four-agent review swarm (lanes A and C independently flagged it, A as confirmed, C as a plausible concern) — not by the original implementation's own tests, which only checked that frames differed, not that occlusion was correct.
**Regression test:** `test_animation_sheet_respects_shared_depth_when_meshes_overlap` — two overlapping planes, one nearer but grazing-lit (dark, ~0.30), one farther but face-lit (bright, ~0.67). Verified to fail against the prior code (shows 0.671, the wrong/far plane) and pass against the fix (shows 0.298, the right/near plane).

---

## Gate Review

**Swarm:** Four-agent independent review, run twice (initial pass + recheck pass after the confirmed bug was fixed), each agent given a distinct lane mapped to one of Section 8's acceptance bullets.

**Model note:** Section 3 of this plan requires the review swarm to run on "Luna" and states the gate should stay blocked, not substitute a different model, if Luna is unavailable. This swarm ran on Haiku at the user's explicit direction ("Run the four-agent HAIKU review for the Phase 4 gate"), not because Luna was checked and found unavailable. The swarm still found a real, confirmed bug (see below) and the fix was independently rechecked by all four lanes, but the model substitution itself is a deviation from the plan's stated process and is recorded here rather than silently normalized.

### Initial pass (commit `cf57750`)

| Lane | Focus | Verdict |
|------|-------|---------|
| A | Shared scene evaluation boundary & rendering pipeline | ❌ FAIL — confirmed bug (animation_sheet occlusion) |
| B | Material/UV/texture correctness in exports | ✅ PASS |
| C | Pose/action/frame selection & manifest correctness | ✅ PASS (same issue noted as a non-blocking plausible concern) |
| D | Independent export validation & render comparison | ✅ PASS |

### Recheck pass (commit `921a064`, after the fix landed)

| Lane | Focus | Verdict |
|------|-------|---------|
| A | Verified the fix: `render_scene()`/`merge_meshes()` correctly used; empty-scene edge case handled; no side effects outside `animation_sheet` | ✅ PASS |
| B | Confirmed the fix commit touched only `executor.py`/`test_executor.py`; material export code path unaffected | ✅ PASS |
| C | Verified the fix mechanism and independently validated the regression test's divergence logic (0.30 vs 0.67) | ✅ PASS |
| D | Confirmed `sprite.py`/`compare.py`/`validate.py` untouched; reran render-comparison and validator tests explicitly (16/16) with zero drift | ✅ PASS |

**Phase 4 gate: ✅ PASS** — one confirmed bug found, fixed, and rechecked by all four lanes; no unresolved findings.

---

## Test Evidence

```
431 passed, 4 warnings in ~32s
```

Key new tests:
- `am3d/export/test_export.py` — material color tests for OBJ/GLB writers
- `am3d/export/test_validate.py` — independent OBJ/GLB validator (10 tests: 7 corruption self-tests, 2 real-recipe integration tests, 1 selected-pose cross-check)
- `am3d/core/test_render_roundtrip.py` — original/reopened render comparison across 6 scenarios (empty, occluding two-object, invisible, translated, rotated, non-uniformly scaled)
- `am3d/core/test_scene.py::test_scene_material_colors_reads_bound_objects_only`
- `am3d/ui/test_ui.py::test_gui_export_scene_applies_transform_and_material`
- `am3d/recipes/test_executor.py::test_animation_sheet_export_renders_distinct_frames`
- `am3d/recipes/test_executor.py::test_animation_sheet_on_empty_scene_fails_loudly`
- `am3d/recipes/test_executor.py::test_recipe_material_color_carries_into_obj_and_glb`
- `am3d/recipes/test_executor.py::test_animation_sheet_respects_shared_depth_when_meshes_overlap`

## Visual Evidence

`scripts/render_roundtrip_evidence.py` renders all 6 render-comparison scenarios and writes original/reopened/diff PNGs plus a numeric summary to `docs/evidence/v3/phase-4/render_roundtrip/` — all six report `OK`, `max_abs_diff=0`, `png_mean_diff=0`.
