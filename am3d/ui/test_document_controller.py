"""Tests for DocumentController's autosave identity and recovery safety.

Covers the Phase 5 "desktop reliability" fixes: distinct autosave slots per
document (so two unrelated documents never collide on one snapshot file),
safe Save-As after recovering from a snapshot, and corrupt-file recovery
that never partially mutates live state.
"""

from __future__ import annotations

import sys

import pytest

from PySide6.QtCore import QStandardPaths


def _qapp():
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        return app
    except Exception:
        pytest.skip("PySide6 not available or no display")


@pytest.fixture()
def isolated_app_data(tmp_path, monkeypatch):
    """Redirect QStandardPaths.AppLocalDataLocation to a tmp dir so autosave
    tests never read or write the user's real app-data directory."""
    monkeypatch.setattr(
        QStandardPaths, "writableLocation",
        staticmethod(lambda *a, **k: str(tmp_path)))
    return tmp_path


@pytest.fixture()
def doc_ctrl(isolated_app_data):
    _qapp()
    from am3d.ui.document_controller import DocumentController
    ctrl = DocumentController(None)
    ctrl.session.create_object("hero")
    return ctrl


def test_untitled_documents_get_distinct_autosave_paths(isolated_app_data):
    """Two never-saved documents must not share an autosave slot just
    because neither has a path yet."""
    _qapp()
    from am3d.ui.document_controller import DocumentController
    a = DocumentController(None)
    b = DocumentController(None)
    assert a.autosave_path() != b.autosave_path()


def test_do_new_regenerates_untitled_identity(doc_ctrl):
    """A fresh blank document (via File->New) must get its own autosave
    slot rather than reusing the discarded document's slot."""
    before = doc_ctrl.autosave_path()
    doc_ctrl.do_new()
    assert doc_ctrl.autosave_path() != before


def test_same_path_reopened_reuses_same_autosave_slot(doc_ctrl, tmp_path):
    """Reopening the same file must land on the same autosave slot both
    times, so recovery finds the latest snapshot for that document."""
    path = str(tmp_path / "vase.am3d")
    doc_ctrl.session.save_project(path)
    doc_ctrl.do_open(path)
    first = doc_ctrl.autosave_path()
    doc_ctrl.do_new()
    doc_ctrl.do_open(path)
    assert doc_ctrl.autosave_path() == first


def test_different_dirs_same_filename_dont_collide(doc_ctrl, tmp_path):
    """Two different files that merely share a basename (e.g. 'vase.am3d'
    in two different folders) must not collide on one autosave slot."""
    dir_a = tmp_path / "a"
    dir_b = tmp_path / "b"
    dir_a.mkdir()
    dir_b.mkdir()
    path_a = str(dir_a / "vase.am3d")
    path_b = str(dir_b / "vase.am3d")
    doc_ctrl.session.save_project(path_a)
    doc_ctrl.session.save_project(path_b)

    doc_ctrl.do_open(path_a)
    slot_a = doc_ctrl.autosave_path()
    doc_ctrl.do_open(path_b)
    slot_b = doc_ctrl.autosave_path()
    assert slot_a != slot_b


def test_recover_from_clears_path_for_safe_save_as(doc_ctrl, tmp_path):
    """A document recovered from an autosave snapshot must not silently
    overwrite that internal snapshot file on the next Save — the next Save
    must route through Save As instead."""
    path = str(tmp_path / "project.am3d")
    doc_ctrl.session.save_project(path)
    doc_ctrl.do_open(path)
    doc_ctrl._mark_clean()

    snapshot = str(tmp_path / "snapshot.autosave.am3d")
    doc_ctrl.session.save_project(snapshot)

    ok = doc_ctrl.recover_from(snapshot)
    assert ok is True
    assert doc_ctrl.path is None
    assert doc_ctrl.dirty is True
    assert doc_ctrl.has_path is False


def test_recover_from_gives_recovered_document_its_own_autosave_slot(doc_ctrl, tmp_path):
    """Recovering must not reuse whatever untitled slot preceded it."""
    before = doc_ctrl.autosave_path()
    snapshot = str(tmp_path / "snapshot.autosave.am3d")
    doc_ctrl.session.save_project(snapshot)
    assert doc_ctrl.recover_from(snapshot) is True
    assert doc_ctrl.autosave_path() != before


def test_recover_from_corrupt_file_returns_false_without_mutating_state(doc_ctrl, tmp_path):
    """A malformed recovery file must fail loudly (return False) and leave
    the current document's path/dirty/session state completely untouched —
    Session.load_project already verifies a candidate in isolation before
    committing, so no partial mutation should reach the controller either."""
    bad = tmp_path / "garbage.am3d"
    bad.write_bytes(b"not a valid am3d file \x00\x01\x02")

    original_path = doc_ctrl.path
    original_dirty = doc_ctrl.dirty
    original_objects = list(doc_ctrl.session.project.objects)

    ok = doc_ctrl.recover_from(str(bad))

    assert ok is False
    assert doc_ctrl.path == original_path
    assert doc_ctrl.dirty == original_dirty
    assert list(doc_ctrl.session.project.objects) == original_objects


def test_do_save_as_removes_stale_untitled_autosave_file(doc_ctrl, tmp_path, monkeypatch):
    """Once a never-saved document's content is safely at its new path, the
    old untitled autosave snapshot is an orphan and should be cleaned up
    rather than left behind for a future recovery scan to offer."""
    stale_autosave = doc_ctrl.autosave_path()
    doc_ctrl.do_autosave()
    assert os_path_exists(stale_autosave)

    dest = str(tmp_path / "saved" / "final.am3d")
    (tmp_path / "saved").mkdir()
    from PySide6.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                         staticmethod(lambda *a, **k: (dest, "")))

    result = doc_ctrl.do_save_as()
    assert result == dest
    assert not os_path_exists(stale_autosave)


def test_autosave_exists_and_lists_the_written_file(doc_ctrl):
    assert doc_ctrl.autosave_exists() is False
    doc_ctrl.mark_dirty()
    doc_ctrl.do_autosave()
    assert doc_ctrl.autosave_exists() is True
    assert doc_ctrl.autosave_path() in doc_ctrl.list_autosave_files()


def os_path_exists(path: str) -> bool:
    import os
    return os.path.exists(path)
