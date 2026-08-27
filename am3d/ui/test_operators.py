"""Tests for the undo/operator layer (am3d.ui.operators).

Commands need QUndoStack (QtGui) but no widgets, so they run anywhere
PySide6 imports; the MainWindow-level tests use the existing
skip-if-no-QApplication style.
"""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.project import ControlPoint
from am3d.core.script import Session
from am3d.ui.operators import (
    AddMaterialCommand, AddObjectCommand, DeleteMaterialCommand,
    DeleteObjectCommand, InsertCPCommand, MoveCPCommand, PoseBoneCommand,
    RemoveCPCommand, RenameObjectCommand, SetBoneEndpointsCommand,
    SetMaterialColorCommand, SetMaterialMapsCommand,
    SetObjectTransformCommand, SetObjectVisibleCommand, QUndoStack,
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
                if a.text() == "Edit"]
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
