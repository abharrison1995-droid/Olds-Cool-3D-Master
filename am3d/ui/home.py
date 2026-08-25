"""Home hub: project-less landing screen for 3D MASTER:2005.

Displayed on launch and whenever no project is open.  Provides quick actions
for New, Open, Recent, Recover, and links to resources.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QPushButton, QSizePolicy, QVBoxLayout, QWidget,
)


class _HomeButton(QPushButton):
    """A large, styled action button for the home screen."""

    def __init__(self, text: str, description: str = ""):
        super().__init__(text)
        self.setObjectName("homeButton")
        self.setMinimumHeight(50)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(description)


class HomeWidget(QWidget):
    """Home screen with action buttons and a recent-projects list."""

    # Signals for the MainWindow to connect.
    action_new = Signal()
    action_open = Signal()
    action_recent = Signal(str)          # project path
    action_recover = Signal(str)         # autosave path
    action_enter_editor = Signal()
    action_about = Signal()
    action_quick_start = Signal()
    action_exit = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("homeWidget")
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(60, 40, 60, 40)
        layout.setSpacing(12)

        # Logo / title
        title = QLabel("3D MASTER:2005")
        title.setObjectName("homeTitle")
        title.setAlignment(Qt.AlignCenter)
        f = title.font()
        f.setPointSize(36)
        f.setBold(True)
        title.setFont(f)
        layout.addWidget(title)

        subtitle = QLabel("Spline-based 3D character animation")
        subtitle.setObjectName("homeSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        f2 = subtitle.font()
        f2.setPointSize(14)
        subtitle.setFont(f2)
        layout.addWidget(subtitle)

        layout.addSpacing(20)

        # Left: buttons / Right: recent projects
        row = QHBoxLayout()
        row.setSpacing(40)

        left = QVBoxLayout()
        left.setSpacing(8)

        def _btn(text, desc, signal):
            b = _HomeButton(text, desc)
            b.clicked.connect(signal.emit)
            left.addWidget(b)

        _btn("New Empty Project", "Create a new blank project", self.action_new)
        _btn("Open Project", "Open an existing .am3d project", self.action_open)
        _btn("Enter Editor", "Continue working in the current project", self.action_enter_editor)
        _btn("Quick Start", "Open the quick-start guide", self.action_quick_start)
        _btn("About", "About 3D MASTER:2005", self.action_about)
        _btn("Exit", "Exit the application", self.action_exit)

        left.addStretch(1)

        row.addLayout(left, 1)

        # Right: recent projects and recovery
        right = QVBoxLayout()
        right.setSpacing(8)

        rec_label = QLabel("Recent Projects")
        rec_label.setObjectName("homeSectionTitle")
        f3 = rec_label.font()
        f3.setPointSize(14)
        f3.setBold(True)
        rec_label.setFont(f3)
        right.addWidget(rec_label)

        self.recent_list = QListWidget()
        self.recent_list.setObjectName("homeRecentList")
        self.recent_list.setMinimumWidth(280)
        self.recent_list.setMaximumWidth(400)
        self.recent_list.itemDoubleClicked.connect(self._on_recent_double_click)
        right.addWidget(self.recent_list, 1)

        self.recover_btn = _HomeButton("Recover Autosave",
                                       "Recover unsaved work from a crash")
        self.recover_btn.setVisible(False)
        self.recover_btn.clicked.connect(self._on_recover)
        right.addWidget(self.recover_btn)

        row.addLayout(right, 1)
        layout.addLayout(row)

        # Version footer
        layout.addStretch(1)
        footer = QLabel("Version 0.2.0b1  |  Built on Python + PySide6")
        footer.setObjectName("homeFooter")
        footer.setAlignment(Qt.AlignCenter)
        layout.addWidget(footer)

    # -- public helpers -----------------------------------------------------

    def set_recent_projects(self, paths: list[str]):
        """Populate the recent-projects list."""
        self.recent_list.clear()
        for p in paths:
            name = Path(p).name
            item = QListWidgetItem(f"{name}  ({p})")
            item.setData(Qt.UserRole, p)
            item.setToolTip(p)
            self.recent_list.addItem(item)
        if not paths:
            item = QListWidgetItem("(No recent projects)")
            item.setFlags(Qt.NoItemFlags)
            self.recent_list.addItem(item)

    def set_recover_visible(self, visible: bool):
        """Show or hide the Recover Autosave button."""
        self.recover_btn.setVisible(visible)

    # -- internal slots -----------------------------------------------------

    def _on_recent_double_click(self, item: QListWidgetItem):
        path = item.data(Qt.UserRole)
        if path:
            self.action_recent.emit(path)

    def _on_recover(self):
        from .document_controller import DocumentController
        # Find the doc controller via parent chain
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, 'doc_ctrl'):
                ctrl = parent.doc_ctrl
                autosaves = ctrl.list_autosave_files()
                if autosaves:
                    self.action_recover.emit(autosaves[0])
                break
            parent = parent.parent()