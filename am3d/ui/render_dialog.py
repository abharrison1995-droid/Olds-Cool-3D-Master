"""Render dialog: destination, size, camera, frame range, progress, cancel.

Finding UI-02: the application could export geometry but had no way to
produce a finished image or frame sequence, so the Render workspace's
shading settings had nothing to apply them to.

The dialog is deliberately thin. Everything that can fail -- validation,
frame enumeration, rendering, writing -- lives in :mod:`am3d.render_job`
so it is testable without a display, and every error the user sees is a
``RenderError`` message that says what to do next.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog,
                               QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QProgressBar, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from am3d.render_job import (SEQUENCE, STILL, RenderCancelled, RenderError,
                             run_render)


class RenderDialog(QDialog):
    """Configure and run a still or animation render."""

    def __init__(self, main, parent=None):
        super().__init__(parent or main)
        self.main = main
        self.setWindowTitle("Render")
        self._cancelled = False
        self._running = False
        self.written = []

        form = QFormLayout()

        self.mode = QComboBox()
        self.mode.addItem("Single image", STILL)
        self.mode.addItem("Frame sequence (PNG per frame)", SEQUENCE)
        self.mode.currentIndexChanged.connect(self._sync_enabled)
        form.addRow("Render", self.mode)

        dest_row = QHBoxLayout()
        self.path = QLineEdit(self._default_path())
        browse = QPushButton("Browse...")
        browse.clicked.connect(self._browse)
        dest_row.addWidget(self.path, 1)
        dest_row.addWidget(browse)
        dest_holder = QWidget()
        dest_holder.setLayout(dest_row)
        form.addRow("Destination", dest_holder)

        size_row = QHBoxLayout()
        self.width = QSpinBox()
        self.width.setRange(1, 8192)
        self.width.setValue(960)
        self.height = QSpinBox()
        self.height.setRange(1, 8192)
        self.height.setValue(540)
        size_row.addWidget(self.width)
        size_row.addWidget(QLabel("x"))
        size_row.addWidget(self.height)
        size_row.addStretch(1)
        size_holder = QWidget()
        size_holder.setLayout(size_row)
        form.addRow("Size (px)", size_holder)

        self.camera = QComboBox()
        self.camera.addItem("Current viewport view", "viewport")
        self.camera.addItem("Fit whole scene", "scene")
        form.addRow("Camera", self.camera)

        self.start_frame = QSpinBox()
        self.start_frame.setRange(0, 1000000)
        self.end_frame = QSpinBox()
        self.end_frame.setRange(0, 1000000)
        self.end_frame.setValue(24)
        self.fps = QSpinBox()
        self.fps.setRange(1, 480)
        self.fps.setValue(int(self._settings().get("fps", 30) or 30))
        range_row = QHBoxLayout()
        range_row.addWidget(self.start_frame)
        range_row.addWidget(QLabel("to"))
        range_row.addWidget(self.end_frame)
        range_row.addWidget(QLabel("at"))
        range_row.addWidget(self.fps)
        range_row.addWidget(QLabel("fps"))
        range_holder = QWidget()
        range_holder.setLayout(range_row)
        form.addRow("Frames", range_holder)

        self.force_software = QCheckBox(
            "Force software rendering (ignore the GPU)")
        form.addRow(self.force_software)

        self.progress = QProgressBar()
        self.progress.setRange(0, 1)
        self.progress.setValue(0)
        self.status = QLabel("")
        self.status.setWordWrap(True)

        self.buttons = QDialogButtonBox()
        self.render_button = self.buttons.addButton(
            "Render", QDialogButtonBox.AcceptRole)
        self.close_button = self.buttons.addButton(QDialogButtonBox.Close)
        self.cancel_button = self.buttons.addButton(
            "Stop", QDialogButtonBox.DestructiveRole)
        self.cancel_button.setEnabled(False)
        self.render_button.clicked.connect(self.start_render)
        self.cancel_button.clicked.connect(self.request_cancel)
        self.close_button.clicked.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        self._sync_enabled()

    # -- helpers ------------------------------------------------------------
    def _settings(self):
        try:
            return self.main.session.project.render_settings or {}
        except Exception:
            return {}

    def _default_path(self):
        name = getattr(self.main, "current_project_name", None) or "render"
        return os.path.join(os.path.expanduser("~"), f"{name}.png")

    def _sync_enabled(self):
        sequence = self.mode.currentData() == SEQUENCE
        for widget in (self.end_frame, self.fps):
            widget.setEnabled(sequence)
        self.start_frame.setEnabled(True)

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Render to", self.path.text(), "PNG image (*.png)")
        if path:
            self.path.setText(path)

    def _camera(self):
        if self.camera.currentData() == "scene":
            from am3d.gpu import resolve_scene, scene_camera
            scene = resolve_scene(self.main.session)
            return scene_camera([m for m in scene.meshes.values()
                                 if len(getattr(m, "vertices", ()))])
        return self.main.viewport.camera

    def request_cancel(self):
        self._cancelled = True
        self.status.setText("Stopping after the current frame...")

    # -- the render ---------------------------------------------------------
    def start_render(self):
        """Validate, render, and report. Returns the paths written."""
        if self._running:
            return []
        self._cancelled = False
        self._running = True
        self.cancel_button.setEnabled(True)
        self.render_button.setEnabled(False)
        mode = self.mode.currentData()
        try:
            self.written = run_render(
                self.main.session, self._camera(),
                path=self.path.text().strip(),
                width=self.width.value(), height=self.height.value(),
                mode=mode,
                start_frame=self.start_frame.value(),
                end_frame=self.end_frame.value(),
                fps=self.fps.value(),
                force_software=self.force_software.isChecked(),
                on_progress=self._on_progress,
                should_cancel=lambda: self._cancelled)
        except RenderCancelled as stop:
            self.status.setText(str(stop))
        except RenderError as err:
            # Actionable message, not a traceback.
            self.status.setText(str(err))
            QMessageBox.warning(self, "Render", str(err))
        except Exception as exc:                    # pragma: no cover
            message = f"The render failed: {exc}"
            self.status.setText(message)
            QMessageBox.critical(self, "Render", message)
        else:
            count = len(self.written)
            where = (os.path.dirname(self.written[0]) if self.written else "")
            self.status.setText(
                f"Wrote {count} file{'s' if count != 1 else ''} to {where}"
                if count else "Nothing was written.")
        finally:
            self._running = False
            self.cancel_button.setEnabled(False)
            self.render_button.setEnabled(True)
        return self.written

    def _on_progress(self, done, total, path):
        self.progress.setRange(0, total)
        self.progress.setValue(done)
        self.status.setText(f"Frame {done} of {total}: "
                            f"{os.path.basename(path)}")
        from PySide6.QtWidgets import QApplication
        instance = QApplication.instance()
        if instance is not None:
            # Keep the progress bar and Stop button responsive.
            instance.processEvents()
