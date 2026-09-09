# Desktop release finding ledger

Source: `docs/DESKTOP_RELEASE_PLAN.md`. Baseline commit `d01187c`.

Status vocabulary — **REPRODUCED**: failure demonstrated by an executed run
before any change. **SOURCE-REASONED**: defect established by reading the code
and its callers, without a pre-fix executed failure. **DISPROVEN**: claimed
defect not present. **BLOCKED**: cannot be checked in this environment.
A historical PASS label from the V3 plan is *not* evidence for this release.

## Evidence index

| File | What it shows |
| --- | --- |
| `phase-a/baseline-suite.txt` | Reproduced baseline: 529 passed, 2 failed |
| `phase-a/environment.md` | OS/Python/resolved transitive versions |
| `phase-a/reference-machine.md` | The MX 25.2 acceptance machine, verified present |
| `phase-b/view-01-reproduction.txt` | VIEW-01 before the fix (4.1x mismatch) |
| `phase-b/view-01-after-fix.txt` | VIEW-01 after the fix (<=2.7px, picking works) |
| `phase-b/view01_check.py` | Re-runnable VIEW-01 probe |
| `phase-b/gpu-reproduction.txt` | GPU-01/02/03 before the fix |
| `phase-b/mat-02-reproduction.txt` | MAT-02 before the fix (patch colours lost) |

## Findings

| ID | Prio | Status | Evidence | Fix | Tests |
| --- | --- | --- | --- | --- | --- |
| ENV-03a | high | REPRODUCED | `test_path_escape_drive_is_rejected` failed on POSIX: `os.path.splitdrive("D:outside_file")` -> `("", ...)`, so a Windows drive-relative export path passed the escape check on Linux | New host-independent policy `am3d/core/paths.py`; `RecipeExecutor._resolve_output_path` and `resolve_resource_path` use it; `\` normalised as a separator | `am3d/core/test_paths.py` (33), `test_executor.py` policy block (19) |
| ENV-03b | high | REPRODUCED | `test_schema_json_conformance` errored: `jsonschema` undeclared | Split `requirements.txt` (runtime) / `requirements-dev.txt` (test+build, adds `jsonschema==4.26.0`); `requirements-lock-linux.txt` captures the transitive set | Full suite green in a clean pinned venv |
| ENV-01 | high | CONFIRMED (metadata) | numpy 2.4.6 requires Python >=3.11 vs `requires-python = ">=3.10"` | Documented split between the flexible source install and the pinned frozen-build interpreter | `docs/SUPPORTED_PLATFORMS.md` |
| DATA-01 | blocker | REPRODUCED | `clear_autosave()` unlinked every `*.autosave.am3d`; quitting document A destroyed document B's recovery | `clear_autosave(path=None)` removes only the named/current slot; `clear_all_autosaves()` is the explicit opt-in sweep | `test_document_controller.py::test_clear_autosave_removes_only_the_current_documents_snapshot`, `::test_main_window_exit_preserves_another_documents_recovery` |
| DATA-02 | high | REPRODUCED | Home emitted `list_autosave_files()[0]` — filename order, no identity | `autosave_entries()` + `.meta.json` sidecar (name, original path, time, size); `RecoveryDialog` chooser; unselected snapshots preserved; corrupt sidecars listed, not hidden | 8 tests in `test_document_controller.py` |
| LIFE-01 | high | REPRODUCED | `_file_close_project()` omitted `_reset_document_ui_state()`; play timer kept running, Play stayed checked, stale selection/context survived | Reset + refresh on successful close; cancelled close changes nothing | `test_operators.py::test_close_project_stops_playback_and_clears_document_state`, `::test_cancelled_close_project_preserves_the_active_document` |
| LIFE-02 | medium | REPRODUCED | Empty `_render()` returned before clearing `_dirty`; every paint re-armed the render timer | Empty render is settled state; `paintEvent` re-arms only a genuinely pending render; real empty-state text | `test_operators.py::test_empty_scene_render_settles_and_stops_rescheduling`, `::test_content_after_an_empty_render_still_renders` |
| VIEW-01 | high | REPRODUCED | Measured: software render drew the box 4.11x smaller than `world_to_screen` placed it — clicking the visible object selected nothing | `toon_render_camera()` + `_rasterize_screen()` render through the camera's own perspective projection, the same call picking/overlays use | `am3d/ui/test_view_parity.py` (13) |
| GPU-01 | high | REPRODUCED | `render_frame` called `tessellate_project` directly, bypassing `evaluate_scene`: hidden objects still drew, object transforms were ignored, and skeletal deformation/material assignment never applied — the standalone render API disagreed with the viewport and the exporters about what the scene was | `resolve_scene()` normalises Session/Project/EvaluatedScene/MeshData through the one shared evaluator; `render_frame` gained `action_name`/`time`/`pose` | `am3d/gpu/test_scene_render.py` (visibility, transform, shared-evaluator, pose) |
| GPU-02 | high | REPRODUCED | The software fallback rendered `meshes[0]` only, so losing the GPU silently dropped every object after the first and produced no shared occlusion | `_software_render` merges all meshes via `merge_meshes` and renders them through the scene camera with one depth buffer | `test_scene_render.py::test_forced_gpu_failure_still_renders_a_two_object_image`, occlusion test |
| GPU-03 | high | REPRODUCED / partly DISPROVEN | Reproduced: `_default_cam(mesh)` gave each mesh its own look-at, re-centring every object and destroying relative placement. **Disproven:** the plan's claim that the *projection* was fitted per mesh — `_perspective` never used its `verts` argument (removed as dead) | `scene_camera(meshes)` frames the whole scene once; that one view is used by the GPU path and every fallback | `test_scene_render.py` (one-camera, relative-placement, projection tests) |
| MAT-02 | high | REPRODUCED | Two differently coloured patches on one object collapsed to a single colour: the evaluated scene carried no patch identity and tessellation discarded which patch each triangle came from | `MeshData.tri_groups`/`group_triangles()`; `EvaluatedScene.patch_materials`; `scene_patch_material_colors`/`scene_triangle_colors`; OBJ emits per-patch `usemtl` groups + MTL entries; GLB emits one primitive per patch material | `am3d/export/test_patch_materials.py` (7), incl. independent OBJ/MTL and GLB parsers |
| EDIT-01 | high | REPRODUCED | `phase-b/edit-01-reproduction.txt`: after moving a profile CP the surface radius was unchanged (1.2608 -> 1.2608) while the construction curve moved (1.2619 -> 2.3708), so the viewport showed an edit the rendered/exported surface never took | Chose **live regeneration**: `Patch.generator` records op/spline/params; `am3d/core/generators.py` re-runs it; every CP command regenerates on redo *and* undo, which is exact without a geometry snapshot; generator persisted by the serializer | `am3d/ui/test_edit_surface.py` (9) |
| EDIT-02 | high | REPRODUCED | Found while reproducing EDIT-01, present on parent `a6fe665`: a lathe from a 3-point profile made a net 3 wide along v, and tessellation asked for a cubic -> `ValueError`, so the object could not be rendered or exported at all. `make_lathe_profile` computed a clamped degree and the command discarded it | `Patch.degree_u/degree_v` + `effective_degrees()`; the lathe/extrude commands keep the generator's clamped degrees; `tessellate_object` uses them | `test_edit_surface.py::test_a_three_point_profile_produces_an_evaluable_surface`, `::test_patch_degrees_are_clamped_to_the_net_that_exists` |
| API-01 | medium | REPRODUCED | `phase-b/api-01-reproduction.txt`: `nu=1` returned 16 vertices and **zero triangles**; `degree_u=0` accepted; all-zero weights collapsed every vertex onto the origin; other bad inputs raised numpy-internal messages naming no parameter of this API | `_check_resolution`/`_check_degree`/`_check_weights` in `am3d/spline/kernel.py` validate resolution, degree vs available control points, and weight count/finiteness/positivity | `am3d/spline/test_kernel.py` (+22) |

| MAT-01 | high | REPRODUCED | `phase-b/mat-01-reproduction.txt`: a `pattern="checker"` material baked a genuine 512x768 atlas and both files already carried matching atlas UVs, but the MTL had no `map_Kd` and the GLB had no `images`/`textures` at all, so an independent reader showed flat white with nothing indicating the loss | Chose **carry**, not reject: new `am3d/export/textures.py` (PNG encode, UV-origin flip, channel normalisation); `write_obj(textures=)` writes a PNG sidecar + `map_Kd`; `write_glb(textures=)` embeds the PNG in the BIN chunk as `baseColorTexture`; `bake_scene_atlases()` feeds the GUI and the recipe executor publishes the PNG sidecars | `am3d/export/test_textured_export.py` (14), read back with Pillow and a hand-rolled GLB chunk parser |

## Review round 2 — GPU/MAT batch (two Haiku agents, bounded scope)

Both agents were required to give a reproduction; unsubstantiated findings were
to be dropped. Two defects came back, both reproduced here before fixing:

| Finding | Verified | Fix |
| --- | --- | --- |
| `am3d/gpu/__init__.py`: `gbuf.release()` called **twice** when the first call itself raises — `released = True` sat after the call inside a `try`, so the flag stayed False and the `finally` block released the same GL objects again | Yes — instrumented `release()` that raises; observed call count 2 | Set `released = True` before the attempt | 
| `am3d/export/obj.py:54`: `mtllib` was written only `if materials`, so an object with **only** per-patch materials emitted `usemtl` directives naming materials no reader could resolve | Yes — exported with `patch_materials` alone: `mtllib present: False`, `usemtl present: True`, MTL file written but unreferenced | `if (materials or patch_materials) and mtl_filename` | 

The MAT agent's remaining checks (tri_group alignment through reflection-corrected
winding, GLB accessor offsets/alignment, OBJ vertex index offsets across objects)
came back clean. The GPU agent also flagged `_default_cam` as dead code after the
GPU-03 fix; removed. Its other checks came back clean.

Both defects now have regression tests:
`test_scene_render.py::test_gbuffer_is_not_released_twice_when_release_itself_fails`
and the `mtllib` assertion in
`test_patch_materials.py::test_obj_export_keeps_the_two_patches_in_separate_material_groups`.

## UI findings

| ID | Prio | Status | Evidence | Fix | Tests |
| --- | --- | --- | --- | --- | --- |
| UI-03 | medium | REPRODUCED | Entering the Render workspace left whatever properties tab was last selected showing, so the render settings the workspace exists for stayed hidden behind a tab the user had to know to click | `Workspace.properties_tab`; `set_workspace` calls the new `PropertiesDock.show_tab`. Model->Object, Rig->Bone, Render->Render; Layout/Animate deliberately leave the selection alone | `test_operators.py::test_entering_the_render_workspace_selects_the_render_tab`, `::test_workspaces_without_a_preferred_tab_leave_the_selection_alone` |
| UI-04 | medium | REPRODUCED | Executed: `CreateActionCommand(s,"Walk")` then `("Wave")` left `active_action == "Walk"` -- `Session.create_action` only activates when nothing is active, so the user named a new action and then keyed into the old one. Separately, `key_bone` returned silently with no active action, so pressing I did nothing and never said why | `CreateActionCommand(activate=True)` activates within the same undo step and undo restores the previous active action; `key_bone`/`key_selected_bone` now report the reason in the status bar | `test_operators.py::test_creating_a_second_action_makes_it_the_active_one`, `::test_creating_the_first_action_still_activates_it`, `::test_keying_without_an_active_action_says_why` |

## Review round 3 — EDIT/MAT batch (one Haiku agent)

Two defects, both reproduced here before fixing:

| Finding | Verified | Fix |
| --- | --- | --- |
| `am3d/ui/operators.py`: `LatheProfileCommand.undo`/`ExtrudeProfileCommand.undo` removed patches **by name**. Every lathe produces a patch named `lathe`, so undoing the second of two lathes on one object deleted the first one's patch too | Yes -- two lathes then one undo left **0** patches, not 1 | Track the created `Patch` objects and remove by identity |
| `am3d/export/textures.py`: `texture_filename` sanitising is lossy, so objects `"a b"` and `"a/b"` both produced `m_a_b.png` and the second atlas silently overwrote the first | Yes -- `texture_filename('m','a b') == texture_filename('m','a/b')` | Append a short blake2s digest of the original name whenever sanitising changed it; already-safe names keep their plain filename, and filenames stay stable across exports |

The agent's other checks came back clean: regeneration idempotency at 1e-12,
generator/degree persistence, no code-execution path through a corrupt
`generator` dict (`_OPS` is a fixed dispatch table), GLB chunk alignment and
lengths, and the PNG vertical flip against both UV conventions.


## Render findings (phase B, priority 6)

| ID | Prio | Status | Evidence | Fix | Tests |
| --- | --- | --- | --- | --- | --- |
| UI-02 | high | IMPLEMENTED | There was no way to produce a final image or an animation from the GUI at all -- the app could model, rig and export geometry but never render a picture | New headless render core `am3d/render_job.py` (still + sequence, destination/size validation, zero-padded frame names, progress callback, cancel that keeps already-written frames, forced-software switch) and `am3d/ui/render_dialog.py`, wired to **File -> Render Image / Sequence... (F12)** | `am3d/ui/test_render_dialog.py` (20 tests) |
| GPU-04 | critical | REPRODUCED ON HARDWARE | `phase-b/gpu-04-reproduction.txt`. With a real GL 4.6 context (Mesa 26.1.4, AMD radeonsi renoir) the deferred pipeline produced a **uniformly blank frame**; the G-buffer held nothing but its clear value. Matrices were uploaded row-major while GLSL reads a uniform block column-major, so all geometry projected off-screen. A/B: `transpose=False -> 0` pixels drawn, `transpose=True -> 404` | Transpose at the upload boundary in `ShaderProgram.uniform`, for both the (4,4) ndarray and flat-16 forms | `test_scene_render.py::test_matrix_uniforms_are_transposed_for_gl` (no GL needed), `::test_the_gpu_pipeline_actually_draws_on_real_hardware`, `::test_gpu_and_software_renders_agree_on_where_the_geometry_is` |

GPU-04 is the clearest case so far for the plan's insistence on hardware
testing: the whole suite passed, offscreen and software rendering were
correct, and the GPU path nevertheless rendered nothing. It was found only
because UI-02's acceptance test compared a GPU render against a
forced-software render of the same scene.

## Rigging findings (phase B, priority 6)

| ID | Prio | Status | Evidence | Fix | Tests |
| --- | --- | --- | --- | --- | --- |
| UI-01 | high | REPRODUCED | The GUI had a Bone tab that could edit an existing bone's head/tail and **nothing that could create one** -- no add, no re-parent, no delete, and no way to bind geometry to a skeleton. A model built in the GUI could only be rigged by writing a script or a recipe. `Session.add_bone` also accepted an unknown object, an empty name, a duplicate name (silently replacing the bone in place and orphaning its children) and a parent that does not exist | Session: validation in `add_bone`, plus `bone_ancestors`, `set_bone_parent` (rejects self-parenting and cycles), `remove_bone` (children move up to the deleted bone's parent; weights, pose and keyframe channels go with it) and `bind_geometry` (proximity auto-weights). UI: `AddBoneCommand`, `SetBoneParentCommand`, `DeleteBoneCommand` (snapshots skeleton, pose and action channels so undo restores the keyframes), `BindGeometryCommand`; a **Rig** menu (Add Bone / Add Child Bone / Delete Selected Bone / Bind Geometry / Clear Pose) and a parent combo plus the four buttons in the Bone tab. The parent combo omits the bone itself and its descendants, so a cycle cannot be selected. Every verb reports a reason in the status bar instead of doing nothing | `am3d/ui/test_rig_editing.py` (17 tests) |
| RIG-01 | high | REPRODUCED | `phase-b/rig-01-reproduction.txt`. `evaluate_scene` deforms from `posed_transforms`, written only by `apply_pose`. `pose_bone` and `clear_pose` left it stale, so a scripted pose was invisible (`without apply_pose moved: False`) and, worse, a cleared pose stayed on the geometry (`after clear_pose, back to rest: False \| still posed: True`). The GUI's PoseBoneCommand happened to call `apply_pose`, so this only bit scripts, recipes and the new bind/pose journey | `pose_bone` and `clear_pose` re-run FK for the object; `clear_pose` drops the cached entry when no skeleton is left | `test_rig_editing.py::test_bound_geometry_follows_a_posed_bone` |

## Review round 4 -- UI-02/GPU-04 and UI-01/RIG-01 batches (two Haiku agents)

**Render/GPU batch (commit e500eda): clean.** The agent independently
re-ran the GPU and forced-software paths and measured **94.5% coverage
overlap**, confirmed the transpose is applied on both matrix upload paths
and nowhere twice, confirmed no 3x3 or array-of-matrix uniform takes the
same route, and found the destination/size validation, the
cancel-keeps-written-frames path and the dialog's concurrent-render and
error recovery all sound. No defects.

**Rig batch (commit a2a5740): two defects, both reproduced here before
fixing.**

| Finding | Verified | Fix |
| --- | --- | --- |
| The new `add_bone` validation broke recipes. A recipe is declarative and may list a child before the parent it names; the imperative `add_bone` (correctly) requires the parent to exist. A previously working recipe now failed with `ScriptingError: no bone 'root' on object 'hero' to parent to` | Yes -- ran the recipe CLI on a forward-referenced rig: `rc: 1` before, `rc: 0` after | `am3d/recipes/executor.py`: new `_bones_in_parent_order` inserts bones parent-first, preserving the written order otherwise, and reports anything unresolvable against the recipe instead of raising. The session-level validation stays as it is |
| `_rig_add_child_bone` crashed with `KeyError` on a stale selection: deleting an object's last bone drops its whole `skeletons` entry, and a Bone tab still pointing at that bone indexed a dict that no longer existed | Yes -- delete the only bone, leave the context, click Add Child: `CRASH: KeyError 'hero'` | `rig_target` no longer returns a bone name that is gone, and `_rig_add_child_bone` reports "Bone ... no longer exists" instead of indexing blindly |

The agent's other checks came back clean: `remove_bone` leaves no dangling
pose/`posed_transforms`/action state and round-trips through the
serializer, `DeleteBoneCommand` survives repeated undo/redo, cycle
detection holds in both directions, and `bind_geometry` indices match the
canonical control-point ordering for objects mixing patches and splines.

Regression tests: `test_rig_editing.py::test_a_stale_bone_selection_does_not_crash_the_rig_verbs`,
`::test_a_recipe_may_list_a_child_bone_before_its_parent`,
`::test_bones_in_parent_order_keeps_the_written_order_otherwise`.
