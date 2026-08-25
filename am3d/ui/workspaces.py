"""Blender-style workspace tabs and per-workspace layout state.

A *workspace* is a named arrangement of areas (which panels are visible,
how the splitters are sized, which tool hints show in the header strip).
The definitions below are pure data — no Qt imports needed for them — so
headless tests can exercise the mode mapping and layout serialization.
The Qt widgets (:class:`WorkspaceTabBar`, :class:`ToolStrip`) live at the
bottom of the module.

Mapping onto the classic A:M modes:

    Layout  -> general (all panels, object editing)
    Model   -> "object"        (outliner + properties, spline focus)
    Rig     -> "segment"       (outliner + properties, bone focus)
    Animate -> "choreography"  (timeline prominent)
    Render  -> "material"      (properties/render settings focus)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field

# Panel identifiers used throughout the tiling code.
PANEL_OUTLINER = "outliner"
PANEL_PROPERTIES = "properties"
PANEL_TIMELINE = "timeline"

# Old four-mode workflow, kept for set_mode() compatibility.
MODES = ("object", "segment", "material", "choreography")


@dataclass
class Workspace:
    """A named, serializable arrangement of the tiled areas."""

    name: str
    mode: str                       # compatibility: classic A:M mode
    panels: tuple = ()              # visible PANEL_* identifiers
    # Default splitter geometry: (center, right) px for the main split,
    # (outliner, properties) px for the right column, timeline height px.
    main_sizes: tuple = (980, 300)
    right_sizes: tuple = (300, 380)
    timeline_size: int = 110
    tool_hint: str = ""             # header strip text (Phase 4 tools)
    # Per-session saved layout (splitter sizes), restored on switch-back.
    state: dict = field(default_factory=dict)


WORKSPACES = {
    "Layout": Workspace(
        name="Layout", mode="object",
        panels=(PANEL_OUTLINER, PANEL_PROPERTIES, PANEL_TIMELINE),
        tool_hint="General layout: scene overview, objects and playback."),
    "Model": Workspace(
        name="Model", mode="object",
        panels=(PANEL_OUTLINER, PANEL_PROPERTIES),
        tool_hint="Model: edit spline CPs (select an object first)."),
    "Rig": Workspace(
        name="Rig", mode="segment",
        panels=(PANEL_OUTLINER, PANEL_PROPERTIES),
        right_sizes=(360, 320),
        tool_hint="Rig: select a bone in the outliner, drag rings to pose."),
    "Animate": Workspace(
        name="Animate", mode="choreography",
        panels=(PANEL_OUTLINER, PANEL_PROPERTIES, PANEL_TIMELINE),
        timeline_size=160,
        tool_hint="Animate: scrub the dope sheet, I keys the selected bone, "
                  "drag keys to move them."),
    "Render": Workspace(
        name="Render", mode="material",
        panels=(PANEL_OUTLINER, PANEL_PROPERTIES),
        tool_hint="Render: material and render settings (Render tab)."),
}

WORKSPACE_NAMES = tuple(WORKSPACES)

# Classic mode -> workspace that replaces it.
MODE_TO_WORKSPACE = {ws.mode: ws.name for ws in WORKSPACES.values()}


def workspace_for_mode(mode):
    """Return the Workspace implementing the classic A:M *mode*."""
    return WORKSPACES[MODE_TO_WORKSPACE[mode]]


def serialize_layout_state(states):
    """Pack ``{workspace_name: {splitter: [sizes]}}`` into a JSON string."""
    return json.dumps({name: {k: list(v) for k, v in s.items()}
                       for name, s in states.items()})


def deserialize_layout_state(text):
    """Inverse of :func:`serialize_layout_state`; tolerant of bad input."""
    try:
        raw = json.loads(text)
    except (TypeError, ValueError):
        return {}
    out = {}
    for name, state in raw.items():
        if name in WORKSPACES and isinstance(state, dict):
            out[name] = {k: [int(x) for x in v]
                         for k, v in state.items()
                         if isinstance(v, (list, tuple))}
    return out


# ---------------------------------------------------------------------------
# Qt widgets (imported lazily by the app; headless users stop above).
# ---------------------------------------------------------------------------

from PySide6.QtCore import Qt, Signal  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QHBoxLayout, QLabel, QSizePolicy, QStackedWidget, QTabBar, QWidget,
)


class WorkspaceTabBar(QTabBar):
    """Document-less tab bar switching workspaces (Blender top-bar style)."""

    workspace_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMovable(False)
        self.setExpanding(False)
        self.setDocumentMode(True)
        for name in WORKSPACE_NAMES:
            self.addTab(name)
        self.currentChanged.connect(self._on_current)

    def _on_current(self, index):
        if 0 <= index < self.count():
            self.workspace_changed.emit(self.tabText(index))

    def set_workspace(self, name):
        """Select the tab for *name* without emitting when already current."""
        index = self.indexOf(name)
        if index < 0:
            return
        if index == self.currentIndex():
            self._on_current(index)     # first activation still applies
        else:
            self.setCurrentIndex(index)

    def indexOf(self, name):            # small helper mirroring QTabWidget
        for i in range(self.count()):
            if self.tabText(i) == name:
                return i
        return -1


class ToolStrip(QWidget):
    """Header strip above the viewport with per-workspace tool options.

    The hint label is the fallback; workspaces with real tool options
    (registered via :meth:`set_options`) show those widgets instead.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(6, 2, 6, 2)
        self.workspace_label = QLabel()
        self.workspace_label.setObjectName("toolStripWorkspace")
        row.addWidget(self.workspace_label)
        self._stack = QStackedWidget()
        self._stack.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Preferred)
        hint_page = QWidget()
        hint_row = QHBoxLayout(hint_page)
        hint_row.setContentsMargins(0, 0, 0, 0)
        self.hint_label = QLabel()
        self.hint_label.setObjectName("toolStripHint")
        hint_row.addWidget(self.hint_label)
        hint_row.addStretch(1)
        self._hint_page = self._stack.addWidget(hint_page)
        row.addWidget(self._stack, 1)
        self._pages = {}
        self.set_workspace(WORKSPACE_NAMES[0])

    def set_options(self, options):
        """Register per-workspace option widgets: ``{name: QWidget}``."""
        for name, widget in options.items():
            if name in WORKSPACES:
                self._pages[name] = self._stack.addWidget(widget)
        self.set_workspace(self.workspace_label.text()
                           or WORKSPACE_NAMES[0])

    def set_workspace(self, name):
        ws = WORKSPACES.get(name)
        if ws is None:
            return
        self.workspace_label.setText(ws.name)
        self.hint_label.setText(ws.tool_hint)
        self._stack.setCurrentIndex(
            self._pages.get(name, self._hint_page))
