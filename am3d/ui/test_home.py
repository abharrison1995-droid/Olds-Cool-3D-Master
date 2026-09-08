"""Tests for the Home hub: bundled Examples, Quick Start, and dirty-safe
navigation back to Home from the editor (Phase 5 bullet 6).
"""

from __future__ import annotations

import sys

import pytest

from PySide6.QtCore import Qt


def _qapp():
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
        return app
    except Exception:
        pytest.skip("PySide6 not available or no display")


# -- HomeWidget (no MainWindow needed) ---------------------------------------

def test_set_examples_populates_list_with_path_userdata():
    _qapp()
    from am3d.ui.home import HomeWidget
    home = HomeWidget()
    home.set_examples([("Vase", "/tmp/vase.am3d"), ("Knight", "/tmp/knight.am3d")])
    assert home.examples_list.count() == 2
    assert home.examples_list.item(0).text() == "Vase"
    assert home.examples_list.item(0).data(Qt.UserRole) == "/tmp/vase.am3d"


def test_set_examples_empty_shows_placeholder_not_clickable():
    _qapp()
    from am3d.ui.home import HomeWidget
    home = HomeWidget()
    home.set_examples([])
    assert home.examples_list.count() == 1
    item = home.examples_list.item(0)
    assert item.flags() == Qt.NoItemFlags


def test_example_double_click_emits_action_example_with_path():
    _qapp()
    from am3d.ui.home import HomeWidget
    home = HomeWidget()
    home.set_examples([("Vase", "/tmp/vase.am3d")])
    received = []
    home.action_example.connect(received.append)
    home._on_example_double_click(home.examples_list.item(0))
    assert received == ["/tmp/vase.am3d"]


# -- MainWindow integration ---------------------------------------------------

def _make_main_window():
    from am3d.ui.test_operators import _make_main_window as _mw
    return _mw()


def test_example_projects_resolve_to_real_bundled_files():
    """The Examples list must point at the actual vase/knight demo assets
    shipped in the repo, not placeholders -- both should load cleanly."""
    import os
    win = _make_main_window()
    try:
        examples = win._example_projects()
        labels = [label for label, _ in examples]
        assert "Vase (lathed spline)" in labels
        assert "Generated character (knight)" in labels
        for _, path in examples:
            assert os.path.isfile(path)
    finally:
        win.viewport._timer.stop()
        win.close()


def test_show_home_populates_examples_list():
    win = _make_main_window()
    try:
        win.show_home()
        assert win.home.examples_list.count() >= 1
        assert "(No examples installed)" not in [
            win.home.examples_list.item(i).text()
            for i in range(win.home.examples_list.count())]
    finally:
        win.viewport._timer.stop()
        win.close()


def test_opening_vase_example_loads_expected_objects():
    """The fresh-launch vase journey: open the bundled example and confirm
    the resulting session matches what the demo script produces. The
    document must be pathless (see test_opening_example_clears_path_*
    below) -- opening an example is not the same as opening a normal
    recent project."""
    win = _make_main_window()
    try:
        examples = dict(win._example_projects())
        vase_path = examples["Vase (lathed spline)"]
        win._open_example(vase_path)
        assert "vase" in win.session.project.objects
        assert win.doc_ctrl.path is None
        assert win.doc_ctrl.dirty is False
        assert win.undo_stack.count() == 0
    finally:
        win.viewport._timer.stop()
        win.close()


def test_opening_knight_example_loads_expected_objects():
    """The fresh-launch generated-character journey."""
    win = _make_main_window()
    try:
        examples = dict(win._example_projects())
        knight_path = examples["Generated character (knight)"]
        win._open_example(knight_path)
        assert "hero" in win.session.project.objects
        assert win.doc_ctrl.path is None
    finally:
        win.viewport._timer.stop()
        win.close()


def test_opening_example_respects_dirty_check(monkeypatch):
    """Double-clicking an Example must go through the same unsaved-changes
    gate as any other Open -- it must not silently discard live edits."""
    win = _make_main_window()
    try:
        examples = dict(win._example_projects())
        vase_path = examples["Vase (lathed spline)"]

        win._do_primitive("sphere", dict(radius=0.8, sections=12, rings=8))
        assert win.doc_ctrl.dirty is True

        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: False)
        win._open_example(vase_path)
        assert "vase" not in win.session.project.objects  # aborted

        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: True)
        win._open_example(vase_path)
        assert "vase" in win.session.project.objects
    finally:
        win.viewport._timer.stop()
        win.close()


def test_opening_example_clears_path_so_save_cannot_overwrite_bundled_asset():
    """Opening an example must not let a plain Ctrl+S silently overwrite the
    shipped asset file -- do_open_example() clears the path so Save routes
    through Save As instead (which conftest's autouse fixture mocks to
    cancel, so this proves the bundled file is untouched either way)."""
    import hashlib
    win = _make_main_window()
    try:
        examples = dict(win._example_projects())
        vase_path = examples["Vase (lathed spline)"]
        with open(vase_path, "rb") as f:
            original = hashlib.sha1(f.read()).hexdigest()

        win._open_example(vase_path)
        assert win.doc_ctrl.path is None
        assert win.doc_ctrl.has_path is False

        win._do_primitive("box", dict(width=1.0, height=1.0, depth=1.0))
        assert win.doc_ctrl.dirty is True

        win._file_save()  # pathless -> do_save_as() -> mocked dialog cancels

        with open(vase_path, "rb") as f:
            after = hashlib.sha1(f.read()).hexdigest()
        assert after == original
    finally:
        win.viewport._timer.stop()
        win.close()


def test_quick_start_button_is_wired_and_does_not_raise(monkeypatch):
    """The Quick Start button previously emitted a signal nobody connected
    to -- a dead control. It must now open real guidance."""
    from PySide6.QtWidgets import QMessageBox
    win = _make_main_window()
    try:
        shown = []
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: shown.append(a) or QMessageBox.Ok))
        win.home.action_quick_start.emit()
        assert len(shown) == 1
    finally:
        win.viewport._timer.stop()
        win.close()


def test_diagnostics_button_is_wired_and_does_not_raise(monkeypatch):
    """The Home screen's Diagnostics button must open a real report -- the
    Help menu is hidden while on Home, so this is the only path to
    diagnostics from a fresh launch."""
    from PySide6.QtWidgets import QMessageBox
    win = _make_main_window()
    try:
        shown = []
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: shown.append(a) or QMessageBox.Ok))
        win.home.action_diagnostics.emit()
        assert len(shown) == 1
    finally:
        win.viewport._timer.stop()
        win.close()


def test_diagnostics_menu_action_is_wired_and_does_not_raise(monkeypatch):
    """Help > Diagnostics... must call the same handler as the Home button."""
    from PySide6.QtWidgets import QMessageBox
    win = _make_main_window()
    try:
        shown = []
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: shown.append(a) or QMessageBox.Ok))
        win._show_diagnostics()
        assert len(shown) == 1
        text = shown[0][2]
        assert "Renderer backend" in text
        assert "Undo entries" in text
        assert "App data directory" in text
    finally:
        win.viewport._timer.stop()
        win.close()


def test_diagnostics_reports_forced_software_backend(monkeypatch):
    """When Settings forces software rendering, diagnostics must say so
    rather than reporting whatever the GPU probe happens to find."""
    from PySide6.QtWidgets import QMessageBox
    win = _make_main_window()
    try:
        win.viewport.force_software = True
        shown = []
        monkeypatch.setattr(
            QMessageBox, "information",
            staticmethod(lambda *a, **k: shown.append(a) or QMessageBox.Ok))
        win._show_diagnostics()
        text = shown[0][2]
        assert "Software (forced by Settings" in text
    finally:
        win.viewport._timer.stop()
        win.close()


def test_gpu_render_available_reflects_probe_cache():
    """gpu_render_available() is a thin public wrapper around the module's
    lazy-cached renderer probe -- it must agree with the private lookup
    regardless of whether the optional GPU module is actually installed."""
    from am3d.ui.viewport3d import gpu_render_available, _get_gpu_render
    assert gpu_render_available() == (_get_gpu_render() is not None)


def test_home_shown_gives_keyboard_focus_to_primary_action(monkeypatch):
    """A keyboard-only user landing on Home (fresh launch or Close Editor)
    must not need a mouse click just to start tabbing through actions.

    hasFocus() depends on window activation, which the offscreen test
    platform doesn't reliably grant -- spy on setFocus() instead of
    asserting the ambient focus state."""
    from am3d.ui.home import _HomeButton
    calls = []
    original = _HomeButton.setFocus
    monkeypatch.setattr(_HomeButton, "setFocus",
                         lambda self, *a: (calls.append(self), original(self, *a)))
    win = _make_main_window()
    try:
        win.show()
        calls.clear()
        win.show_home()
        assert win.home._new_btn in calls
    finally:
        win.viewport._timer.stop()
        win.close()


def test_close_editor_is_dirty_safe_round_trip():
    """'Close Editor' must not lose unsaved work -- it only navigates to
    Home, leaving the in-memory document (and its undo history) intact so
    Enter Editor resumes exactly where the user left off."""
    win = _make_main_window()
    try:
        # _make_main_window() already seeds a fixture object named "sphere"
        # directly (bypassing undo); use a different primitive so the new
        # object's undo entry is unambiguous.
        win._do_primitive("box", dict(width=1.0, height=1.0, depth=1.0))
        assert win.doc_ctrl.dirty is True
        count_before = win.undo_stack.count()

        win.show_home()
        assert win.doc_ctrl.dirty is True  # unaffected by the navigation
        assert win.undo_stack.count() == count_before
        assert "box" in win.session.project.objects

        win.show_editor()
        assert win.doc_ctrl.dirty is True
        assert win.undo_stack.count() == count_before
        assert "box" in win.session.project.objects

        win.undo_stack.undo()
        assert "box" not in win.session.project.objects
    finally:
        win.viewport._timer.stop()
        win.close()
