"""Small diagnostic desktop flow for recipe-v1 local generation (M2)."""

from __future__ import annotations

from pathlib import Path
import time

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPlainTextEdit,
    QPushButton, QVBoxLayout,
)

from am3d.ai.contracts import GenerationStatus
from am3d.ai.runner import GenerationRunner


_STAGE_LABELS = {
    GenerationStatus.PREPARING: "Preparing",
    GenerationStatus.VALIDATING: "Validating",
    GenerationStatus.STARTING_WORKER: "Starting worker",
    GenerationStatus.BUILDING: "Building",
    GenerationStatus.CHECKING: "Checking",
    GenerationStatus.RENDERING_PREVIEW: "Rendering preview",
    GenerationStatus.PUBLISHING: "Publishing",
    GenerationStatus.COMPLETE: "Complete",
    GenerationStatus.FAILED: "Failed",
    GenerationStatus.CANCELLED: "Cancelled",
    GenerationStatus.TIMED_OUT: "Timed out",
}


class GenerationDialog(QDialog):
    """Choose/paste a recipe, observe the real worker stages, and inspect output."""

    def __init__(self, runner: GenerationRunner, on_open, parent=None):
        super().__init__(parent)
        self.runner = runner
        self.on_open = on_open
        self.active_run_id: str | None = None
        self._opened_result_id: str | None = None
        self._started_at = 0.0
        self._last_result = None
        self.setWindowTitle("Generate from recipe")
        self.resize(760, 720)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            'Paste a recipe-v1 JSON document, for example:\n'
            '{"version":1,"name":"shape","objects":[{"name":"box","primitive":"box"}]}')
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.stage = QLabel("Ready")
        self.stage.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.elapsed = QLabel("")
        self.preview = QLabel("A whole-scene preview will appear here after checks.")
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(280)
        self.preview.setStyleSheet("QLabel { border: 1px solid #555; }")
        self.details = QLabel("")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.browse_button = QPushButton("Choose recipe JSON…")
        self.generate_button = QPushButton("Generate")
        self.cancel_button = QPushButton("Cancel run")
        self.open_button = QPushButton("Open in Editor")
        self.close_button = QPushButton("Close")
        self.cancel_button.setEnabled(False)
        self.open_button.setEnabled(False)

        top = QHBoxLayout()
        top.addWidget(self.browse_button)
        top.addStretch(1)
        top.addWidget(self.generate_button)
        top.addWidget(self.cancel_button)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self.open_button)
        buttons.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Recipe-v1 JSON"))
        layout.addWidget(self.editor, 2)
        layout.addLayout(top)
        status_row = QHBoxLayout()
        status_row.addWidget(self.stage, 1)
        status_row.addWidget(self.elapsed)
        layout.addLayout(status_row)
        layout.addWidget(self.preview, 2)
        layout.addWidget(self.details)
        layout.addLayout(buttons)

        self.browse_button.clicked.connect(self._browse)
        self.generate_button.clicked.connect(self._generate)
        self.cancel_button.clicked.connect(self._cancel)
        self.open_button.clicked.connect(self._open)
        self.close_button.clicked.connect(self.reject)
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._poll)
        self.timer.start()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose recipe", "", "Recipe JSON (*.json);;All files (*)")
        if not path:
            return
        try:
            with open(path, "rb") as fh:
                raw = fh.read(128 * 1024 + 1)
            self.editor.setPlainText(raw.decode("utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            QMessageBox.warning(self, "Could not read recipe", str(exc))

    def _generate(self):
        text = self.editor.toPlainText()
        self.preview.clear()
        self.preview.setText("Generation is running…")
        self.details.clear()
        self.open_button.setEnabled(False)
        try:
            self.active_run_id = self.runner.start(text)
        except Exception as exc:
            QMessageBox.warning(self, "Could not start generation", str(exc))
            self.preview.setText("Generation did not start.")
            return
        self._last_result = None
        self._opened_result_id = None
        self._started_at = time.monotonic()
        self.stage.setText("Preparing")
        self.elapsed.setText("0.0 s")
        self._set_input_enabled(False)
        self.generate_button.setEnabled(False)
        self.cancel_button.setEnabled(self.runner.running)

    def _cancel(self):
        if self.runner.cancel():
            self.cancel_button.setEnabled(False)
            self.stage.setText("Stopping worker…")
            self.preview.setText("Waiting for the worker process to stop.")

    def _poll(self):
        result = self.runner.poll()
        for event in self.runner.drain_events():
            if event.run_id == self.active_run_id:
                self.stage.setText(_STAGE_LABELS.get(event.stage, event.stage.value))
                if event.elapsed_seconds is not None:
                    self.elapsed.setText(f"{event.elapsed_seconds:.1f} s")
        if self.active_run_id is None:
            return
        if self.runner.running and self.runner.latest_run_id == self.active_run_id:
            self.elapsed.setText(f"{time.monotonic() - self._started_at:.1f} s")
            self.cancel_button.setEnabled(not self.runner.cancelling)
        if result is not None and result.run_id == self.active_run_id:
            self._last_result = result
        # Another app-owned timer may poll the process first. The result is
        # retained by the runner, so this dialog still receives its terminal
        # state without a UI-thread race.
        if (self._last_result is None and self.runner.last_result is not None and
                self.runner.last_result.run_id == self.active_run_id):
            self._last_result = self.runner.last_result
        if self._last_result is None:
            return
        final = self._last_result
        self.stage.setText(_STAGE_LABELS.get(final.status, final.status.value))
        self.elapsed.setText(f"{final.elapsed_seconds:.1f} s")
        self._set_input_enabled(True)
        self.generate_button.setEnabled(True)
        self.cancel_button.setEnabled(False)
        if final.ok and self.runner.is_current(final.run_id):
            path = self.runner.store.generations / final.run_id / "preview.png"
            pixmap = QPixmap(str(path))
            if not pixmap.isNull():
                self.preview.setPixmap(pixmap.scaled(
                    self.preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.preview.setText("Preview file could not be displayed.")
            self.details.setText(
                f"Checks passed: {sum(item.ok for item in final.checks)} · "
                f"Artifacts: {len(final.artifacts)} · Run {final.run_id}")
            self.open_button.setEnabled(True)
        else:
            errors = final.error_records or ({"message": "Generation failed."},)
            self.details.setText("\n".join(
                f"{item.get('stage', 'failure')}: {item.get('path', '')}: "
                f"{item.get('message', 'Generation failed.') }"
                for item in errors[:8]))
            self.preview.setText("No successful generation preview is available.")
            self.open_button.setEnabled(False)

    def _set_input_enabled(self, enabled: bool):
        self.editor.setEnabled(enabled)
        self.browse_button.setEnabled(enabled)

    def _open(self):
        result = self._last_result
        if (result is None or not result.ok or
                not self.runner.is_current(result.run_id) or
                self._opened_result_id == result.run_id):
            QMessageBox.warning(self, "Generation is no longer current",
                                "Start a fresh run before opening this result.")
            return
        try:
            opened = self.on_open(result.run_id)
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))
            return
        if opened:
            self._opened_result_id = result.run_id
            self.accept()

    def reject(self):
        if self.runner.running and self.runner.latest_run_id == self.active_run_id:
            self.runner.cancel()
            self.stage.setText("Stopping worker before closing…")
            return
        self.timer.stop()
        super().reject()
