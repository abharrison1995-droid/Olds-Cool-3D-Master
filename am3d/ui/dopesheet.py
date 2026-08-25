"""Dope sheet dock — keyframe editing and playback for choreography.

Replaces the original single-slider timeline.  The dock owns the project
clock (``Project.frame``, in seconds), the frame range / FPS (persisted in
``Project.animation_settings``) and playback; the inner
:class:`DopeSheetWidget` paints a frame ruler plus one row per animated
bone of the active action.

Interactions:

* Click / drag the ruler to scrub (drives the viewport pose chain).
* Drag a keyframe marker to move it (undoable, one command on release).
* ``I`` inserts a key for the selected bone's current pose at the current
  frame; ``Delete`` removes the selected keys; both undoable.
* Play runs a QTimer at the configured FPS and wraps at the range end.

The class is still named ``TimelineDock`` so the tiled layout and earlier
phase code keep working; ``timeline.py`` re-exports it for compatibility.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QSpinBox,
    QToolButton, QVBoxLayout, QWidget,
)

_DEFAULT_SETTINGS = {"frame_start": 0, "frame_end": 120, "fps": 30.0}


class DopeSheetWidget(QWidget):
    """Frame ruler + per-bone keyframe rows for the dock's active action."""

    RULER_H = 22
    ROW_H = 18
    LABEL_W = 130

    def __init__(self, dock):
        super().__init__(dock)
        self.dock = dock
        self.setMinimumHeight(90)
        self.setMouseTracking(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.selected = set()          # {(bone, prop, index)}
        self._drag = None              # {"kind": "scrub"|"key", ...}

    # -- model --------------------------------------------------------------
    def _settings(self):
        proj = self.dock.main.session.project
        return getattr(proj, "animation_settings", None) or \
            dict(_DEFAULT_SETTINGS)

    def _action(self):
        s = self.dock.main.session
        return s.actions.get(s.active_action) if s.active_action else None

    def _rows(self):
        """[(bone, [(channel, key_index, key), ...])] for the active action."""
        act = self._action()
        if act is None:
            return []
        rows = {}
        for ch in act.channels:
            rows.setdefault(ch.bone, []).extend(
                (ch, i, k) for i, k in enumerate(ch.keys))
        return sorted(rows.items())

    # -- mapping --------------------------------------------------------------
    def _frame_span(self):
        st = self._settings()
        start = float(st.get("frame_start", 0))
        end = float(st.get("frame_end", 120))
        return start, max(end, start + 1)

    def frame_to_x(self, frame):
        start, end = self._frame_span()
        w = max(self.width() - self.LABEL_W - 10, 1)
        return self.LABEL_W + (float(frame) - start) / (end - start) * w

    def x_to_frame(self, x):
        start, end = self._frame_span()
        w = max(self.width() - self.LABEL_W - 10, 1)
        f = start + (x - self.LABEL_W) / w * (end - start)
        return min(max(f, start), end)

    def _row_y(self, row_index):
        return self.RULER_H + row_index * self.ROW_H

    def _hit_key(self, x, y):
        """(bone, channel, index) of the key near (x, y), or None."""
        for row, (bone, keys) in enumerate(self._rows()):
            ry = self._row_y(row) + self.ROW_H // 2
            if abs(y - ry) > self.ROW_H // 2:
                continue
            for ch, i, k in keys:
                kx = self.frame_to_x(k.time * self._fps())
                if abs(x - kx) <= 5:
                    return bone, ch, i
        return None

    def _fps(self):
        return float(self._settings().get("fps", 30.0))

    # -- painting --------------------------------------------------------------
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(58, 58, 58))
        start, end = self._frame_span()
        fps = self._fps()

        # Ruler: adaptive tick spacing (aim for >= 60 px between labels).
        painter.fillRect(0, 0, self.width(), self.RULER_H,
                         QColor(45, 45, 48))
        w = max(self.width() - self.LABEL_W - 10, 1)
        px_per_frame = w / (end - start)
        step = 1
        while step * px_per_frame < 60:
            step *= 10 if step * px_per_frame < 6 else 5
        pen = QPen(QColor(200, 200, 200))
        painter.setPen(pen)
        f = start
        while f <= end:
            x = self.frame_to_x(f)
            painter.drawLine(int(x), self.RULER_H - 8, int(x), self.RULER_H)
            if abs((f - start) % step) < 1e-9:
                painter.drawText(int(x) + 2, self.RULER_H - 10, str(int(f)))
            f += 1
        painter.drawLine(self.LABEL_W, self.RULER_H - 1,
                         self.width(), self.RULER_H - 1)

        # Rows.
        rows = self._rows()
        ghost = self._drag if self._drag and self._drag["kind"] == "key" \
            else None
        for row, (bone, keys) in enumerate(rows):
            y = self._row_y(row)
            painter.fillRect(0, y, self.width(), self.ROW_H,
                             QColor(64, 64, 64) if row % 2
                             else QColor(58, 58, 58))
            painter.setPen(QPen(QColor(220, 220, 220)))
            painter.drawText(4, y + self.ROW_H - 5, bone)
            for ch, i, k in keys:
                frame = k.time * fps
                if ghost is not None and ghost["key"] == (bone, ch, i):
                    frame = ghost["ghost"]
                x = self.frame_to_x(frame)
                cy = y + self.ROW_H // 2
                sel = (bone, ch.property, i) in self.selected
                color = QColor(255, 150, 40) if sel else QColor(90, 200, 255)
                painter.setPen(QPen(color))
                painter.setBrush(color)
                painter.drawPolygon([
                    QPoint(int(x), cy - 5),
                    QPoint(int(x) + 5, cy),
                    QPoint(int(x), cy + 5),
                    QPoint(int(x) - 5, cy),
                ])

        # Current-frame line.
        painter.setBrush(Qt.NoBrush)
        painter.setPen(QPen(QColor(230, 70, 70)))
        cx = int(self.frame_to_x(self.dock.current_frame()))
        painter.drawLine(cx, 0, cx, self.height())
        painter.end()

    # -- interaction ---------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return super().mousePressEvent(event)
        x, y = event.position().x(), event.position().y()
        if y <= self.RULER_H:
            self._drag = {"kind": "scrub"}
            self.dock.set_frame(self.x_to_frame(x))
            return
        hit = self._hit_key(x, y)
        if hit is not None:
            bone, ch, i = hit
            self.selected = {(bone, ch.property, i)}
            self._drag = {"kind": "key", "bone": bone, "channel": ch,
                          "index": i, "key": (bone, ch, i),
                          "start_frame": round(ch.keys[i].time * self._fps()),
                          "ghost": round(ch.keys[i].time * self._fps())}
        else:
            self.selected = set()
        self.update()

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        x = event.position().x()
        if self._drag["kind"] == "scrub":
            self.dock.set_frame(self.x_to_frame(x))
        else:
            self._drag["ghost"] = round(self.x_to_frame(x))
            self.update()

    def mouseReleaseEvent(self, event):
        d, self._drag = self._drag, None
        if d is None or d["kind"] != "key":
            return
        after = int(d["ghost"])
        if after == d["start_frame"]:
            self.update()
            return
        from .operators import MoveKeyCommand, push_or_apply
        s = self.dock.main.session
        cmd = MoveKeyCommand(s, s.active_action, d["bone"],
                             d["channel"].property, d["index"],
                             after / self._fps())
        push_or_apply(self.dock.main, cmd, emit=self.dock.data_changed)
        self.selected = set()
        self.dock.refresh()
        self.dock.data_changed.emit()

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Delete, Qt.Key_X):
            self.dock.delete_selected_keys()
        elif key == Qt.Key_I:
            self.dock.key_selected_bone()
        elif key == Qt.Key_Space:
            self.dock.toggle_play()
        else:
            super().keyPressEvent(event)
            return
        self.update()


class TimelineDock(QWidget):
    """Dope sheet + transport for the Animate workspace.

    A plain widget so it can live inside the tiled area layout; the
    "Dock" name is kept for compatibility with earlier phases.
    """

    data_changed = Signal()
    # Emitted whenever the project clock moves (seconds).
    frame_changed = Signal(float)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self.setWindowTitle("Timeline")
        self._syncing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)

        row = QHBoxLayout()
        self.play_button = QToolButton()
        self.play_button.setText("Play")
        self.play_button.setCheckable(True)
        self.play_button.toggled.connect(self._on_play_toggled)
        row.addWidget(self.play_button)

        row.addWidget(QLabel("Frame:"))
        self.frame_spin = QSpinBox()
        self.frame_spin.valueChanged.connect(
            lambda v: self.set_frame(float(v)))
        row.addWidget(self.frame_spin)
        row.addWidget(QLabel("Range:"))
        self.start_spin = QSpinBox()
        self.end_spin = QSpinBox()
        for spin in (self.start_spin, self.end_spin):
            spin.setRange(-100000, 100000)
            spin.valueChanged.connect(self._on_range_changed)
            row.addWidget(spin)
        row.addWidget(QLabel("FPS:"))
        self.fps_spin = QDoubleSpinBox()
        self.fps_spin.setRange(1.0, 240.0)
        self.fps_spin.valueChanged.connect(self._on_range_changed)
        row.addWidget(self.fps_spin)

        row.addWidget(QLabel("Action:"))
        self.action_combo = QComboBox()
        self.action_combo.currentTextChanged.connect(self._on_action_changed)
        row.addWidget(self.action_combo)
        self.auto_key = QCheckBox("Auto-key")
        row.addWidget(self.auto_key)
        row.addStretch(1)
        layout.addLayout(row)

        self.sheet = DopeSheetWidget(self)
        layout.addWidget(self.sheet, 1)

        self._play_timer = QTimer(self)
        self._play_timer.timeout.connect(self._play_tick)

        self.refresh()

    # -- settings / clock ---------------------------------------------------
    def settings(self):
        proj = self.main.session.project
        settings = getattr(proj, "animation_settings", None)
        if settings is None:
            settings = proj.animation_settings = dict(_DEFAULT_SETTINGS)
        return settings

    def current_frame(self):
        return float(self.main.session.project.frame) * \
            float(self.settings().get("fps", 30.0))

    def set_frame(self, frame):
        """Move the clock to *frame*, evaluate assigned actions, refresh."""
        st = self.settings()
        start = float(st.get("frame_start", 0))
        end = float(st.get("frame_end", 120))
        fps = float(st.get("fps", 30.0))
        frame = min(max(float(frame), start), end)
        s = self.main.session
        s.project.frame = frame / fps
        # Sample -> pose -> FK for every assigned object; the viewport bone
        # overlay and skinned deform read session.posed_transforms.
        for oname, aname in s.action_assignments.items():
            s.apply_action_frame(oname, s.project.frame, aname)
        self._syncing = True
        try:
            self.frame_spin.setValue(int(round(frame)))
            self.sheet.update()
            self.frame_changed.emit(s.project.frame)
            self.data_changed.emit()
        finally:
            self._syncing = False

    # -- playback -------------------------------------------------------------
    def toggle_play(self):
        self.play_button.setChecked(not self.play_button.isChecked())

    def _on_play_toggled(self, playing):
        self.play_button.setText("Pause" if playing else "Play")
        if playing:
            fps = float(self.settings().get("fps", 30.0))
            self._play_timer.start(max(1, int(1000.0 / fps)))
        else:
            self._play_timer.stop()

    def _play_tick(self):
        st = self.settings()
        start = float(st.get("frame_start", 0))
        end = float(st.get("frame_end", 120))
        nxt = self.current_frame() + 1
        self.set_frame(start if nxt > end else nxt)     # loop

    # -- edits ---------------------------------------------------------------
    def _on_range_changed(self, *_args):
        if self._syncing:
            return
        from .operators import SetAnimationSettingsCommand, push_or_apply
        before = dict(self.settings())
        after = {"frame_start": self.start_spin.value(),
                 "frame_end": max(self.end_spin.value(),
                                  self.start_spin.value() + 1),
                 "fps": float(self.fps_spin.value())}
        if after == before:
            return
        push_or_apply(self.main,
                      SetAnimationSettingsCommand(self.main.session,
                                                  before, after),
                      emit=self.data_changed)
        self.refresh()
        self.data_changed.emit()

    def _on_action_changed(self, name):
        if self._syncing:
            return
        self.main.session.set_active_action(name or None)
        self.sheet.selected = set()
        self.sheet.update()

    def key_selected_bone(self):
        """Insert a key for the context bone's current pose (``I``)."""
        kind, oname, bname = getattr(self.main, "current_context",
                                     ("", "", ""))
        if kind == "bone":
            self.key_bone(oname, bname)

    def key_bone(self, object_name, bone_name):
        """Undoably key one bone's pose into the active action now."""
        import numpy as np
        from am3d.core.mathutil import decompose_trs
        from .operators import InsertKeyCommand, push_or_apply
        s = self.main.session
        if not s.active_action:
            return
        time = self.current_frame() / float(self.settings().get("fps", 30.0))
        rot = s.poses.get(object_name, {}).get(bone_name)
        m = np.eye(4)
        if rot is not None:
            m[:3, :3] = np.asarray(rot, dtype=np.float64).reshape(3, 3)
        _, euler_deg, _ = decompose_trs(m)
        push_or_apply(self.main, InsertKeyCommand(
            s, s.active_action, bone_name, "rotate", time,
            np.deg2rad(euler_deg)), emit=self.data_changed)
        offset = s.pose_offsets.get(object_name, {}).get(bone_name)
        if offset is not None:
            push_or_apply(self.main, InsertKeyCommand(
                s, s.active_action, bone_name, "translate", time, offset),
                emit=self.data_changed)
        self.refresh()
        self.data_changed.emit()

    def delete_selected_keys(self):
        """Undoably delete every selected key (highest index first)."""
        from .operators import DeleteKeyCommand, push_or_apply
        s = self.main.session
        if not s.active_action or not self.sheet.selected:
            return
        # Descending index per channel keeps indices valid as redos fire.
        for bone, prop, index in sorted(self.sheet.selected,
                                        key=lambda t: -t[2]):
            push_or_apply(self.main, DeleteKeyCommand(
                s, s.active_action, bone, prop, index),
                emit=self.data_changed)
        self.sheet.selected = set()
        self.refresh()
        self.data_changed.emit()

    # -- refresh ---------------------------------------------------------------
    def refresh(self):
        """Sync widgets from the session — does not emit ``data_changed``."""
        if self._syncing:
            return
        self._syncing = True
        try:
            st = self.settings()
            self.start_spin.setValue(int(st.get("frame_start", 0)))
            self.end_spin.setValue(int(st.get("frame_end", 120)))
            self.fps_spin.setValue(float(st.get("fps", 30.0)))
            start = float(st.get("frame_start", 0))
            end = float(st.get("frame_end", 120))
            self.frame_spin.setRange(int(start), int(end))
            self.frame_spin.setValue(int(round(self.current_frame())))

            s = self.main.session
            current = self.action_combo.currentText()
            active = s.active_action or current
            self.action_combo.clear()
            self.action_combo.addItems(list(s.actions))
            if active in s.actions:
                self.action_combo.setCurrentText(active)
        finally:
            self._syncing = False
        self.sheet.update()
