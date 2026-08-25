"""Tests for the dope sheet / playback dock (am3d.ui.dopesheet).

Skip-if-no-QApplication style, matching the other UI tests: seek, key
insert/move/delete, playback wrap and settings edits are exercised on a
real MainWindow offscreen.
"""

from __future__ import annotations

import os

import numpy as np
import pytest


def _make_window():
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            import sys
            app = QApplication(sys.argv)
    except Exception:
        pytest.skip("PySide6 not available or no display")
    from am3d.ui.app import MainWindow
    win = MainWindow()
    win.set_workspace("Animate")
    return win


def _add_hero(win):
    s = win.session
    s.create_object("hero")
    s.add_bone("hero", "hip", (0, 0, 0), (0, 0.5, 0))
    s.add_bone("hero", "upper", (0, 0.5, 0), (0, 1.0, 0), parent="hip")
    return s


def _walk_path():
    return os.path.abspath(os.path.join(
        os.path.dirname(__file__), "..", "..", "assets", "walk.am3a"))


def test_dopesheet_defaults_and_settings_edits():
    win = _make_window()
    try:
        dock = win.timeline_dock
        assert dock.settings() == {"frame_start": 0, "frame_end": 120,
                                   "fps": 30.0}
        assert dock.sheet._rows() == []

        # Range/FPS edits persist into the project and are undoable.
        dock.end_spin.setValue(240)
        assert win.session.project.animation_settings["frame_end"] == 240
        win.undo_stack.undo()
        assert win.session.project.animation_settings["frame_end"] == 120
        dock.fps_spin.setValue(24.0)
        assert win.session.project.animation_settings["fps"] == 24.0
    finally:
        win.viewport._timer.stop()
        win.timeline_dock._play_timer.stop()
        win.close()


def test_seek_evaluates_assigned_action():
    win = _make_window()
    try:
        s = _add_hero(win)
        s.load_action_file(_walk_path())
        s.assign_action("walk", "hero")
        dock = win.timeline_dock
        seen = []
        dock.frame_changed.connect(seen.append)

        dock.set_frame(0.0)
        hip0 = s.posed_transforms["hero"]["hip"][:3, 3].copy()
        dock.set_frame(30.0)                    # 1.0 s at 30 fps
        assert np.isclose(s.project.frame, 1.0)
        hip1 = s.posed_transforms["hero"]["hip"][:3, 3]
        assert np.allclose(hip1 - hip0, [0.5, 0, 0], atol=1e-9)
        assert seen                             # frame_changed emitted
    finally:
        win.viewport._timer.stop()
        win.timeline_dock._play_timer.stop()
        win.close()


def test_ruler_click_seeks():
    win = _make_window()
    try:
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        dock = win.timeline_dock
        sheet = dock.sheet
        sheet.resize(800, 100)
        x = sheet.frame_to_x(60)
        ev = QMouseEvent(QEvent.Type.MouseButtonPress, QPointF(x, 5),
                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
        sheet.mousePressEvent(ev)
        assert int(round(dock.current_frame())) == 60
        assert np.isclose(win.session.project.frame, 2.0)
    finally:
        win.viewport._timer.stop()
        win.timeline_dock._play_timer.stop()
        win.close()


def test_insert_key_for_poses_bone_undoable():
    win = _make_window()
    try:
        s = _add_hero(win)
        s.create_action("clip")
        s.pose_bone("hero", "upper", (0.0, 0.0, 30.0))
        s.apply_pose("hero")
        win.current_context = ("bone", "hero", "upper")

        dock = win.timeline_dock
        dock.set_frame(15.0)
        count0 = win.undo_stack.count()
        dock.key_selected_bone()
        assert win.undo_stack.count() > count0
        ch = s.get_action("clip").get_channel("upper", "rotate")
        assert ch is not None and len(ch.keys) == 1
        assert np.isclose(ch.keys[0].time, 0.5)
        win.undo_stack.undo()
        ch = s.get_action("clip").get_channel("upper", "rotate")
        assert ch is None or len(ch.keys) == 0
    finally:
        win.viewport._timer.stop()
        win.timeline_dock._play_timer.stop()
        win.close()


def test_drag_key_moves_with_undo():
    win = _make_window()
    try:
        from PySide6.QtCore import QEvent, QPointF, Qt
        from PySide6.QtGui import QMouseEvent
        s = _add_hero(win)
        s.create_action("clip")
        s.insert_keyframe("clip", "hip", "rotate", 0.0, [0.0, 0.0, 0.0])
        dock = win.timeline_dock
        dock.refresh()
        sheet = dock.sheet
        sheet.resize(800, 100)

        ch = s.get_action("clip").get_channel("hip", "rotate")
        x = sheet.frame_to_x(0)
        y = sheet._row_y(0) + sheet.ROW_H // 2

        def ev(kind, x_, y_):
            return QMouseEvent(kind, QPointF(x_, y_), Qt.LeftButton,
                               Qt.LeftButton, Qt.NoModifier)

        count0 = win.undo_stack.count()
        sheet.mousePressEvent(ev(QEvent.Type.MouseButtonPress, x, y))
        assert sheet._drag is not None and sheet._drag["kind"] == "key"
        sheet.mouseMoveEvent(ev(QEvent.Type.MouseMove,
                                sheet.frame_to_x(30), y))
        sheet.mouseReleaseEvent(ev(QEvent.Type.MouseButtonRelease,
                                   sheet.frame_to_x(30), y))
        assert win.undo_stack.count() == count0 + 1
        assert np.isclose(ch.keys[0].time, 1.0)      # frame 30 @ 30 fps
        win.undo_stack.undo()
        assert np.isclose(ch.keys[0].time, 0.0)
    finally:
        win.viewport._timer.stop()
        win.timeline_dock._play_timer.stop()
        win.close()


def test_delete_selected_keys_undoable():
    win = _make_window()
    try:
        s = _add_hero(win)
        s.create_action("clip")
        s.insert_keyframe("clip", "hip", "rotate", 0.0, [0.0, 0.0, 0.0])
        s.insert_keyframe("clip", "hip", "rotate", 1.0, [1.0, 0.0, 0.0])
        s.insert_keyframe("clip", "hip", "translate", 1.0, [0.5, 0, 0])
        dock = win.timeline_dock
        dock.refresh()
        # Select both keys at index 1 (across two channels).
        dock.sheet.selected = {("hip", "rotate", 1), ("hip", "translate", 0)}
        dock.delete_selected_keys()
        ch = s.get_action("clip").get_channel("hip", "rotate")
        assert len(ch.keys) == 1 and np.isclose(ch.keys[0].time, 0.0)
        ch2 = s.get_action("clip").get_channel("hip", "translate")
        assert len(ch2.keys) == 0
        win.undo_stack.undo()
        win.undo_stack.undo()
        assert len(ch.keys) == 2 and len(ch2.keys) == 1
    finally:
        win.viewport._timer.stop()
        win.timeline_dock._play_timer.stop()
        win.close()


def test_playback_timer_wraps_at_range_end():
    win = _make_window()
    try:
        dock = win.timeline_dock
        dock.toggle_play()
        assert dock._play_timer.isActive()
        assert dock.play_button.text() == "Pause"
        dock.set_frame(119.0)
        dock._play_tick()
        assert int(round(dock.current_frame())) == 120
        dock._play_tick()                           # wraps to start
        assert int(round(dock.current_frame())) == 0
        dock.toggle_play()
        assert not dock._play_timer.isActive()
    finally:
        win.viewport._timer.stop()
        win.timeline_dock._play_timer.stop()
        win.close()


def test_outliner_lists_actions_and_assigns():
    win = _make_window()
    try:
        s = _add_hero(win)
        s.create_action("clip")
        win.object_dock.refresh()
        item = win.object_dock._find("action", "", "clip")
        assert item is not None
        # Selecting the action row makes it the dope sheet's active action.
        win.object_dock.tree.setCurrentItem(item)
        assert s.active_action == "clip"
        # Assigning to the hero shows the assignment in the outliner label.
        win.viewport.set_selected("hero")
        win.object_dock._assign_action("clip", "hero")
        from PySide6.QtWidgets import QApplication
        QApplication.processEvents()         # outliner pushes are deferred
        assert s.action_assignments == {"hero": "clip"}
        win.undo_stack.undo()
        assert s.action_assignments == {}
    finally:
        win.viewport._timer.stop()
        win.timeline_dock._play_timer.stop()
        win.close()
