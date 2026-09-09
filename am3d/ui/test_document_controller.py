"""Tests for DocumentController's autosave identity and recovery safety.

Covers the Phase 5 "desktop reliability" fixes: distinct autosave slots per
document (so two unrelated documents never collide on one snapshot file),
safe Save-As after recovering from a snapshot, and corrupt-file recovery
that never partially mutates live state.
"""

from __future__ import annotations

import os
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


def test_do_new_applies_default_fps_and_frame_end_from_settings(doc_ctrl, monkeypatch):
    """File->New should build the new project with the persisted
    Settings defaults (default FPS / default frame end), not Project's
    own hardcoded 30fps/120-frame values."""
    from PySide6.QtCore import QSettings
    s = QSettings("3DMASTER2005", "app")
    s.setValue("defaultFps", 24.0)
    s.setValue("defaultFrameEnd", 240)
    try:
        doc_ctrl.do_new()
        assert doc_ctrl.session.project.fps == 24.0
        assert doc_ctrl.session.project.animation_settings["fps"] == 24.0
        assert doc_ctrl.session.project.animation_settings["frame_end"] == 240
    finally:
        s.remove("defaultFps")
        s.remove("defaultFrameEnd")


def test_do_new_falls_back_on_corrupt_settings_values(doc_ctrl, monkeypatch):
    """A hand-edited/corrupted QSettings store must not crash File->New."""
    from PySide6.QtCore import QSettings
    monkeypatch.setattr(
        QSettings, "value",
        lambda self, key, default=None: "not-a-number")
    doc_ctrl.do_new()  # must not raise
    assert doc_ctrl.session.project.fps == 30.0
    assert doc_ctrl.session.project.animation_settings["frame_end"] == 120


def os_path_exists(path: str) -> bool:
    import os
    return os.path.exists(path)


# --- DATA-01: quitting one document must not destroy another's recovery -----

def test_clear_autosave_removes_only_the_current_documents_snapshot(
        isolated_app_data):
    """The DATA-01 blocker, reproduced end to end.

    Before the fix, clear_autosave() unlinked every ``*.autosave.am3d`` in
    the app-data directory, so closing document A on exit destroyed the
    unsaved recovery snapshot of document B.
    """
    _qapp()
    from am3d.ui.document_controller import DocumentController
    a = DocumentController(None)
    a.session.create_object("from_a")
    a.do_autosave()
    b = DocumentController(None)
    b.session.create_object("from_b")
    b.do_autosave()

    a_snap, b_snap = a.autosave_path(), b.autosave_path()
    assert a_snap != b_snap
    assert os.path.exists(a_snap) and os.path.exists(b_snap)

    a.clear_autosave()                      # what closeEvent() does on quit

    assert not os.path.exists(a_snap), "A's own snapshot should be cleared"
    assert os.path.exists(b_snap), "B's recovery must survive A's exit"

    # And B is still genuinely recoverable, not merely present as a file.
    fresh = DocumentController(None)
    assert fresh.recover_from(b_snap) is True
    assert "from_b" in fresh.session.project.objects


def test_clear_autosave_removes_the_sidecar_with_the_snapshot(doc_ctrl):
    doc_ctrl.do_autosave()
    meta = doc_ctrl.autosave_path() + ".meta.json"
    assert os.path.exists(meta)
    doc_ctrl.clear_autosave()
    assert not os.path.exists(meta)


def test_clear_all_autosaves_is_the_explicit_opt_in_sweep(isolated_app_data):
    _qapp()
    from am3d.ui.document_controller import DocumentController
    a, b = DocumentController(None), DocumentController(None)
    a.do_autosave(); b.do_autosave()
    a.clear_all_autosaves()
    assert a.list_autosave_files() == []


def test_main_window_exit_preserves_another_documents_recovery(
        isolated_app_data, tmp_path):
    """The plan's acceptance scenario driven through the real MainWindow:
    create recoveries for A and B, close A, and prove B is still offered."""
    _qapp()
    from am3d.ui.app import MainWindow
    from am3d.ui.document_controller import DocumentController

    other = DocumentController(None)
    other.session.create_object("document_b")
    other.do_autosave()
    b_snap = other.autosave_path()

    win = MainWindow()
    try:
        win.doc_ctrl.session.create_object("document_a")
        win.doc_ctrl.mark_dirty()
        win.doc_ctrl._testing_discard = True
        win.doc_ctrl.do_autosave()
        a_snap = win.doc_ctrl.autosave_path()
        assert os.path.exists(a_snap)
        win.close()                      # closeEvent -> clear_autosave()
    finally:
        win.deleteLater()

    assert not os.path.exists(a_snap)
    assert os.path.exists(b_snap)
    assert b_snap in [e["path"] for e in other.autosave_entries()]


# --- DATA-02: the recovery chooser -----------------------------------------

def test_autosave_entries_describe_document_identity_and_time(doc_ctrl,
                                                              tmp_path):
    target = tmp_path / "hero.am3d"
    doc_ctrl.session.save_project(str(target))
    doc_ctrl.path = str(target)
    doc_ctrl.do_autosave()

    entries = doc_ctrl.autosave_entries()
    assert len(entries) == 1
    entry = entries[0]
    assert entry["display_name"] == "hero.am3d"
    assert entry["original_path"] == str(target)
    assert entry["saved_at"] > 0
    assert entry["size_bytes"] > 0
    assert entry["is_current"] is True
    assert entry["corrupt"] is False


def test_autosave_entries_are_newest_first_not_filename_sorted(
        isolated_app_data):
    """Home used to emit ``list_autosave_files()[0]`` -- filename order.
    A name that sorts first must not outrank a newer snapshot."""
    _qapp()
    from am3d.ui.document_controller import DocumentController
    old = DocumentController(None)
    old.session.create_object("older")
    old.do_autosave()
    _age(old.autosave_path(), seconds=3600)

    new = DocumentController(None)
    new.session.create_object("newer")
    new.do_autosave()

    entries = old.autosave_entries()
    assert len(entries) == 2
    assert entries[0]["path"] == new.autosave_path()


def test_autosave_entries_flag_corrupt_sidecars_without_hiding_the_snapshot(
        doc_ctrl):
    doc_ctrl.do_autosave()
    with open(doc_ctrl.autosave_path() + ".meta.json", "w") as fh:
        fh.write("{not json")
    entries = doc_ctrl.autosave_entries()
    assert len(entries) == 1, "a damaged sidecar must not hide the recovery"
    assert entries[0]["corrupt"] is True


def test_autosave_entries_tolerate_a_snapshot_with_no_sidecar(doc_ctrl):
    doc_ctrl.do_autosave()
    os.unlink(doc_ctrl.autosave_path() + ".meta.json")
    entries = doc_ctrl.autosave_entries()
    assert len(entries) == 1
    assert entries[0]["corrupt"] is False       # recoverable, just less described


def test_recovery_dialog_selects_a_specific_snapshot_and_keeps_the_rest(
        isolated_app_data):
    _qapp()
    from am3d.ui.document_controller import DocumentController
    from am3d.ui.recovery_dialog import RecoveryDialog

    a, b = DocumentController(None), DocumentController(None)
    a.session.create_object("alpha"); a.do_autosave()
    b.session.create_object("beta"); b.do_autosave()

    dlg = RecoveryDialog(a.autosave_entries())
    try:
        assert dlg.list.count() == 2
        # Choose the *second* row explicitly, not whatever came first.
        dlg.list.setCurrentRow(1)
        chosen = dlg._current_entry()["path"]
        dlg._accept_selection()
        assert dlg.selected_path == chosen
        # The unselected snapshot is untouched on disk.
        others = [e["path"] for e in a.autosave_entries()]
        assert len(others) == 2
    finally:
        dlg.deleteLater()


def test_recovery_dialog_refuses_to_recover_a_corrupt_entry(isolated_app_data):
    _qapp()
    from am3d.ui.recovery_dialog import RecoveryDialog
    dlg = RecoveryDialog([{"path": "/nonexistent/x.autosave.am3d",
                           "display_name": "broken", "original_path": None,
                           "saved_at": 1.0, "size_bytes": 1,
                           "is_current": False, "corrupt": True}])
    try:
        dlg._accept_selection()
        assert dlg.selected_path is None
    finally:
        dlg.deleteLater()


def _age(path, seconds):
    """Backdate a file's mtime and its sidecar's recorded time."""
    import json
    stamp = os.path.getmtime(path) - seconds
    os.utime(path, (stamp, stamp))
    meta = path + ".meta.json"
    if os.path.exists(meta):
        with open(meta) as fh:
            data = json.load(fh)
        data["saved_at"] = stamp
        with open(meta, "w") as fh:
            json.dump(data, fh)


# --- PATH-01 ----------------------------------------------------------------

def test_application_identity_moves_user_data_out_of_the_generic_location():
    """Nothing named the application, so every autosave landed in the
    generic ``PySideApp`` directory Qt hands an unnamed PySide program --
    shared with any other such program on the machine (finding PATH-01)."""
    app = _qapp()
    from am3d.ui.app import APP_NAME, ORG_NAME, configure_application_identity

    previous = (app.organizationName(), app.applicationName())
    try:
        configure_application_identity(app)
        assert app.organizationName() == ORG_NAME
        assert app.applicationName() == APP_NAME
        location = QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation)
        assert not location.endswith("PySideApp"), location
        assert ORG_NAME in location or APP_NAME in location, location
    finally:
        app.setOrganizationName(previous[0])
        app.setApplicationName(previous[1])


def test_a_snapshot_left_in_the_old_location_is_still_offered(
        tmp_path, monkeypatch):
    """Moving the data location must not strand work an earlier build
    autosaved in the old one."""
    _qapp()
    from am3d.ui.document_controller import DocumentController

    new_dir = tmp_path / "new"
    legacy_dir = tmp_path / "legacy"
    new_dir.mkdir()
    legacy_dir.mkdir()
    (new_dir / "current-aaaaaaaaaa.autosave.am3d").write_bytes(b"x")
    (legacy_dir / "older-bbbbbbbbbb.autosave.am3d").write_bytes(b"y")

    monkeypatch.setattr(DocumentController, "autosave_dirs",
                        staticmethod(lambda: [new_dir, legacy_dir]))
    ctrl = DocumentController(None)
    found = [os.path.basename(p) for p in ctrl.list_autosave_files()]
    assert "current-aaaaaaaaaa.autosave.am3d" in found
    assert "older-bbbbbbbbbb.autosave.am3d" in found
    assert ctrl.autosave_exists()
