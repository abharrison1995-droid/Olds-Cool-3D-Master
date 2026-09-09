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
    "multi_object_software_rendering",
    "save_and_reopen",
    "transformed_export",
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

    app = QApplication.instance() or QApplication([])
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

    for name, fn in [
        ("blank_startup", _blank_startup),
        ("new_project", _new_project),
        ("primitive_and_profile_creation", _primitive_and_profile),
        ("material_reference", _material_reference),
        ("rig_and_weighted_action_playback", _rig_and_playback),
        ("multi_object_software_rendering", _multi_object_render),
        ("save_and_reopen", _save_and_reopen),
        ("transformed_export", _transformed_export),
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
