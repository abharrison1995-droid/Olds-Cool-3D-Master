"""Shared test fixtures for am3d.ui.

Prevents blocking QMessageBox / QFileDialog dialogs from appearing during the
test suite so CI and interactive runs both complete unattended.

Individual tests that need to exercise the real dialog behaviour can
override the ``nondialog`` marker or restore the unpatched symbols explicitly.
"""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_blocking_dialogs(monkeypatch):
    """Patch QMessageBox.exec and QFileDialog to never block.

    * ``QMessageBox.exec`` returns ``Discard`` so that
      ``maybe_abandon_document`` short-circuits to "proceed".
    * ``QMessageBox.critical`` / ``QMessageBox.warning`` / ``QMessageBox.about``
      are no-ops (they normally call exec internally on some platforms, though
      on others they are static and modal already).
    * ``SettingsDialog.exec`` is redirected to ``reject`` so _file_settings
      returns immediately.
    * File-dialog getters return ``(None, None)`` so Open/Save-As / Import /
      Export operations cancel cleanly unless a test deliberately sets a path.
    """
    from PySide6.QtWidgets import QMessageBox
    import PySide6.QtWidgets as _qtw

    # --- QMessageBox ---------------------------------------------------------
    monkeypatch.setattr(QMessageBox, "exec", lambda self, *a, **kw: QMessageBox.Discard)

    # critical / warning / about are static methods on some PySide builds;
    # if they are instance-level, also patch them.
    for _mname in ("critical", "warning", "about", "aboutQt", "information",
                   "question"):
        if hasattr(QMessageBox, _mname) and callable(getattr(QMessageBox, _mname)):
            try:
                monkeypatch.setattr(QMessageBox, _mname,
                                    lambda *a, **kw: None)
            except (AttributeError, TypeError):
                pass

    # --- SettingsDialog.exec -------------------------------------------------
    try:
        from .settings import SettingsDialog
        monkeypatch.setattr(SettingsDialog, "exec",
                            lambda self, *a, **kw: 0)  # rejected → cancelled
    except Exception:
        pass

    # --- QFileDialog ---------------------------------------------------------
    # Return None/empty so operations that depend on a path short-circuit.
    _qtw.QFileDialog.getOpenFileName = lambda *a, **kw: (None, "")
    _qtw.QFileDialog.getSaveFileName = lambda *a, **kw: (None, "")
    _qtw.QFileDialog.getExistingDirectory = lambda *a, **kw: ""
    _qtw.QFileDialog.getOpenFileNames = lambda *a, **kw: ([], "")

    yield
