"""Focused Phase 9 compact-layout and diagnostics regressions."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QMessageBox, QPlainTextEdit,
    QPushButton, QScrollArea,
)


@pytest.fixture(autouse=True)
def _isolated_qsettings(tmp_path):
    """Route all UI preferences to this test's temporary INI store."""
    old_format = QSettings.defaultFormat()
    old_user = QSettings(QSettings.IniFormat, QSettings.UserScope,
                         "3DMASTER2005", "app").fileName()
    old_system = QSettings(QSettings.IniFormat, QSettings.SystemScope,
                           "3DMASTER2005", "app").fileName()
    user_dir = tmp_path / "user-settings"
    system_dir = tmp_path / "system-settings"
    user_dir.mkdir()
    system_dir.mkdir()
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(user_dir))
    QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope,
                      str(system_dir))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    yield
    QSettings.setDefaultFormat(old_format)
    if old_user:
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                          str(Path(old_user).parent.parent))
    if old_system:
        QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope,
                          str(Path(old_system).parent.parent))


def _app():
    return QApplication.instance() or QApplication([])


def _main_window():
    from am3d.ui.test_operators import _make_main_window

    return _make_main_window()


def test_compact_ai_settings_controls_are_scrollable_and_tab_reachable():
    app = _app()
    from am3d.ui.ai_settings import AISettingsDialog

    dialog = AISettingsDialog()
    try:
        dialog.resize(520, 360)
        dialog.show()
        app.processEvents()
        scroll = dialog.findChild(QScrollArea, "aiSettingsScroll")
        assert scroll is not None
        assert dialog.width() <= 640
        assert dialog.height() <= 410
        assert dialog.maximumHeight() <= 410

        save = dialog.dialog_buttons.button(QDialogButtonBox.Save)
        cancel = dialog.dialog_buttons.button(QDialogButtonBox.Cancel)
        controls = [dialog.endpoint_edit, dialog.model_edit,
                    dialog.storage_combo, dialog.key_edit,
                    dialog.delete_key_button, save, cancel]
        dialog.endpoint_edit.setFocus()
        app.processEvents()
        for expected in controls:
            assert app.focusWidget() is expected
            if expected in controls[:5]:
                scroll.ensureWidgetVisible(expected)
            QTest.keyClick(expected, Qt.Key_Tab)
            app.processEvents()
    finally:
        dialog.close()
        dialog.deleteLater()
        app.processEvents()


def test_workspace_tab_path_includes_settings_before_brief():
    app = _app()
    win = _main_window()
    try:
        win.show()
        win.show_ai_workspace()
        app.processEvents()
        ai = win.ai_workspace
        ai.back_button.setFocus()
        QTest.keyClick(ai.back_button, Qt.Key_Tab)
        app.processEvents()
        assert app.focusWidget() is ai.settings_button
        QTest.keyClick(ai.settings_button, Qt.Key_Tab)
        app.processEvents()
        assert app.focusWidget() is ai.brief_edit
    finally:
        win.viewport._timer.stop()
        win.close()


def test_main_window_compact_ai_flow_and_editor_minimum_restore():
    app = _app()
    win = _main_window()
    try:
        original_policy = win._stack_page_size_policies[win.editor_widget]
        original_editor_minimum = win.editor_widget.minimumSizeHint()
        win.show()
        win.show_ai_workspace()
        win.resize(640, 410)
        app.processEvents()

        assert win.stack.currentWidget() is win.ai_workspace
        assert win.width() <= 640
        assert win.height() <= 410
        assert win.ai_workspace.back_button.isVisible()
        assert win.ai_workspace.settings_button.isVisible()
        assert win.ai_workspace.scroll.verticalScrollBar().maximum() > 0
        win.ai_workspace.scroll.ensureWidgetVisible(
            win.ai_workspace.generate_button)
        app.processEvents()
        assert win.ai_workspace.generate_button.isVisible()
        generate_pos = win.ai_workspace.generate_button.mapTo(
            win.ai_workspace.scroll.viewport(), QPoint(0, 0))
        generate_rect = win.ai_workspace.generate_button.rect()
        generate_rect.moveTopLeft(generate_pos)
        assert generate_rect.intersects(
            win.ai_workspace.scroll.viewport().rect())

        win.show_home()
        win._do_primitive("box", {"width": 1.0, "height": 1.0,
                                   "depth": 1.0})
        original_session = win.session
        undo_count = win.undo_stack.count()
        assert undo_count > 0
        assert win.doc_ctrl.dirty is True

        win.show_ai_workspace()
        assert win.session is original_session
        assert win.undo_stack.count() == undo_count
        assert win.doc_ctrl.dirty is True

        win.show_editor()
        active_policy = win.editor_widget.sizePolicy()
        assert active_policy.horizontalPolicy() == original_policy.horizontalPolicy()
        assert active_policy.verticalPolicy() == original_policy.verticalPolicy()
        assert win.stack.minimumSizeHint().width() >= original_editor_minimum.width()

        win.show_home()
        win.resize(640, 410)
        app.processEvents()
        assert win.width() < original_editor_minimum.width()
        assert win.session is original_session
        assert win.undo_stack.count() == undo_count
        assert win.doc_ctrl.dirty is True
    finally:
        win.viewport._timer.stop()
        win.close()


def test_home_compact_scroll_reaches_primary_and_manual_actions():
    app = _app()
    win = _main_window()
    try:
        win.show_home()
        win.show()
        win.resize(640, 410)
        app.processEvents()
        home = win.home
        assert win.width() <= 640
        assert win.height() <= 410
        assert home.scroll.verticalScrollBar().maximum() > 0
        assert home._create_ai_btn.isVisible()
        assert app.focusWidget() is home._create_ai_btn

        quick_start = next(
            button for button in home.findChildren(QPushButton)
            if button.text() == "&Quick Start")
        home.scroll.ensureWidgetVisible(quick_start)
        app.processEvents()
        button_pos = quick_start.mapTo(home.scroll.viewport(), QPoint(0, 0))
        button_rect = quick_start.rect()
        button_rect.moveTopLeft(button_pos)
        assert button_rect.intersects(home.scroll.viewport().rect())

        QTest.mouseClick(home._create_ai_btn, Qt.LeftButton)
        app.processEvents()
        assert win.stack.currentWidget() is win.ai_workspace
        assert win.width() <= 640
        assert win.height() <= 410
    finally:
        win.viewport._timer.stop()
        win.close()


def test_diagnostics_omit_private_inputs_and_paths_and_force_plain_text(
        monkeypatch):
    _app()
    from am3d.ai.credentials import SessionCredentialStore, SystemCredentialStore

    calls = []
    credential_sentinel = "CREDENTIAL_DIAGNOSTIC_SENTINEL"

    def credential_getter(*_args, **_kwargs):
        calls.append(credential_sentinel)
        return credential_sentinel

    monkeypatch.setattr(SystemCredentialStore, "get", credential_getter)
    monkeypatch.setattr(SessionCredentialStore, "get", credential_getter)
    win = _main_window()
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda box: shown.append(box) or 0)
    try:
        settings = QSettings("3DMASTER2005", "app")
        settings.setValue("autosaveInterval", "AUTOSAVE_BAD_VALUE_<b>")
        settings.sync()
        win.doc_ctrl.path = "DIAGNOSTIC_FILENAME_SENTINEL.am3d"
        win.ai_workspace.brief_edit.setPlainText(
            "PRIVATE_PROMPT_DIAGNOSTIC_SENTINEL")

        text = win._diagnostics_text()
        assert "Autosave interval: 5 min" in text
        assert "Build identity:" in text
        assert "Document: saved, clean" in text
        assert "Objects:" in text and "Actions:" in text
        assert "Undo entries:" in text
        assert "DIAGNOSTIC_FILENAME_SENTINEL" not in text
        assert "PRIVATE_PROMPT_DIAGNOSTIC_SENTINEL" not in text
        assert credential_sentinel not in text
        assert "AUTOSAVE_BAD_VALUE" not in text
        assert "App data directory" not in text
        assert calls == []

        win._show_diagnostics()
        assert len(shown) == 1
        assert shown[0].textFormat() == Qt.PlainText
        assert credential_sentinel not in shown[0].text()
    finally:
        win.doc_ctrl.path = None
        win.viewport._timer.stop()
        win.close()


def test_about_and_quick_start_match_development_candidate_and_current_flow(
        monkeypatch):
    app = _app()
    win = _main_window()
    message_boxes = []
    dialogs = []
    monkeypatch.setattr(QMessageBox, "exec",
                        lambda box: message_boxes.append(box) or 0)
    monkeypatch.setattr(QDialog, "exec",
                        lambda dialog: dialogs.append(dialog) or 0)
    try:
        win._about()
        about = message_boxes[0]
        assert about.textFormat() == Qt.PlainText
        assert "Version 1.0.0.dev1" in about.text()
        assert "spline-patch 3D editor" in about.text()
        assert "internal tessellation" in about.text()
        assert "development test candidate" in about.text()
        assert "target-platform gates are pending" in about.text()

        win._show_quick_start()
        quick_start = dialogs[0]
        guide = quick_start.findChild(QPlainTextEdit)
        assert guide is not None and guide.isReadOnly()
        buttons = quick_start.findChild(QDialogButtonBox)
        assert buttons is not None
        assert buttons.button(QDialogButtonBox.Ok) is not None
        assert quick_start.maximumHeight() <= 410
        assert quick_start.maximumWidth() <= 640
        guide_text = guide.toPlainText()
        for expected in ("Create with AI…", "AI Settings…", "Generate…",
                         "Send request", "Open in Editor", "Local history",
                         "Refine Selected…", "Session-only key (memory)",
                         "static pose exports", "manual edits"):
            assert expected.casefold() in guide_text.casefold()
        assert "no JSON is required" in guide_text
        assert "ten-minute deadline" in guide_text
        assert "dollar cost are unknown" in guide_text
    finally:
        win.viewport._timer.stop()
        win.close()


def test_version_and_package_description_are_consistent_and_truthful():
    import am3d

    root = Path(__file__).resolve().parents[2]
    project_text = (root / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'^version = "([^"]+)"$', project_text, re.MULTILINE)
    description_match = re.search(r'^description = "([^"]+)"$', project_text,
                                  re.MULTILINE)
    assert version and description_match
    description = description_match.group(1).casefold()
    assert am3d.__version__ == version.group(1) == "1.0.0.dev1"
    assert "spline-patch 3d editor" in description
    assert "internal tessellation" in description
    assert "in-app ai development workflow" in description
    assert "gates pending" in description
    assert "pure spline" not in description
    assert "no polygon meshes" not in description
