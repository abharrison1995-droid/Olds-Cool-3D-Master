"""Tests for the undo/operator layer (am3d.ui.operators).

Commands need QUndoStack (QtGui) but no widgets, so they run anywhere
PySide6 imports; the MainWindow-level tests use the existing
skip-if-no-QApplication style.
"""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.animation import Action
from am3d.core.project import ControlPoint
from am3d.core.script import Session
from am3d.ui.operators import (
    AddMaterialCommand, AddObjectCommand, ClearPoseCommand,
    CreatePrimitiveCommand,
    DeleteMaterialCommand, DeleteObjectCommand, ImportActionCommand,
    InsertCPCommand, MoveCPCommand, PoseBoneCommand,
    RemoveCPCommand, RenameObjectCommand, SetActiveActionCommand,
    SetBoneEndpointsCommand,
    SetMaterialColorCommand, SetMaterialMapsCommand,
    SetObjectTransformCommand, SetObjectVisibleCommand,
    SetRenderSettingsCommand, QUndoStack,
)


@pytest.fixture()
def session():
    s = Session()
    s.create_object("hero")
    s.create_material("base", color=(0.5, 0.5, 0.5))
    return s


@pytest.fixture()
def stack():
    return QUndoStack()


def test_rename_undo_redo(session, stack):
    stack.push(RenameObjectCommand(session, "hero", "knight"))
    assert list(session.project.objects) == ["knight"]
    stack.undo()
    assert list(session.project.objects) == ["hero"]
    stack.redo()
    assert "knight" in session.project.objects


def test_delete_object_restores_skeleton_and_order(session, stack):
    session.add_bone("hero", "root", (0, 0, 0), (0, 1, 0))
    session.create_object("prop")
    stack.push(DeleteObjectCommand(session, "hero"))
    assert "hero" not in session.project.objects
    assert "hero" not in session.project.skeletons
    stack.undo()
    assert list(session.project.objects) == ["hero", "prop"]
    assert "root" in session.project.skeletons["hero"]
    stack.redo()
    assert "hero" not in session.project.objects


def test_add_object_undo(session, stack):
    stack.push(AddObjectCommand(session, "extra"))
    assert "extra" in session.project.objects
    stack.undo()
    assert "extra" not in session.project.objects


def test_visibility_toggle(session, stack):
    stack.push(SetObjectVisibleCommand(session, "hero", False))
    assert session.get_object("hero").visible is False
    stack.undo()
    assert session.get_object("hero").visible is True


def test_transform_command(session, stack):
    before = session.get_object("hero").transform.copy()
    after = before.copy()
    after[:3, 3] = (1.0, 2.0, 3.0)
    stack.push(SetObjectTransformCommand(session, "hero", before, after))
    assert np.allclose(session.get_object("hero").transform[:3, 3],
                       (1, 2, 3))
    stack.undo()
    assert np.allclose(session.get_object("hero").transform, before)
    stack.redo()
    assert np.allclose(session.get_object("hero").transform[:3, 3],
                       (1, 2, 3))


def test_material_color_and_maps(session, stack):
    stack.push(SetMaterialColorCommand(session, "base", (1, 0, 0, 1)))
    assert session.project.materials["base"].color == (1, 0, 0, 1)
    stack.undo()
    assert session.project.materials["base"].color == (0.5, 0.5, 0.5)

    stack.push(SetMaterialMapsCommand(session, "base", "b.png", None,
                                      "s.png"))
    mat = session.project.materials["base"]
    assert (mat.bump_map, mat.transparency_map, mat.specular_map) == \
        ("b.png", None, "s.png")
    stack.undo()
    mat = session.project.materials["base"]
    assert (mat.bump_map, mat.transparency_map, mat.specular_map) == \
        (None, None, None)


def test_add_and_delete_material(session, stack):
    stack.push(AddMaterialCommand(session, "glow"))
    assert "glow" in session.project.materials
    stack.undo()
    assert "glow" not in session.project.materials

    stack.push(DeleteMaterialCommand(session, "base"))
    assert "base" not in session.project.materials
    stack.undo()
    assert list(session.project.materials) == ["base"]
    assert session.project.materials["base"].color == (0.5, 0.5, 0.5)


def test_bone_endpoints(session, stack):
    session.add_bone("hero", "arm", (0, 0, 0), (0, 1, 0))
    stack.push(SetBoneEndpointsCommand(session, "hero", "arm",
                                       ((0, 0, 0), (0, 1, 0)),
                                       ((1, 0, 0), (2, 1, 0))))
    bone = session.project.skeletons["hero"]["arm"]
    assert np.allclose(bone.head, (1, 0, 0))
    stack.undo()
    assert np.allclose(bone.head, (0, 0, 0))
    assert np.allclose(bone.tail, (0, 1, 0))


def test_cp_move_insert_remove(session, stack):
    session.add_spline("hero", [(0, 0, 0), (1, 0, 0), (2, 0, 0),
                                (3, 0, 0)], degree=3, name="sp")
    spline = session.project.objects["hero"].splines["sp"]

    stack.push(MoveCPCommand(session, "hero", "sp", 1,
                             (1, 0, 0), (1, 5, 0)))
    assert np.allclose(spline.cps[1].position, (1, 5, 0))
    stack.undo()
    assert np.allclose(spline.cps[1].position, (1, 0, 0))

    stack.push(InsertCPCommand(session, "hero", "sp", 1,
                               ControlPoint.from_tuple(9, 9, 9)))
    assert len(spline.cps) == 5
    assert np.allclose(spline.cps[1].position, (9, 9, 9))
    stack.undo()
    assert len(spline.cps) == 4

    stack.push(RemoveCPCommand(session, "hero", "sp", 0))
    assert len(spline.cps) == 3
    stack.undo()
    assert len(spline.cps) == 4
    assert np.allclose(spline.cps[0].position, (0, 0, 0))


def test_pose_bone_command(session, stack):
    session.add_bone("hero", "arm", (0, 0, 0), (0, 1, 0))
    rot = np.eye(3)
    stack.push(PoseBoneCommand(session, "hero", "arm", None, rot))
    assert "arm" in session.poses["hero"]
    assert "hero" in session.posed_transforms
    stack.undo()
    assert "arm" not in session.poses.get("hero", {})


def test_clear_pose_command_undo_redo(session, stack):
    session.add_bone("hero", "arm", (0, 0, 0), (0, 1, 0))
    session.pose_bone("hero", "arm", np.eye(3))
    session.apply_pose("hero")
    assert "arm" in session.poses["hero"]

    stack.push(ClearPoseCommand(session, "hero"))
    assert "hero" not in session.poses
    stack.undo()
    assert "arm" in session.poses["hero"]
    stack.redo()
    assert "hero" not in session.poses


def test_render_settings_command_undo_redo(session, stack):
    session.project.render_settings = {"supersample": 2, "toon": True}
    before = dict(session.project.render_settings)
    after = {"supersample": 4, "toon": False}
    stack.push(SetRenderSettingsCommand(session, before, after))
    assert session.project.render_settings["supersample"] == 4
    assert session.project.render_settings["toon"] is False
    stack.undo()
    assert session.project.render_settings["supersample"] == 2
    assert session.project.render_settings["toon"] is True


def test_render_settings_command_undo_restores_empty_before_state(session, stack):
    """A project that never had render_settings before the first edit must
    undo back to nothing -- not retain the edited keys via a dict merge."""
    session.project.render_settings = None
    before = {}
    after = {"supersample": 4, "toon": False}
    stack.push(SetRenderSettingsCommand(session, before, after))
    assert session.project.render_settings == after
    stack.undo()
    assert session.project.render_settings == {}


def test_import_action_command_undo_redo_new_name(session, stack):
    act = Action(name="walk", duration=2.0)
    assert "walk" not in session.actions
    assert session.active_action is None

    stack.push(ImportActionCommand(session, act))
    assert session.actions["walk"] is act
    assert session.active_action == "walk"  # first action becomes active
    assert session.project.active_action == "walk"

    stack.undo()
    assert "walk" not in session.actions
    assert session.active_action is None

    stack.redo()
    assert session.actions["walk"] is act
    assert session.active_action == "walk"


def test_import_action_command_undo_redo_overwrites_existing(session, stack):
    old = Action(name="walk", duration=1.0)
    session.actions["walk"] = old
    session.active_action = "walk"
    session.project.active_action = "walk"

    new = Action(name="walk", duration=5.0)
    stack.push(ImportActionCommand(session, new))
    assert session.actions["walk"] is new
    assert session.active_action == "walk"  # unchanged, already active

    stack.undo()
    # ImportActionCommand deep-copies the "before" action for snapshot
    # safety, so undo restores an equal-but-distinct object, not `old` itself.
    assert session.actions["walk"] is not new
    assert session.actions["walk"].duration == old.duration
    assert session.active_action == "walk"


def test_set_active_action_command_undo_redo(session, stack):
    session.actions["walk"] = Action(name="walk", duration=1.0)
    session.actions["run"] = Action(name="run", duration=1.0)
    session.active_action = "walk"
    session.project.active_action = "walk"

    stack.push(SetActiveActionCommand(session, "walk", "run"))
    assert session.active_action == "run"
    assert session.project.active_action == "run"

    stack.undo()
    assert session.active_action == "walk"
    assert session.project.active_action == "walk"

    stack.redo()
    assert session.active_action == "run"


def test_undo_stack_clean_state(session, stack):
    assert stack.isClean()
    stack.push(SetObjectVisibleCommand(session, "hero", False))
    assert not stack.isClean()
    stack.undo()
    assert stack.isClean()


# ---------------------------------------------------------------------------
# MainWindow-level UI tests (skip when no display / QApplication).
# ---------------------------------------------------------------------------

def _make_main_window():
    import sys
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
    except Exception:
        pytest.skip("PySide6 not available or no display")
    from am3d.ui.app import MainWindow
    win = MainWindow()
    _add_test_sphere(win)
    win.show_editor()
    return win


def _add_test_sphere(win):
    """Add a test sphere to a MainWindow for tests that need it."""
    from am3d.recipes.primitives import build_primitive
    from am3d.core.project import Patch
    s = win.session
    s.create_object("sphere")
    for pname, net, du, dv in build_primitive(
            "sphere", dict(radius=0.8, sections=12, rings=8))["patches"]:
        s.get_object("sphere").patches.append(
            Patch(name=pname, splines=[], interior=net))
    s.create_material("base", color=(0.72, 0.75, 0.85))


def test_mainwindow_undo_via_properties_panel():
    """TRS spinbox edit lands on the undo stack; Ctrl+Z reverts it."""
    win = _make_main_window()
    try:
        win.properties_dock.set_context("object", "sphere", "")
        win.properties_dock.obj_loc.spins[0].setValue(2.5)
        assert np.isclose(
            win.session.get_object("sphere").transform[0, 3], 2.5)
        assert not win.undo_stack.isClean()
        win.undo_stack.undo()
        assert np.isclose(
            win.session.get_object("sphere").transform[0, 3], 0.0)
        win.undo_stack.redo()
        assert np.isclose(
            win.session.get_object("sphere").transform[0, 3], 2.5)
    finally:
        win.viewport._timer.stop()
        win.close()


def test_mainwindow_edit_menu_actions():
    win = _make_main_window()
    try:
        edit = [a for a in win.menuBar().actions()
                if a.text().replace("&", "") == "Edit"]
        assert edit
        texts = [a.text() for a in edit[0].menu().actions()]
        assert any("Undo" in t for t in texts)
        assert any("Redo" in t for t in texts)
    finally:
        win.viewport._timer.stop()
        win.close()


def test_file_new_dirty_check(monkeypatch):
    """File->New on a clean project works; dirty check via DocumentController."""
    from am3d.core.script import Session
    win = _make_main_window()
    win.show()
    try:
        # Test that _file_new on a clean project works without dialog
        win._file_new()
        assert len(win.session.project.objects) == 0
        assert win.undo_stack.isClean()

        # Test that DocumentController.maybe_abandon_document returns True
        # for a clean project (no dialog)
        assert win.doc_ctrl.maybe_abandon_document() is True

        # Make a change and verify it's dirty
        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        assert not win.undo_stack.isClean()
        assert win.doc_ctrl.dirty

        # Monkeypatch maybe_abandon_document to test Cancel behavior
        original = win.doc_ctrl.maybe_abandon_document
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document",
                            lambda: False)
        win._file_new()
        assert "sphere" in win.session.project.objects  # aborted

        # Now test Discard: make maybe_abandon_document return True
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document",
                            lambda: True)
        win._file_new()
        assert "sphere" not in win.session.project.objects
        assert win.undo_stack.isClean()
    finally:
        win.viewport._timer.stop()
        win.close()


def test_gizmo_mode_hotkeys_and_toolbar_sync():
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent, Qt
    win = _make_main_window()
    try:
        for key, mode in ((Qt.Key_W, "translate"), (Qt.Key_E, "rotate"),
                          (Qt.Key_X, None)):
            ev = QKeyEvent(QEvent.KeyPress, key, Qt.NoModifier)
            win.viewport.keyPressEvent(ev)
            assert win.viewport.gizmo_mode == mode
        # Toolbar buttons track the keyboard-set mode.
        assert win.tool_strip is not None
        win._build_tool_options  # exists
        buttons = win._gizmo_button_sets[0]
        assert buttons["translate"].isChecked() is False  # mode is None now
        assert buttons[None].isChecked()
    finally:
        win.viewport._timer.stop()
        win.close()


def test_modal_grab_confirm_and_cancel():
    """G grab: mouse moves translate in view plane; Enter commits (undoable),
    Esc cancels."""
    win = _make_main_window()
    try:
        win.resize(640, 480)
        win.viewport.set_selected("sphere")
        obj = win.session.get_object("sphere")
        before = obj.transform.copy()

        win.viewport._begin_modal("translate")
        win.viewport._update_modal(100, 100)
        win.viewport._update_modal(140, 120)
        assert not np.allclose(obj.transform, before)
        win.viewport._confirm_modal()
        assert not win.undo_stack.isClean()
        win.undo_stack.undo()
        assert np.allclose(obj.transform, before)
        win.undo_stack.redo()

        win.viewport._begin_modal("scale")
        win.viewport._update_modal(200, 200)
        win.viewport._update_modal(260, 200)
        win.viewport._cancel_modal()
        assert np.allclose(obj.transform,
                           win.undo_stack.command(
                               win.undo_stack.index() - 1).after
                           if win.undo_stack.index() else before)
    finally:
        win.viewport._timer.stop()
        win.close()


def test_viewport_gizmo_translate_drag_commits_one_undo():
    """Dragging the translate gizmo moves the object and pushes one undo."""
    win = _make_main_window()
    try:
        win.resize(640, 480)
        win.show()
        vp = win.viewport
        vp.resize(640, 480)
        vp.set_selected("sphere")
        vp.set_gizmo_mode("translate")
        obj = win.session.get_object("sphere")
        before = obj.transform.copy()
        origin = before[:3, 3]

        # Find the X arrow midpoint on screen and drag it.
        from am3d.ui import gizmos
        handles = gizmos.handle_geometry(vp.camera, vp.width(),
                                         vp.height(), origin, "translate")
        line = dict((h, p) for h, _, p in handles)["tx"][0]
        mx, my = (line[0] + line[1]) / 2
        count0 = win.undo_stack.count()
        assert vp._begin_tool_drag(mx, my)
        vp._update_tool_drag(mx + 40, my)
        vp._end_tool_drag()
        assert not np.allclose(obj.transform, before)
        assert win.undo_stack.count() == count0 + 1
        win.undo_stack.undo()
        assert np.allclose(obj.transform, before)
    finally:
        win.viewport._timer.stop()
        win.close()


def test_viewport_cp_drag_and_add_remove():
    """Model workspace: CP hit-test, drag (undoable), A-insert, X-delete."""
    win = _make_main_window()
    try:
        win.resize(640, 480)
        win.show()
        vp = win.viewport
        vp.resize(640, 480)
        win.set_workspace("Model")
        s = win.session
        s.add_spline("sphere", [(0, 0, 0), (0, 0.4, 0), (0, 0.8, 0),
                                (0, 1.2, 0)], name="sp")
        vp.set_selected("sphere")
        vp.refresh()

        from am3d.ui import tools_spline
        obj = s.get_object("sphere")
        w, h = vp.width(), vp.height()
        pos = tools_spline.cp_screen_positions(obj, vp.camera, w, h)
        x, y, valid = pos[("sp", 1)]
        assert valid
        assert 0 < x < w and 0 < y < h

        spline = obj.splines["sp"]
        cp_before = spline.cps[1].position.copy()
        count0 = win.undo_stack.count()
        assert vp._begin_tool_drag(x, y)
        assert vp._selected_cp == ("sp", 1)
        vp._update_tool_drag(x, y - 30)
        vp._end_tool_drag()
        assert not np.allclose(spline.cps[1].position, cp_before)
        assert win.undo_stack.count() == count0 + 1
        win.undo_stack.undo()
        assert np.allclose(spline.cps[1].position, cp_before)
        win.undo_stack.redo()

        vp._add_cp()                               # insert after selected
        assert len(spline.cps) == 5
        win.undo_stack.undo()
        assert len(spline.cps) == 4
        win.undo_stack.redo()

        vp._selected_cp = ("sp", 1)
        assert vp._delete_selected_cp()
        assert len(spline.cps) == 4
        win.undo_stack.undo()
        assert len(spline.cps) == 5
    finally:
        win.viewport._timer.stop()
        win.close()


def test_viewport_bone_pose_drag():
    """Rig workspace: dragging a bone ring poses it (undoable)."""
    win = _make_main_window()
    try:
        win.resize(640, 480)
        win.show()
        vp = win.viewport
        vp.resize(640, 480)
        win.session.add_bone("sphere", "root", (0, 0, 0), (0, 1, 0))
        win.set_workspace("Rig")
        win.object_dock.refresh()
        item = win.object_dock._find("bone", "sphere", "root")
        win.object_dock.tree.setCurrentItem(item)
        assert win.current_context == ("bone", "sphere", "root")

        from am3d.ui import tools_bone
        head = tools_bone.bone_endpoints(win.session, "sphere")["root"][0]
        xs, ys, valid = vp.camera.world_to_screen([head],
                                                  vp.width(), vp.height())
        count0 = win.undo_stack.count()
        # The ring surrounds the head: start just outside it.
        assert vp._begin_tool_drag(xs[0] + 40, ys[0])
        vp._update_tool_drag(xs[0] + 40, ys[0] - 25)
        vp._end_tool_drag()
        assert "root" in win.session.poses.get("sphere", {})
        assert win.undo_stack.count() == count0 + 1
        win.undo_stack.undo()
        assert "root" not in win.session.poses.get("sphere", {})
    finally:
        win.viewport._timer.stop()
        win.close()


def test_open_recent_resets_document_ui_state(monkeypatch, tmp_path):
    """_open_recent must reset viewport/selection/playback like _file_open
    does — otherwise selection and timeline state from the old document
    leak into the newly-opened one."""
    win = _make_main_window()
    try:
        path = str(tmp_path / "other.am3d")
        other = Session()
        other.create_object("cube")
        other.save_project(path)

        win.properties_dock.set_context("object", "sphere", "")
        win.current_context = ("object", "sphere", "")

        win._open_recent(path)

        assert "sphere" not in win.session.project.objects
        assert "cube" in win.session.project.objects
        assert win.current_context == ("", "", "")
    finally:
        win.viewport._timer.stop()
        win.close()


def test_recover_project_resets_document_ui_state(tmp_path):
    """_recover_project must reset viewport/selection/playback like
    _file_open does, for the same reason as _open_recent."""
    win = _make_main_window()
    try:
        snapshot = str(tmp_path / "snap.autosave.am3d")
        other = Session()
        other.create_object("cube")
        other.save_project(snapshot)

        win.properties_dock.set_context("object", "sphere", "")
        win.current_context = ("object", "sphere", "")

        win._recover_project(snapshot)

        assert "sphere" not in win.session.project.objects
        assert "cube" in win.session.project.objects
        assert win.current_context == ("", "", "")
        assert win.doc_ctrl.dirty is True
        assert win.doc_ctrl.path is None
    finally:
        win.viewport._timer.stop()
        win.close()


def test_reset_document_ui_state_cancels_inflight_viewport_interaction():
    """_reset_document_ui_state must abandon an in-progress CP drag / gizmo
    drag / modal grab, not just the object selection -- those hold direct
    references into the document being replaced, and surviving into the
    next document risks a stale-reference crash or writing transform/pose
    data onto a coincidentally-named object in the new project."""
    win = _make_main_window()
    try:
        win.viewport._drag = {"kind": "test", "obj": object()}
        win.viewport._modal = {"kind": "translate", "obj": object()}
        win.viewport._selected_cp = ("spline", 0)

        win._reset_document_ui_state()

        assert win.viewport._drag is None
        assert win.viewport._modal is None
        assert win.viewport._selected_cp is None
    finally:
        win.viewport._timer.stop()
        win.close()


def test_recover_project_reports_failure_and_preserves_active_document(monkeypatch, tmp_path):
    """recover_from() reports a corrupt/unreadable snapshot by returning
    False rather than raising. _recover_project must check that return
    value: silently falling through to _reset_document_ui_state() would
    drop the user into a blank editor with no error and no indication that
    nothing was actually recovered, while the active document must be
    preserved untouched (Phase 5 acceptance: "cancelled or failed
    replacement preserves the active document")."""
    win = _make_main_window()
    try:
        win.properties_dock.set_context("object", "sphere", "")
        win.current_context = ("object", "sphere", "")

        monkeypatch.setattr(win.doc_ctrl, "recover_from", lambda path: False)
        win._recover_project(str(tmp_path / "corrupt.autosave.am3d"))

        # Active document and UI context must be untouched.
        assert "sphere" in win.session.project.objects
        assert win.current_context == ("object", "sphere", "")
    finally:
        win.viewport._timer.stop()
        win.close()


def test_apply_autosave_interval_falls_back_on_corrupt_settings_value(monkeypatch):
    """A hand-edited/corrupted QSettings store (non-numeric autosaveInterval)
    must not crash MainWindow startup — _apply_autosave_interval() runs from
    __init__, so any uncaught exception there would make the app unlaunchable."""
    from PySide6.QtCore import QSettings
    win = _make_main_window()
    try:
        monkeypatch.setattr(QSettings, "value",
                             lambda self, key, default=None: "not-a-number")
        win._apply_autosave_interval()  # must not raise
        assert win._autosave_timer.interval() == 5 * 60_000
    finally:
        win._autosave_timer.stop()
        win.viewport._timer.stop()
        win.close()


def test_autosave_timer_fires_only_when_dirty(monkeypatch):
    """The lifecycle-owned autosave timer must call do_autosave() when the
    document is dirty, and must never mark the document clean itself —
    autosave is a recovery safety net, not a substitute for Save."""
    win = _make_main_window()
    try:
        calls = []
        monkeypatch.setattr(win.doc_ctrl, "do_autosave", lambda: calls.append(1))

        assert win.doc_ctrl.dirty is False
        win._on_autosave_timeout()
        assert calls == []

        win.doc_ctrl.mark_dirty()
        win._on_autosave_timeout()
        assert calls == [1]
        assert win.doc_ctrl.dirty is True  # autosave never cleans the doc
    finally:
        win._autosave_timer.stop()
        win.viewport._timer.stop()
        win.close()


def test_apply_autosave_interval_reads_settings_in_minutes(monkeypatch):
    """Changing the Settings autosave-interval preference reschedules the
    same timer instance (not a new one) with the interval in milliseconds."""
    from PySide6.QtCore import QSettings
    win = _make_main_window()
    try:
        timer_before = win._autosave_timer
        s = QSettings("3DMASTER2005", "app")
        s.setValue("autosaveInterval", 7)
        try:
            win._apply_autosave_interval()
            assert win._autosave_timer is timer_before
            assert win._autosave_timer.interval() == 7 * 60_000
        finally:
            s.remove("autosaveInterval")
    finally:
        win._autosave_timer.stop()
        win.viewport._timer.stop()
        win.close()


def test_apply_settings_wires_grid_and_render_backend(monkeypatch):
    """The Settings 'Show grid' and 'Render backend' controls must reach
    live viewport state, not sit disconnected (previously dead controls)."""
    from PySide6.QtCore import QSettings
    win = _make_main_window()
    try:
        s = QSettings("3DMASTER2005", "app")
        s.setValue("showGrid", False)
        s.setValue("renderBackend", "Software only")
        try:
            win._apply_settings()
            assert win.viewport.show_grid is False
            assert win.viewport.force_software is True
        finally:
            s.remove("showGrid")
            s.remove("renderBackend")

        s.setValue("showGrid", True)
        s.setValue("renderBackend", "Auto (GPU preferred)")
        try:
            win._apply_settings()
            assert win.viewport.show_grid is True
            assert win.viewport.force_software is False
        finally:
            s.remove("showGrid")
            s.remove("renderBackend")
    finally:
        win._autosave_timer.stop()
        win.viewport._timer.stop()
        win.close()


def test_apply_settings_sets_undo_limit_only_while_stack_empty(monkeypatch):
    """QUndoStack silently refuses to change its limit once any command has
    been pushed (Qt would have to discard history to shrink it) — verified
    empirically: calling setUndoLimit() on a non-empty stack is a no-op.
    _apply_settings() must only apply the new limit while the stack is
    still empty, and must not raise or silently claim success otherwise."""
    from PySide6.QtCore import QSettings
    win = _make_main_window()
    try:
        s = QSettings("3DMASTER2005", "app")
        s.setValue("undoDepth", 42)
        try:
            assert win.undo_stack.count() == 0
            win._apply_settings()
            assert win.undo_stack.undoLimit() == 42
        finally:
            s.remove("undoDepth")

        # Once a command has been pushed, changing the limit must not
        # silently appear to succeed nor crash.
        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        assert win.undo_stack.count() > 0
        s.setValue("undoDepth", 7)
        try:
            win._apply_settings()  # must not raise
            assert win.undo_stack.undoLimit() == 42  # unchanged, not 7
        finally:
            s.remove("undoDepth")
    finally:
        win._autosave_timer.stop()
        win.viewport._timer.stop()
        win.close()


def test_apply_settings_falls_back_on_corrupt_undo_depth(monkeypatch):
    """A non-numeric undoDepth value must not crash Settings-apply."""
    from PySide6.QtCore import QSettings
    win = _make_main_window()
    try:
        monkeypatch.setattr(
            QSettings, "value",
            lambda self, key, default=None, **kw: "not-a-number")
        win._apply_settings()  # must not raise
        assert win.undo_stack.undoLimit() == 100
    finally:
        win._autosave_timer.stop()
        win.viewport._timer.stop()
        win.close()


def test_render_settings_change_is_undoable_and_dirty(monkeypatch):
    """Editing the Render tab's Supersample/Toon controls must be undoable
    and must mark the document dirty -- previously it mutated
    project.render_settings directly, bypassing both the undo stack and
    dirty tracking (so it could be lost silently on Close without a save
    prompt)."""
    win = _make_main_window()
    try:
        win.properties_dock.set_context("render", "", "")
        panel = win.properties_dock
        panel._loading = False
        assert win.doc_ctrl.dirty is False
        count0 = win.undo_stack.count()

        panel.rnd_supersample.setValue(6)
        panel._render_changed()

        assert win.session.project.render_settings["supersample"] == 6
        assert win.doc_ctrl.dirty is True
        assert win.undo_stack.count() == count0 + 1

        win.undo_stack.undo()
        assert win.session.project.render_settings.get("supersample", 2) != 6
    finally:
        win.viewport._timer.stop()
        win.close()


def test_import_action_is_undoable_and_dirty(monkeypatch, tmp_path):
    """Importing an .am3a action file must be undoable and mark the
    document dirty, like any other authoring action -- previously it
    called Session.load_action_file() directly, which mutated session
    state outside the undo stack."""
    from am3d.core.animation import Action
    from am3d.core.serializer import save_action
    from PySide6.QtWidgets import QFileDialog

    win = _make_main_window()
    try:
        path = str(tmp_path / "walk.am3a")
        save_action(Action(name="walk", duration=1.5), path)

        monkeypatch.setattr(QFileDialog, "getOpenFileName",
                             staticmethod(lambda *a, **k: (path, "")))
        assert win.doc_ctrl.dirty is False
        count0 = win.undo_stack.count()

        win._file_import_action()

        assert "walk" in win.session.actions
        assert win.doc_ctrl.dirty is True
        assert win.undo_stack.count() == count0 + 1

        win.undo_stack.undo()
        assert "walk" not in win.session.actions
    finally:
        win.viewport._timer.stop()
        win.close()


def test_clear_pose_is_undoable_and_dirty():
    """Reset Pose must be undoable and mark the document dirty -- previously
    it called Session.clear_pose()/apply_pose() directly, bypassing both."""
    win = _make_main_window()
    try:
        win.session.add_bone("sphere", "root", (0, 0, 0), (0, 1, 0))
        win.session.pose_bone("sphere", "root", np.eye(3))
        win.session.apply_pose("sphere")
        win.doc_ctrl._mark_clean()
        win.current_context = ("bone", "sphere", "root")

        assert win.doc_ctrl.dirty is False
        count0 = win.undo_stack.count()

        win._clear_pose()

        assert "sphere" not in win.session.poses
        assert win.doc_ctrl.dirty is True
        assert win.undo_stack.count() == count0 + 1

        win.undo_stack.undo()
        assert "root" in win.session.poses.get("sphere", {})
    finally:
        win.viewport._timer.stop()
        win.close()


def test_switching_active_action_is_undoable_and_dirty():
    """Picking a different action from the Timeline dropdown must be
    undoable and mark the document dirty -- previously it called
    Session.set_active_action() directly, bypassing both, even though
    active_action is persisted document state (see serializer.py)."""
    win = _make_main_window()
    try:
        win.session.actions["walk"] = Action(name="walk", duration=1.0)
        win.session.actions["run"] = Action(name="run", duration=1.0)
        win.session.set_active_action("walk")
        win.doc_ctrl._mark_clean()

        assert win.doc_ctrl.dirty is False
        count0 = win.undo_stack.count()

        win.timeline_dock._on_action_changed("run")

        assert win.session.active_action == "run"
        assert win.doc_ctrl.dirty is True
        assert win.undo_stack.count() == count0 + 1

        win.undo_stack.undo()
        assert win.session.active_action == "walk"
    finally:
        win.viewport._timer.stop()
        win.close()


def test_file_new_clears_undo_history():
    """File->New must not let Ctrl+Z reach into the previous document's
    edits -- previously the undo stack was never cleared on New, only
    reset to a "clean" marker at whatever index it already had."""
    win = _make_main_window()
    win.show()
    try:
        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        assert win.undo_stack.count() > 0

        win._file_new()

        assert win.undo_stack.count() == 0
        assert win.undo_stack.isClean()
    finally:
        win.viewport._timer.stop()
        win.close()


def test_file_open_clears_undo_history(tmp_path, monkeypatch):
    """File->Open must not let Ctrl+Z reach into the previously open
    document's edits."""
    from PySide6.QtWidgets import QFileDialog
    win = _make_main_window()
    try:
        other = Session()
        other.create_object("cube")
        path = str(tmp_path / "other.am3d")
        other.save_project(path)

        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        assert win.undo_stack.count() > 0

        monkeypatch.setattr(
            QFileDialog, "getOpenFileName",
            staticmethod(lambda *a, **k: (path, "")))
        win._file_open()

        assert win.undo_stack.count() == 0
        assert win.undo_stack.isClean()
        assert "cube" in win.session.project.objects
    finally:
        win.viewport._timer.stop()
        win.close()


# --- LIFE-01 / LIFE-02: document lifecycle and empty-scene scheduling -------

def test_close_project_stops_playback_and_clears_document_state():
    """Finding LIFE-01: Close Project used to leave the playback timer
    running and the Play button checked while Home was shown, with the
    previous document's selection and properties context still live."""
    win = _make_main_window()
    try:
        win.doc_ctrl.session.create_object("hero")
        win._refresh_all()
        win.viewport.set_selected("hero")
        win.current_context = ("object", "hero", "")
        win.properties_dock.set_context("object", "hero", "")
        win.timeline_dock.play_button.setChecked(True)
        assert win.timeline_dock._play_timer.isActive()

        win.doc_ctrl._testing_discard = True
        win._file_close_project()

        assert not win.timeline_dock._play_timer.isActive(), "playback must stop"
        assert not win.timeline_dock.play_button.isChecked()
        assert win.current_context == ("", "", "")
        assert win.viewport._drag is None
        assert "hero" not in win.doc_ctrl.session.project.objects
    finally:
        win.viewport._timer.stop()
        win.close()


def test_cancelled_close_project_preserves_the_active_document(monkeypatch):
    """A cancelled Save/Discard/Cancel gate must change nothing at all."""
    win = _make_main_window()
    try:
        win.doc_ctrl.session.create_object("hero")
        win.doc_ctrl.mark_dirty()
        win.current_context = ("object", "hero", "")
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document",
                            lambda: False)
        win._file_close_project()
        assert "hero" in win.doc_ctrl.session.project.objects
        assert win.current_context == ("object", "hero", "")
    finally:
        win.viewport._timer.stop()
        win.close()


def test_empty_scene_render_settles_and_stops_rescheduling():
    """Finding LIFE-02: an empty scene left _dirty True forever, so every
    paint event re-enqueued a render that could never produce a frame."""
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QPaintEvent
    win = _make_main_window()
    try:
        vp = win.viewport
        win.doc_ctrl.session.project.objects.clear()
        vp.refresh()
        vp._render()
        assert vp._frame is None, "nothing to draw in an empty scene"
        assert vp._dirty is False, "the empty render is complete, not pending"

        vp._timer.stop()
        for _ in range(5):
            vp.paintEvent(QPaintEvent(QRect(0, 0, max(vp.width(), 1),
                                            max(vp.height(), 1))))
            assert not vp._timer.isActive(), \
                "a settled empty scene must not re-arm the render timer"
    finally:
        win.viewport._timer.stop()
        win.close()


def test_content_after_an_empty_render_still_renders():
    """The LIFE-02 fix must not make the viewport go permanently inert."""
    win = _make_main_window()
    try:
        vp = win.viewport
        win.doc_ctrl.session.project.objects.clear()
        vp.refresh(); vp._render()
        assert vp._frame is None and vp._dirty is False

        win.push_command(CreatePrimitiveCommand(
            win.doc_ctrl.session, "box", "box"))
        vp.refresh()
        assert vp._dirty is True
        assert vp._timer.isActive(), "new content must re-arm the render timer"
        vp._render()
        assert vp._frame is not None, "a non-empty scene must produce a frame"
    finally:
        win.viewport._timer.stop()
        win.close()
