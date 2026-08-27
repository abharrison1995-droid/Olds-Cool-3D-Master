# AM3D Modernization — Progress Report

Date: 2026-08-26
Status: **V1 Phases 0–5 below are complete and verified. A post-implementation
review found several of these "complete" phases did not satisfy their exit
gates for a real beta release — see [`docs/V2_BETA_IMPLEMENTATION_PLAN.md`](docs/V2_BETA_IMPLEMENTATION_PLAN.md),
which now supersedes this document and Phase 6 below as the source of truth
for beta-readiness. Current test count: 302 passing (see V2 plan section 13
for what's still open: serializer hardening, Lathe/Extrude architecture
duplication, material persistence, autosave/recovery, Home/Settings, export
parity, Windows packaging).**

Full plan lives in the approved implementation plan (bug review + 7 phases). This document tracks execution state through V1 Phase 5; V1 Phase 6 and all beta-remediation work moved to the V2 plan linked above.

## Completed

### Phase 0 — Bug-fix sprint ✅ (178 → 191 tests)

~28 review findings fixed, all with regression tests:

- **GPU crashes**: ambiguous ndarray truth-value bugs in `gpu/shaders.py` (uvs), `gpu/__init__.py:85` (camera), `gpu/__init__.py:103` (`finally: if not final`); double `gbuf.release()` removed.
- **Pixel-scale contract unified**: all render-boundary functions (`toon_render_view`, `sprite.render_view`, `gpu.render_frame`) return float32 RGBA 0..1; uint8 conversion only at QImage/file-export edges. Fixed sprite top-left-crop "downsample" (now block-mean), `_software_render` alpha/black-frame bugs, hardcoded `aspect=1.0` in `_perspective`.
- **Core math**: smartskin single-bone `IndexError` fixed; skinning now correct LBS delta `T_cur @ inv(T_rest)`; spline degree clamped to `len(pts)-1`; `build_extrude_net` rejects `n_rings<2`; `eval_curve(0/1)` evaluate as parameters; true angle-weighted normals in `compute_normals`.
- **Animation**: un-swapped Hermite in/out tangents; Catmull-Rom tangents scaled by key interval; `ActionBlender.sample` renormalizes per-bone weight mass.
- **Serialization**: keyframe in/out tangents persisted (`ti`/`to`); material bump/transparency/specular maps persisted; optional versioned `actions` section in `.am3d`; `Session.save_project/load_project` added and exported. Backward compatible — `assets/walk.am3a`, `assets/vase_demo.am3d` load (tested).
- **Scene/export correctness**: `Object3D.transform` baked into OBJ/glB/sprite exports; atlas layout unified on `ceil(sqrt(n))` grid (both `materials.bake_atlas` and `atlas_grid_layout`); torus tube seam closed; `_atlas_outdir` considers all export specs; per-patch material assignment actually works; dead `mesh._obj_base` removed.
- **GL hygiene**: gbuffer texture filters use `moderngl.NEAREST`; `lighting.light_pass` releases VBO/VAO per call.
- **Viewport (old)**: camera mouse control actually re-renders; pan translates eye+target; renders all meshes; QImage buffer lifetime fixed.
- Verified: `python -m pytest am3d -q` → 191 passed; `scripts/demo_vase.py` runs clean.
- Investigated `[render] hero: 0 verts` in demo output → **not a bug** (`hero` is a bone-only character with no geometry).

### Phase 1 — Viewport rewrite ✅ (191 → 208 tests)

- New `am3d/ui/camera.py` — Qt-free orbit `Camera` (yaw/pitch/distance/target, view+perspective matrices with real aspect, pan moves eye+target, presets front/side/top/perspective, `view_ray()`).
- New `am3d/ui/picking.py` — vectorized Möller–Trumbore ray-triangle picking, `pick_object()`.
- New `am3d/ui/viewport3d.py` — `Viewport` rewrite (old `viewport.py` is a compat shim): renders all objects, bakes object transforms in `_scene_meshes` (note: transform bake lives here, not in `tessellate_project` — revisit if exports and viewport should share it), tessellation cache invalidated via `refresh()`, grid floor + wireframe (W) + selection-box overlays, click-to-select with `selection_changed = Signal(str, int)` + `set_selected(name)`, hotkeys 1/3/7/0 view presets, G grid toggle. Controls: MMB orbit, Shift+MMB pan, wheel zoom, LMB orbit (A:M style) + LMB click select.
- Offscreen end-to-end smoke test: MainWindow renders 640×480 toon frame, center click picks the seeded sphere.

### Phase 2 — Outliner + Properties ✅ (208 → 216 tests)

- `am3d/ui/object_panel.py` rewritten as **Outliner** (`ObjectDock`): Scene → Objects → Patches/Splines/Bones/Materials tree, visibility checkboxes, F2/double-click rename, Del + context menu (Add/Rename/Delete with confirm), two-way selection sync with viewport, `context_changed(kind, object_name, item_name)` signal, signal-loop guards.
- New `am3d/ui/properties.py` — `PropertiesDock`, tabbed context-sensitive editor: Object (name, TRS spinboxes, visibility), Bone (head/tail), Material (albedo swatch + bump/transparency/specular paths), Render (supersample, toon toggle).
- `segment_panel.py` / `material_panel.py` deleted (folded into the above).
- Model additions: `Object3D.visible`, `Project.rename_object`, `Project.render_settings` dict, `Session.rename_object` / `set_object_visible`, `compose_trs`/`decompose_trs` in mathutil; all serialized (backward compatible).
- `data_changed` signal now actually wired through panels → viewport.

### Phase 3 — Workspaces, tiled layout, retro theme ✅ (216 → 223 tests)

- `am3d/ui/workspaces.py` — Workspace dataclass registry (Layout/Model/Rig/Animate/Render mapped to the classic modes), `WorkspaceTabBar`, `ToolStrip`, JSON layout-state round-trip.
- `am3d/ui/area_layout.py` — `TiledArea` QSplitter layout with collapsible area panels; per-workspace splitter sizes saved/restored on switch.
- `am3d/ui/theme_am2005.qss` — retro A:M 2005 theme; status bar with workspace/selection/frame/backend labels.

### Phase 4 — Tools, gizmos, undo ✅ (223 → 259 tests)

- `am3d/ui/operators.py` — QUndoCommand layer on a MainWindow `QUndoStack` (Edit menu Undo/Redo, Ctrl+Z / Ctrl+Y / Ctrl+Shift+Z). Commands: object rename/delete/add, visibility, TRS transform, material add/delete/color/maps, bone head/tail, bone pose, CP move/insert/remove. Absolute before/after values make redo idempotent (live drags commit one command on release). Panels route through `MainWindow.push_command` (`push_or_apply` fallback for isolated panels); outliner tree edits apply synchronously and defer only the stack push to avoid re-entrant tree clears.
- File→New dirty-check prompt when the undo stack isn't clean; save marks clean; open/new clear the stack.
- `am3d/ui/gizmos.py` — Qt-free gizmo geometry + hit-testing + drag math (translate arrows, rotate rings, scale handles + centre, constant screen size). `viewport3d.py` draws them over the render; drag updates `Object3D.transform` live, one undo command on release. G/R/S modal grab (view-plane translate / view-axis rotate / uniform scale; LMB or Enter confirms, Esc cancels).
- Hotkeys: W/E gizmo translate/rotate, R modal rotate-grab, X gizmo off (grid/wireframe toggles moved to Shift+G/Shift+W). Toolbar buttons in the ToolStrip mirror the gizmo mode both ways.
- `am3d/ui/tools_spline.py` — Model workspace CP editing: CP overlay handles, click select, drag move (view-plane ray), A / double-click inserts midpoint CP, X/Delete removes with the degree+1 minimum guard; all undoable, written to the `Spline` model in object space.
- `am3d/ui/tools_bone.py` + `Session.pose_bone/clear_pose/apply_pose` — pose rotations stored per object/bone (Euler deg or 3x3), composed with `rest_local_transform` and run through `fk_pose` (`rigging.rest_local_transform` is the new public alias). Rig workspace draws posed bone chains; dragging the rotate ring on the selected bone sets its pose (undoable); ToolStrip has a Clear Pose button. Posed world transforms cached on `session.posed_transforms` for Phase 5 skinning.
- ToolStrip hint placeholder replaced by real per-workspace option widgets (`ToolStrip.set_options`): gizmo buttons in Layout/Model, CP tool hints in Model, pose options in Rig.

Undo coverage: object rename/delete/add, visibility (outliner + properties), TRS spinboxes, gizmo drags, modal grabs, material color/maps/add/delete, bone head/tail, bone pose, CP move/insert/delete. **Not undoable:** render-settings edits (supersample/toon), camera moves, selection changes.

Deferred to Phase 5: skinned viewport deform (posed bones move the bone overlay only; mesh deform via smartskin not wired), ik_two_bone UI wiring, keyframe/dope-sheet editors.

### Phase 5 — Animation editors ✅ (259 → 276 tests)

- `am3d/ui/dopesheet.py` — new **TimelineDock** (same class name; `timeline.py` is now a compat shim): frame ruler with adaptive ticks, one row per animated bone of the active action, diamond key markers. Click/drag the ruler to scrub; drag keys to move them (ghost preview, one undoable `MoveKeyCommand` on release); click selects, `Delete`/`X` removes selected keys (undoable, multi-channel index-safe), `I` keys the context bone's pose, `Space` toggles playback. Transport row: Play/Pause (QTimer at FPS, wraps at range end), frame spin, range start/end + FPS spinboxes (undoable via `SetAnimationSettingsCommand`), action combo, Auto-key toggle.
- Settings: `Project.animation_settings = {"frame_start": 0, "frame_end": 120, "fps": 30.0}` (0–120 @ 30 fps == the old hardcoded 4.0 s), serialized backward-compatibly in `.am3d` (old files load with defaults).
- Pose chain: `TimelineDock.set_frame` → `Session.apply_action_frame` samples the assigned Action (rotate channels = Euler XYZ radians → pose rotations; translate = bone-local offsets via new `session.pose_offsets`, composed in `apply_pose`) → `fk_pose` → `session.posed_transforms`. The viewport bone overlay is now drawn in **Animate** as well as Rig, and `_scene_meshes` skins weighted objects through the new `rigging.deform_object` (canonical CP order: patch interiors C-order, then splines; `Bone.cp_weights` indexes it) before tessellation — deform recomputes only on refresh (frame/pose change).
- Action management: `Session.delete_action` / `rename_action` / `set_active_action` / `assign_action` / `unassign_action` / `insert_keyframe` / `remove_keyframe` / `key_bone_from_pose` (pose 3x3 → Euler key round-trips through `apply_action_frame`), all exported on the scripting facade. Outliner has an **Actions** node (assignment shown in the label) with Add/Rename/Delete/**Assign to Selected Object**; File → Import Action (.am3a). Selecting an action row makes it the active action. `assets/walk.am3a` loads and drives the hero skeleton (tested at several frames against `Action.sample`).
- New undo commands: `CreateActionCommand`, `DeleteActionCommand`, `RenameActionCommand`, `AssignActionCommand`, `InsertKeyCommand` (restores a replaced key on undo), `MoveKeyCommand` (key identity, resort), `DeleteKeyCommand`, `SetAnimationSettingsCommand`. Auto-key: after a viewport bone-ring drag, `_auto_key` keys the bone at the current frame when the dock's Auto-key is on.
- Animate workspace now includes the outliner (bone selection for keying) — `test_main_window_smoke` updated accordingly.

Deferred to Phase 6: graph editor, ik_two_bone UI wiring, pose/assignment serialization in .am3d, GPU skinning.

## Not started

- **Phase 6 — Polish**: pie menus, asset browser, `atlas`/`render` export formats, quad-view, GPU skinning, graph editor, ik_two_bone UI wiring, persistence of poses/action assignments in .am3d. *(Superseded — pose/assignment persistence now lands as part of the V2 plan's Phase 1; the rest of this list is still genuinely not started.)*

## Known loose ends

- Render-tab settings don't affect the GPU render path (software toon path only).
- Deleting an object leaves a stale properties context (harmless; guarded).
- Transform baking duplicated between viewport `_scene_meshes` and export path — consider unifying in `tessellate_project`.
- Software rasterizer is orthographic (perspective only via camera transform for picking/overlays); perspective-correct CPU rasterization is open.
- `Hook` / `Patch.splines` connectivity still decorative in the engine; 3-sided patches unsupported.

## How to resume

Work here now tracks `docs/V2_BETA_IMPLEMENTATION_PLAN.md`, not this
document's Phase 6. That plan's section 13 has current status and a
prioritized remaining-work list (serializer hardening gaps and the
Lathe/Extrude facade duplication first, then material persistence, then
Phases 2–6 of that plan). V1 Phase 6 (polish: pie menus, asset browser,
export formats, quad-view, GPU skinning) remains genuinely not started and
comes after the V2 plan's beta-readiness work.
