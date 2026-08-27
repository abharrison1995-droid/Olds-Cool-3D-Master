"""Phase 0 regression tests: primitive creation, dirty/save, undo/redo.

These test exact user-facing actions through the MainWindow.
"""
from __future__ import annotations

import sys
import numpy as np
import pytest

from am3d.ui.operators import (
    CreatePrimitiveCommand, CreateSplineProfileCommand,
    LatheProfileCommand, ExtrudeProfileCommand, DuplicateObjectCommand,
)


# -- helper: create a minimal QtMainWindow for tests -----------------------

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


# -- primitive creation tests ----------------------------------------------

def test_sphere_one_click():
    """Create -> Sphere adds one object named 'sphere'."""
    win = _make_main_window()
    try:
        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        assert "sphere" in win.session.project.objects
        assert len(win.session.project.objects["sphere"].patches) == 1
        assert not win.undo_stack.isClean()
    finally:
        win.viewport._timer.stop()
        win.close()


def test_sphere_undo_redo():
    """Sphere creation is undoable and redoable."""
    win = _make_main_window()
    try:
        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        assert "sphere" in win.session.project.objects
        win.undo_stack.undo()
        assert "sphere" not in win.session.project.objects
        win.undo_stack.redo()
        assert "sphere" in win.session.project.objects
    finally:
        win.viewport._timer.stop()
        win.close()


def test_repeated_sphere_creation_collision():
    """Repeated Sphere creation allocates collision-safe names."""
    win = _make_main_window()
    try:
        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        assert "sphere" in win.session.project.objects
        assert "sphere_001" in win.session.project.objects
        assert "sphere_002" in win.session.project.objects
    finally:
        win.viewport._timer.stop()
        win.close()


def test_all_six_primitives():
    """All six primitives create with one click and support undo."""
    prims = [
        ("sphere", dict(radius=0.8, sections=12, rings=8)),
        ("box", dict(width=1.0, height=1.0, depth=1.0)),
        ("cylinder", dict(radius=0.5, height=1.0)),
        ("cone", dict(radius=0.5, height=1.0)),
        ("torus", dict(major_radius=0.6, minor_radius=0.2)),
        ("plane", dict(width=1.0, height=1.0)),
    ]
    win = _make_main_window()
    try:
        for i, (pname, params) in enumerate(prims):
            name = f"obj_{i}"
            from am3d.ui.operators import push_or_apply
            push_or_apply(win, CreatePrimitiveCommand(
                win.session, name, pname, params))
            assert name in win.session.project.objects
            assert len(win.session.project.objects[name].patches) > 0
        assert not win.undo_stack.isClean()
        # Undo all
        for _ in prims:
            win.undo_stack.undo()
        assert len(win.session.project.objects) == 0
    finally:
        win.viewport._timer.stop()
        win.close()


def test_profile_spline_undoable():
    """Create Profile/Spline is undoable and marks dirty."""
    win = _make_main_window()
    try:
        win._create_spline()
        assert "spline" in win.session.project.objects
        assert not win.undo_stack.isClean()
        win.undo_stack.undo()
        assert "spline" not in win.session.project.objects
        win.undo_stack.redo()
        assert "spline" in win.session.project.objects
    finally:
        win.viewport._timer.stop()
        win.close()