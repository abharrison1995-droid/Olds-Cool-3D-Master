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

import am3d
from PySide6.QtCore import QTimer
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

        # One lifecycle-owned autosave timer, created once and reused for
        # the life of the window; only its interval changes when the user
        # edits the Settings preference. It never marks the main document
        # clean — do_autosave() writes to a separate app-data snapshot file
        # and leaves self.doc_ctrl.dirty untouched either way.
        self._autosave_timer = QTimer(self)
        self._autosave_timer.timeout.connect(self._on_autosave_timeout)
        self._apply_autosave_interval()
        self._autosave_timer.start()

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
        self._apply_settings()
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
            from .operators import ClearPoseCommand
            self.push_command(ClearPoseCommand(self.session, target))
            self._refresh_all()

    def _auto_key(self, object_name, bone_name):
        """Auto-key hook: key a bone pose after a viewport pose drag."""
        dock = getattr(self, "timeline_dock", None)
        if dock is not None and dock.auto_key.isChecked() \
                and self.session.active_action:
            dock.key_bone(object_name, bone_name)

    
    def _build_menu(self):
        m = self.menuBar()
        fm = m.addMenu("&File")

        def _add(label, slot, sc=None):
            a = QAction(label, self)
            if sc:
                a.setShortcut(sc)
            a.triggered.connect(slot)
            fm.addAction(a)

        _add("&New", self._file_new, "Ctrl+N")
        _add("&Open .am3d...", self._file_open, "Ctrl+O")
        fm.addSeparator()
        _add("&Save .am3d", self._file_save, "Ctrl+S")
        _add("Save &As .am3d...", self._file_save_as)
        fm.addSeparator()
        _add("&Close Project", self._file_close_project)
        _add("Close &Editor", self.show_home)
        fm.addSeparator()
        _add("&Import Action (.am3a)...", self._file_import_action)
        _add("&Render Image / Sequence...", self._file_render, "F12")
        _add("Export O&BJ...", self._file_export_obj)
        _add("Export &GLB...", self._file_export_glb)
        fm.addSeparator()
        _add("&Quit", self.close, "Ctrl+Q")

        em = m.addMenu("&Edit")
        undo = self.undo_stack.createUndoAction(self, "&Undo")
        undo.setShortcut(QKeySequence.Undo)
        redo = self.undo_stack.createRedoAction(self, "&Redo")
        redo.setShortcuts([QKeySequence.Redo, QKeySequence("Ctrl+Shift+Z")])
        em.addAction(undo)
        em.addAction(redo)

        cm = m.addMenu("&Create")
        self._build_create_menu(cm)

        rm = m.addMenu("&Rig")
        rm.addAction("Add &Bone", self._rig_add_bone)
        rm.addAction("Add &Child Bone", self._rig_add_child_bone)
        rm.addAction("&Delete Selected Bone", self._rig_delete_bone)
        rm.addSeparator()
        rm.addAction("Bind &Geometry to Skeleton", self._rig_bind_geometry)
        rm.addAction("Clear &Pose", self._clear_pose)

        wm = m.addMenu("&Workspace")
        for name in WORKSPACE_NAMES:
            wm.addAction(name, lambda _=False, n=name: self.set_workspace(n))
        sm = m.addMenu("&Settings")
        sm.addAction("&Preferences...", self._file_settings)

        hm = m.addMenu("&Help")
        hm.addAction("&Quick Start", self._show_quick_start)
        hm.addAction("&Diagnostics...", self._show_diagnostics)
        hm.addAction("&About", self._about)

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
        from am3d.core.naming import allocate_unique_name
        obj_name = allocate_unique_name(self.session.project.objects.keys(), name)
        push_or_apply(self, CreatePrimitiveCommand(
            self.session, obj_name, name, params))
        self._refresh_all()

    # -- rigging (finding UI-01) ---------------------------------------------
    def rig_target(self):
        """``(object_name, bone_name)`` the Rig menu acts on.

        A selected bone names both; a selected object names the object with
        no bone; otherwise the viewport selection is used.
        """
        kind, oname, iname = self.current_context
        if kind == "bone" and oname in self.session.project.objects:
            # The selection can outlive the bone: deleting the last bone
            # drops the object's whole skeleton entry, and a stale context
            # then named a bone that no longer exists. Fall through to the
            # object-only answer instead of handing back a dead name.
            if iname in self.session.project.skeletons.get(oname, {}):
                return oname, iname
            return oname, ""
        if kind != "object" or not oname:
            sel = getattr(self.viewport, "selected", None) \
                or getattr(self.viewport, "_selected", None)
            if sel and sel[0] in self.session.project.objects:
                oname = sel[0]
        if oname in self.session.project.objects:
            return oname, ""
        return "", ""

    def _rig_status(self, message):
        self.statusBar().showMessage(message, 5000)

    def _object_extent(self, object_name):
        """``(center, size)`` of an object's control points, in object space."""
        import numpy as np
        from am3d.core.rigging import object_cp_positions
        obj = self.session.project.objects[object_name]
        positions, _ = object_cp_positions(obj)
        positions = np.asarray(positions, dtype=np.float64).reshape(-1, 3)
        if not len(positions):
            return np.zeros(3), np.ones(3)
        lo, hi = positions.min(axis=0), positions.max(axis=0)
        return (lo + hi) / 2.0, np.maximum(hi - lo, 1e-6)

    def _new_bone_name(self, object_name):
        from am3d.core.naming import allocate_unique_name
        existing = [b.name for b in self.session.get_bones(object_name)]
        return allocate_unique_name(existing, "bone")

    def _add_bone(self, object_name, head, tail, parent=None):
        from .operators import AddBoneCommand, push_or_apply
        name = self._new_bone_name(object_name)
        push_or_apply(self, AddBoneCommand(self.session, object_name, name,
                                           head, tail, parent=parent))
        self._refresh_all()
        self.current_context = ("bone", object_name, name)
        self.properties_dock.set_context("bone", object_name, name)
        self._rig_status(f"Added bone {name} on {object_name}")
        return name

    def _rig_add_bone(self):
        """Add a root bone spanning the lower half of the selected object."""
        import numpy as np
        object_name, _ = self.rig_target()
        if not object_name:
            self._rig_status("Select an object first to add a bone to it")
            return None
        center, size = self._object_extent(object_name)
        head = np.array([center[0], center[1] - size[1] / 2.0, center[2]])
        tail = head + np.array([0.0, size[1] / 2.0, 0.0])
        return self._add_bone(object_name, head, tail)

    def _rig_add_child_bone(self):
        """Add a bone continuing from the selected bone's tail."""
        import numpy as np
        object_name, bone_name = self.rig_target()
        if not object_name:
            self._rig_status("Select an object first to add a bone to it")
            return None
        if not bone_name:
            self._rig_status(
                "Select a bone first -- a child bone continues from its tail")
            return None
        bone = self.session.project.skeletons.get(object_name, {}).get(bone_name)
        if bone is None:      # selection went stale between click and call
            self._rig_status(f"Bone {bone_name!r} no longer exists")
            return None
        head = np.asarray(bone.tail, dtype=np.float64)
        direction = head - np.asarray(bone.head, dtype=np.float64)
        if float(np.linalg.norm(direction)) < 1e-9:
            direction = np.array([0.0, 1.0, 0.0])
        return self._add_bone(object_name, head, head + direction,
                              parent=bone_name)

    def _rig_delete_bone(self):
        from .operators import DeleteBoneCommand, push_or_apply
        object_name, bone_name = self.rig_target()
        if not object_name or not bone_name:
            self._rig_status("Select a bone to delete")
            return False
        push_or_apply(self, DeleteBoneCommand(self.session, object_name,
                                              bone_name))
        self.current_context = ("object", object_name, "")
        self.properties_dock.set_context("object", object_name, "")
        self._refresh_all()
        self._rig_status(f"Deleted bone {bone_name}; its children moved up")
        return True

    def _rig_bind_geometry(self):
        """Bind the selected object's geometry to its bones."""
        from am3d.core.script import ScriptingError
        from .operators import BindGeometryCommand, push_or_apply
        object_name, _ = self.rig_target()
        if not object_name:
            self._rig_status("Select an object to bind to its skeleton")
            return False
        if not self.session.get_bones(object_name):
            self._rig_status(
                f"{object_name} has no bones yet -- add a bone first")
            return False
        try:
            push_or_apply(self, BindGeometryCommand(self.session, object_name))
        except ScriptingError as exc:
            self._rig_status(f"Could not bind: {exc}")
            return False
        self._refresh_all()
        bound = sum(len(b.cp_weights)
                    for b in self.session.get_bones(object_name))
        self._rig_status(
            f"Bound {object_name} to {len(self.session.get_bones(object_name))} "
            f"bone(s); {bound} control-point weight(s) assigned")
        return True

    def _build_create_menu_workaround(self, cm):
        # _build_create_menu is defined above
        pass

    def _create_spline(self):
        """Undoably create a new object with a profile spline."""
        from .operators import CreateSplineProfileCommand, push_or_apply
        from am3d.core.naming import allocate_unique_name
        import numpy as np
        name = allocate_unique_name(self.session.project.objects.keys(), "spline")
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
        # Profile spline varies in X/Y; extract [radius, axial] as [X, Y].
        profile = pts[:, [0, 1]]  # X -> radius, Y -> axial
        if len(profile) < 2:
            return
        push_or_apply(self, LatheProfileCommand(
            self.session, oname, profile, sections=24,
            source_spline=sname))
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
            self.session, oname, pts, height=1.0, rings=4,
            source_spline=sname))
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
        from am3d.core.naming import allocate_unique_name
        name = allocate_unique_name(self.session.project.objects.keys(), f"{oname}_copy")
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
        # Show the properties tab this workspace exists for (finding UI-03).
        if ws.properties_tab and hasattr(self.properties_dock, "show_tab"):
            self.properties_dock.show_tab(ws.properties_tab)
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
        # Stop playback. setChecked(False) runs _on_play_toggled, which
        # stops the dopesheet's play timer -- leaving it running would keep
        # advancing frames on a document that is no longer open.
        self.timeline_dock.play_button.setChecked(False)
        self.timeline_dock._play_timer.stop()
        # Clear selections and abandon any in-progress drag/modal transform --
        # those hold direct references into the document being replaced.
        self.viewport.set_selected(None)
        self.viewport.cancel_interactions()
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
        self.home.set_examples(self._example_projects())
        self.menuBar().setVisible(False)
        self.workspace_tabs.setVisible(False)
        self.tiled.setVisible(False)
        self.update()

    def _example_projects(self) -> list[tuple[str, str]]:
        """Bundled example projects for the Home screen's Examples list.

        Resolved relative to the repo/package layout (am3d/ui/app.py ->
        parents[2] is the repo root) rather than hardcoded, so the app
        degrades to an empty list instead of a broken entry if the assets
        directory isn't present alongside the installed package.
        """
        assets = Path(__file__).resolve().parents[2] / "assets"
        candidates = [
            ("Vase (lathed spline)", assets / "vase_demo.am3d"),
            ("Generated character (knight)", assets / "demo" / "knight_project.am3d"),
        ]
        return [(label, str(path)) for label, path in candidates if path.is_file()]

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
        h.action_quick_start.connect(self._show_quick_start)
        h.action_diagnostics.connect(self._show_diagnostics)
        h.action_exit.connect(self._file_quit)
        h.action_recent.connect(self._open_recent)
        h.action_recover.connect(self._recover_project)
        h.action_example.connect(self._open_example)

    def _open_recent(self, path: str):
        """Open a project from the recent-projects list."""
        if not self.doc_ctrl.maybe_abandon_document():
            return
        try:
            self.doc_ctrl.do_open(path)
            self.doc_ctrl.add_recent(path)
            self._reset_document_ui_state()
            self._refresh_all()
            self.show_editor()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Open failed", str(exc))

    def _open_example(self, path: str):
        """Open a bundled example project (Home screen's Examples list).

        Uses do_open_example(), not do_open(), so the loaded document is
        pathless -- a plain Ctrl+S must route through Save As rather than
        silently overwriting the shipped asset file. Examples are also kept
        out of the recent-projects list: reopening via Recent would go
        through the ordinary do_open()/add_recent() and reintroduce the same
        overwrite risk.
        """
        if not self.doc_ctrl.maybe_abandon_document():
            return
        try:
            self.doc_ctrl.do_open_example(path)
            self._reset_document_ui_state()
            self._refresh_all()
            self.show_editor()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Open failed", str(exc))

    def _recover_project(self, path: str):
        """Open a recovery/autosave file."""
        if not self.doc_ctrl.maybe_abandon_document():
            return
        try:
            # recover_from() reports failure (corrupt/unreadable snapshot) by
            # returning False rather than raising, so it must be checked
            # explicitly — otherwise a failed recovery would fall through to
            # resetting the UI and entering the editor with nothing loaded,
            # and the user would never see an error.
            if not self.doc_ctrl.recover_from(path):
                from PySide6.QtWidgets import QMessageBox
                QMessageBox.critical(
                    self, "Recovery failed",
                    f"Could not recover project from:\n{path}")
                return
            self._reset_document_ui_state()
            self._refresh_all()
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
        """Close current project and return to Home.

        Finding LIFE-01: this used to swap the document and show Home without
        resetting the editor, so the playback timer kept ticking (and the Play
        button stayed checked) against the replaced document, an in-progress
        viewport drag kept a reference into it, and the stale selection and
        properties context survived into the next document. A *cancelled*
        close (maybe_abandon_document returning False) still changes nothing.
        """
        if not self.doc_ctrl.maybe_abandon_document():
            return
        self.doc_ctrl.do_new()
        self._reset_document_ui_state()
        self._refresh_all()
        self.show_home()

    def _file_import_action(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import action", "", "AM3D Action (*.am3a)")
        if not path:
            return
        try:
            # Parse the file first (no session side effects), then apply
            # the resulting Action through an undoable command — importing
            # an action is an authoring action like any other and must be
            # reversible with Ctrl+Z, not applied directly to the session.
            from am3d.core.serializer import load_action_file
            from .operators import ImportActionCommand
            act = load_action_file(path)
            self.push_command(ImportActionCommand(self.session, act))
            self.statusBar().showMessage(f"Imported action: {act.name}")
            self._refresh_all()
        except Exception as exc:
            QMessageBox.critical(self, "Import failed", str(exc))

    def _export_scene(self):
        """Evaluated world-space meshes and material colours for the
        current pose/frame — the same boundary the viewport and recipe
        exporter use, so a GUI export matches what's on screen (baked
        transforms, current pose deformation, visibility, material colour)
        rather than re-tessellating raw bind-pose geometry."""
        from am3d.core.scene import (bake_scene_atlases,
                                     scene_material_colors,
                                     scene_patch_material_colors)
        scene = self.session.evaluate_scene(apply_transforms=True, visible_only=True)
        meshes = {name: mesh for name, mesh in scene.meshes.items() if len(mesh.vertices)}
        # Per-patch assignments travel alongside the object colours so two
        # differently coloured patches on one object stay distinct in the
        # exported file (finding MAT-02); baked atlases carry pattern and
        # image appearance that a flat colour cannot express (MAT-01).
        atlases = {n: a for n, a in bake_scene_atlases(self.session).items()
                   if n in meshes}
        return (meshes, scene_material_colors(scene),
                scene_patch_material_colors(scene), atlases)

    def _file_render(self):
        """Open the render dialog (finding UI-02)."""
        from .render_dialog import RenderDialog
        dialog = RenderDialog(self)
        dialog.exec()
        if dialog.written:
            self.statusBar().showMessage(
                f"Rendered {len(dialog.written)} file(s): "
                f"{dialog.written[0]}", 8000)

    def _file_export_obj(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export OBJ", "model.obj", "Wavefront (*.obj)")
        if not path:
            return
        try:
            from am3d.export.obj import write_obj
            meshes, mat_colors, patch_colors, atlases = self._export_scene()
            write_obj(path, meshes, materials=mat_colors or None,
                      patch_materials=patch_colors or None,
                      textures=atlases or None)
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
            meshes, mat_colors, patch_colors, atlases = self._export_scene()
            write_glb(path, meshes, materials=mat_colors or None,
                      patch_materials=patch_colors or None,
                      textures=atlases or None)
            self.statusBar().showMessage("Exported: " + path)
        except Exception as exc:
            QMessageBox.critical(self, "Export failed", str(exc))

    def _file_settings(self):
        """Open the Settings dialog."""
        from .settings import SettingsDialog
        dlg = SettingsDialog(self)
        if dlg.exec():
            self._apply_autosave_interval()
            self._apply_settings()

    def _apply_settings(self):
        """Apply the undo-depth, grid-visibility, and render-backend
        Settings preferences to live state. Read fresh from QSettings each
        call (at startup and whenever Settings is accepted) rather than
        cached, so a mid-session change always takes effect immediately."""
        from PySide6.QtCore import QSettings
        s = QSettings("3DMASTER2005", "app")

        try:
            undo_depth = int(s.value("undoDepth", 100))
        except (TypeError, ValueError):
            undo_depth = 100
        # Qt silently refuses to change QUndoStack's limit once any command
        # has been pushed (it would have to discard history to shrink it) —
        # only apply it while the stack is still empty. The new value is
        # already persisted, so it takes effect on the next New/Open, which
        # starts with a fresh stack.
        if self.undo_stack.count() == 0:
            self.undo_stack.setUndoLimit(max(1, undo_depth))

        self.viewport.show_grid = s.value("showGrid", True, type=bool)
        self.viewport.force_software = (
            s.value("renderBackend", "Auto (GPU preferred)") == "Software only")
        self.viewport.update()

    def _apply_autosave_interval(self):
        """(Re)schedule the lifecycle-owned autosave timer from the Settings
        preference, in minutes. Reschedules the existing timer rather than
        recreating it, so a mid-session Settings change takes effect without
        disturbing the timer's identity or its connected signal."""
        from PySide6.QtCore import QSettings
        raw = QSettings("3DMASTER2005", "app").value("autosaveInterval", 5)
        try:
            minutes = int(raw)
        except (TypeError, ValueError):
            # A hand-edited or corrupted settings store must not be able to
            # crash startup (this runs from MainWindow.__init__) — fall back
            # to the dialog's own default rather than propagating.
            minutes = 5
        self._autosave_timer.setInterval(max(1, minutes) * 60_000)

    def _on_autosave_timeout(self):
        """Write an autosave snapshot if the document has unsaved changes.
        Never touches doc_ctrl.dirty — autosave is a recovery safety net,
        not a save, so the document must still prompt on Close/Quit/New."""
        if self.doc_ctrl.dirty:
            self.doc_ctrl.do_autosave()

    def _about(self):
        QMessageBox.about(
            self, "About 3D MASTER:2005",
            f"3D MASTER:2005  Version {am3d.__version__}\n\n"
            "A pure spline-based 3D character animation suite.\n"
            "Workspaces: Layout  Model  Rig  Animate  Render")

    def _show_quick_start(self):
        QMessageBox.information(
            self, "Quick Start",
            "1. New Empty Project (Ctrl+N), or double-click an Example "
            "below to open a finished one.\n"
            "2. Model: Create menu > a primitive, or draw a profile spline "
            "and Lathe/Extrude it into a surface.\n"
            "3. Rig: Rig menu > Add Bone, then Add Child Bone for each "
            "bone after it, then Bind Geometry to Skeleton -- until you "
            "bind, posing moves the bone but not the model. Select a bone "
            "in the Outliner and drag it in the viewport to pose it; the "
            "bundled Examples come pre-rigged.\n"
            "4. Animate: switch to the Animate workspace, set poses on the "
            "Timeline to key an Action.\n"
            "5. Save (Ctrl+S). Render Image / Sequence (F12) makes the "
            "final picture; Export OBJ/GLB writes the surfaces.\n\n"
            "Undo/Redo (Ctrl+Z / Ctrl+Y) cover every edit above, including "
            "keying poses and importing actions.\n\n"
            "The Vase and Generated Character entries under Examples are "
            "complete projects you can open, edit, and re-export to see the "
            "whole pipeline end to end.")

    def _show_diagnostics(self):
        """Report the live state a bug report or support request would
        actually need: versions, active renderer backend and why, the
        current document's identity/size, undo/autosave state, and where
        on disk the app is reading/writing from."""
        import sys as _sys
        import PySide6
        from PySide6.QtCore import qVersion, QSettings, QStandardPaths
        from .viewport3d import gpu_render_available

        s = QSettings("3DMASTER2005", "app")
        if self.viewport.force_software:
            backend = "Software (forced by Settings > Render backend)"
        elif gpu_render_available():
            backend = "GPU"
        else:
            backend = "Software (GPU renderer module unavailable)"

        proj = self.session.project
        doc_desc = (Path(self.doc_ctrl.path).name if self.doc_ctrl.has_path
                    else "(unsaved)")
        undo_limit = self.undo_stack.undoLimit()

        app_data = QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation)

        QMessageBox.information(
            self, "Diagnostics",
            f"3D MASTER:2005  Version {am3d.__version__}\n"
            f"Python {_sys.version.split()[0]}   "
            f"PySide6 {PySide6.__version__}   Qt {qVersion()}\n\n"
            f"Renderer backend: {backend}\n\n"
            f"Document: {doc_desc}"
            f"{'  (modified)' if self.doc_ctrl.dirty else ''}\n"
            f"Objects: {len(proj.objects)}   "
            f"Actions: {len(self.session.actions)}\n"
            f"Undo entries: {self.undo_stack.count()}   "
            f"Undo limit: {undo_limit if undo_limit else 'unlimited'}\n\n"
            f"Autosave interval: {int(s.value('autosaveInterval', 5))} min   "
            f"Snapshots on disk: {len(self.doc_ctrl.list_autosave_files())}\n"
            f"App data directory: {app_data}")


def main(argv=None) -> int:
    """Launch the application, or run packaged smoke-test mode.

    ``--smoke-test`` drives a real MainWindow through a representative
    workflow (see :mod:`am3d.ui.smoke`) instead of entering the interactive
    event loop, and returns without ever opening a persistent window --
    for a packaged build's own CI-style self-check (build_windows.ps1).
    ``--out PATH`` additionally writes the machine-readable manifest there
    (it is always printed to stdout).
    """
    raw_argv = list(argv if argv is not None else sys.argv)
    smoke_test = "--smoke-test" in raw_argv
    if smoke_test:
        raw_argv.remove("--smoke-test")
    out_path = None
    if "--out" in raw_argv:
        i = raw_argv.index("--out")
        if i + 1 >= len(raw_argv):
            print("error: --out requires a PATH argument", file=sys.stderr)
            return 2
        out_path = raw_argv[i + 1]
        del raw_argv[i:i + 2]

    app = QApplication.instance() or QApplication(raw_argv)
    apply_theme(app)

    if smoke_test:
        import json
        import tempfile
        from .smoke import run_smoke_test
        with tempfile.TemporaryDirectory(prefix="am3d_smoke_") as td:
            manifest = run_smoke_test(Path(td))
        text = json.dumps(manifest, indent=2)
        if out_path:
            Path(out_path).write_text(text, encoding="utf-8")
        print(text)
        return 0 if manifest["ok"] else 1

    win = MainWindow()
    win.show()
    return app.exec()