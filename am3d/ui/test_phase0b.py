"""Phase 0 regression tests: lathe, extrude, duplicate, dirty/save semantics.
"""
from __future__ import annotations

import sys
import numpy as np
import pytest

from am3d.ui.operators import (
    CreatePrimitiveCommand, CreateSplineProfileCommand,
    LatheProfileCommand, ExtrudeProfileCommand, DuplicateObjectCommand,
)


def _make_main_window():
    """Create a MainWindow (skip when no display is available)."""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
    except Exception:
        pytest.skip("PySide6 not available or no display")
    from am3d.ui.app import MainWindow
    win = MainWindow()
    win.doc_ctrl._testing_discard = True  # suppress Save/Discard/Cancel dialogs
    win.show_editor()
    win.show()
    return win


def _create_spline_obj(win):
    """Helper: create an object with a profile spline."""
    from am3d.core.project import Spline, ControlPoint
    s = win.session
    obj = s.create_object("vase")
    obj.add_spline(Spline(name="profile", cps=[
        ControlPoint(np.array([0.5, 0.0, 0.0])),
        ControlPoint(np.array([0.8, 0.5, 0.0])),
        ControlPoint(np.array([0.6, 1.0, 0.0])),
        ControlPoint(np.array([0.3, 1.5, 0.0])),
    ]))
    return obj


def test_lathe_undoable():
    """Lathe Selected Profile is undoable and marks dirty."""
    win = _make_main_window()
    try:
        _create_spline_obj(win)
        win.current_context = ("object", "vase", "profile")
        win._lathe_selected()
        assert len(win.session.project.objects["vase"].patches) > 0
        assert not win.undo_stack.isClean()
        win.undo_stack.undo()
        assert len(win.session.project.objects["vase"].patches) == 0
    finally:
        win.viewport._timer.stop()
        win.close()


def test_extrude_undoable():
    """Extrude Selected Spline is undoable and marks dirty."""
    win = _make_main_window()
    try:
        _create_spline_obj(win)
        win.current_context = ("object", "vase", "profile")
        win._extrude_selected()
        assert len(win.session.project.objects["vase"].patches) > 0
        assert not win.undo_stack.isClean()
        win.undo_stack.undo()
        assert len(win.session.project.objects["vase"].patches) == 0
    finally:
        win.viewport._timer.stop()
        win.close()


def test_duplicate_undoable():
    """Duplicate Object is undoable and marks dirty."""
    win = _make_main_window()
    try:
        _create_spline_obj(win)
        win.current_context = ("object", "vase", "")
        win._duplicate_object()
        assert "vase_copy" in win.session.project.objects
        assert not win.undo_stack.isClean()
        win.undo_stack.undo()
        assert "vase_copy" not in win.session.project.objects
    finally:
        win.viewport._timer.stop()
        win.close()


def test_save_then_undo_is_dirty():
    """Edit -> Save -> Undo leaves document dirty (diverges from saved)."""
    win = _make_main_window()
    try:
        import tempfile, os
        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        tmp = tempfile.NamedTemporaryFile(suffix=".am3d", delete=False)
        tmp.close()
        path = tmp.name
        win.doc_ctrl.path = path
        win.doc_ctrl.do_save()
        assert win.undo_stack.isClean()
        win.undo_stack.undo()
        assert not win.undo_stack.isClean()
        assert win.doc_ctrl.dirty
        os.unlink(path)
    finally:
        win.viewport._timer.stop()
        win.close()


def test_new_clears_stale_selection():
    """File -> New clears stale selection and context (via testing flag)."""
    win = _make_main_window()
    try:
        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        win.current_context = ("object", "sphere", "")
        # Enable testing discard so _file_new doesn't show dialog
        win.doc_ctrl._testing_discard = True
        win._file_new()
        assert win.current_context == ("", "", "")
        assert len(win.session.project.objects) == 0
    finally:
        win.viewport._timer.stop()
        win.close()


# -- Operator-level tests (no display needed) ------------------------------

@pytest.fixture
def session():
    from am3d.core.script import Session
    s = Session()
    s.create_object("hero")
    return s


def test_create_spline_profile_command(session):
    cmd = CreateSplineProfileCommand(
        session, "newobj", "profile",
        [np.array([0.0, 0.0, 0.0]), np.array([0.5, 1.0, 0.0])])
    cmd.redo()
    assert "newobj" in session.project.objects
    assert "profile" in session.project.objects["newobj"].splines
    cmd.undo()
    assert "newobj" not in session.project.objects
    cmd.redo()
    assert "newobj" in session.project.objects


def test_lathe_profile_command(session):
    profile = np.array([[0.5, 0.0], [0.8, 0.5], [0.6, 1.0], [0.3, 1.5]])
    cmd = LatheProfileCommand(session, "hero", profile, sections=16)
    cmd.redo()
    assert len(session.project.objects["hero"].patches) == 1
    cmd.undo()
    assert len(session.project.objects["hero"].patches) == 0


def test_extrude_profile_command(session):
    profile = np.array([[0.5, 0.0, 0.0], [0.5, 1.0, 0.5], [0.5, 2.0, 0.0]])
    cmd = ExtrudeProfileCommand(session, "hero", profile, height=2.0)
    cmd.redo()
    assert len(session.project.objects["hero"].patches) == 1
    cmd.undo()
    assert len(session.project.objects["hero"].patches) == 0


def test_duplicate_object_command(session):
    session.add_bone("hero", "root", (0, 0, 0), (0, 1, 0))
    cmd = DuplicateObjectCommand(session, "hero", "hero_copy")
    cmd.redo()
    assert "hero_copy" in session.project.objects
    assert "hero_copy" in session.project.skeletons
    cmd.undo()
    assert "hero_copy" not in session.project.objects
    assert "hero_copy" not in session.project.skeletons