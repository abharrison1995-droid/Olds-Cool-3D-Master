"""Settings dialog for 3D MASTER:2005.

Persists user preferences via QSettings.  Accessed from the Home screen
and the File/Edit menu.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox,
    QFormLayout, QGroupBox, QLabel, QSpinBox, QVBoxLayout, QWidget,
)


class SettingsDialog(QDialog):
    """Application settings: theme, navigation, rendering, project defaults."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(480)
        self._build_ui()
        self._load()

    def _build_ui(self):
        layout = QVBoxLayout(self)

        # -- General group ---------------------------------------------------
        grp = QGroupBox("General")
        form = QFormLayout(grp)

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["am2005", "dark"])
        self.theme_combo.setEnabled(False)  # only one theme for now
        form.addRow("Theme", self.theme_combo)

        self.undo_depth = QSpinBox()
        self.undo_depth.setRange(10, 500)
        self.undo_depth.setValue(100)
        form.addRow("Undo depth", self.undo_depth)

        self.autosave_interval = QSpinBox()
        self.autosave_interval.setSuffix(" min")
        self.autosave_interval.setRange(1, 60)
        self.autosave_interval.setValue(5)
        form.addRow("Autosave interval", self.autosave_interval)

        layout.addWidget(grp)

        # -- Rendering group -------------------------------------------------
        grp2 = QGroupBox("Rendering")
        form2 = QFormLayout(grp2)

        self.render_backend = QComboBox()
        self.render_backend.addItems(["Auto (GPU preferred)", "Software only"])
        form2.addRow("Render backend", self.render_backend)

        self.tessellation_preset = QComboBox()
        self.tessellation_preset.addItems(["Classic", "Chunky", "Smooth"])
        form2.addRow("Tessellation preset", self.tessellation_preset)

        self.show_grid = QCheckBox("Show grid in viewport")
        self.show_grid.setChecked(True)
        form2.addRow(self.show_grid)

        layout.addWidget(grp2)

        # -- Project defaults group ------------------------------------------
        grp3 = QGroupBox("Project defaults")
        form3 = QFormLayout(grp3)

        self.default_fps = QDoubleSpinBox()
        self.default_fps.setRange(1, 240)
        self.default_fps.setValue(30.0)
        form3.addRow("Default FPS", self.default_fps)

        self.default_frame_end = QSpinBox()
        self.default_frame_end.setRange(10, 10000)
        self.default_frame_end.setValue(120)
        form3.addRow("Default frame end", self.default_frame_end)

        layout.addWidget(grp3)

        # -- Buttons ---------------------------------------------------------
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load(self):
        """Load current values from QSettings."""
        s = QSettings("3DMASTER2005", "app")
        self.theme_combo.setCurrentText(s.value("theme", "am2005"))
        self.undo_depth.setValue(int(s.value("undoDepth", 100)))
        self.autosave_interval.setValue(int(s.value("autosaveInterval", 5)))
        self.render_backend.setCurrentText(
            s.value("renderBackend", "Auto (GPU preferred)"))
        self.tessellation_preset.setCurrentText(
            s.value("tessellationPreset", "Classic"))
        self.show_grid.setChecked(
            s.value("showGrid", True, type=bool))
        self.default_fps.setValue(float(s.value("defaultFps", 30.0)))
        self.default_frame_end.setValue(int(s.value("defaultFrameEnd", 120)))

    def _save(self):
        """Save current values to QSettings."""
        s = QSettings("3DMASTER2005", "app")
        s.setValue("theme", self.theme_combo.currentText())
        s.setValue("undoDepth", self.undo_depth.value())
        s.setValue("autosaveInterval", self.autosave_interval.value())
        s.setValue("renderBackend", self.render_backend.currentText())
        s.setValue("tessellationPreset", self.tessellation_preset.currentText())
        s.setValue("showGrid", self.show_grid.isChecked())
        s.setValue("defaultFps", self.default_fps.value())
        s.setValue("defaultFrameEnd", self.default_frame_end.value())
        self.accept()