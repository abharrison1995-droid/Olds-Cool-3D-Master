"""Tiled area layout: Blender-style non-overlapping splitters.

Replaces the QDockWidget arrangement with a fixed tiling: a central
viewport, a right column (outliner over properties) and a bottom
timeline, all joined by drag-to-resize QSplitters.  Each area gets a
small header bar with its title, a collapse button and a context menu
placeholder (real split/join arrives with Phase 4).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QMenu, QSizePolicy, QSplitter, QToolButton,
    QVBoxLayout, QWidget,
)

from .workspaces import (
    PANEL_OUTLINER, PANEL_PROPERTIES, PANEL_TIMELINE,
)


class AreaPanel(QWidget):
    """A tiled area: header bar + one content widget."""

    collapsed_changed = Signal(bool)

    def __init__(self, title, content, parent=None):
        super().__init__(parent)
        self.content = content
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setObjectName("areaHeader")
        row = QHBoxLayout(header)
        row.setContentsMargins(6, 1, 2, 1)
        title_label = QLabel(title)
        title_label.setObjectName("areaTitle")
        row.addWidget(title_label)
        row.addStretch(1)

        self.collapse_button = QToolButton()
        self.collapse_button.setObjectName("areaCollapse")
        self.collapse_button.setText("–")
        self.collapse_button.setToolTip("Collapse this area")
        self.collapse_button.setAutoRaise(True)
        self.collapse_button.clicked.connect(self.toggle_collapsed)
        row.addWidget(self.collapse_button)

        menu_button = QToolButton()
        menu_button.setObjectName("areaMenu")
        menu_button.setText("▾")
        menu_button.setToolTip("Area options")
        menu_button.setAutoRaise(True)
        menu = QMenu(menu_button)
        menu.addAction("Split Area... (Phase 4)").setEnabled(False)
        menu.addAction("Join Area... (Phase 4)").setEnabled(False)
        menu_button.setMenu(menu)
        row.addWidget(menu_button)

        layout.addWidget(header)
        layout.addWidget(content, 1)
        self._collapsed = False

    def toggle_collapsed(self):
        self.set_collapsed(not self._collapsed)

    def set_collapsed(self, collapsed):
        self._collapsed = bool(collapsed)
        self.content.setVisible(not self._collapsed)
        self.collapse_button.setText("+" if self._collapsed else "–")
        self.collapsed_changed.emit(self._collapsed)


class TiledArea(QWidget):
    """The fixed tiling hosting viewport + panels in QSplitters."""

    def __init__(self, viewport, outliner, properties, timeline, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.viewport_panel = AreaPanel("Viewport", viewport)
        self.outliner_panel = AreaPanel("Outliner", outliner)
        self.properties_panel = AreaPanel("Properties", properties)
        self.timeline_panel = AreaPanel("Timeline", timeline)
        self._panels = {
            PANEL_OUTLINER: self.outliner_panel,
            PANEL_PROPERTIES: self.properties_panel,
            PANEL_TIMELINE: self.timeline_panel,
        }

        self.right_splitter = QSplitter(Qt.Vertical)
        self.right_splitter.setChildrenCollapsible(False)
        self.right_splitter.addWidget(self.outliner_panel)
        self.right_splitter.addWidget(self.properties_panel)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.addWidget(self.viewport_panel)
        self.main_splitter.addWidget(self.right_splitter)
        self.main_splitter.setStretchFactor(0, 1)
        self.main_splitter.setStretchFactor(1, 0)

        self.outer_splitter = QSplitter(Qt.Vertical)
        self.outer_splitter.setChildrenCollapsible(False)
        self.outer_splitter.addWidget(self.main_splitter)
        self.outer_splitter.addWidget(self.timeline_panel)
        self.outer_splitter.setStretchFactor(0, 1)
        self.outer_splitter.setStretchFactor(1, 0)

        layout.addWidget(self.outer_splitter)
        for panel in self._panels.values():
            panel.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.viewport_panel.setSizePolicy(
            QSizePolicy.Expanding, QSizePolicy.Expanding)

    # -- panel visibility ---------------------------------------------------
    def panel(self, name):
        return self._panels[name]

    def set_visible_panels(self, panels):
        for name, panel in self._panels.items():
            panel.setVisible(name in panels)

    def visible_panels(self):
        return tuple(name for name, p in self._panels.items()
                     if p.isVisible())

    # -- layout state ---------------------------------------------------------
    def sizes(self):
        """Current splitter sizes as a plain dict (JSON-friendly)."""
        return {
            "main": list(self.main_splitter.sizes()),
            "right": list(self.right_splitter.sizes()),
            "outer": list(self.outer_splitter.sizes()),
        }

    def set_sizes(self, state):
        """Restore splitter sizes saved by :meth:`sizes` (best effort)."""
        try:
            if state.get("main"):
                self.main_splitter.setSizes([int(x) for x in state["main"]])
            if state.get("right"):
                self.right_splitter.setSizes(
                    [int(x) for x in state["right"]])
            if state.get("outer"):
                self.outer_splitter.setSizes(
                    [int(x) for x in state["outer"]])
        except (TypeError, ValueError):
            pass
