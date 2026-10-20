from __future__ import annotations

import json
import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path
from types import SimpleNamespace

os.environ["QT_QPA_PLATFORM"] = "offscreen"
REPO = Path.cwd()
sys.path.insert(0, str(REPO))

from PySide6.QtCore import QSettings, QPoint, QPointF, Qt
from PySide6.QtGui import QColor, QFontDatabase, QImage, QPainter, QPolygonF
from PySide6.QtTest import QTest
from PySide6.QtWidgets import (
    QApplication, QDialog, QDialogButtonBox, QMessageBox, QScrollArea,
)

from am3d.ui.app import MainWindow, apply_theme, configure_application_identity
from am3d.ui.ai_settings import AISettingsDialog


EVIDENCE = REPO / "docs" / "evidence" / "v1" / "phase-9" / "final"
SCREENS = EVIDENCE / "screens"
SCREENS.mkdir(parents=True, exist_ok=True)


def capture(widget, name):
    path = SCREENS / name
    image = widget.grab().toImage()
    if image.isNull() or not image.save(str(path), "PNG"):
        raise RuntimeError(f"offscreen Qt capture failed for {name}")
    return path.relative_to(EVIDENCE).as_posix()


def main():
    with tempfile.TemporaryDirectory(prefix="phase9-ui-") as isolated:
        temp = Path(isolated)
        user_settings = temp / "user-settings"
        system_settings = temp / "system-settings"
        user_settings.mkdir()
        system_settings.mkdir()
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                          str(user_settings))
        QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope,
                          str(system_settings))
        QSettings.setDefaultFormat(QSettings.IniFormat)
        app = QApplication.instance() or QApplication([])
        font_id = QFontDatabase.addApplicationFont(r"C:\Windows\Fonts\tahoma.ttf")
        if font_id < 0 or "Tahoma" not in QFontDatabase.applicationFontFamilies(font_id):
            raise RuntimeError("Installed Windows Tahoma could not be registered for offscreen capture")
        configure_application_identity(app)
        apply_theme(app)

        settings = QSettings("3DMASTER2005", "app")
        settings.clear()
        settings.setValue("autosaveInterval", 5)
        settings.setValue("ai/endpoint", "https://api.openai.com/v1/chat/completions")
        settings.setValue("ai/model", "")
        settings.setValue("ai/credentialStorage", "system")
        settings.sync()

        win = MainWindow()
        win.ai_controller.data_root = temp / "isolated-app-data"
        win._autosave_timer.stop()
        win.viewport._timer.stop()
        win.show()
        win.show_home()
        win.resize(640, 410)
        app.processEvents()
        QTest.qWait(60)
        home_scroll = win.home.scroll
        primary_pos = win.home._create_ai_btn.mapTo(
            home_scroll.viewport(), QPoint(0, 0))
        primary_rect = win.home._create_ai_btn.rect()
        primary_rect.moveTopLeft(primary_pos)
        screenshots = [{
            "surface": "Home hub at compact logical proxy",
            "logical_proxy": "200pct-logical-proxy",
            "requested_window": [640, 410],
            "actual_client": [win.width(), win.height()],
            "actual_frame": [win.frameGeometry().width(),
                             win.frameGeometry().height()],
            "scroll_viewport": [home_scroll.viewport().width(),
                                home_scroll.viewport().height()],
            "horizontal_scroll_range": [
                home_scroll.horizontalScrollBar().minimum(),
                home_scroll.horizontalScrollBar().maximum()],
            "vertical_scroll_range": [
                home_scroll.verticalScrollBar().minimum(),
                home_scroll.verticalScrollBar().maximum()],
            "primary_action_focused": app.focusWidget() is win.home._create_ai_btn,
            "primary_action_reachable": primary_rect.intersects(
                home_scroll.viewport().rect()),
            "screenshot": capture(win, "home-640x410.png"),
        }]

        original_message_exec = QMessageBox.exec
        diagnostic_capture = []

        def capture_diagnostics(box):
            box.show()
            app.processEvents()
            QTest.qWait(40)
            diagnostic_capture.append({
                "surface": "Allowlisted diagnostics from compact Home",
                "parent_actual_client": [win.width(), win.height()],
                "dialog_client": [box.width(), box.height()],
                "dialog_frame": [box.frameGeometry().width(),
                                 box.frameGeometry().height()],
                "plain_text": box.textFormat() == Qt.PlainText,
                "screenshot": capture(box, "diagnostics-home-640x410.png"),
            })
            box.close()
            return QMessageBox.Ok

        QMessageBox.exec = capture_diagnostics
        try:
            win._show_diagnostics()
        finally:
            QMessageBox.exec = original_message_exec
        screenshots.extend(diagnostic_capture)

        win.show_ai_workspace()
        app.processEvents()
        deadline = time.monotonic() + 4
        while win.ai_controller.busy and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)
        ai = win.ai_workspace

        sizes = [(1280, 820, "100pct-logical-proxy"),
                 (853, 546, "150pct-logical-proxy"),
                 (640, 410, "200pct-logical-proxy")]
        for width, height, proxy in sizes:
            win.resize(width, height)
            app.processEvents()
            QTest.qWait(60)
            screenshots.append({
                "surface": "MainWindow Create with AI idle",
                "logical_proxy": proxy,
                "requested_window": [width, height],
                "actual_client": [win.width(), win.height()],
                "actual_frame": [win.frameGeometry().width(),
                                 win.frameGeometry().height()],
                "scroll_viewport": [ai.scroll.viewport().width(),
                                    ai.scroll.viewport().height()],
                "scroll_range": [ai.scroll.verticalScrollBar().minimum(),
                                 ai.scroll.verticalScrollBar().maximum()],
                "screenshot": capture(win, f"main-idle-{width}x{height}.png"),
            })
            dialog = AISettingsDialog(parent=win)
            dialog.show()
            app.processEvents()
            QTest.qWait(40)
            scroll = dialog.findChild(QScrollArea, "aiSettingsScroll")
            screenshots.append({
                "surface": "AI Settings with empty model and key fields",
                "logical_proxy": proxy,
                "parent_requested_window": [width, height],
                "parent_actual_client": [win.width(), win.height()],
                "requested_dialog": [560, 360],
                "actual_dialog_client": [dialog.width(), dialog.height()],
                "actual_dialog_frame": [dialog.frameGeometry().width(),
                                         dialog.frameGeometry().height()],
                "scroll_viewport": [scroll.viewport().width(),
                                    scroll.viewport().height()],
                "scroll_range": [scroll.verticalScrollBar().minimum(),
                                 scroll.verticalScrollBar().maximum()],
                "footer_visible": dialog.dialog_buttons.isVisible(),
                "screenshot": capture(dialog, f"settings-{width}x{height}.png"),
            })
            dialog.close()
            dialog.deleteLater()
            app.processEvents()

        preview = QImage(320, 200, QImage.Format.Format_ARGB32)
        preview.fill(QColor("#282e35"))
        painter = QPainter(preview)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#e1e3e2"))
        painter.setBrush(QColor("#4f8fa8"))
        painter.drawEllipse(95, 112, 130, 42)
        painter.setBrush(QColor("#d98435"))
        painter.drawPolygon(QPolygonF([QPointF(155, 26), QPointF(155, 113),
                                       QPointF(98, 108)]))
        painter.setBrush(QColor("#c5c9ca"))
        painter.drawPolygon(QPolygonF([QPointF(163, 44), QPointF(213, 101),
                                       QPointF(163, 107)]))
        painter.end()
        preview_root = temp / "synthetic-checked-result"
        preview_root.mkdir()
        preview.save(str(preview_root / "preview.png"), "PNG")
        preview_copy = preview.copy()

        win.show()
        win.show_ai_workspace()
        win.resize(1280, 820)
        ai.brief_edit.setPlainText(
            "A small cobalt-blue sailboat with a low cabin and one orange sail.")
        run_id = "11111111-1111-4111-8111-111111111111"
        record = {
            "run_id": run_id,
            "status": "complete",
            "accepted_brief": {
                "brief": "A small cobalt-blue sailboat with a low cabin and one orange sail.",
                "approximations": ["Simple low-detail cabin shape."],
            },
            "accepted_recipe": {
                "objects": [{"name": "sailboat"}],
                "materials": [{"name": "cobalt"}],
            },
            "manifest": [{"path": "sailboat.am3d", "bytes": 12345},
                         {"path": "preview.png", "bytes": 1700}],
            "artifact_manifest": [{"path": "sailboat.am3d", "bytes": 12345},
                                  {"path": "preview.png", "bytes": 1700}],
            "check_report": {"ok": True,
                             "limitations": ["Simple low-detail cabin shape."]},
        }
        ai._on_outcome(SimpleNamespace(
            status="completed", record=record,
            check_report=record["check_report"],
            published_path=str(preview_root), error=None))
        app.processEvents()
        ai.scroll.ensureWidgetVisible(ai.preview_label)
        app.processEvents()
        screenshots.append({
            "surface": "Checked-result UI with synthetic offline fixture",
            "logical_proxy": "100pct-logical-proxy",
            "requested_window": [1280, 820],
            "actual_client": [win.width(), win.height()],
            "screenshot": capture(win, "main-result-synthetic-fixture.png"),
        })

        parent_id = "22222222-2222-4222-8222-222222222222"
        child_id = "33333333-3333-4333-8333-333333333333"
        rows = [
            {"run_id": parent_id, "status": "complete",
             "brief": "A small cobalt-blue sailboat with one orange sail.",
             "completed_utc": "2026-10-13T12:00:00Z"},
            {"run_id": child_id, "status": "complete",
             "parent_generation_id": parent_id,
             "brief": "Widen the sail while keeping the hull.",
             "completed_utc": "2026-10-13T12:10:00Z"},
        ]
        ai._on_history_list(rows)
        ai.history_list.blockSignals(True)
        ai.history_list.setCurrentRow(1)
        ai.history_list.blockSignals(False)
        child_record = dict(record)
        child_record.update({
            "run_id": child_id, "status": "complete",
            "parent_generation_id": parent_id,
            "accepted_brief": {
                "brief": "A small cobalt-blue sailboat. Change: Widen the sail while keeping the hull.",
                "approximations": ["Simple low-detail cabin shape."],
            },
        })
        parent_record = dict(record)
        parent_record.update({"run_id": parent_id, "status": "complete"})
        ai._on_history_detail({
            "record": child_record, "parent_record": parent_record,
            "preview_image": preview_copy, "project_digest": "a" * 64,
            "recipe_diff": "Changed sail width: 1.0 to 1.2.",
        })
        app.processEvents()
        ai.scroll.ensureWidgetVisible(ai.history_list)
        app.processEvents()
        screenshots.append({
            "surface": "Verified history UI with synthetic offline fixture",
            "logical_proxy": "100pct-logical-proxy",
            "requested_window": [1280, 820],
            "actual_client": [win.width(), win.height()],
            "screenshot": capture(win, "main-history-synthetic-fixture.png"),
        })
        ai.refinement_edit.setPlainText(
            "Make the sail wider while keeping the hull and cabin unchanged.")
        ai.scroll.ensureWidgetVisible(ai.refinement_edit)
        app.processEvents()
        screenshots.append({
            "surface": "Refinement request for selected verified synthetic parent",
            "logical_proxy": "100pct-logical-proxy",
            "requested_window": [1280, 820],
            "actual_client": [win.width(), win.height()],
            "screenshot": capture(win, "main-refinement-synthetic-fixture.png"),
        })

        error = {
            "code": "deadline_exceeded", "stage": "orchestrator",
            "message": "The shared generation time limit expired.",
            "hint": "Try a shorter brief or retry later.",
        }
        ai._on_outcome(SimpleNamespace(
            status="timed_out", record={}, error=error,
            check_report=None, published_path=None))
        app.processEvents()
        ai.scroll.ensureWidgetVisible(ai.status_label)
        app.processEvents()
        screenshots.append({
            "surface": "Fixed timeout error UI with synthetic offline fixture",
            "logical_proxy": "100pct-logical-proxy",
            "requested_window": [1280, 820],
            "actual_client": [win.width(), win.height()],
            "screenshot": capture(win, "main-error-synthetic-fixture.png"),
        })

        win.resize(640, 410)
        app.processEvents()
        original_exec = QDialog.exec
        quick_start = []

        def capture_quick_start(dialog):
            dialog.show()
            app.processEvents()
            QTest.qWait(40)
            buttons = dialog.findChild(QDialogButtonBox)
            quick_start.append({
                "surface": "Quick Start scroll guide at compact logical proxy",
                "logical_proxy": "200pct-logical-proxy",
                "parent_requested_window": [640, 410],
                "parent_actual_client": [win.width(), win.height()],
                "requested_dialog": [620, 380],
                "actual_dialog_client": [dialog.width(), dialog.height()],
                "actual_dialog_frame": [dialog.frameGeometry().width(),
                                         dialog.frameGeometry().height()],
                "footer_visible": buttons.isVisible() if buttons else False,
                "screenshot": capture(dialog, "quick-start-640x410.png"),
            })
            dialog.close()
            return QDialog.Rejected

        QDialog.exec = capture_quick_start
        try:
            win._show_quick_start()
        finally:
            QDialog.exec = original_exec
        screenshots.extend(quick_start)

        result = {
            "platform": "Windows 10 IoT Enterprise LTSC build 19044 x64",
            "python": __import__("sys").version.split()[0],
            "qt": __import__("PySide6").__version__,
            "qt_platform": "offscreen",
            "capture_command": "$env:QT_QPA_PLATFORM='offscreen'; .venv\\Scripts\\python.exe docs\\evidence\\v1\\phase-9\\final\\capture_phase9_ui.py",
            "font_for_offscreen_capture": "Installed Windows Tahoma registered from C:\\Windows\\Fonts\\tahoma.ttf; offscreen Qt initially exposed no font families.",
            "requested_logical_proxies": [
                {"label": proxy, "requested": [width, height]}
                for width, height, proxy in sizes
            ],
            "physical_dpi_qualification": False,
            "provider_or_network_calls": 0,
            "credential_values_read": 0,
            "source_sha256": {
                relative: hashlib.sha256((REPO / relative).read_bytes()).hexdigest()
                for relative in (
                    "am3d/__init__.py", "pyproject.toml",
                    "am3d/ui/app.py", "am3d/ui/home.py",
                    "am3d/ui/ai_settings.py", "am3d/ui/ai_workspace.py",
                    "am3d/ui/test_home.py", "am3d/ui/test_phase9_ui.py",
                )
            },
            "capture_script_sha256": hashlib.sha256(
                Path(__file__).read_bytes()).hexdigest(),
            "fixture_note": "Result/history/refinement/error screens are actual Qt widgets populated with synthetic safe offline UI fixtures. The sailboat preview is drawn only for layout evidence and is not an AI-generated result.",
            "capture_note": "MainWindow Home and Create with AI are measured after the inactive stack-page minimum correction. Home content and AI work area are scrollable at the compact logical proxy. All dimensions are Qt logical pixels; no physical-DPI claim is made.",
            "screenshots": screenshots,
        }
        identity_path = REPO / "docs" / "evidence" / "v1" / "phase-9" / "SOURCE_IDENTITY.json"
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
        old_receipt = identity.get("phase9_ui_evidence_sha256_at_documentation_check", {})
        replaced = {
            relative: {
                "previously_recorded_sha256": expected,
                "current_intermediate_sha256": hashlib.sha256(
                    (REPO / relative).read_bytes()).hexdigest(),
            }
            for relative, expected in old_receipt.items()
            if relative.startswith("docs/evidence/v1/phase-9/screens/")
            or relative == "docs/evidence/v1/phase-9/ui-capture-measurements.json"
        }
        result["historical_capture_receipt"] = {
            "status": "intermediate capture overwrote the earlier files before their recorded hashes were discovered",
            "identity_file_preserved": "docs/evidence/v1/phase-9/SOURCE_IDENTITY.json",
            "previous_receipt_comparison": replaced,
            "earlier_png_bytes_recovered": False,
            "note": "Prior source-identity hashes remain as historical claims only. The earlier raw PNG bytes were not available for restoration. These corrected captures are separately written under phase-9/final/ and bind their own source hashes.",
        }
        (EVIDENCE / "ui-capture-measurements.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8")
        win.viewport._timer.stop()
        win._autosave_timer.stop()
        win.close()
        print(json.dumps({
            "screenshots": len(screenshots),
            "window_measurements": screenshots,
            "screen_available": [app.primaryScreen().availableGeometry().width(),
                                 app.primaryScreen().availableGeometry().height()],
        }, indent=2))


if __name__ == "__main__":
    main()
