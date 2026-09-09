"""Recovery chooser (finding DATA-02).

Home used to emit ``list_autosave_files()[0]`` -- the first entry of a list
sorted by *file name*. With more than one snapshot on disk that silently
recovered an arbitrary document, gave the user no way to tell which one, and
offered no route to the others. This dialog shows document identity, the
original path and the snapshot time, and recovers only the selected entry;
every unselected snapshot is left untouched.
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QPushButton, QVBoxLayout)


def _format_time(value):
    if not value:
        return "unknown time"
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(value))


def _format_size(value):
    if not value:
        return "unknown size"
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} GB"


class RecoveryDialog(QDialog):
    """Pick one autosave snapshot to recover, or delete one deliberately."""

    def __init__(self, entries: list[dict], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recover unsaved work")
        self.setMinimumWidth(560)
        self._entries = list(entries)
        self._selected_path: str | None = None

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(
            "These snapshots were saved automatically and were never closed "
            "cleanly.\nChoose one to recover. The others are kept on disk."))

        self.list = QListWidget(self)
        self.list.setAlternatingRowColors(True)
        for entry in self._entries:
            self.list.addItem(self._make_item(entry))
        if self.list.count():
            self.list.setCurrentRow(0)
        self.list.itemDoubleClicked.connect(lambda _i: self._accept_selection())
        layout.addWidget(self.list, 1)

        self.detail = QLabel("")
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(self.detail)
        self.list.currentRowChanged.connect(self._update_detail)

        row = QHBoxLayout()
        self.delete_btn = QPushButton("Delete snapshot…", self)
        self.delete_btn.setToolTip(
            "Permanently discard the selected snapshot. Other snapshots and "
            "your saved project files are not affected.")
        self.delete_btn.clicked.connect(self._delete_selected)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Open | QDialogButtonBox.Cancel, parent=self)
        buttons.button(QDialogButtonBox.Open).setText("Recover")
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        self.buttons = buttons
        row.addWidget(buttons)
        layout.addLayout(row)
        # After the buttons exist: _update_detail() drives _sync_enabled().
        self._update_detail(self.list.currentRow())

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _make_item(entry: dict) -> QListWidgetItem:
        label = entry.get("display_name") or "Untitled"
        when = _format_time(entry.get("saved_at"))
        text = f"{label}    —  {when}"
        if entry.get("corrupt"):
            text += "   [unreadable snapshot]"
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, entry.get("path"))
        if entry.get("corrupt"):
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable)
        return item

    def _current_entry(self) -> dict | None:
        row = self.list.currentRow()
        if 0 <= row < len(self._entries):
            return self._entries[row]
        return None

    def _update_detail(self, _row=None):
        entry = self._current_entry()
        if entry is None:
            self.detail.setText("")
            self._sync_enabled()
            return
        origin = entry.get("original_path") or "never saved to a file yet"
        lines = [f"Original document: {origin}",
                 f"Snapshot: {entry.get('path')}",
                 f"Saved: {_format_time(entry.get('saved_at'))}   "
                 f"Size: {_format_size(entry.get('size_bytes'))}"]
        if entry.get("corrupt"):
            lines.append("This snapshot's description could not be read. "
                         "Recovery may fail; the file is left on disk either way.")
        self.detail.setText("\n".join(lines))
        self._sync_enabled()

    def _sync_enabled(self):
        entry = self._current_entry()
        usable = entry is not None and not entry.get("corrupt")
        self.buttons.button(QDialogButtonBox.Open).setEnabled(usable)
        self.delete_btn.setEnabled(entry is not None)

    def _accept_selection(self):
        entry = self._current_entry()
        if entry is None or entry.get("corrupt"):
            return
        self._selected_path = entry.get("path")
        self.accept()

    def _delete_selected(self):
        entry = self._current_entry()
        if entry is None:
            return
        confirm = QMessageBox.question(
            self, "Delete snapshot",
            f"Permanently delete the snapshot for “"
            f"{entry.get('display_name')}”?\n\nOther snapshots are kept.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if confirm != QMessageBox.Yes:
            return
        path = entry.get("path")
        for candidate in (path, str(path) + ".meta.json"):
            try:
                os.unlink(candidate)
            except OSError:
                pass
        row = self.list.currentRow()
        self._entries.pop(row)
        self.list.takeItem(row)
        self._update_detail()

    # -- public -------------------------------------------------------------

    @property
    def selected_path(self) -> str | None:
        """The snapshot the user chose, or None if they cancelled."""
        return self._selected_path
