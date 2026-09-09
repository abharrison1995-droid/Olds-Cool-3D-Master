"""Packaged smoke mode: drive the real MainWindow through a representative
workflow so a broken packaged build fails at build time, not at a user's
first launch.  See docs/V3_FUNCTIONAL_IMPLEMENTATION_PLAN.md Phase 6
bullet 4.

Invoked via ``3D MASTER 2005.exe --smoke-test --out <manifest.json>``
(see :func:`am3d.ui.app.main`); also directly importable for
``python -m am3d.ui.smoke`` or a pytest regression test.

Each step is independent evidence in the manifest: a step's dict starts
as ``{"name": ..., "status": "not_run"}`` and only flips to "ok" or
"failed" once actually attempted, so a run that stops partway through
(the intended behaviour on the first failure, since later steps build on
earlier state) is visible as incomplete rather than silently absent.
"""

from __future__ import annotations

import time
import traceback
from pathlib import Path

STEPS = [
    "blank_startup",
    "new_project",
    "primitive_and_profile_creation",
    "material_reference",
    "rig_and_weighted_action_playback",
    "gui_rig_build_and_bind",
    "multi_object_software_rendering",
    "still_render_to_png",
    "save_and_reopen",
    "transformed_export",
    "recipe_output_opens_in_the_gui",
    "autosave_snapshot_and_recovery",
    "damaged_project_is_reported_not_swallowed",
    "posed_export_carries_the_pose",
]


def run_smoke_test(tmp_dir: Path) -> dict:
    """Run every step in :data:`STEPS` in order, stopping at first failure.

    Returns a manifest: ``{"ok": bool, "version": str, "steps": [...],
    "artifacts": {...}}``.
    """
    import am3d
    from PySide6.QtWidgets import QApplication

    manifest = {
        "ok": True,
        "version": am3d.__version__,
        "steps": [{"name": n, "status": "not_run"} for n in STEPS],
        "artifacts": {},
    }
    by_name = {s["name"]: s for s in manifest["steps"]}

    from .app import configure_application_identity

    app = configure_application_identity(
        QApplication.instance() or QApplication([]))
    win = None

    def step(name, fn):
        entry = by_name[name]
        t0 = time.monotonic()
        try:
            fn()
            entry["status"] = "ok"
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = f"{type(exc).__name__}: {exc}"
            entry["traceback"] = traceback.format_exc()
            manifest["ok"] = False
        finally:
            entry["duration_ms"] = round((time.monotonic() - t0) * 1000, 1)
        return entry["status"] == "ok"

    def _blank_startup():
        nonlocal win
        from .app import MainWindow
        win = MainWindow()
        win.show()
        app.processEvents()
        if win.stack.currentIndex() != 0:
            raise AssertionError("expected Home screen on blank launch")
        if win.doc_ctrl.has_path:
            raise AssertionError("a fresh launch must not have a document path")

    def _new_project():
        win.doc_ctrl.do_new()
        win._reset_document_ui_state()
        win.show_editor()
        if win.stack.currentIndex() != 1:
            raise AssertionError("New Project did not switch to the editor")

    def _primitive_and_profile():
        from .operators import (
            CreatePrimitiveCommand, CreateSplineProfileCommand,
            LatheProfileCommand,
        )
        win.push_command(CreatePrimitiveCommand(win.session, "Box", "box", {}))
        if not win.session.project.objects["Box"].patches:
            raise AssertionError("primitive command created no geometry")

        # LatheProfileCommand tessellates with a fixed degree-3 net (it
        # doesn't carry the degree make_lathe_profile() would clamp to a
        # shorter profile -- see am3d/ui/operators.py's LatheProfileCommand),
        # so this needs >=4 points or tessellation raises ValueError.
        profile_cps = [(0.3, 0.0, 0), (0.5, 0.3, 0), (0.5, 0.6, 0),
                       (0.3, 0.9, 0), (0.2, 1.2, 0)]
        win.push_command(CreateSplineProfileCommand(
            win.session, "Vase", "profile", profile_cps))
        win.push_command(LatheProfileCommand(
            win.session, "Vase", [(cp[0], cp[1]) for cp in profile_cps]))
        if not win.session.project.objects["Vase"].patches:
            raise AssertionError("lathe command created no geometry")

    def _material_reference():
        from .operators import AddMaterialCommand, SetMaterialColorCommand
        win.push_command(AddMaterialCommand(win.session, "Red"))
        win.push_command(SetMaterialColorCommand(
            win.session, "Red", (1.0, 0.0, 0.0, 1.0)))
        win.session.project.objects["Box"].material = "Red"
        if win.session.project.materials["Red"].color != (1.0, 0.0, 0.0, 1.0):
            raise AssertionError("material color command did not apply")

    def _rig_and_playback():
        from .operators import (
            CreateActionCommand, InsertKeyCommand, AssignActionCommand,
        )
        win.session.add_bone("Box", "root", head=(0, 0, 0), tail=(0, 1, 0))
        win.push_command(CreateActionCommand(win.session, "Wave", duration=2.0))
        win.push_command(InsertKeyCommand(
            win.session, "Wave", "root", "rotate", 0.0, (0.0, 0.0, 0.0)))
        win.push_command(InsertKeyCommand(
            win.session, "Wave", "root", "rotate", 2.0, (0.0, 0.0, 1.57)))
        win.push_command(AssignActionCommand(win.session, "Wave", "Box"))
        # Sample mid-way between the two keyframes (not on a key boundary)
        # so this actually exercises the interpolation weighting, not just
        # a direct keyframe readback.
        pose = win.session.apply_action_frame("Box", 1.0, action_name="Wave")
        if "root" not in pose.get("Box", {}):
            raise AssertionError("weighted action playback produced no pose")

    def _gui_rig_build_and_bind():
        """Finding UI-01: build a skeleton and bind geometry to it through
        the same MainWindow verbs the Rig menu calls, then confirm the
        geometry actually follows a posed bone."""
        import numpy as np
        from am3d.core.scene import evaluate_scene

        win.current_context = ("object", "Vase", "")
        root = win._rig_add_bone()
        child = win._rig_add_child_bone()
        if not root or not child:
            raise AssertionError("could not create bones through the Rig verbs")
        if win.session.project.skeletons["Vase"][child].parent != root:
            raise AssertionError("the child bone was not parented to the root")
        if not win._rig_bind_geometry():
            raise AssertionError("binding geometry to the skeleton failed")
        if not any(b.cp_weights for b in win.session.get_bones("Vase")):
            raise AssertionError("binding assigned no control-point weights")

        rest = evaluate_scene(win.session).meshes["Vase"].vertices.copy()
        win.session.pose_bone("Vase", child, (0.0, 0.0, 35.0))
        posed = evaluate_scene(win.session).meshes["Vase"].vertices
        if np.allclose(rest, posed):
            raise AssertionError("bound geometry did not follow the posed bone")
        win.session.clear_pose("Vase")
        manifest["artifacts"]["bound_weight_count"] = sum(
            len(b.cp_weights) for b in win.session.get_bones("Vase"))

    def _still_render():
        """Finding UI-02: produce a final image the way File -> Render
        Image / Sequence does, and require it to be non-blank."""
        import numpy as np
        from PIL import Image
        from am3d.render_job import STILL, run_render

        out = tmp_dir / "smoke_render.png"
        written = run_render(win.session, None, mode=STILL, path=str(out),
                             width=160, height=120, force_software=True)
        if not written or not Path(written[0]).exists():
            raise AssertionError("the render produced no file")
        with Image.open(written[0]) as im:
            arr = np.asarray(im)
        lit = int((arr[..., :3].sum(axis=2) > 8).sum())
        if lit < 50:
            raise AssertionError(f"the rendered image is blank ({lit} lit pixels)")
        manifest["artifacts"]["render_path"] = str(written[0])
        manifest["artifacts"]["render_lit_pixels"] = lit

        # GPU-vs-software parity on whatever hardware this artifact is
        # actually running on (finding GPU-04: the GPU path once rendered a
        # uniformly blank frame while every software test passed). When no
        # GL context can be created the comparison is recorded as skipped
        # rather than quietly counted as a pass.
        try:
            from am3d.gpu import create_offscreen_context
            probe = create_offscreen_context(16, 16)
            has_gl = getattr(probe, "ctx", None) is not None
            try:
                probe.destroy()
            except Exception:
                pass
        except Exception:
            has_gl = False
        if not has_gl:
            manifest["artifacts"]["gpu_parity"] = "skipped: no GL context"
            return
        gpu_out = tmp_dir / "smoke_render_gpu.png"
        gpu_written = run_render(win.session, None, mode=STILL,
                                 path=str(gpu_out), width=160, height=120,
                                 force_software=False)
        with Image.open(gpu_written[0]) as im:
            gpu_arr = np.asarray(im)
        gpu_lit = int((gpu_arr[..., :3].sum(axis=2) > 8).sum())
        if gpu_lit < 50:
            raise AssertionError(
                f"the GPU render is blank ({gpu_lit} lit pixels) while the "
                f"software render has {lit}")
        ratio = gpu_lit / max(lit, 1)
        if not 0.4 <= ratio <= 2.5:
            raise AssertionError(
                f"GPU and software renders disagree: {gpu_lit} vs {lit} "
                f"lit pixels (ratio {ratio:.2f})")
        # Equal *amounts* of lit pixel are not equal pictures: the two paths
        # must also put the geometry in the same place, which is what
        # finding GPU-05 got wrong. Compare the silhouettes directly.
        gpu_mask = gpu_arr[..., :3].sum(axis=2) > 8
        sw_mask = arr[..., :3].sum(axis=2) > 8
        union = int((gpu_mask | sw_mask).sum())
        iou = int((gpu_mask & sw_mask).sum()) / max(union, 1)
        if iou < 0.6:
            raise AssertionError(
                f"GPU and software renders place the scene differently "
                f"(silhouette IoU {iou:.2f})")
        manifest["artifacts"]["gpu_parity"] = {
            "gpu_lit_pixels": gpu_lit, "software_lit_pixels": lit,
            "ratio": round(ratio, 3), "silhouette_iou": round(iou, 3),
        }

    def _multi_object_render():
        from .operators import CreatePrimitiveCommand
        win.push_command(CreatePrimitiveCommand(win.session, "Ball", "sphere", {}))
        win.viewport.force_software = True
        win.viewport.resize(320, 240)
        win.viewport.refresh()
        win.viewport._render()
        if win.viewport._frame is None:
            raise AssertionError("software renderer produced no frame")
        mesh_count = len(win.viewport._scene_meshes())
        if mesh_count < 2:
            raise AssertionError(
                f"expected >=2 rendered objects, got {mesh_count}")
        manifest["artifacts"]["rendered_objects"] = mesh_count

    def _save_and_reopen():
        save_path = str(tmp_dir / "smoke_project.am3d")
        win.doc_ctrl.path = save_path
        result = win.doc_ctrl.do_save()
        if result != save_path or Path(save_path).stat().st_size <= 0:
            raise AssertionError("save produced no (or an empty) file")

        win.doc_ctrl.do_open(save_path)
        win._reset_document_ui_state()
        win._refresh_all()
        objs = win.session.project.objects
        if "Box" not in objs or "Vase" not in objs or "Ball" not in objs:
            raise AssertionError(
                f"reopened project is missing objects: {sorted(objs)}")
        manifest["artifacts"]["saved_project_path"] = save_path

    def _transformed_export():
        from .operators import SetObjectTransformCommand
        from am3d.export.obj import write_obj
        before = win.session.project.objects["Box"].transform.copy()
        after = before.copy()
        after[:3, 3] += (1.0, 2.0, 3.0)
        win.push_command(SetObjectTransformCommand(
            win.session, "Box", before, after))

        meshes, mat_colors, patch_colors, atlases = win._export_scene()
        export_path = str(tmp_dir / "smoke_export.obj")
        write_obj(export_path, meshes, materials=mat_colors or None,
                  patch_materials=patch_colors or None,
                  textures=atlases or None)
        size = Path(export_path).stat().st_size
        if size <= 0:
            raise AssertionError("export produced an empty file")
        manifest["artifacts"]["export_size_bytes"] = size

    def _recipe_output_opens_in_the_gui():
        """Journey 6: build a project with the recipe engine the standalone
        CLI runs, then open that output in the GUI. The two shipped
        executables have to agree about what a project file is; nothing else
        in this smoke run crosses that boundary."""
        import json

        from am3d.recipes.cli import main as recipe_main

        recipe_path = tmp_dir / "smoke_recipe.json"
        recipe_path.write_text(json.dumps({
            "version": 1,
            "name": "smoke_recipe",
            "objects": [{"name": "recipe_cube", "primitive": "box",
                         "params": {"width": 1.0, "height": 1.0,
                                    "depth": 1.0}}],
            "exports": [{"format": "am3d", "path": "recipe_project"}],
        }), encoding="utf-8")
        out_dir = tmp_dir / "recipe_out"
        rc = recipe_main(["--recipe", str(recipe_path), "--out", str(out_dir)])
        if rc != 0:
            raise AssertionError(f"the recipe CLI failed (exit {rc})")
        produced = sorted(out_dir.rglob("*.am3d"))
        if not produced:
            raise AssertionError(
                f"the recipe wrote no project: {sorted(out_dir.rglob('*'))}")

        win.doc_ctrl.do_open(str(produced[0]))
        win._reset_document_ui_state()
        win._refresh_all()
        if "recipe_cube" not in win.session.project.objects:
            raise AssertionError(
                f"the GUI opened the recipe's project but it has no "
                f"recipe_cube: {sorted(win.session.project.objects)}")
        manifest["artifacts"]["recipe_project_path"] = str(produced[0])

    def _autosave_snapshot_and_recovery():
        """Crash recovery, in the bundle: take a snapshot of an unsaved
        document, prove it is listed with an identity a user can recognise,
        and load it back. Recovery is the one journey whose failure costs
        work that cannot be redone, so it is checked in the shipped
        executable rather than only in the test suite."""
        from .operators import CreatePrimitiveCommand

        win.doc_ctrl.do_new()
        win._reset_document_ui_state()
        win.push_command(CreatePrimitiveCommand(
            win.session, "Unsaved", "box", {}))
        win.doc_ctrl.mark_dirty()
        win.doc_ctrl.do_autosave()

        snapshot = win.doc_ctrl.autosave_path()
        if not Path(snapshot).is_file():
            raise AssertionError(f"no autosave was written at {snapshot}")
        entries = win.doc_ctrl.autosave_entries()
        mine = [e for e in entries if e["path"] == snapshot]
        if not mine:
            raise AssertionError(
                f"the snapshot is not offered for recovery: "
                f"{[e['path'] for e in entries]}")
        if not mine[0].get("display_name"):
            raise AssertionError("the recovery entry has no name to choose by")

        # Lose the document the way a crash would, then recover it.
        win.doc_ctrl.do_new()
        win._reset_document_ui_state()
        if "Unsaved" in win.session.project.objects:
            raise AssertionError("the new document kept the old objects")
        if not win.doc_ctrl.recover_from(snapshot):
            raise AssertionError("recover_from() refused the snapshot")
        win._refresh_all()
        if "Unsaved" not in win.session.project.objects:
            raise AssertionError(
                f"recovery lost the work: {sorted(win.session.project.objects)}")
        if win.doc_ctrl.has_path:
            raise AssertionError(
                "a recovered document must be pathless so Save cannot "
                "overwrite the snapshot in place")
        manifest["artifacts"]["autosave_dir"] = str(Path(snapshot).parent)
        manifest["artifacts"]["autosave_recovered_objects"] = sorted(
            win.session.project.objects)
        win.doc_ctrl.clear_autosave(snapshot)

    def _damaged_project_is_reported():
        """A corrupt project file must fail loudly and leave the open
        document alone -- not half-load, and not be silently swallowed."""
        from .operators import CreatePrimitiveCommand

        win.doc_ctrl.do_new()
        win._reset_document_ui_state()
        win.push_command(CreatePrimitiveCommand(win.session, "Keep", "box", {}))

        damaged = tmp_dir / "damaged_project.am3d"
        damaged.write_bytes(b"this is not a project file\x00\xff")
        try:
            win.doc_ctrl.do_open(str(damaged))
        except Exception as exc:
            manifest["artifacts"]["damaged_open_error"] = \
                f"{type(exc).__name__}: {exc}"[:200]
        else:
            raise AssertionError(
                "opening a corrupt project reported success")
        if "Keep" not in win.session.project.objects:
            raise AssertionError(
                "the failed open destroyed the document that was open: "
                f"{sorted(win.session.project.objects)}")

        missing = tmp_dir / "no_such_project.am3d"
        try:
            win.doc_ctrl.do_open(str(missing))
        except Exception:
            pass
        else:
            raise AssertionError("opening a missing project reported success")

    def _posed_export_carries_the_pose():
        """A GUI export must write the pose that is on screen, not the bind
        pose. Exported at two different times of the same action, the files
        have to differ -- and differ only in where the vertices are, not in
        how many there are."""
        import numpy as np

        from am3d.export.obj import write_obj
        from .operators import (
            CreateActionCommand, InsertKeyCommand, AssignActionCommand,
            CreatePrimitiveCommand,
        )

        win.doc_ctrl.do_new()
        win._reset_document_ui_state()
        win.show_editor()
        win.push_command(CreatePrimitiveCommand(win.session, "Arm", "box", {}))
        win.session.add_bone("Arm", "root", head=(0, 0, 0), tail=(0, 1, 0))
        win.session.bind_geometry("Arm")
        win.push_command(CreateActionCommand(win.session, "Bend", duration=2.0))
        win.push_command(InsertKeyCommand(
            win.session, "Bend", "root", "rotate", 0.0, (0.0, 0.0, 0.0)))
        win.push_command(InsertKeyCommand(
            win.session, "Bend", "root", "rotate", 2.0, (0.0, 0.0, 1.2)))
        win.push_command(AssignActionCommand(win.session, "Bend", "Arm"))

        def export_at(t, name):
            win.session.apply_action_frame("Arm", t, action_name="Bend")
            win._refresh_all()
            meshes, mat_colors, patch_colors, atlases = win._export_scene()
            path = str(tmp_dir / name)
            write_obj(path, meshes, materials=mat_colors or None,
                      patch_materials=patch_colors or None,
                      textures=atlases or None)
            verts = np.asarray(
                [v for m in meshes.values() for v in np.asarray(m.vertices)],
                dtype=np.float64)
            return path, verts

        rest_path, rest = export_at(0.0, "posed_export_rest.obj")
        bent_path, bent = export_at(2.0, "posed_export_bent.obj")
        if rest.shape != bent.shape:
            raise AssertionError(
                f"the two poses exported different geometry: "
                f"{rest.shape} vs {bent.shape}")
        moved = float(np.abs(rest - bent).max())
        if moved < 1e-3:
            raise AssertionError(
                "the exported mesh is identical at both ends of the action: "
                "the export is writing the bind pose, not the pose on screen")
        manifest["artifacts"]["posed_export"] = {
            "rest": rest_path, "bent": bent_path,
            "max_vertex_shift": round(moved, 4),
        }

    for name, fn in [
        ("blank_startup", _blank_startup),
        ("new_project", _new_project),
        ("primitive_and_profile_creation", _primitive_and_profile),
        ("material_reference", _material_reference),
        ("rig_and_weighted_action_playback", _rig_and_playback),
        ("gui_rig_build_and_bind", _gui_rig_build_and_bind),
        ("multi_object_software_rendering", _multi_object_render),
        ("still_render_to_png", _still_render),
        ("save_and_reopen", _save_and_reopen),
        ("transformed_export", _transformed_export),
        ("recipe_output_opens_in_the_gui", _recipe_output_opens_in_the_gui),
        ("autosave_snapshot_and_recovery", _autosave_snapshot_and_recovery),
        ("damaged_project_is_reported_not_swallowed",
         _damaged_project_is_reported),
        ("posed_export_carries_the_pose", _posed_export_carries_the_pose),
    ]:
        if not step(name, fn):
            break

    if win is not None:
        try:
            # The smoke run deliberately ends with unsaved changes
            # (transformed_export pushes a command after the last save), so
            # a plain win.close() would hit closeEvent's real, blocking
            # "Save changes?" QMessageBox.exec() -- fine under pytest, where
            # conftest.py patches QMessageBox to never block, but a genuine
            # hang here under offscreen platform with no user to click it
            # (confirmed via a direct, non-pytest run). Same suppression
            # test_phase0a.py/test_phase0b.py use for headless cleanup.
            win.doc_ctrl._testing_discard = True
            win.close()
        except Exception:
            pass
    return manifest
