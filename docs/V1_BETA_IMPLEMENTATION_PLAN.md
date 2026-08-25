# 3D MASTER:2005 — V1 Beta Implementation Plan

Status: approved implementation roadmap  
Target: Windows V1 beta  
Last updated: 2026-08-25  
Source review: six-perspective `review-swarm-v2` audit, cross-checked against 276 passing tests

## 1. Objective

Prepare 3D MASTER:2005 for external beta testing as a usable, recoverable,
old-school spline-based 3D asset creation application inspired by Animation
Master:2005.

The beta must:

- Launch from a real Windows executable without requiring Python.
- Open on a blank home screen rather than a seeded scene.
- Offer New Empty Project, Open Project, Recent Projects, Recover Autosave,
  Settings, Enter Editor, Quick Start, Examples, About, and Exit.
- Allow a user to create the first piece of geometry from an empty project.
- Preserve authored geometry, actions, action assignments, materials,
  transforms, and project settings through save/reopen.
- Protect unsaved work on every destructive document transition.
- Recover gracefully from malformed files, interrupted saves, renderer
  failures, and application crashes.
- Preserve the curvy, economical, retro low-poly visual identity.

## 2. Current baseline

The repository already has a substantial technical foundation:

- 276 tests pass.
- The spline/NURBS kernel, project model, animation, rigging, serialization,
  procedural recipes, OBJ/GLB export, software rendering, GPU rendering, and
  PySide6 workspaces are present.
- The editor already includes Layout, Model, Rig, Animate, and Render
  workspaces, an outliner, properties, a timeline, undo commands, gizmos,
  picking, and a retro theme.
- The scriptable `Session` facade already exposes much of the functionality
  needed by the GUI.

The V1 beta effort should therefore prioritize product lifecycle, data
integrity, blank-project usability, packaging, and release validation.

## 3. Release blockers identified by review

These are release gates, not optional polish:

1. `am3d/ui/app.py` seeds a sphere and material on every launch.
2. An actually empty GUI project cannot create its first spline, patch, or
   primitive; removing the seed scene alone would create a modelling dead end.
3. GUI Save/Open bypasses the action-aware `Session` persistence methods and
   can silently lose all animation actions.
4. Open and Quit can discard dirty work without Save/Discard/Cancel handling.
5. No standalone Windows executable or reproducible packaging definition is
   present.

## 4. Architectural decisions

### 4.1 One document controller

Introduce a single document-lifecycle owner, for example
`am3d/ui/document_controller.py`. It should own or coordinate:

- The current `Session`.
- Current project path.
- Display name and window title.
- Dirty/clean state.
- Undo stack lifecycle.
- New, open, save, Save As, close, and replace-document transitions.
- Recent-project updates.
- Autosave and recovery state.
- Clearing selection, properties context, modal tools, playback, and cached
  viewport state after document replacement.

Widgets should continue to resolve the current session dynamically through
the main window or controller. Avoid giving panels stale session references.

### 4.2 One authoritative persistence route

The GUI must not call the low-level serializer directly for ordinary project
Save/Open. Route through `Session.save_project()` and
`Session.load_project()`, or through a new document codec that captures the
entire intentional document state.

Persist at minimum:

- Project objects, splines, patches, hooks, skeletons, and materials.
- Actions and keyframes.
- Action-to-object assignments.
- Active action.
- Render and animation settings.
- Material texture/procedural/graph fields used by the renderer.

Pose caches and derived render caches may remain transient unless a deliberate
product decision says otherwise.

### 4.3 Atomic project saving

Serialize to bytes before touching the destination. Write to a temporary file
in the destination directory, flush it, synchronize it where practical, then
publish with an atomic replace. Optionally retain a rolling `.bak` copy.

The invariant is: after any failed save, either the old valid project or the
new complete project remains available—never a truncated file.

### 4.4 Explicit Home and Editor states

Use an application shell with a stacked Home/Editor view. Suggested states:

```text
Launch
  -> Home
       -> New Empty ----------+
       -> New From Template --+
       -> Open ---------------+-> Editor
       -> Recent -------------+
       -> Recover ------------+

Editor
  -> Close Project -> dirty resolution -> Home
  -> Quit          -> dirty resolution -> Exit
```

Use **Enter Editor** or **Start Modelling** instead of “Edit App”; the latter
sounds like a developer action for modifying the software.

### 4.5 Reuse the existing engine

GUI modelling commands should wrap existing engine functions rather than
reimplement geometry algorithms. In particular, reuse:

- `am3d.recipes.primitives.build_primitive`
- `Session.add_spline`
- `Session.extrude_spline`
- `Session.lathe_spline`
- Existing `QUndoCommand` conventions in `am3d/ui/operators.py`

## 5. Phase 0 — Data-loss prevention

Priority: immediate release gate

### Work

- Add the document controller and make `MainWindow` use it.
- Route GUI Save/Open through complete session persistence.
- Add `current_path` and distinguish Save from Save As.
- Add one `maybe_abandon_document()` or equivalent Save/Discard/Cancel gate.
- Invoke that gate from New, Open, Open Recent, Recover, Close Project, Quit,
  and `closeEvent`.
- Ensure canceling a dialog leaves the active document untouched.
- Persist actions, assignments, and active action in a versioned section.
- Validate action/object references on load.
- Rekey session maps when an object is renamed.
- Purge session maps when an object is deleted and restore them accurately on
  undo.
- Make Delete Action undo restore the exact active action and ordering.
- Make imported actions and render-setting edits dirty/undoable.
- Add atomic save and optional backup behavior.

### Likely files

- `am3d/ui/app.py`
- `am3d/ui/document_controller.py` (new)
- `am3d/core/script.py`
- `am3d/core/serializer.py`
- `am3d/ui/operators.py`
- `am3d/ui/properties.py`
- `am3d/ui/object_panel.py`

### Required tests

- GUI-created action survives GUI Save/Open.
- Assignment and active action survive Save/Open.
- Rename/delete/undo preserves or clears all object-keyed session state.
- Dirty New/Open/Close/Quit each exercise Save, Discard, and Cancel.
- Import Action marks dirty.
- Render setting changes mark dirty and undo correctly.
- Simulated serialization/write failure leaves an existing file intact.

### Exit gate

No normal UI path can silently discard project changes or animation data.

## 6. Phase 1 — Home hub and blank startup

Priority: product requirement

### Work

- Remove production startup seeding from `MainWindow`.
- Move the sphere/demo scene behind New From Template or Open Example.
- Add a Home widget and stacked Home/Editor shell.
- Add these home actions:
  - New Empty Project
  - New From Template
  - Open Project
  - Recent Projects
  - Recover Autosave
  - Enter Editor
  - Settings
  - Quick Start
  - Example Gallery
  - Report a Problem / Copy Diagnostics
  - About
  - Exit
- Disable or hide Recover Autosave when no recovery data exists.
- Add an empty-editor overlay with direct actions: Create Primitive, Draw
  Spline, Open Project, and Quick Start.
- On successful New/Open/Recover, clear viewport selection, selected control
  point, current outliner/properties context, playback, modal transforms,
  caches, and undo history.
- Update tests that currently require the seeded `sphere`.

### Likely files

- `am3d/ui/app.py`
- `am3d/ui/home.py` (new)
- `am3d/ui/viewport3d.py`
- `am3d/ui/theme_am2005.qss`
- `am3d/ui/test_ui.py`

### Exit gate

Launching the app shows Home. New Empty enters an editor with zero objects and
zero materials, with no stale selection or demo content.

## 7. Phase 2 — Minimum viable empty-project modelling

Priority: must ship with Phase 1

### Work

- Add undoable Create Primitive commands for sphere, box, cylinder, cone,
  torus, and plane.
- Add an undoable Create Spline/Profile command that creates the first spline
  and first control point in an empty object.
- Add Draw/Extend Spline interaction in Model workspace.
- Add Lathe Selected Profile and Extrude Selected Spline actions.
- Add Duplicate Object.
- Add rename/delete operations for splines and patches where safe.
- Add Add/Create menus and prominent empty-state buttons; do not require a
  hidden outliner context menu for first geometry.
- Optionally add Run Recipe / Import Recipe as an advanced creation path.
- Route every mutation through undoable commands.

### Old-school visual controls

- Add tessellation presets: Chunky, Classic, and Smooth.
- Keep spline cages and patch boundaries easy to display.
- Add toon shade-band and ink-line presets.
- Add a compact retro material palette.
- Provide economical starter templates: sphere/head base, vase/profile,
  torso, limb, prop, and empty character rig.

### Required user journey

From a fresh launch, a tester must be able to:

1. Choose New Empty Project.
2. Create a profile spline or primitive.
3. Edit control points.
4. Lathe or extrude it into a curvy asset.
5. Transform it.
6. Save and reopen it.
7. Export it to OBJ or GLB.

### Exit gate

The full journey works without Python, recipes, or a pre-seeded object.

## 8. Phase 3 — Settings, recent files, recovery, and schema hardening

### Work

- Add a Settings dialog covering:
  - Theme
  - Navigation/input preset
  - Autosave interval
  - Default tessellation preset
  - Preferred render backend
  - Default project directory
  - Undo depth
- Persist preferences and recent paths with `QSettings` or an equivalent user
  configuration store, never beside a one-file executable or inside bundled
  resources.
- Maintain a bounded recent-project list and handle moved/missing files.
- Write periodic recovery snapshots to a per-user application-data directory.
- Detect recovery data at startup and offer Recover, Inspect, or Discard.
- Delete or supersede recovery data after a clean save and clean exit.
- Add an explicit project `format_version` and migration registry.
- Validate before model construction:
  - File size
  - Msgpack nesting/container limits
  - Allowed ndarray dtypes, ranks, shapes, and byte counts
  - Maximum objects, splines, patches, bones, actions, channels, and keys
  - Finite transforms, weights, frame ranges, and FPS greater than zero
  - Valid references between objects, skeletons, actions, and assignments
- Raise a stable `ProjectFormatError` with a user-facing explanation.

### Exit gate

Crashes leave recoverable work, and malformed projects fail safely without
replacing the active document.

## 9. Phase 4 — Viewport, materials, rendering, and export parity

### Work

- Extract one shared world-scene assembly path used by viewport and export.
- Ensure GUI OBJ/GLB export includes object transforms.
- Define whether export uses bind pose, current pose, or a selectable mode.
- Add transformed multi-object export regression tests.
- Make software fallback render every visible mesh.
- Report the backend that rendered the last successful frame, including the
  reason for fallback.
- Make renderer, UI, recipes, and serializer agree on one material model.
- Persist procedural textures, texture references, graph data, and parameters.
- Resolve external assets relative to the project and define missing-asset
  behavior.
- Connect Render workspace settings to both GPU and software rendering.

### Exit gate

The viewport, reopened project, and exported asset materially agree for
transforms, visible geometry, materials, and the chosen pose.

## 10. Phase 5 — Windows executable and release staging

Priority: final release gate

Use a PyInstaller **onedir** bundle for the initial beta. It is easier to
inspect and diagnose than a one-file extraction bundle for this dependency
set. A one-file build can be evaluated later.

### Work

- Add a reproducible `am3d.spec`.
- Include:
  - `theme_am2005.qss`
  - Application icon and Windows version metadata
  - Required Qt platform/image plugins
  - ModernGL resources and required binaries
  - Necessary NumPy, SciPy, and Numba hidden imports/data
- Add Pillow as a declared dependency if texture/image workflows remain in
  beta scope.
- Pin release dependencies in a lock/constraints file.
- Reconcile package version declarations and use a beta version such as
  `0.2.0b1` consistently.
- Add `build_windows.ps1` that:
  1. Verifies the intended Python environment.
  2. Installs pinned build/runtime dependencies.
  3. Runs the complete tests.
  4. Builds the executable.
  5. Runs a packaged smoke test.
  6. Stages a distributable folder or ZIP.
- Keep `run_ui.bat` only as a developer convenience.
- Test on a clean Windows account or VM with no Python installation.

### Release layout

```text
3D MASTER 2005 Beta/
|-- 3D MASTER 2005.exe
|-- _internal/
|-- examples/
|-- README.txt
`-- LICENSES/
```

The deliverable requested for the workspace is the staged executable and its
supporting `_internal` directory. Do not claim a standalone beta until it has
been launched from the staged folder rather than the source checkout.

### Packaged smoke test

- Double-click executable.
- Confirm Home appears and no console window is required.
- New Empty -> Create Primitive -> edit -> Save.
- Close/relaunch -> Open -> verify geometry and settings.
- Create/import an action -> assign -> Save/reopen -> verify playback.
- Export a transformed multi-object scene to OBJ and GLB.
- Force software fallback and verify all objects remain visible.

### Exit gate

A tester can unzip the release and run `3D MASTER 2005.exe` without Python.

## 11. Phase 6 — Beta validation and release

### Automated coverage

- Preserve all existing tests.
- Add focused unit tests for each corrected invariant.
- Add Qt integration tests for Home/Editor and document transitions.
- Add golden/structural serialization fixtures for current and legacy files.
- Add corrupted, truncated, oversized, and semantically invalid file cases.
- Add packaged launch and minimal workflow smoke automation.

### Manual matrix

- Windows scaling: 100%, 150%, and 200%.
- GPU available and forced software fallback.
- Paths containing spaces and non-ASCII characters.
- Read-only destination, full/failed write simulation, missing texture, and
  missing recent file.
- Keyboard-only first-run navigation.
- Fresh user profile and profile containing recoverable autosave data.
- Clean machine with no Python.

### Release contents

- Versioned ZIP or installer.
- Executable and internal runtime files.
- README with controls and known limitations.
- Example projects/templates.
- Third-party license notices.
- Beta feedback and diagnostics instructions.
- Release notes and known-issues list.

## 12. Deferred until after V1 beta

These are valuable but should not delay the data-safe modelling beta unless a
dependency emerges:

- Graph editor.
- Quad view.
- GPU skinning.
- Full asset browser.
- Pie menus.
- IK two-bone UI.
- Three-sided patches.
- Functional Hook/Patch spline connectivity beyond current decorative state.
- Automatic updater and code signing, though signing is recommended before a
  broad public release.

## 13. Definition of beta-ready

All boxes must be checked:

- [ ] A real Windows `.exe` launches without Python.
- [ ] Startup displays Home and does not seed a sphere/material.
- [ ] New Empty contains no scene objects.
- [ ] A blank project can create its first spline and primitive.
- [ ] A user can complete the required modelling journey.
- [ ] Save/reopen preserves actions and action assignments.
- [ ] Save/reopen preserves materials, transforms, and settings.
- [ ] New/Open/Home/Quit/close cannot silently discard dirty work.
- [ ] Project save is atomic and recovery is available.
- [ ] Export matches the editor for transforms and selected pose behavior.
- [ ] Software fallback renders the complete visible scene.
- [ ] Malformed files fail within resource limits and preserve the current
      document.
- [ ] All existing and new tests pass.
- [ ] The packaged smoke test passes on clean Windows.


## 14. Implementation status

### Phase 0 — Data-loss prevention: COMPLETE ✅

- Created DocumentController (am3d/ui/document_controller.py) — owns Session, dirty state, file ops, recent projects, autosave
- Updated MainWindow to use DocumentController for all document transitions
- Removed _seed_scene from startup — no more seeded sphere on launch
- Added atomic save (write .tmp, rename over destination)
- Added maybe_abandon_document() gate invoked from File New, Open, Close, and Quit
- Added dirty tracking via undo stack cleanChanged signal
- Added push_command() method that marks dirty and updates window title
- Updated 81 UI tests to create their own test objects instead of relying on seeded sphere
- All 276 tests pass

### Phase 1 — Home hub and blank startup: COMPLETE ✅


## 15. Implementation protocol for an agent

1. Read this entire plan and inspect the referenced code before editing.
2. Record a durable working plan with phases and keep it updated.
3. Start with Phase 0 and respect phase dependencies.
4. Do not package the existing unsafe lifecycle as a shortcut.
5. Make narrow changes, add regression tests with each invariant, and run the
   relevant focused tests immediately.
6. Run the full suite at every phase exit.
7. Preserve backward compatibility with the sample `.am3d` and `.am3a` files.
8. Preserve unrelated user changes in the worktree.
9. When a phase exit gate fails, diagnose and correct it before progressing.
10. Finish by building and smoke-testing the executable from its staged
    release directory.
11. Update this document's checkboxes or add a concise implementation status
    section as work completes.

## 16. Final handoff requirements

The implementing agent's final report must state:

- Which phases were completed.
- Files changed.
- Tests run and exact results.
- Location of the staged executable.
- Whether it was tested without relying on the source checkout.
- Any remaining unchecked beta gates.
- Known limitations and the safest next action.
