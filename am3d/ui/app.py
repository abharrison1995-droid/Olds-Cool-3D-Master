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
    QStackedWidget, QToolButton, QVBoxLayout, QWidget,
)

from am3d.core.script import Session
from .area_layout import TiledArea
from .dopesheet import TimelineDock
from .home import HomeWidget
from .object_panel import ObjectDock
from .properties import PropertiesDock
from .viewport import Viewport
from .document_controller import DocumentController
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

        # Document controller owns the session, dirty state, and file ops.
        self.doc_ctrl = DocumentController(self)

        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._on_clean_changed)
        self.doc_ctrl.set_undo_stack(self.undo_stack)

        self.current_workspace = WORKSPACE_NAMES[0]
        self.current_mode = MODES[0]
        # Current outliner/viewport context (kind, object_name, item_name).
        self.current_context = ("", "", "")
        # Saved splitter sizes per workspace (restored on switch-back).
        self._workspace_state = {}
        self.viewport = Viewport(self)
        self._build_panels()
        self._build_central()
        self._build_menu()
        self._build_status_bar()
        self._connect()
        self.home = HomeWidget()
        self._connect_home()
        self.editor_widget = self._editor_widget  # built by _build_central
        self.stack = QStackedWidget()
        self.stack.addWidget(self.home)         # index 0
        self.stack.addWidget(self.editor_widget) # index 1
        self.setCentralWidget(self.stack)
        self.show_home()

    # -- session shortcut (backward compat for panels) -----------------------

    @property
    def session(self) -> Session:
        return self.doc_ctrl.session

    @session.setter
    def session(self, value: Session):
        self.doc_ctrl.session = value

    # -- title / dirty -------------------------------------------------------

    def _update_title(self):
        ctrl = self.doc_ctrl
        title = ctrl.display_name or "Untitled"
        if ctrl.dirty:
            title += " *"
        self.setWindowTitle(f"{title} - 3D MASTER:2005")

    def _on_clean_changed(self, clean: bool):
        self.doc_ctrl.dirty = not clean
        self._update_title()

    # -- construction ---------------------------------------------------------
    def _build_panels(self):
        self.object_dock = ObjectDock(self)
        self.properties_dock = PropertiesDock(self)
        self.timeline_dock = TimelineDock(self)
        self.tiled = TiledArea(self.viewport, self.object_dock,
                               self.properties_dock, self.timeline_dock,
                               self)

    def _build_central(self):
        self._editor_widget = QWidget()
        layout = QVBoxLayout(self._editor_widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.workspace_tabs = WorkspaceTabBar()
        self.workspace_tabs.workspace_changed.connect(self.set_workspace)
        layout.addWidget(self.workspace_tabs)
        self.tool_strip = ToolStrip()
        self._build_tool_options()
        layout.addWidget(self.tool_strip)
        layout.addWidget(self.tiled, 1)
        # Don't setCentralWidget here — we'll wrap it in a stack in __init__

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

    
    def _build_menu(self):
        m = self.menuBar()
        fm = m.addMenu("File")

        def _add(label, slot, sc=None):
            a = QAction(label, self)
            if sc:
                a.setShortcut(sc)
            a.triggered.connect(slot)
            fm.addAction(a)

        _add("New", self._file_new, "Ctrl+N")
        _add("Open .am3d...", self._file_open, "Ctrl+O")
        fm.addSeparator()
        _add("Save .am3d", self._file_save, "Ctrl+S")
        _add("Save As .am3d...", self._file_save_as)
        fm.addSeparator()
        _add("Close Project", self._file_close_project)
        _add("Close Editor", self.show_home)
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

        cm = m.addMenu("Create")
        self._build_create_menu(cm)

        wm = m.addMenu("Workspace")
        for name in WORKSPACE_NAMES:
            wm.addAction(name, lambda _=False, n=name: self.set_workspace(n))
        sm = m.addMenu("Settings")
        sm.addAction("Preferences...", self._file_settings)

        hm = m.addMenu("Help")
        hm.addAction("About", self._about)

    def _build_create_menu(self, cm):
        """Populate the Create menu with primitives and spline actions."""
        from .operators import CreatePrimitiveCommand

        primitives = [
            ("sphere", "Sphere", dict(radius=0.8, sections=12, rings=8)),
            ("box", "Box", dict(width=1.0, height=1.0, depth=1.0)),
            ("cylinder", "Cylinder", dict(radius=0.5, height=1.0)),
            ("cone", "Cone", dict(radius=0.5, height=1.0)),
            ("torus", "Torus", dict(major_radius=0.6, minor_radius=0.2)),
            ("plane", "Plane", dict(width=1.0, height=1.0)),
        ]
        for pname, label, params in primitives:
            act = cm.addAction(label)
            act.triggered.connect(
                lambda _=False, n=pname, p=params: self._do_primitive(n, p))

        cm.addSeparator()
        cm.addAction("Profile/Spline", self._create_spline)
        cm.addAction("Lathe Selected Profile", self._lathe_selected)
        cm.addAction("Extrude Selected Spline", self._extrude_selected)
        cm.addSeparator()
        cm.addAction("Duplicate Object", self._duplicate_object)

    def _do_primitive(self, name, params):
        """Undoably create a primitive object with collision-safe naming."""
        from .operators import CreatePrimitiveCommand, push_or_apply
        base = name
        obj_name = base
        i = 1
        while obj_name in self.session.project.objects:
            obj_name = f"{base}_{i:03d}"
            i += 1
            if i > 999:
                return
        push_or_apply(self, CreatePrimitiveCommand(
            self.session, obj_name, name, params))
        self._refresh_all()

    def _build_create_menu_workaround(self, cm):
        # _build_create_menu is defined above
        pass

    def _create_spline(self):
        """Undoably create a new object with a profile spline."""
        from .operators import CreateSplineProfileCommand, push_or_apply
        import numpy as np
        base = "spline"
        name = base
        i = 1
        while name in self.session.project.objects:
            name = f"{base}_{i:03d}"
            i += 1
            if i > 999:
                return
        cps = [
            np.array([0.0, -0.5, 0.0], dtype=np.float64),
            np.array([0.3, 0.0, 0.0], dtype=np.float64),
            np.array([0.0, 0.5, 0.0], dtype=np.float64),
            np.array([-0.3, 1.0, 0.0], dtype=np.float64),
        ]
        push_or_apply(self, CreateSplineProfileCommand(
            self.session, name, "profile", cps))
        self._refresh_all()

    def _lathe_selected(self):
        """Undoably lathe the selected object's profile spline."""
        from .operators import LatheProfileCommand, push_or_apply
        kind, oname, sname = self.current_context
        if kind != "object" or not oname:
            sel = getattr(self.viewport, "_selected", None)
            if sel and sel[0] in self.session.project.objects:
                oname = sel[0]
        obj = self.session.project.objects.get(oname)
        if not obj or not obj.splines:
            return
        sname = sname if sname in obj.splines else next(iter(obj.splines))
        spline = obj.splines[sname]
        pts = spline.point_array()
        # Profile spline varies in X/Y; extract [radius, axial] as [X, Z].
        profile = pts[:, [0, 2]]  # X -> radius, Z -> axial
        if len(profile) < 2:
            return
        push_or_apply(self, LatheProfileCommand(
            self.session, oname, profile, sections=24))
        self._refresh_all()

    def _extrude_selected(self):
        """Undoably extrude the selected spline."""
        from .operators import ExtrudeProfileCommand, push_or_apply
        kind, oname, sname = self.current_context
        if kind != "object" or not oname:
            sel = getattr(self.viewport, "_selected", None)
            if sel and sel[0] in self.session.project.objects:
                oname = sel[0]
        obj = self.session.project.objects.get(oname)
        if not obj or not obj.splines:
            return
        sname = sname if sname in obj.splines else next(iter(obj.splines))
        spline = obj.splines[sname]
        pts = spline.point_array()
        if len(pts) < 2:
            return
        push_or_apply(self, ExtrudeProfileCommand(
            self.session, oname, pts, height=1.0, rings=4))
        self._refresh_all()

    def _duplicate_object(self):
        """Undoably duplicate the selected object."""
        from .operators import DuplicateObjectCommand, push_or_apply
        kind, oname, _ = self.current_context
        if kind != "object" or not oname:
            sel = getattr(self.viewport, "_selected", None)
            if sel and sel[0] in self.session.project.objects:
                oname = sel[0]
        obj = self.session.project.objects.get(oname)
        if obj is None:
            return
        base = f"{oname}_copy"
        name = base
        i = 1
        while name in self.session.project.objects:
            name = f"{base}_{i:03d}"
            i += 1
            if i > 999:
                return
        push_or_apply(self, DuplicateObjectCommand(
            self.session, oname, name))
        self._refresh_all()

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
        self.undo_stack.indexChanged.connect(self._on_index_changed)

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
        self._update_title()

    def _tessellate(self):
        from am3d.renderer.tessellate import tessellate_project
        return tessellate_project(self.session.project)

    def _file_new(self):
        if not self.doc_ctrl.maybe_abandon_document():
            return
        self.doc_ctrl.do_new()
        self._reset_document_ui_state()
        self._refresh_all()
        self.show_editor()

    def _file_open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open project", "", "AM3D Project (*.am3d)")
        if not path:
            return
        # Check abandon only after the user has chosen a file
        if not self.doc_ctrl.maybe_abandon_document():
            return
        try:
            self.doc_ctrl.do_open(path)
            self._reset_document_ui_state()
            self._refresh_all()
            self.show_editor()
        except Exception as exc:
            QMessageBox.critical(self, "Open failed", str(exc))

    def _reset_document_ui_state(self):
        """Reset viewport, selection, panels, and playback after doc replacement."""
        # Stop playback
        self.timeline_dock.play_button.setChecked(False)
        # Clear selections
        self.viewport.set_selected(None)
        self.current_context = ("", "", "")
        # Clear properties and outliner
        self.properties_dock.set_context("", "", "")
        self.object_dock.refresh()
        self.properties_dock.refresh()
        self.timeline_dock.refresh()
        self.viewport._timer.stop()
        self.viewport._timer.start(33)

    def _file_save(self):
        try:
            result = self.doc_ctrl.do_save()
            if result:
                self.doc_ctrl.add_recent(result)
                self.statusBar().showMessage("Saved: " + result)
                self._update_title()
                self.home.set_recent_projects(self.doc_ctrl.recent_projects())
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def show_home(self):
        """Switch to the Home hub."""
        self.stack.setCurrentIndex(0)
        self.home.set_recent_projects(self.doc_ctrl.recent_projects())
        self.home.set_recover_visible(self.doc_ctrl.autosave_exists())
        self.menuBar().setVisible(False)
        self.workspace_tabs.setVisible(False)
        self.tiled.setVisible(False)
        self.update()

    def show_editor(self):
        """Switch to the editor workspace."""
        self.stack.setCurrentIndex(1)
        self.menuBar().setVisible(True)
        self.workspace_tabs.setVisible(True)
        self.tiled.setVisible(True)
        self._refresh_all()
        self.update()

    def _connect_home(self):
        """Wire HomeWidget signals to MainWindow actions."""
        h = self.home
        h.action_new.connect(self._file_new)
        h.action_open.connect(self._file_open)
        h.action_enter_editor.connect(self.show_editor)
        h.action_about.connect(self._about)
        h.action_exit.connect(self._file_quit)
        h.action_recent.connect(self._open_recent)
        h.action_recover.connect(self._recover_project)

    def _open_recent(self, path: str):
        """Open a project from the recent-projects list."""
        if not self.doc_ctrl.maybe_abandon_document():
            return
        try:
            self.doc_ctrl.do_open(path)
            self.doc_ctrl.add_recent(path)
            self.show_editor()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Open failed", str(exc))

    def _recover_project(self, path: str):
        """Open a recovery/autosave file."""
        if not self.doc_ctrl.maybe_abandon_document():
            return
        try:
            self.doc_ctrl.recover_from(path)
            self.show_editor()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Recovery failed", str(exc))

    def _file_quit(self):
        """Exit the application with dirty check."""
        self.close()

    def closeEvent(self, event):
        """Warn about unsaved changes on close."""
        if self.doc_ctrl.maybe_abandon_document():
            self.doc_ctrl.clear_autosave()
            event.accept()
        else:
            event.ignore()

    def _on_index_changed(self, *args):
        """Refresh all panels on undo/redo."""
        self._refresh_all()

    def push_command(self, cmd):
        """Push a QUndoCommand onto the undo stack (used by panels)."""
        self.undo_stack.push(cmd)
        self.doc_ctrl.mark_dirty()
        self._update_title()

    def _file_save_as(self):
        """Save to a new path."""
        try:
            result = self.doc_ctrl.do_save_as()
            if result:
                self.doc_ctrl.add_recent(result)
                self.statusBar().showMessage("Saved: " + result)
                self._update_title()
                self.home.set_recent_projects(self.doc_ctrl.recent_projects())
        except Exception as exc:
            QMessageBox.critical(self, "Save failed", str(exc))

    def _file_close_project(self):
        """Close current project and return to Home."""
        if self.doc_ctrl.maybe_abandon_document():
            self.doc_ctrl.do_new()
            self.show_home()

    def _file_import_action(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import action", "", "AM3D Action (*.am3a)")
        if not path:
            return
        try:
            act = self.session.load_action_file(path)
            self.doc_ctrl.mark_dirty()
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

    def _file_settings(self):
        """Open the Settings dialog."""
        from .settings import SettingsDialog
        dlg = SettingsDialog(self)
        dlg.exec()

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