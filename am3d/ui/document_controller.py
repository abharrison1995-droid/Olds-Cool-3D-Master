"""Document-lifecycle controller: owns the Session, dirty state, Save/Open/Close transitions.

This is the single authority for the current document.  Widgets resolve the
session through the main window; the controller ensures that every destructive
transition (New, Open, Close, Quit) goes through a Save/Discard/Cancel gate.

Atomic save: serialize to bytes first, write to a temp file, flush, then
rename over the destination.  On failure the original file remains intact.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget

from am3d.core.script import Session


class DocumentController:
    """Owns the current Session, project path, and dirty lifecycle."""

    def __init__(self, parent_widget: QWidget):
        self._parent = parent_widget
        self.session = Session()
        self._path: str | None = None
        self._dirty = False
        self._undo_blocked = False
        self._testing_discard = False  # When True, maybe_abandon_document auto-discards
        # Identity for an untitled/never-saved document's autosave slot —
        # regenerated whenever a *new* untitled document replaces this one
        # (do_new, recover_from), so two distinct blank documents never
        # share an autosave file just because neither has a path yet.
        self._untitled_id = uuid.uuid4().hex[:10]

    # -- properties ----------------------------------------------------------

    @property
    def path(self) -> str | None:
        return self._path

    @path.setter
    def path(self, value: str | None):
        self._path = value

    @property
    def dirty(self) -> bool:
        return self._dirty

    @dirty.setter
    def dirty(self, value: bool):
        self._dirty = bool(value)

    @property
    def display_name(self) -> str:
        """Human-readable name for the window title / dialogs."""
        name = self.session.project.name if self.session else "Untitled"
        if self._path:
            return Path(self._path).name
        return name

    @property
    def has_path(self) -> bool:
        return self._path is not None

    # -- undo stack sync ----------------------------------------------------

    def set_undo_stack(self, stack):
        """Attach the MainWindow's QUndoStack for clean-revision tracking."""
        self._undo_stack = stack

    def _mark_clean(self):
        """Mark the attached undo stack clean so dirty == divergence."""
        self._dirty = False
        stack = getattr(self, '_undo_stack', None)
        if stack is not None:
            stack.setClean()

# -- document transitions ------------------------------------------------

    def _ensure_atomic_save(self, path: str) -> None:
        """Save session atomically (delegating to Session.save_project)."""
        self.session.save_project(path)

    def do_new(self) -> None:
        """Reset to a blank project.  Caller must have checked maybe_abandon()."""
        self.session.new_project()
        self._apply_project_defaults()
        self._path = None
        self._untitled_id = uuid.uuid4().hex[:10]
        # A new blank document has no history of its own -- without this,
        # Ctrl+Z after File->New could undo edits from the *previous*
        # document, since QUndoStack has no concept of "which document".
        self._clear_undo()
        self._mark_clean()

    def _apply_project_defaults(self) -> None:
        """Apply the Settings dialog's default FPS / frame-end preference to
        a freshly created project, instead of Project's own hardcoded
        30fps/120-frame values."""
        from PySide6.QtCore import QSettings
        s = QSettings("3DMASTER2005", "app")
        try:
            fps = float(s.value("defaultFps", 30.0))
        except (TypeError, ValueError):
            fps = 30.0
        try:
            frame_end = int(s.value("defaultFrameEnd", 120))
        except (TypeError, ValueError):
            frame_end = 120
        # A hand-edited/corrupted settings store could carry a frame_end
        # <= frame_start (0); floor it the same way undo_depth is floored,
        # rather than handing the new project a degenerate animation range.
        frame_end = max(1, frame_end)
        project = self.session.project
        project.fps = fps
        project.animation_settings["fps"] = fps
        project.animation_settings["frame_end"] = frame_end

    def do_open(self, path: str) -> None:
        """Load *path*, replacing the current session."""
        self.session.load_project(path)
        self._path = path
        # Same reasoning as do_new(): a newly opened document must not
        # inherit undo history from whatever was open before it.
        self._clear_undo()
        self._mark_clean()

    def do_save(self) -> str | None:
        """Save to current path or prompt (Save As).  Returns path or None."""
        if self._path:
            self._ensure_atomic_save(self._path)
            self._mark_clean()
            return self._path
        return self.do_save_as()

    def do_save_as(self) -> str | None:
        """Prompt for a path then save.  Returns path or None on cancel."""
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(
            self._parent, "Save project",
            f'{self.display_name or "project"}.am3d',
            "AM3D Project (*.am3d)")
        if not path:
            return None
        if not path.endswith(".am3d"):
            path += ".am3d"
        stale_autosave = self.autosave_path()
        self._ensure_atomic_save(path)
        self._path = path
        self._mark_clean()
        # The document's identity (and so its autosave slot) just changed —
        # the content is now safely at *path*, so the previous slot is an
        # orphan. Clean it up rather than leaving a stale snapshot behind
        # that a future startup-recovery scan would offer for a document
        # that no longer exists in that form.
        if stale_autosave != self.autosave_path():
            try:
                Path(stale_autosave).unlink(missing_ok=True)
            except OSError:
                pass
        return path

    def maybe_abandon_document(self) -> bool:
        """If dirty, ask Save/Discard/Cancel.  True = proceed, False = cancel."""
        if not self._dirty:
            return True
        if self._testing_discard:
            return True
        if not self._parent or not self._parent.isVisible():
            return True

        msg = QMessageBox(self._parent)
        msg.setWindowTitle("Unsaved Changes")
        msg.setText(f"Save changes to \u201c{self.display_name}\u201d before proceeding?")
        msg.setInformativeText("Your changes will be lost if you don't save them.")
        msg.setIcon(QMessageBox.Question)
        msg.setStandardButtons(
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        msg.setDefaultButton(QMessageBox.Save)
        ret = msg.exec()

        if ret == QMessageBox.Save:
            result = self.do_save()
            if result is None:
                return False
            return True
        if ret == QMessageBox.Discard:
            return True
        return False  # Cancel

# -- dirty tracking helpers ----------------------------------------------

    def mark_dirty(self) -> None:
        self._dirty = True

    def _clear_undo(self) -> None:
        """Clear the undo stack on the parent MainWindow if available."""
        mw = getattr(self._parent, "main", None) or self._parent
        stack = getattr(mw, "undo_stack", None)
        if stack is not None:
            stack.clear()

    # -- recent projects (backed by QSettings) -------------------------------

    _MAX_RECENT = 10

    def recent_projects(self) -> list[str]:
        """Return the recent-project list (most recent first)."""
        from PySide6.QtCore import QSettings
        s = QSettings("3DMASTER2005", "app")
        raw = s.value("recentProjects", [])
        if not isinstance(raw, list):
            raw = []
        return [str(p) for p in raw if p and os.path.exists(str(p))]

    def add_recent(self, path: str) -> None:
        """Add *path* to the recent-project list (deduped, bounded)."""
        from PySide6.QtCore import QSettings
        s = QSettings("3DMASTER2005", "app")
        recent = self.recent_projects()
        try:
            recent = [str(path)] + [p for p in recent if p != str(path)]
        except Exception:
            recent = [str(path)]
        s.setValue("recentProjects", recent[:self._MAX_RECENT])

    # -- autosave ------------------------------------------------------------

    def _document_identity(self) -> str:
        """Stable id for this document's autosave slot.

        Derived from the resolved save path when one exists, so reopening
        the same file always lands on the same slot; otherwise the random
        id assigned to this untitled document. Without this, two different
        documents that merely share a filename (e.g. "vase.am3d" in two
        different folders) would collide on the same autosave file and
        silently clobber each other's recovery snapshot.
        """
        if self._path:
            resolved = os.path.realpath(self._path)
            return hashlib.sha1(
                resolved.encode("utf-8", "surrogateescape")).hexdigest()[:10]
        return self._untitled_id

    def autosave_path(self) -> str:
        """Return the autosave path for the current project."""
        from PySide6.QtCore import QStandardPaths
        app_data = Path(QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation))
        app_data.mkdir(parents=True, exist_ok=True)
        stem = Path(self._path).stem if self._path else "untitled"
        return str(app_data / f"{stem}-{self._document_identity()}.autosave.am3d")

    def do_autosave(self) -> None:
        """Write an autosave snapshot (best effort, never raises)."""
        try:
            path = self.autosave_path()
            self._ensure_atomic_save(path)
        except Exception:
            pass

    def autosave_exists(self) -> bool:
        """Check if any autosave file exists."""
        from PySide6.QtCore import QStandardPaths
        app_data = Path(QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation))
        return len(list(app_data.glob("*.autosave.am3d"))) > 0

    def list_autosave_files(self) -> list[str]:
        """List all autosave files in the app data directory."""
        from PySide6.QtCore import QStandardPaths
        app_data = Path(QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation))
        return sorted(str(p) for p in app_data.glob("*.autosave.am3d"))

    def recover_from(self, path: str) -> bool:
        """Load a recovery/autosave file.  Returns True on success.

        A recovered document opens dirty and pathless, even though the
        autosave file it loaded from has a real path on disk: the autosave
        slot is an internal app-data snapshot, not a project location the
        user chose, so the next Save must go through Save As rather than
        silently overwriting the snapshot file in place. A fresh untitled
        identity means the recovered document also gets its own autosave
        slot instead of reusing whatever untitled slot preceded it.
        """
        try:
            self.do_open(path)
            self._path = None
            self._untitled_id = uuid.uuid4().hex[:10]
            self._dirty = True
            return True
        except Exception:
            return False

    def clear_autosave(self) -> None:
        """Delete autosave files after a clean save/exit."""
        for p in self.list_autosave_files():
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass
