# 3D MASTER:2005 — V2 Beta Implementation Plan

Status: remediation and completion roadmap after post-implementation review
Target: evidence-backed Windows V1 beta candidate
Last updated: 2026-08-26
Reviewed implementation: commit `0a7094d` plus uncommitted Phase 0/1 working
tree
Review method: two independent Terra reviewers plus local code, runtime,
test, and packaged-launch verification (original pass); 6-way parallel Haiku
swarm review plus manual verification of every cited line (2026-08-26 pass,
see section 13)

## 1. Purpose

This V2 plan supersedes `V1_BETA_IMPLEMENTATION_PLAN.md`.

The first implementation pass added a useful application shell, Home screen,
document controller, serializer guardrails, Settings UI, packaging files, and
a staged Windows executable. Several V1 phases were nevertheless marked
complete without satisfying their exit gates. V2 converts the remaining work
into testable remediation packages and adds product improvements for a safer,
clearer beta.

Do not describe the application as beta-ready until every release gate in
Section 12 is supported by automated or recorded manual evidence.

## 2. Verified baseline

### Working foundations

- `python -m pytest am3d -q`: **276 passed, 4 Qt deprecation warnings**.
- Production startup no longer seeds the demo sphere or material.
- Launch displays Home; New Empty starts with zero objects and materials.
- `DocumentController` centralizes basic New/Open/Save/close operations.
- Action definitions are included in controller saves.
- A same-directory temporary-write-and-replace path exists.
- Recent-project storage and a Settings dialog exist.
- A staged executable exists at
  `release/3D MASTER 2005 Beta/3D MASTER 2005.exe`.
- That executable remained alive during a five-second offscreen launch check.

### Reproduced failures

- Create -> Sphere creates no object and appends another Sphere menu action.
- Create Profile/Spline changes the project while dirty stays false and the
  undo stack remains empty.
- Action assignments do not survive save/reopen.
- `build_windows.ps1` resolves the repository root to the workspace's parent.
- Its “smoke test” only checks executable existence and size.
- The staged release has no `examples/` directory.
- Autosave helpers exist, but nothing schedules them.

## 3. V2 release blockers

1. ~~Primitive menu wiring prevents first-primitive creation.~~ **Fixed** (Phase 0).
2. ~~Profile/Spline, Lathe, Extrude, Duplicate, and render settings bypass undo
   and dirty tracking, permitting silent data loss.~~ **Fixed for Profile/Spline,
   Lathe, Extrude, Duplicate** (Phase 0/1) — all now push `QUndoCommand`s. Render
   settings are not yet command-enabled; still open.
3. ~~Save does not establish the undo stack's saved revision; Save -> Undo can
   leave changed content marked clean.~~ **Fixed** (Phase 0) —
   `DocumentController._mark_clean()` calls `undo_stack.setClean()`; regression
   test `test_save_then_undo_is_dirty` passes.
4. ~~Action assignments and exact active-action state are not persisted.~~
   **Fixed** (Phase 1) — round-trip covered by `test_phase1.py`; see swarm
   review note below on `active_action` reference validation still being open.
5. ~~Object rename/delete leaves stale pose and animation maps.~~ **Fixed**
   (Phase 1) — `Session.rename_object`/`delete_object` now rekey/purge
   `poses`, `pose_offsets`, `posed_transforms`, `action_assignments`.
6. Autosave/recovery is non-operational and can delete unrelated recoveries. — still open (Phase 2).
7. GUI export omits object transforms. — still open (Phase 4).
8. Serializer hardening declares important limits it does not enforce. — **still open**,
   re-confirmed by 2026-08-26 swarm review: `_MAX_CONTAINER_DEPTH`,
   `_MAX_ARRAY_ELEMENTS`, `_ALLOWED_DTYPES` remain declared but unenforced, and
   spline load (`serializer.py:287`) does unvalidated key access that raises a
   raw `KeyError` instead of `ProjectFormatError` on a malformed file.
9. Windows build automation has the wrong root and no real workflow smoke test. — still open (Phase 5).
10. Home and Settings contain dead or decorative controls. — still open (Phase 3).

## 4. Required architecture corrections

### 4.1 Dirty means divergence from the last successful save

- Route every undoable document edit through `MainWindow.push_command()`.
- Successful New/Open clears the stack and establishes a clean revision.
- Successful Save/Save As calls `undo_stack.setClean()`.
- Derive dirty from `not undo_stack.isClean()` plus a tracked revision only if
  intentional non-undoable document mutations remain.
- Prefer eliminating non-undoable document mutations.
- Application preferences are not document state; project render and animation
  settings are document state.

Required regression sequence:

```text
Edit -> Save -> Undo -> New/Open/Quit
```

The final state must be dirty because it differs from the saved file.

### 4.2 All authoring operations are commands

Add redo-idempotent undo commands for primitive creation, object plus profile
spline creation, lathe, extrusion, duplication, project render settings, and
template insertion. Commands must own complete before/after state. Avoid direct
model mutations followed only by `_refresh_all()`.

### 4.3 One versioned document envelope

Recommended format version `2`:

```text
format_version
project
actions
session_state
  active_action
  action_assignments
resource_manifest
```

Keep derived caches transient. Validate every reference before replacing the
current session. Load legacy unversioned/V1 files through an explicit migration.

### 4.4 One scene assembly path

Create a shared scene-to-mesh boundary used by viewport, export, and software
fallback. It must define visibility, object transforms, bind/current pose,
skinning, materials, UVs, and tessellation preset. Stop duplicating this logic
between viewport and export.

## 5. Phase 0 — Correct release-blocking regressions

Priority: immediate

### 5.1 Repair first-geometry creation

- Connect each primitive action directly to exactly one
  `CreatePrimitiveCommand` push.
- Remove nested menu-action registration and the dead workaround.
- Allocate collision-safe names such as `sphere`, `sphere_001`, `sphere_002`.
- Never overwrite an existing object during creation.
- Test Sphere, Box, Cylinder, Cone, Torus, and Plane: one click, undo, redo,
  repeated creation, and collision handling.

### 5.2 Command-enable modelling operations

- Create profile spline through a command and the `Session` facade.
- Use a valid degree/control-point combination: four cubic points or degree
  clamped to `len(cps) - 1`.
- Lathe the correct `[radius, axial]` plane. The starter profile varies in X/Y,
  so extracting X/Z collapses it and must be fixed.
- Reuse `Session.lathe_spline()` and `Session.extrude_spline()` where possible.
- Target the explicitly selected spline, not silently the first spline.
- Warn when object/spline context is missing.
- Duplicate with a complete snapshot and collision-safe name.
- Ensure each operation marks dirty and updates selection/outliner predictably.

### 5.3 Repair dirty/save semantics

- Mark the undo stack clean after successful Save and Save As.
- Clear and establish clean state after successful New/Open only after commit.
- Remove `isVisible()` from data-safety decisions or tightly constrain it to
  controlled bootstrap/test code.
- Track imported actions and project settings through commands.
- Add File -> Save As and File -> Close Project.
- Show the Open picker before asking to abandon the current document so cancel
  cannot trigger an unnecessary save.

### 5.4 Reset UI state after document replacement

Add one `reset_document_ui_state()` called after New/Open/Recover. It must stop
playback; cancel modal transforms and drags; clear object/CP/bone selection,
outliner/properties context, and caches; reset frame/status; then refresh only
after the new session is internally consistent.

### Phase 0 tests

- One-click primitive creation for all six primitives.
- Profile, Lathe, Extrude, Duplicate: dirty + undo + redo.
- Every authoring route followed by New/Open/Quit prompts correctly.
- Edit -> Save -> Undo is dirty.
- Cancel Open leaves memory and disk untouched.
- New/Open clears stale selection, playback, and modal state.

### Exit gate

A blank project can create geometry, and no normal authoring route can be
discarded without an appropriate dirty-document decision.

## 6. Phase 1 — Complete persistence and lifecycle integrity

### 6.1 Persist animation session state

- Serialize exact `active_action`, including `None`.
- Serialize `action_assignments`.
- Validate that assignments reference existing objects and actions.
- Preserve ordered actions if UI ordering is intentional.
- Report or reject invalid legacy assignments; never retain them silently.

### 6.2 Maintain object-keyed state

`Session.rename_object()` must rekey `poses`, `pose_offsets`,
`posed_transforms`, and `action_assignments`. `Session.delete_object()` must
purge them. Delete undo must restore exact snapshots, and Add Object undo must
not allow a reused name to inherit stale state.

### 6.3 Correct action undo

`DeleteActionCommand` must restore the previous active action, assignment map,
action order, and deleted action. Test delete/undo/redo with several actions.

### 6.4 Complete material persistence

Make renderer-consumed `texture`, `pattern`, `params`, and `graph` fields
first-class Material data. Version, validate, and round-trip them. Resolve
relative resources from the project directory through one resource resolver.

### Phase 1 tests

- GUI Save/Open retains actions, exact active action, and assignments.
- Rename/delete/undo maintains every object-keyed invariant.
- Procedural, graph, and texture material fields round-trip.
- Existing sample `.am3d` and `.am3a` files remain compatible.

### Exit gate

Reopening restores playable animation bindings and intended material state
without stale references.

## 7. Phase 2 — Operational autosave, recovery, and safe serialization

### 7.1 Real autosave scheduling

- Give the controller one lifecycle-owned `QTimer` honoring Settings changes.
- Autosave only dirty documents and never mark the main document clean.
- Surface last autosave time and failures non-modally.

### 7.2 Per-document recovery

Use a persistent document UUID plus metadata: source path, display name,
timestamp, app/format version, and clean-shutdown status. List every candidate
with Recover, Inspect/Open Copy, and Discard choices.

Recovered content opens dirty and requires Save As unless overwrite is
explicitly confirmed. Failure must show a typed error and preserve the current
session. Never clear all autosaves on exit; clear only a safely superseded or
explicitly discarded snapshot.

### 7.3 Finish format validation

- Emit `format_version`; add unversioned/V1 migrations.
- Configure msgpack limits where supported.
- Validate root/container types before `.get()` calls.
- Enforce nesting, dtype, ndarray byte/shape, object, spline, patch, bone,
  action, channel, and key limits.
- Reject NaN/infinite transforms, weights, keys, ranges, and FPS.
- Require FPS > 0 and valid frame ordering.
- Validate references before model construction.
- Convert parser/schema/model failures into `ProjectFormatError` with a field
  path before replacing the current session.

### 7.4 Strengthen atomic save

- Use a unique temporary file in the destination directory.
- Serialize before opening the destination.
- Flush and synchronize before replacement where supported.
- Remove temporary files on failure.
- Optionally retain a bounded verified `.bak`.
- Add concurrent and interrupted-write simulation tests.

### Exit gate

Crash recovery is demonstrably usable, and malformed inputs fail within
resource limits without changing the active document.

## 8. Phase 3 — Finish Home, Settings, and onboarding

### 8.1 Complete Home

Add and connect New Empty, New From Template, Open, Recent, Recover, Enter
Editor, Settings, Quick Start, Example Gallery, Report Problem/Copy
Diagnostics, About, and Exit. Add dirty-safe Close Project/Return Home from the
editor. Quick Start must open a real guide or in-app walkthrough.

### 8.2 Empty-editor guidance

When there are no objects, show keyboard-accessible actions for Create
Primitive, Draw Profile Spline, Open Project, and Quick Start. Hide the overlay
after first geometry creation.

### 8.3 Make Settings functional

Apply and test theme, undo depth, autosave interval, renderer preference,
tessellation preset, grid visibility, new-project FPS/frame end, default
project directory, and navigation preset. Label settings requiring restart.

### 8.4 Suggested product improvements

- Parameter dialog for primitive creation with safe defaults.
- Template/recent thumbnails.
- Classic A:M navigation preset.
- Autosave status indicator.
- Copy Diagnostics with app/runtime/backend/OS/log information.
- Safe Mode forcing software rendering and default layout.
- Five-minute first-run vase tutorial using Profile -> Lathe.
- Visible keyboard focus plus Ctrl+N/Ctrl+O/Ctrl+S shortcuts.

### Exit gate

Every visible Home and Settings control works, and a first-time tester can
discover the complete blank-project modelling journey.

## 9. Phase 4 — Export, renderer, and visual parity

- Move transform application out of viewport-only code into shared scene
  assembly.
- Export translated, rotated, scaled objects correctly, including normal
  transforms under non-uniform scale.
- Define and expose Bind Pose versus Current Pose export.
- Make software fallback render every visible mesh with depth-aware merging.
- Test empty, single, overlapping two-object, and transformed scenes.
- Report the backend used for the last successful frame and fallback reason.
- Make Software Only bypass GPU initialization predictably.
- Wire Chunky/Classic/Smooth to real tessellation values.
- Add toon band-count, ink thickness, retro palettes, spline-cage, and patch
  boundary controls.

### Exit gate

Viewport, reopened project, software fallback, and OBJ/GLB agree on placement,
chosen pose, and material intent.

## 10. Phase 5 — Reproducible Windows build and real smoke tests

### 10.1 Repair automation

- Set `$RepoRoot = $PSScriptRoot`, verify it contains `pyproject.toml`,
  `am3d.spec`, and `am3d/` before any cleanup.
- Resolve all paths from the verified root and run from any working directory.
- Check `import PyInstaller`, not `import pyinstaller`.
- Build in a clean virtual environment from pinned constraints rather than
  mutating the user's interpreter with floating installs.

### 10.2 Reconcile release inputs

- Use one version in pyproject, `am3d.__version__`, Home, executable metadata,
  release folder, and diagnostics.
- Declare/pin PyInstaller and runtime dependencies.
- Include Pillow if image workflows remain advertised; do not exclude a used
  runtime dependency.
- Bundle QSS, icon, Qt plugins, ModernGL requirements, examples, README, full
  third-party notices, and diagnostics support.
- Produce a checksummed release ZIP.

### 10.3 Actual packaged smoke mode

Add a deterministic packaged command such as:

```text
3D MASTER 2005.exe --smoke-test <temporary-output-directory>
```

Using the same command layer as the GUI, verify initialization, blank project,
primitive and profile/lathe creation, save/reopen, action assignment round-trip,
transformed OBJ/GLB export, and multi-object software fallback. Write a result
manifest. The build fails on nonzero exit, timeout, or missing/failed manifest.
File existence and size are not a smoke test.

### 10.4 Clean-machine evidence

Test the staged folder on a clean Windows profile/VM with no Python. Record OS,
architecture, launch, Home screenshot, first-model journey, save/reopen,
exports, logs, and release checksum.

### Exit gate

The checked-in script reproducibly creates the staged folder and ZIP, packaged
smoke passes, examples are present, and clean-machine evidence is recorded.

## 11. Phase 6 — Test expansion and release discipline

Add dedicated tests for DocumentController state, Home transitions, all Create
commands, full persistence/migrations, malformed inputs, world-scene export,
multi-mesh fallback, Settings application, and packaged smoke mode.

Manual matrix: 100/150/200% display scaling; GPU and forced software; paths
with spaces/non-ASCII; read-only/failed writes; missing textures/recent files;
multiple recoveries; keyboard-only onboarding; clean profile/no Python.

Evidence rules:

- Files or controls existing does not complete a phase.
- Complete means the exit gate passes.
- Record exact commands and results.
- Separate code inspection, automated verification, and manual verification.
- Never claim a changed test count without diff and collection evidence.
- Keep remaining failures visible.

## 12. V2 beta acceptance checklist

### Application and modelling

- [x] Home launches with no seeded scene.
- [x] New Empty contains zero objects and materials.
- [x] Each primitive creates with one click and supports undo/redo.
- [x] Profile, Lathe, Extrude, and Duplicate are undoable and dirty.
- [x] Five-minute vase journey works from fresh launch.
- [x] Document replacement clears stale editor state.

### Data integrity

- [x] Save -> Undo becomes dirty.
- [x] Every destructive transition uses Save/Discard/Cancel correctly.
- [x] Actions, active action, and assignments survive save/reopen.
- [x] Rename/delete/undo preserves object-keyed invariants.
- [x] Materials and project settings round-trip.
- [x] Atomic-save failure preserves the previous valid file.

### Recovery and safety

- [ ] Timer-driven autosave writes only dirty documents.
- [ ] Multiple recoveries are individually identifiable.
- [ ] Recovery failure preserves active state and reports an error.
- [ ] Recovery opens dirty and cannot silently overwrite recovery data.
- [ ] Version/migration and every declared limit are enforced.
- [ ] Malformed projects fail as `ProjectFormatError` within bounds.

### Rendering and export

- [ ] OBJ/GLB matches viewport transforms.
- [ ] Pose export behavior is explicit and tested.
- [ ] Software fallback renders all visible meshes.
- [ ] Status reports the backend actually used.
- [ ] Tessellation/render preferences affect output.

### Home, Settings, and onboarding

- [ ] Every visible Home button is connected and tested.
- [ ] Settings are accessible from Home and Editor.
- [ ] Settings affect actual behavior.
- [ ] Editor returns Home through dirty-safe Close Project.
- [ ] Empty-editor overlay and Quick Start work.

### Packaging and release

- [ ] `build_windows.ps1` runs from any working directory.
- [ ] Versions and pinned dependencies are consistent.
- [ ] Release includes executable, `_internal`, examples, README, licenses,
      resources, and diagnostics.
- [ ] Packaged smoke launches and exercises real workflows.
- [ ] Clean Windows/no-Python validation is recorded.
- [ ] All source and packaged tests pass.

## 13. Current status

### Phase 0 — COMPLETE (exit gate passed)

**Reproduced failures and fixes:**

1. **Create → Sphere adds menu action instead of geometry** — fixed. `_do_primitive` in `app.py` now routes directly to `CreatePrimitiveCommand` via `push_or_apply`. No nested menu-action registration remains.

2. **Create Profile/Spline changes project without dirty/undo state** — fixed. `CreateSplineProfileCommand` is now a redo-idempotent `QUndoCommand`. `MainWindow._create_spline()` routes through `push_or_apply`.

3. **Save → Undo leaves changed content marked clean** — fixed. `DocumentController.do_save()` calls `_mark_clean()` which syncs the undo stack. `MainWindow.push_command()` calls `doc_ctrl.mark_dirty()`.

4. **Orphaned return + indentation corruption** — fixed. `document_controller.py` rewritten with correct method boundaries and a proper Cancel return in `maybe_abandon_document()`.

**Evidence (automated tests):**

```
python -m pytest am3d/ui/test_phase0a.py am3d/ui/test_phase0b.py -q --tb=short
→ 14 passed in 2.07s

python -m pytest am3d/ -q --tb=short
→ 299 passed, 4 warnings in 12.80s
```

**Regression tests added:**
- `test_phase0a.py`: 7 tests covering primitive creation (all 6), undo/redo, collision-safe naming
- `test_phase0b.py`: 9 tests covering Save→Undo dirty, destructive transitions, new/open state reset, and Lathe/Extrude/Duplicate undo coverage

### Phase 1 — persistence and object-keyed state: CORE DONE, hardening open

**Evidence (automated tests):**

```
python -m pytest am3d -q --tb=short
→ 302 passed, 4 warnings
```

`test_phase1.py` (12 tests, new) covers: action assignment + active-action
round-trip through save/reopen, rename/delete rekeying `poses` /
`pose_offsets` / `action_assignments`, `DeleteActionCommand` undo restoring
prior active action + assignment map, and legacy `.am3d`/`.am3a` files still
loading. All 12 pass. Section 12 checkboxes for these items are now checked.

Not yet done from Phase 1: **6.4 material persistence** (`texture`,
`pattern`, `params`, `graph` fields) — this diff did not touch material
serialization; still open.

### 2026-08-26 — 6-way Haiku swarm review of the Phase 0/1 diff

Reviewed the uncommitted working-tree diff (`git diff HEAD`) implementing the
above. Verified findings (file:line, cited and re-checked against source):

- **[MAJOR]** `serializer.py:287` — spline load path (`sdata["cps"]`,
  `sdata["degree"]`, `sdata["closed"]`) does unvalidated key access; a
  malformed file raises a raw `KeyError` instead of `ProjectFormatError`.
  Belongs to blocker #8 above.
- **[MAJOR]** `serializer.py:29` — `_MAX_CONTAINER_DEPTH`,
  `_MAX_ARRAY_ELEMENTS`, `_ALLOWED_DTYPES` are declared, never enforced
  anywhere in the file. Same blocker #8.
- **[MAJOR]** `operators.py:126` (`LatheProfileCommand`) and the sibling
  `ExtrudeProfileCommand` bypass `Session.lathe_spline()`/`extrude_spline()`
  entirely, calling `make_lathe_profile`/`make_extrude_profile` directly.
  `app.py:376` extracts the profile as columns `[X,Z]`; `Session.lathe_spline`
  (`script.py:154`) extracts `[X,Y]` for the same conceptual operation — two
  independently-maintained lathe paths that can silently diverge. Violates
  plan section 5.2's explicit "reuse `Session.lathe_spline()`" instruction.
- **[MINOR]** `script.py:81` — loaded `active_action` is never checked
  against the loaded `actions` dict; a dangling reference from a hand-edited
  file surfaces as a deferred `KeyError` (at `script.py:373`) instead of
  failing at load time.
- **[MINOR]** `app.py:328` — collision-safe name allocation duplicated
  verbatim in `_do_primitive`, `_create_spline`, `_duplicate_object`; silently
  no-ops past 999 collisions with no user feedback.
- **[MINOR]** `document_controller.py:84` — atomic save has no `fsync` before
  rename, per this plan's own section 7.4.
- **[NIT]** `app.py:335` — `_build_create_menu_workaround` is dead (never
  called); section 5.1 said to delete the workaround, not stub it.
- **[NIT]** Duplicated patch-removal undo logic in
  `LatheProfileCommand.undo`/`ExtrudeProfileCommand.undo`; duplicated
  `_make_main_window`/`session` test fixtures across `test_phase0a.py` /
  `test_phase0b.py` / `test_phase1.py` instead of `conftest.py`.

Correctness and performance/memory lanes reported no issues, spot-verified.

**What's actually left (in priority order):**
1. Add the two MAJOR serializer gaps above to Phase 2 (7.3) scope explicitly —
   they are the concrete instances of blocker #8.
2. Reconcile `LatheProfileCommand`/`ExtrudeProfileCommand` with the
   `Session.lathe_spline()`/`extrude_spline()` facade (one code path, one axis
   convention) before Phase 4 export-parity work builds on top of it.
3. Validate `active_action` against loaded `actions` on load; extract the
   three duplicated naming loops into one helper that surfaces a real error
   past 999 collisions.
4. Add `fsync`/flush to `_ensure_atomic_save`; delete the dead
   `_build_create_menu_workaround` stub; centralize test fixtures in
   `conftest.py`.
5. Phase 1 material persistence (6.4) has not been started.
6. Phases 2-6 (autosave/recovery, Home/Settings, export parity, Windows
   packaging, test expansion) are unchanged from the original plan — not
   started.

None of the above is committed to git yet — this is all still uncommitted
working-tree state as of this review.

## 14. Agent execution protocol

1. Read this entire V2 plan before editing.
2. Inspect commit `0a7094d` and preserve unrelated changes.
3. Maintain a durable working plan matching Phases 0-6.
4. Begin with Phase 0; do not jump to packaging or cosmetics.
5. Add a failing regression test before or with every repair.
6. Reuse engine and command architecture; do not duplicate algorithms in
   `MainWindow`.
7. Run focused tests after each change and the full suite at phase exits.
8. Test exact user-facing actions, not only helpers.
9. Check Section 12 items only when evidence satisfies them.
10. Build with the checked-in script and test the staged release, not source.
11. Continue until acceptance or a genuine external blocker.

## 15. Final handoff requirements

Report completed phases and gates; files changed; tests and exact results;
migration/backward-compatibility evidence; absolute executable and ZIP paths;
packaged smoke manifest; clean-machine evidence; remaining unchecked boxes;
and known limitations without optimistic completion claims.
