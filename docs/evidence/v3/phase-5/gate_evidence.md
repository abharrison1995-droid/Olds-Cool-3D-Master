# Phase 5 Gate Evidence — Desktop Reliability and Recovery

**Date:** 2026-09-08
**Test result:** 480 passed, 0 failed
**Previous baseline (Phase 4):** 431 passed, 0 failed (see `docs/evidence/v3/phase-4/gate_evidence.md`)
**New tests added this phase:** 49

---

## Phase 5 Acceptance Criteria

| Criterion | Status |
|-----------|--------|
| Normal modelling/animation workflows are undoable and durable | ✅ PASS |
| Crash recovery is demonstrated | ✅ PASS |
| No visible dead controls | ✅ PASS |
| Fresh users can open an externally generated project, play it, edit it, save it, and export it | ✅ PASS |

---

## Bullet-by-Bullet Summary

### 1. Complete command coverage; dirty derives from saved revision
**Commits:** `3395c65`, `ed5ce44`
Added `ClearPoseCommand`, `SetRenderSettingsCommand`, `ImportActionCommand`, `SetActiveActionCommand` — Reset Pose, Render tab edits, Import Action, and Timeline/Outliner active-action switching were previously silent no-ops for Ctrl+Z and never marked the document dirty. Also fixed `DocumentController._clear_undo()` never being called from `do_new()`/`do_open()` (a real cross-document undo-leakage bug). "Templates" confirmed N/A — no implementation exists anywhere in `am3d`.
**Review found:** `SetRenderSettingsCommand._apply()` merged via `dict.update()` instead of replacing, so undo couldn't clear keys redo had added; active-action switching bypassed undo entirely. Both fixed and rechecked clean.

### 2–4. Reset on New/Open/Recover; autosave lifecycle; recovery identity
**Commits:** `d0c1355`, `f6ba0fa`, `ae045dc`
Single lifecycle-owned `QTimer`, rescheduled (not recreated) on preference change, firing `do_autosave()` only when dirty and never marking the document clean. Per-document autosave identity (SHA1 of resolved path, or a per-controller uuid for untitled documents) prevents same-named files in different folders — or two blank documents — from colliding on one snapshot. `recover_from()` opens dirty and pathless so Save routes through Save As instead of overwriting the snapshot file.
**Review found (initial):** `_apply_autosave_interval()` crashed the app at startup on a non-numeric QSettings value; `_recover_project()` ignored `recover_from()`'s failure return, silently dropping the user into an empty editor with no error. Both fixed (`f6ba0fa`) and rechecked clean.
**Review found (final gate pass):** `_reset_document_ui_state()` cleared object selection but not an in-progress viewport CP drag, gizmo drag, or G/R/S modal grab — those hold direct references into the document being replaced. Fixed via `Viewport.cancel_interactions()` (`ae045dc`), rechecked clean by all four lanes.

### 5. Wire live Home/Settings controls, or remove the unwireable one
**Commit:** `39acf86`
Undo depth, render backend, grid visibility, and default FPS/frame-end are now genuinely live. Tessellation preset was removed from Settings rather than fake-wired — nothing in the tessellation pipeline has a concept of a global preset to hook it to (resolution is per-primitive). All QSettings reads that feed live behavior fall back to their dialog defaults on a corrupted/non-numeric value instead of raising.
**Review found:** none confirmed.

### 6. Real quick start, examples, dirty-safe return Home, keyboard access, diagnostics
**Commits:** `046b350`, `0b82554`, `a65f244`
Quick Start guide covers the actual New→Model→Rig→Animate→Save→Export workflow. Examples section surfaces the two bundled demo projects (vase, generated-character knight) that shipped in the repo but were never reachable from the UI. "Close Editor" verified already dirty-safe. Diagnostics (Help menu + Home button) reports version info, active renderer backend and why, document state, undo/autosave counts, and the app-data directory. Mnemonics added to every top-level menu, File-menu item, and Home button; Home's primary action gets default keyboard focus whenever it becomes visible.
**Review found:** opening an example via the ordinary recent-file path left the document's save path pointing at the bundled asset file — a plain Ctrl+S after editing an example would have silently overwritten `assets/vase_demo.am3d`/`assets/demo/knight_project.am3d`. Fixed via `DocumentController.do_open_example()` (`0b82554`). Quick Start's rigging step claimed a UI control that doesn't exist ("add bones to a mesh") — reworded to match reality. Both fixed and rechecked clean.

---

## Gate Review

**Swarm:** Four-agent independent review, run as a final holistic pass over Phase 5 as a whole (distinct from each bullet's own incremental review during development), followed by a recheck pass after the one confirmed bug was fixed.

**Model note:** Section 3 of this plan requires the review swarm to run on "Luna." As with the Phase 4 gate, this swarm ran on Haiku at the user's standing direction for this project, not because Luna was checked and found unavailable — recorded here per the same convention as `docs/evidence/v3/phase-4/gate_evidence.md`.

### Final gate pass (commit `a65f244`, before the recheck fix)

| Lane | Focus | Verdict |
|------|-------|---------|
| A | Bullet 1: command coverage, dirty/undo correctness | ✅ PASS |
| B | Bullets 2–4: reset on New/Open/Recover, autosave lifecycle, recovery identity | ❌ FAIL — confirmed bug (viewport drag/modal state not cleared) |
| C | Bullet 5 + no-dead-controls: Settings/Home controls | ✅ PASS |
| D | Bullet 6 + fresh-user-journey acceptance: end-to-end vase/knight save+export | ✅ PASS |

### Recheck pass (commit `ae045dc`, after the fix landed)

| Lane | Focus | Verdict |
|------|-------|---------|
| A | Confirmed the fix is undo-safe: discards drag/modal state directly, pushes no command, doesn't touch `_cancel_modal()`'s transform-restore path | ✅ PASS |
| B | Verified the fix against all five document-replacement call sites (`_file_new`, `_file_open`, `_open_recent`, `_open_example`, `_recover_project`) with an independent manual repro of each | ✅ PASS |
| C | Confirmed the fix touches only `app.py`/`viewport3d.py`/`test_operators.py`; Settings/Home area unaffected | ✅ PASS |
| D | Confirmed the fix is a safe no-op on the common case (nothing in progress) and correctly clears state on the vase example journey | ✅ PASS |

**Phase 5 gate: ✅ PASS** — one confirmed bug found on the final holistic pass, fixed, and rechecked clean by all four lanes; no unresolved findings. (Earlier per-bullet incremental reviews during development — `ed5ce44`, `f6ba0fa`, `0b82554` — each found and fixed their own confirmed bugs before this final gate pass began; see the bullet-by-bullet summary above.)

---

## Test Evidence

```
480 passed, 4 warnings in ~37s
```

Key new tests this phase:
- `am3d/ui/test_operators.py` — `SetActiveActionCommand`/`SetRenderSettingsCommand`/`ImportActionCommand`/`ClearPoseCommand` undo/redo/dirty coverage, cross-document undo isolation, autosave-identity/corrupt-recovery/UI-state-reset coverage, `test_reset_document_ui_state_cancels_inflight_viewport_interaction`
- `am3d/ui/test_home.py` — bundled-example loading/dirty-safety/overwrite-protection, Quick Start wiring, Diagnostics wiring (menu + Home button), keyboard-focus-on-Home, `gpu_render_available()` probe parity
- `am3d/ui/test_ui.py` / settings tests — undo-depth empty-stack guard, grid/render-backend live wiring, default FPS/frame-end wiring, corrupted-settings fallback coverage across all QSettings-backed preferences

The 4 pre-existing PySide6 `QMouseEvent` deprecation warnings (`test_dopesheet.py`) are unrelated to this phase and unchanged from the Phase 4 baseline.
