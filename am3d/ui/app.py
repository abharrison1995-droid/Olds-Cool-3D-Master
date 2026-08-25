"""Application entry: QMainWindow with Blender-style workspace tabs.

Run with ``python -m am3d.ui`` or ``python -m am3d.ui.app``.

The window hosts a fixed tiled area layout (see
:mod:`am3d.ui.area_layout`) switched between named workspaces
(:mod:`am3d.ui.workspaces`).  The classic four-mode workflow survives
through :meth:`MainWindow.set_mode`, which maps each mode onto its
workspace.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QAction, QKeySequence, QUndoStack
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QLabel, QMainWindow, QMessageBox,
    QToolButton, QVBoxLayout, QWidget,
)

from am3d.core.script import Session
from .area_layout import TiledArea
from .dopesheet import TimelineDock
from .object_panel import ObjectDock
from .properties import PropertiesDock
from .viewport import Viewport
from .workspaces import (
    MODE_TO_WORKSPACE, MODES, WORKSPACE_NAMES, WORKSPACES,
    ToolStrip, WorkspaceTabBar, workspace_for_mode,
)

# Classic A:M modes, kept for compatibility (see set_mode).
__all__ = ["MainWindow", "main", "MODES", "load_theme", "apply_theme"]

THEME_DIR = Path(__file__).resolve().parent
DEFAULT_THEME = "am2005"


def load_theme(name=DEFAULT_THEME):
    """Read the stylesheet ``theme_<name>.qss`` shipped with the UI.

    A future theme (e.g. "dark") is just another ``theme_dark.qss`` file
    in this directory.
    """
    path = THEME_DIR / f"theme_{name}.qss"
    return path.read_text(encoding="utf-8")


def apply_theme(app, name=DEFAULT_THEME):
    """Apply a named theme app-wide; returns True on success."""
    try:
        app.setStyleSheet(load_theme(name))
    except OSError:
        return False
    return True


def _render_backend_name():
    """Label for the status bar: GPU pipeline when importable, else toon."""
    try:
        from am3d.gpu import render_frame  # noqa: F401
    except Exception:
        return "software (toon)"
    return "GPU (moderngl)"


class MainWindow(QMainWindow):
    """The workspace-based editor window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("3D MASTER:2005")
        self.resize(1280, 820)
        self.session = Session()
        self.undo_stack = QUndoStack(self)
        self.current_workspace = WORKSPACE_NAMES[0]
        self.current_mode = MODES[0]
        # Current outliner/viewport context (kind, object_name, item_name).
        self.current_context = ("", "", "")
        # Saved splitter sizes per workspace (restored on switch-back).
        self._workspace_state = {}
        self._seed_scene()
        self.viewport = Viewport(self)
        self._build_panels()
        self._build_central()
        self._build_menu()
        self._build_status_bar()
        self._connect()
        self.set_workspace(WORKSPACE_NAMES[0])

    # -- construction ---------------------------------------------------------
    def _seed_scene(self):
        from am3d.recipes.primitives import build_primitive
        from am3d.core.project import Patch
        s = self.session
        s.create_object("sphere")
        for pname, net, du, dv in build_primitive(
                "sphere", dict(radius=0.8, sections=12, rings=8))["patches"]:
            s.get_object("sphere").patches.append(
                Patch(name=pname, splines=[], interior=net))
        s.create_material("base", color=(0.72, 0.75, 0.85))

    def _build_panels(self):
        self.object_dock = ObjectDock(self)
        self.properties_dock = PropertiesDock(self)
        self.timeline_dock = TimelineDock(self)
        self.tiled = TiledArea(self.viewport, self.object_dock,
                               self.properties_dock, self.timeline_dock,
                               self)

    def _build_central(self):
        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.workspace_tabs = WorkspaceTabBar()
        self.workspace_tabs.workspace_changed.connect(self.set_workspace)
        layout.addWidget(self.workspace_tabs)
        self.tool_strip = ToolStrip()
        self._build_tool_options()
        layout.addWidget(self.tool_strip)
        layout.addWidget(self.tiled, 1)
        self.setCentralWidget(central)

        # Compatibility layer: the old mode toolbar is gone, but the
        # checkable actions remain so set_mode() and any external
        # references keep working.
        self.mode_actions = {}
        for mode in MODES:
            act = QAction(mode.capitalize(), self)
            act.setCheckable(True)
            act.triggered.connect(lambda _, m=mode: self.set_mode(m))
            self.mode_actions[mode] = act

    def _build_tool_options(self):
        """Real per-workspace tool options for the header ToolStrip."""
        from PySide6.QtWidgets import QHBoxLayout
        self._gizmo_button_sets = []

        def gizmo_bar():
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            buttons = {}
            for label, mode in (("Move", "translate"),
                                ("Rotate", "rotate"),
                                ("Scale", "scale"),
                                ("Off", None)):
                btn = QToolButton()
                btn.setText(label)
                btn.setCheckable(True)
                btn.setAutoExclusive(True)
                btn.clicked.connect(
                    lambda _=False, m=mode: self.viewport.set_gizmo_mode(m))
                buttons[mode] = btn
                row.addWidget(btn)
            buttons[None].setChecked(True)
            row.addStretch(1)
            self._gizmo_button_sets.append(buttons)
            return w

        def hint_bar(text):
            w = QWidget()
            row = QHBoxLayout(w)
            row.setContentsMargins(0, 0, 0, 0)
            row.addWidget(QLabel(text))
            row.addStretch(1)
            return w

        model_bar = QWidget()
        row = QHBoxLayout(model_bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(gizmo_bar())
        row.addWidget(QLabel(
            "CP: click select · drag move · A / double-click add · "
            "X / Del delete"))
        row.addStretch(1)

        rig_bar = QWidget()
        row = QHBoxLayout(rig_bar)
        row.setContentsMargins(0, 0, 0, 0)
        clear = QToolButton()
        clear.setText("Clear Pose")
        clear.clicked.connect(self._clear_pose)
        row.addWidget(clear)
        row.addWidget(QLabel("Drag a ring on the selected bone to pose it"))
        row.addStretch(1)

        self.tool_strip.set_options({
            "Layout": gizmo_bar(),
            "Model": model_bar,
            "Rig": rig_bar,
            "Animate": hint_bar(
                "Animate: scrub ruler · drag keys · I key pose · "
                "Del remove · Space play"),
        })

    def _gizmo_mode_changed(self, mode):
        """Viewport gizmo mode changed (hotkey): sync the toolbar buttons."""
        for buttons in getattr(self, "_gizmo_button_sets", []):
            btn = buttons.get(mode)
            if btn is not None and not btn.isChecked():
                btn.setChecked(True)

    def _clear_pose(self):
        kind, oname, _ = self.current_context
        target = oname if kind == "bone" else (
            self.viewport.selected[0] if self.viewport.selected else None)
        if target:
            self.session.clear_pose(target)
            self.session.apply_pose(target)
            self._refresh_all()

    def _auto_key(self, object_name, bone_name):
        """Auto-key hook: key a bone pose after a viewport pose drag."""
        dock = getattr(self, "timeline_dock", None)
        if dock is not None and dock.auto_key.isChecked() \
                and self.session.active_action:
            dock.key_bone(object_name, bone_name)

    def push_command(self, command):
        """Push an undoable command (see :mod:`am3d.ui.operators`)."""
        self.undo_stack.push(command)

    def _build_menu(self):
        m = self.menuBar()
        fm = m.addMenu("File")

        def _add(label, slot, sc=None):
            a = QAction(label, self)
            if sc:
                a.setShortcut(sc)
            a.triggered.connect(slot)
            fm.addAction(a)

        _add("New", self._file_new)
        _add("Open .am3d...", self._file_open)
        _add("Save .am3d", self._file_save)
        fm.addSeparator()
        _add("Import Action (.am3a)...", self._file_import_action)
        _add("Export OBJ...", self._file_export_obj)
        _add("Export GLB...", self._file_export_glb)
        fm.addSeparator()
        _add("Quit", self.close, "Ctrl+Q")

        em = m.addMenu("Edit")
        undo = self.undo_stack.createUndoAction(self, "&Undo")
        undo.setShortcut(QKeySequence.Undo)
        redo = self.undo_stack.createRedoAction(self, "&Redo")
        redo.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Shift+Z")])
        em.addAction(undo)
        em.addAction(redo)
        wm = m.addMenu("Workspace")
        for name in WORKSPACE_NAMES:
            wm.addAction(name, lambda _=False, n=name: self.set_workspace(n))
        hm = m.addMenu("Help")
        hm.addAction("About", self._about)

    def _build_status_bar(self):
        bar = self.statusBar()
        self.status_workspace = QLabel()
        self.status_selection = QLabel("No selection")
        self.status_frame = QLabel()
        self.status_backend = QLabel(_render_backend_name())
        for w in (self.status_workspace, self.status_selection,
                  self.status_frame, self.status_backend):
            bar.addPermanentWidget(w)
        self._update_frame_status()

    def _connect(self):
        for d in (self.object_dock, self.properties_dock,
                  self.timeline_dock):
            d.data_changed.connect(self._refresh_all)
        self.viewport.selection_changed.connect(
            self.object_dock.on_viewport_selection)
        self.viewport.selection_changed.connect(
            self._on_viewport_selection)
        self.object_dock.context_changed.connect(
            self.properties_dock.set_context)
        self.object_dock.context_changed.connect(
            self._on_context_changed)
        self.timeline_dock.frame_changed.connect(
            self._update_frame_status)
        self.undo_stack.indexChanged.connect(lambda *_: self._refresh_all())

    # -- status bar -----------------------------------------------------------
    def _on_viewport_selection(self, name, _index):
        if name:
            self.properties_dock.set_context("object", name, "")
            self.current_context = ("object", name, "")
        else:
            self.current_context = ("", "", "")
        self._update_selection_status(name)

    def _on_context_changed(self, kind, object_name, item_name):
        self.current_context = (kind, object_name, item_name)
        label = {"object": object_name,
                 "bone": f"{object_name} / {item_name}",
                 "material": item_name}.get(kind, "")
        self._update_selection_status(label)

    def _update_selection_status(self, text):
        self.status_selection.setText(text or "No selection")

    def _update_frame_status(self, *_args):
        frame = float(getattr(self.session.project, "frame", 0.0))
        st = getattr(self.session.project, "animation_settings",
                     {"frame_start": 0, "frame_end": 120, "fps": 30.0})
        dur = (st["frame_end"] - st["frame_start"]) / st["fps"]
        self.status_frame.setText(f"Frame {frame:.1f} / {dur:.1f} s")

    # -- workspaces / modes -----------------------------------------------------
    def set_workspace(self, name):
        """Switch to workspace *name*, preserving per-workspace layout."""
        ws = WORKSPACES.get(name)
        if ws is None:
            return
        if name != self.current_workspace:
            # Remember how the user left the workspace we are leaving.
            self._workspace_state[self.current_workspace] = \
                self.tiled.sizes()
        self.current_workspace = name
        self.current_mode = ws.mode
        self.tiled.set_visible_panels(ws.panels)
        saved = self._workspace_state.get(name, ws.state)
        if saved:
            self.tiled.set_sizes(saved)
        else:
            self.tiled.set_sizes({
                "main": ws.main_sizes,
                "right": ws.right_sizes,
                "outer": (self.tiled.outer_splitter.height() or 700,
                          ws.timeline_size),
            })
        if self.workspace_tabs.indexOf(name) != \
                self.workspace_tabs.currentIndex():
            self.workspace_tabs.set_workspace(name)
        self.tool_strip.set_workspace(name)
        for m, act in self.mode_actions.items():
            act.setChecked(m == ws.mode)
        self.status_workspace.setText(f"Workspace: {name}")
        self.statusBar().showMessage(
            f"Workspace: {name} (mode: {ws.mode})")
        self._update_frame_status()
        self._refresh_all()

    def set_mode(self, mode):
        """Compatibility: classic A:M mode -> its workspace."""
        if mode not in MODES:
            return
        self.set_workspace(MODE_TO_WORKSPACE[mode])

    def _refresh_all(self):
        self.viewport.refresh()
        for d in (self.object_dock, self.properties_dock,
                  self.timeline_dock):
            d.refresh()
        self.viewport.update()

    def _save_project(self, project, path):
        from am3d.core.serializer import save_project
        save_project(project, path)

    def _load_project(self, path):
        from am3d.core.serializer import load_project
        return load_project(path)

    def _tessellate(self):
        from am3d.renderer.tessellate import tessellate_project
        return tessellate_project(self.session.project)

    def _file_new(self):
        if not self.undo_stack.isClean():
            answer = QMessageBox.question(
                self, "Unsaved changes",
                "Discard unsaved changes and start a new project?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if answer != QMessageBox.Yes:
                return
        self.session.new_project("Untitled")
        self.undo_stack.clear()
        self._refresh_all()

    def _file_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "AM3D Project (*.am3d)")
        if not path:
            return
        try:
            self.session = Session(project=self._load_project(path))
            self.undo_stack.clear()
            self._refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))

    def _file_save(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save project", "project.am3d", "AM3D Project (*.am3d)")
        if not path:
            return
        try:
            self._save_project(self.session.project, path)
            self.undo_stack.setClean()
            self.statusBar().showMessage("Saved: " + path)
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _file_import_action(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import action", "", "AM3D Action (*.am3a)")
        if not path:
            return
        try:
            act = self.session.load_action_file(path)
            self.statusBar().showMessage(f"Imported action: {act.name}")
            self._refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))

    def _file_export_obj(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export OBJ", "model.obj", "Wavefront (*.obj)")
        if not path:
            return
        try:
            from am3d.export.obj import write_obj
            write_obj(path, self._tessellate())
            self.statusBar().showMessage("Exported: " + path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _file_export_glb(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export GLB", "model.glb", "glTF binary (*.glb)")
        if not path:
            return
        try:
            from am3d.export.gltf import write_glb
            write_glb(path, self._tessellate())
            self.statusBar().showMessage("Exported: " + path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _about(self):
        QMessageBox.about(
            self, "About 3D MASTER:2005",
            "A pure spline-based 3D character animation suite.\n"
            "Workspaces: Layout  Model  Rig  Animate  Render")


def main(argv=None) -> int:
    """Launch the application."""
    app = QApplication(argv if argv is not None else sys.argv)
    apply_theme(app)
    win = MainWindow()
    win.show()
    return app.exec()
