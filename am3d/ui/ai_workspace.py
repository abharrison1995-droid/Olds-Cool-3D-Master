"""Native, scrollable Create with AI work area."""

from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy,
    QVBoxLayout, QWidget,
)


class AIWorkspace(QWidget):
    """Brief entry, explicit transmission confirmation, status, and result."""

    back_home = Signal()
    settings_requested = Signal()
    adoption_requested = Signal(str, bool)
    refinement_requested = Signal(str, str)

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._started_at: float | None = None
        self._last_outcome = None
        self._copying = False
        self._showing_history = False
        self._history_rows: dict[str, dict] = {}
        self._history_detail: dict | None = None
        self._last_refinement: tuple[str, str] | None = None
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._update_elapsed)

        controller.event_changed.connect(self._on_event)
        controller.outcome_ready.connect(self._on_outcome)
        controller.copy_ready.connect(self._on_copy_ready)
        controller.copy_failed.connect(self._on_copy_failed)
        controller.busy_changed.connect(self._on_busy_changed)
        controller.cancellation_changed.connect(self._on_cancellation_changed)
        controller.history_list_ready.connect(self._on_history_list)
        controller.history_detail_ready.connect(self._on_history_detail)
        controller.history_failed.connect(self._on_history_failed)
        controller.history_deleted.connect(self._on_history_deleted)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header = QFrame()
        header.setObjectName("aiWorkspaceHeader")
        header_row = QHBoxLayout(header)
        header_row.setContentsMargins(10, 6, 10, 6)
        self.back_button = QPushButton("← Home")
        self.back_button.setAccessibleName("Return to Home")
        self.back_button.clicked.connect(self.back_home.emit)
        header_row.addWidget(self.back_button)
        title = QLabel("Create with AI")
        title.setObjectName("aiWorkspaceTitle")
        title.setTextFormat(Qt.PlainText)
        header_row.addWidget(title)
        header_row.addStretch(1)
        self.settings_button = QPushButton("AI Settings…")
        self.settings_button.setAccessibleName("Configure AI provider and key")
        self.settings_button.clicked.connect(self.settings_requested.emit)
        header_row.addWidget(self.settings_button)
        root.addWidget(header)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        content.setObjectName("aiWorkspaceContent")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        intro = QLabel(
            "Describe the asset you want. Generation runs only after you choose Generate and approve the provider request.")
        intro.setWordWrap(True)
        intro.setTextFormat(Qt.PlainText)
        layout.addWidget(intro)

        brief_group = QGroupBox("Brief")
        brief_layout = QVBoxLayout(brief_group)
        self.brief_edit = QPlainTextEdit()
        self.brief_edit.setObjectName("aiBriefEdit")
        self.brief_edit.setAccessibleName("Describe the 3D asset to create")
        self.brief_edit.setPlaceholderText(
            "For example: A small blue ceramic vase with a narrow neck and a wide base.")
        self.brief_edit.setMinimumHeight(150)
        self.brief_edit.setMaximumHeight(270)
        # A brief is one continuous natural-language field; Tab should move
        # focus to the actions rather than insert an invisible indentation.
        self.brief_edit.setTabChangesFocus(True)
        brief_layout.addWidget(self.brief_edit)
        layout.addWidget(brief_group)

        note = QLabel(
            "Offline editing stays available without a model, key, or network. An approved AI run may send this brief, provider-generated normalized requirements and candidate recipes, the fixed recipe-v1 context, and bounded sanitized repair or check feedback. "
            "Native AM3D keeps the editable project; OBJ and GLB are static pose exports, and cost is unavailable.")
        note.setWordWrap(True)
        note.setTextFormat(Qt.PlainText)
        note.setObjectName("aiPrivacyNote")
        layout.addWidget(note)

        buttons = QHBoxLayout()
        self.generate_button = QPushButton("Generate…")
        self.generate_button.setObjectName("aiGenerateButton")
        self.generate_button.setAccessibleName("Generate from brief")
        self.generate_button.setDefault(True)
        self.generate_button.clicked.connect(self._begin_generation)
        buttons.addWidget(self.generate_button)

        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setAccessibleName("Cancel current generation, history job, or project copy")
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(self._cancel)
        buttons.addWidget(self.cancel_button)

        self.retry_button = QPushButton("Retry")
        self.retry_button.setAccessibleName("Retry the current brief with a new run")
        self.retry_button.setEnabled(False)
        self.retry_button.clicked.connect(self._retry)
        buttons.addWidget(self.retry_button)
        buttons.addStretch(1)
        layout.addLayout(buttons)

        state_group = QGroupBox("Run status")
        state_layout = QVBoxLayout(state_group)
        self.status_label = QLabel("Ready. No provider request has been made.")
        self.status_label.setObjectName("aiStatusLabel")
        self.status_label.setWordWrap(True)
        self.status_label.setTextFormat(Qt.PlainText)
        self.status_label.setAccessibleName("AI generation status")
        state_layout.addWidget(self.status_label)

        metrics = QHBoxLayout()
        self.stage_label = QLabel("Stage: —")
        self.stage_label.setTextFormat(Qt.PlainText)
        self.stage_label.setAccessibleName("Actual generation stage")
        metrics.addWidget(self.stage_label)
        self.attempt_label = QLabel("Attempt: —")
        self.attempt_label.setTextFormat(Qt.PlainText)
        self.attempt_label.setAccessibleName("Actual attempt count")
        metrics.addWidget(self.attempt_label)
        self.elapsed_label = QLabel("Elapsed: 0.0 s")
        self.elapsed_label.setTextFormat(Qt.PlainText)
        self.elapsed_label.setAccessibleName("Actual elapsed time")
        metrics.addWidget(self.elapsed_label)
        metrics.addStretch(1)
        state_layout.addLayout(metrics)
        layout.addWidget(state_group)

        result_group = QGroupBox("Checked result")
        result_layout = QVBoxLayout(result_group)
        self.preview_label = QLabel("A checked whole-scene preview will appear here after a successful run.")
        self.preview_label.setObjectName("aiPreview")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumSize(240, 180)
        self.preview_label.setMaximumHeight(360)
        self.preview_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.preview_label.setWordWrap(True)
        self.preview_label.setTextFormat(Qt.PlainText)
        result_layout.addWidget(self.preview_label)

        self.result_summary = QPlainTextEdit()
        self.result_summary.setReadOnly(True)
        self.result_summary.setAccessibleName("Checked project summary and exports")
        self.result_summary.setMaximumHeight(150)
        self.result_summary.setPlainText("No checked result yet.")
        result_layout.addWidget(self.result_summary)

        self.limitations = QPlainTextEdit()
        self.limitations.setReadOnly(True)
        self.limitations.setAccessibleName("Generation limitations and approximations")
        self.limitations.setMaximumHeight(100)
        self.limitations.setPlainText("Limitations and approximations will appear here.")
        result_layout.addWidget(self.limitations)

        self.open_button = QPushButton("Open in Editor")
        self.open_button.setAccessibleName("Create a writable copy and open it in the editor")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_in_editor)
        result_layout.addWidget(self.open_button)
        layout.addWidget(result_group)

        source_group = QGroupBox("Recipe and check report")
        source_layout = QVBoxLayout(source_group)
        self.source_report = QPlainTextEdit()
        self.source_report.setReadOnly(True)
        self.source_report.setAccessibleName("Accepted recipe and deterministic check report")
        self.source_report.setMinimumHeight(150)
        self.source_report.setMaximumHeight(280)
        self.source_report.setPlainText("A successful, checked recipe and report will appear here.")
        source_layout.addWidget(self.source_report)
        layout.addWidget(source_group)

        history_group = QGroupBox("Saved generations and refinements")
        history_layout = QVBoxLayout(history_group)
        history_note = QLabel(
            "History is stored locally. Select a row to verify its saved files and preview. Refinement starts from the saved recipe and creates a new child; manual edits are never merged automatically.")
        history_note.setWordWrap(True)
        history_note.setTextFormat(Qt.PlainText)
        history_layout.addWidget(history_note)
        self.history_list = QListWidget()
        self.history_list.setAccessibleName("Saved AI generations and refinement history")
        self.history_list.setMinimumHeight(120)
        self.history_list.setMaximumHeight(230)
        self.history_list.currentItemChanged.connect(self._on_history_selection)
        history_layout.addWidget(self.history_list)
        history_buttons = QHBoxLayout()
        self.refresh_history_button = QPushButton("Refresh History")
        self.refresh_history_button.setAccessibleName("Reload local generation history")
        self.refresh_history_button.clicked.connect(self.refresh_history)
        history_buttons.addWidget(self.refresh_history_button)
        self.restore_history_button = QPushButton("Restore Selected in Editor")
        self.restore_history_button.setAccessibleName(
            "Create a writable copy of the selected generation and open it")
        self.restore_history_button.setEnabled(False)
        self.restore_history_button.clicked.connect(self._restore_selected_history)
        history_buttons.addWidget(self.restore_history_button)
        self.delete_history_button = QPushButton("Delete Selected")
        self.delete_history_button.setAccessibleName("Delete selected local generation history")
        self.delete_history_button.setEnabled(False)
        self.delete_history_button.clicked.connect(self._delete_selected_history)
        history_buttons.addWidget(self.delete_history_button)
        history_buttons.addStretch(1)
        history_layout.addLayout(history_buttons)
        self.history_status = QLabel("History has not been loaded.")
        self.history_status.setWordWrap(True)
        self.history_status.setTextFormat(Qt.PlainText)
        self.history_status.setAccessibleName("Saved history status")
        history_layout.addWidget(self.history_status)
        self.refinement_edit = QPlainTextEdit()
        self.refinement_edit.setAccessibleName("Describe a change to the selected saved generation")
        self.refinement_edit.setPlaceholderText(
            "For example: Make the roof flatter while keeping the body and wheels.")
        self.refinement_edit.setTabChangesFocus(True)
        self.refinement_edit.setMaximumHeight(88)
        history_layout.addWidget(self.refinement_edit)
        self.refinement_note = QLabel(
            "Refinement sends the saved parent brief and recipe plus this change request. The model returns a full replacement recipe. OBJ and GLB remain static pose exports.")
        self.refinement_note.setWordWrap(True)
        self.refinement_note.setTextFormat(Qt.PlainText)
        history_layout.addWidget(self.refinement_note)
        self.refine_button = QPushButton("Refine Selected…")
        self.refine_button.setAccessibleName(
            "Create a new child generation from the selected checked recipe")
        self.refine_button.setEnabled(False)
        self.refine_button.clicked.connect(self._refine_selected_history)
        history_layout.addWidget(self.refine_button)
        layout.addWidget(history_group)
        layout.addStretch(1)

        self.scroll.setWidget(content)
        root.addWidget(self.scroll, 1)
        self.setTabOrder(self.back_button, self.settings_button)
        self.setTabOrder(self.settings_button, self.brief_edit)
        self.setTabOrder(self.brief_edit, self.generate_button)
        self.setTabOrder(self.generate_button, self.cancel_button)
        self.setTabOrder(self.cancel_button, self.retry_button)
        self.setTabOrder(self.retry_button, self.open_button)
        self.setTabOrder(self.open_button, self.history_list)
        self.setTabOrder(self.history_list, self.refinement_edit)
        self.setTabOrder(self.refinement_edit, self.refine_button)

    def _confirm_transmission(self, endpoint: str, model: str,
                              refinement: tuple[str, str] | None = None) -> bool:
        if refinement is None:
            requested_content = (
                "The request may include the brief you entered, its provider-generated normalized requirements, generated candidate recipes, fixed recipe-v1 capability/schema context, and bounded sanitized repair or check feedback. It does not include the current project, project files, images, or local filesystem paths.")
            question = "Send this brief to the configured provider?"
        else:
            parent_id, instruction = refinement
            requested_content = (
                "The request includes the selected saved generation's accepted brief and recipe, its verified parent-child identity, and your explicit change request below. The model returns a full replacement recipe. Your current project and its files, images, manual edits, and local filesystem paths are not sent or merged.\n\n"
                f"Selected parent: {parent_id}\nChange request: {instruction}")
            question = "Send this refinement request using the selected saved recipe?"
        text = (
            f"Destination: {endpoint}\n"
            f"Model: {model}\n\n"
            f"{requested_content} The provider key is sent only in the authorization header.\n\n"
            "Limits: at most 5 semantic provider calls and 10 HTTP attempts; 90 seconds per HTTP attempt; 10 minutes total. Worker attempts are limited to 3 minutes each. OBJ and GLB output is static. Cost is unavailable. Local run records are saved under:\n"
            f"{self.controller.app_data_root()}\n\n"
            "Choose Send request to authorize this run.")
        box = QMessageBox(self)
        box.setWindowTitle("Confirm AI request")
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.PlainText)
        box.setText(question)
        box.setInformativeText(text)
        send = box.addButton("Send request", QMessageBox.AcceptRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        return box.clickedButton() is send

    def _begin_generation(self):
        brief = self.brief_edit.toPlainText()
        if not brief.strip():
            self._show_message("Enter a brief before generating.")
            self.brief_edit.setFocus()
            return
        snapshot = self.controller.settings_snapshot()
        if not snapshot["model"].strip():
            self._show_message("Choose an explicit model in AI Settings before generating.")
            self.settings_button.setFocus()
            return
        if not self._confirm_transmission(snapshot["endpoint"], snapshot["model"]):
            return
        self._start_generation(brief)

    def launch_refinement(self, parent_id: str, instruction: str) -> bool:
        """Confirm and start a recipe-based child after divergence choice."""
        snapshot = self.controller.settings_snapshot()
        if not snapshot["model"].strip():
            self._show_message("Choose an explicit model in AI Settings before refining.")
            self.settings_button.setFocus()
            return False
        if not self._confirm_transmission(
                snapshot["endpoint"], snapshot["model"],
                refinement=(parent_id, instruction)):
            return False
        try:
            run_id = self.controller.start_generation(
                "", parent_generation_id=parent_id,
                refinement_request=instruction)
        except ValueError as exc:
            self._show_message(str(exc))
            return False
        if not run_id:
            self.history_status.setText("Another owned AI operation is still running. Wait for it to finish before refining.")
            return False
        self._last_refinement = (parent_id, instruction)
        self._last_outcome = None
        self._copying = False
        self._started_at = time.monotonic()
        self._timer.start()
        self.status_label.setText(
            "Refining from the verified saved recipe. Manual edits are not merged into this new child.")
        self.stage_label.setText("Stage: starting")
        self.attempt_label.setText("Attempt: 0")
        self.elapsed_label.setText("Elapsed: 0.0 s")
        self.retry_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("Waiting for a checked child preview.")
        self.result_summary.setPlainText(
            f"Refinement child is running. Parent generation: {parent_id}")
        self.limitations.setPlainText("The full replacement recipe is being checked.")
        self.source_report.setPlainText("Refinement starts from the parent's stored accepted recipe.")
        return True

    def _start_generation(self, brief: str):
        try:
            self.controller.start_generation(brief)
        except ValueError as exc:
            self._show_message(str(exc))
            return
        self._last_outcome = None
        self._last_refinement = None
        self._copying = False
        self._started_at = time.monotonic()
        self._timer.start()
        self.status_label.setText("Starting generation. Waiting for the actual pipeline stage.")
        self.stage_label.setText("Stage: starting")
        self.attempt_label.setText("Attempt: 0")
        self.elapsed_label.setText("Elapsed: 0.0 s")
        self.retry_button.setEnabled(False)
        self.open_button.setEnabled(False)
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("Waiting for a checked preview.")
        self.result_summary.setPlainText("Generation is running.")
        self.limitations.setPlainText("Generation is running.")
        self.source_report.setPlainText("Generation is running.")

    def _retry(self):
        # Every retry has a new transmission preflight and a fresh controller UUID.
        if self._last_refinement is not None:
            parent_id, instruction = self._last_refinement
            detail = self._history_detail
            record = detail.get("record") if isinstance(detail, dict) else None
            if not isinstance(record, dict) or record.get("run_id") != parent_id:
                self.history_status.setText(
                    "Select and verify the original parent again before retrying this refinement. The failed child remains in history.")
                return
            self.launch_refinement(parent_id, instruction)
            return
        self._begin_generation()

    def _cancel(self):
        if not self.controller.cancel():
            return
        self.status_label.setText("Cancelling. Waiting for the owned operation to acknowledge cancellation.")
        self.cancel_button.setEnabled(False)

    def _open_in_editor(self):
        if self.controller.create_editor_copy():
            self._copying = True
            self.status_label.setText("Creating and verifying a writable project copy in the background.")
            self.cancel_button.setEnabled(True)
            self.cancel_button.setText("Cancel copy")
            self.open_button.setEnabled(False)

    def refresh_history(self):
        if self.controller.busy:
            return
        self._history_detail = None
        self.history_list.blockSignals(True)
        self.history_list.clear()
        self.history_list.blockSignals(False)
        self._history_rows.clear()
        self._update_history_actions()
        self.history_status.setText("Loading saved history and recovering interrupted runs…")
        self.controller.refresh_history()

    def _on_history_list(self, rows):
        rows = rows if isinstance(rows, list) else []
        self._history_rows = {
            row["run_id"]: row for row in rows
            if isinstance(row, dict) and isinstance(row.get("run_id"), str)
        }
        self.history_list.blockSignals(True)
        self.history_list.clear()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("run_id"), str):
                continue
            run_id = row["run_id"]
            status = str(row.get("status", "unavailable"))
            state = {
                "complete": "Complete · select to verify",
                "running": "Interrupted recovery pending",
                "checking": "Interrupted recovery pending",
                "failed": "Failed",
                "cancelled": "Cancelled",
                "interrupted": "Interrupted · retry available",
            }.get(status, "Unavailable")
            brief = " ".join(str(row.get("brief", "")).split())
            if len(brief) > 92:
                brief = brief[:89] + "…"
            when = str(row.get("completed_utc", ""))[:19].replace("T", " ")
            lineage = ""
            parent = row.get("parent_generation_id")
            if isinstance(parent, str):
                lineage = f" · child of {parent[:8]}"
            elif any(item.get("parent_generation_id") == run_id
                     for item in self._history_rows.values()):
                lineage = " · parent"
            label = f"{state} · {when}{lineage}\n{brief or '(No brief recorded)'}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, run_id)
            item.setToolTip(run_id)
            self.history_list.addItem(item)
        self.history_list.blockSignals(False)
        self.history_status.setText(
            f"{len(self._history_rows)} local record(s). Complete rows are verified when selected. Interrupted runs remain unsuccessful until an explicit retry.")
        self._update_history_actions()

    def _on_history_selection(self, current, _previous):
        run_id = current.data(Qt.UserRole) if current is not None else None
        self._history_detail = None
        self.open_button.setEnabled(False)
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("Select a completed saved generation to verify its checked preview.")
        self.result_summary.setPlainText("Select a saved generation to inspect its verified history.")
        self.source_report.setPlainText("The selected record and its artifact manifest have not been verified yet.")
        if not isinstance(run_id, str):
            self._showing_history = False
            self.history_status.setText("Select a saved run to inspect its status and lineage.")
            self._update_history_actions()
            return
        self.history_status.setText("Verifying the selected record, immutable manifest, native project and checked preview…")
        self._showing_history = True
        self._update_history_actions()
        self.controller.load_history_record(run_id)

    def _on_history_detail(self, detail):
        if not isinstance(detail, dict):
            self._on_history_failed("The selected history record could not be verified.")
            return
        record = detail.get("record")
        current = self.history_list.currentItem()
        selected = current.data(Qt.UserRole) if current is not None else None
        if not isinstance(record, dict) or record.get("run_id") != selected:
            return
        self._history_detail = detail
        image = detail.get("preview_image")
        if image is not None and not image.isNull():
            self.preview_label.setPixmap(QPixmap.fromImage(image).scaled(
                512, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        else:
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("The checked preview is unavailable.")
        recipe = record.get("accepted_recipe")
        brief = record.get("accepted_brief")
        brief_text = brief.get("brief", "") if isinstance(brief, dict) else brief
        parent_id = record.get("parent_generation_id")
        children = sorted(
            (run_id for run_id, row in self._history_rows.items()
             if row.get("parent_generation_id") == record.get("run_id")))
        lineage = [f"Generation ID: {record.get('run_id', '')}"]
        lineage.append(f"Parent generation: {parent_id or 'None (original run)'}")
        lineage.append("Children: " + (", ".join(item[:8] for item in children)
                                      if children else "None listed"))
        artifacts = record.get("artifact_manifest", [])
        files = [f"{item.get('path')} ({item.get('bytes')} bytes)"
                 for item in artifacts if isinstance(item, dict)]
        lineage.append("Verified files: " + (", ".join(files[:16]) or "None"))
        lineage.append("Native project content digest: " + str(detail.get("project_digest", "unavailable")))
        if isinstance(brief_text, str):
            lineage.append("Accepted brief: " + brief_text)
        self.result_summary.setPlainText("\n".join(lineage))
        limitations = []
        if isinstance(brief, dict) and isinstance(brief.get("approximations"), list):
            limitations.extend(str(item) for item in brief["approximations"])
        report = record.get("check_report")
        if isinstance(report, dict) and isinstance(report.get("limitations"), list):
            limitations.extend(str(item) for item in report["limitations"])
        self.limitations.setPlainText(
            "Limitations and approximations:\n" +
            ("\n".join(f"• {item}" for item in limitations) if limitations
             else "None recorded."))
        source = {"accepted_recipe": recipe, "check_report": report,
                  "verified_artifact_manifest": artifacts}
        if isinstance(detail.get("recipe_diff"), str):
            source["deterministic_recipe_diff"] = detail["recipe_diff"]
        if parent_id and detail.get("parent_record") is None:
            self.history_status.setText(
                "Record verified. Its parent reference remains visible, but the parent history is unavailable.")
        else:
            self.history_status.setText(
                f"Verified checked generation {record.get('run_id', '')}. This snapshot remains immutable.")
        self.source_report.setPlainText(_safe_json(source))
        self.open_button.setEnabled(False)
        self._update_history_actions()

    def _on_history_failed(self, message):
        self._history_detail = None
        self.history_status.setText(str(message))
        self._update_history_actions()

    def _selected_history_id(self):
        item = self.history_list.currentItem()
        value = item.data(Qt.UserRole) if item is not None else None
        return value if isinstance(value, str) else None

    def _update_history_actions(self):
        busy = self.controller.busy
        selected = self._selected_history_id()
        verified = (self._history_detail or {}).get("record")
        is_verified = (isinstance(verified, dict)
                       and verified.get("run_id") == selected
                       and verified.get("status") == "complete")
        self.refresh_history_button.setEnabled(not busy)
        self.delete_history_button.setEnabled(not busy and selected is not None)
        self.restore_history_button.setEnabled(not busy and is_verified)
        self.refine_button.setEnabled(not busy and is_verified)
        self.refinement_edit.setReadOnly(busy)

    def _restore_selected_history(self):
        run_id = self._selected_history_id()
        if run_id and self.controller.restore_history_copy(run_id):
            self._copying = True
            self.status_label.setText("Verifying and copying the selected immutable generation to a new writable project…")
            self.cancel_button.setEnabled(True)
            self.cancel_button.setText("Cancel copy")
            self.restore_history_button.setEnabled(False)

    def _delete_selected_history(self):
        run_id = self._selected_history_id()
        if not run_id or self.controller.busy:
            return
        box = QMessageBox(self)
        box.setWindowTitle("Delete saved generation")
        box.setIcon(QMessageBox.Warning)
        box.setTextFormat(Qt.PlainText)
        box.setText("Delete this selected local history record and its saved files?")
        box.setInformativeText(
            "Deletion cannot be undone. Child generations, if any, will never be deleted automatically.")
        remove = box.addButton("Delete history", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        if box.clickedButton() is not remove:
            return
        self.history_status.setText("Deleting the confirmed local history record…")
        self.controller.delete_history_record(run_id)

    def _on_history_deleted(self, run_id, result):
        if not isinstance(result, dict):
            self._on_history_failed("The selected history record could not be deleted.")
            return
        if result.get("needs_parent_confirmation"):
            children = result.get("child_generation_ids", [])
            child_text = ", ".join(str(item) for item in children[:8]) or "one or more children"
            box = QMessageBox(self)
            box.setWindowTitle("Delete refinement parent")
            box.setIcon(QMessageBox.Warning)
            box.setTextFormat(Qt.PlainText)
            box.setText("This saved generation is a parent of child refinements.")
            box.setInformativeText(
                f"The child records and files will remain, but their parent history will no longer be available. Children: {child_text}. Delete the parent anyway?")
            remove = box.addButton("Delete parent only", QMessageBox.DestructiveRole)
            box.addButton("Keep parent", QMessageBox.RejectRole)
            box.exec()
            if box.clickedButton() is remove:
                self.history_status.setText("Deleting the confirmed parent record; children remain intact…")
                self.controller.delete_history_record(run_id, confirm_parent=True)
            else:
                self.history_status.setText("Parent history was kept; child records remain unchanged.")
            return
        if result.get("deleted"):
            self.history_status.setText("Selected local history record deleted. Referenced children were not cascaded.")
            self._history_detail = None
            self.refresh_history()
            return
        self._on_history_failed("The selected history record was not found; refresh history and try again.")

    def _refine_selected_history(self):
        detail = self._history_detail
        record = detail.get("record") if isinstance(detail, dict) else None
        if not isinstance(record, dict) or record.get("run_id") != self._selected_history_id():
            self.history_status.setText("Select and verify a completed generation before refining.")
            return
        instruction = self.refinement_edit.toPlainText().strip()
        if not instruction:
            self.history_status.setText("Enter a change request before refining.")
            self.refinement_edit.setFocus()
            return
        if len(instruction.encode("utf-8")) > 4 * 1024:
            self.history_status.setText("Change requests are limited to 4 KiB.")
            return
        self.refinement_requested.emit(record["run_id"], instruction)

    def _on_event(self, event):
        if self._started_at is None:
            # The worker can emit its first stage immediately after start(),
            # before _start_generation has returned and initialized the view.
            # The controller timestamp is captured before the worker starts.
            self._started_at = getattr(self.controller, "active_started", None)
            if self._started_at is None:
                return
            self._timer.start()
        stage = str(getattr(event, "stage", "working"))
        attempt = int(getattr(event, "attempt", 0))
        message = str(getattr(event, "message", "Working"))
        self.stage_label.setText(f"Stage: {stage}")
        self.attempt_label.setText(f"Attempt: {attempt}")
        if not self.controller.cancellation_pending:
            self.status_label.setText(message)

    def _on_outcome(self, outcome):
        self._timer.stop()
        self._last_outcome = outcome
        self._showing_history = False
        self._started_at = None
        status = str(getattr(outcome, "status", "failed"))
        record = getattr(outcome, "record", {})
        error = getattr(outcome, "error", None)
        self.stage_label.setText(f"Stage: {status}")
        self.elapsed_label.setText(
            f"Elapsed: {max(0.0, time.monotonic() - self.controller.active_started):.1f} s"
            if self.controller.active_started is not None else "Elapsed: —")
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancel")
        if status == "completed" and isinstance(record, dict):
            checked_result_visible = self._show_success(outcome, record)
            self.retry_button.setEnabled(False)
            self.open_button.setEnabled(checked_result_visible)
            self.history_status.setText(
                "The checked result is saved locally. Choose Refresh History to verify and inspect its saved record.")
            return
        self.preview_label.setPixmap(QPixmap())
        self.preview_label.setText("No checked preview is available for this run.")
        message = "Generation ended without a checked, published project."
        if isinstance(error, dict):
            if isinstance(error.get("message"), str):
                message = error["message"]
            hint = error.get("hint")
            if isinstance(hint, str) and hint:
                message += "\n" + hint
        self.status_label.setText(message)
        self.result_summary.setPlainText(f"Run status: {status}\nNo project was opened.")
        self.limitations.setPlainText(
            "This request needs an explicit revision before retrying."
            if status == "user_choice_required"
            else "No result limitations are available for this unsuccessful run.")
        self.source_report.setPlainText(_safe_json({
            "error": error if isinstance(error, dict) else {},
            "check_report": getattr(outcome, "check_report", None),
        }))
        self.retry_button.setEnabled(status != "user_choice_required")
        self.open_button.setEnabled(False)
        self.history_status.setText(
            "This terminal run remains in local history. Choose Refresh History to inspect or delete its attempt record.")

    def _show_success(self, outcome, record: dict):
        root = getattr(outcome, "published_path", None)
        check_report = getattr(outcome, "check_report", None)
        preview = Path(root) / "preview.png" if isinstance(root, str) else None
        if (not isinstance(check_report, dict) or check_report.get("ok") is not True
                or preview is None or not preview.is_file()):
            self.status_label.setText(
                "The run returned without a verified preview. No editor handoff is available.")
            self.preview_label.setPixmap(QPixmap())
            self.preview_label.setText("Checked preview is unavailable.")
            self.open_button.setEnabled(False)
            return False
        pixmap = QPixmap(str(preview))
        if pixmap.isNull():
            self.preview_label.setText("The checked preview could not be decoded.")
            self.open_button.setEnabled(False)
            return False
        self.preview_label.setPixmap(pixmap.scaled(
            512, 320, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        self.status_label.setText("Complete. The generated project passed deterministic checks.")
        recipe = record.get("accepted_recipe")
        recipe = recipe if isinstance(recipe, dict) else {}
        objects = recipe.get("objects", [])
        materials = recipe.get("materials", [])
        exports = [item.get("path") for item in record.get("manifest", [])
                   if isinstance(item, dict) and isinstance(item.get("path"), str)]
        summary = [
            "Status: checked and published",
            f"Objects: {len(objects) if isinstance(objects, list) else 0}",
            f"Materials: {len(materials) if isinstance(materials, list) else 0}",
            f"Generation ID: {record.get('run_id', '')}",
            "Files: " + (", ".join(exports) if exports else "native project and checked preview"),
            "Cost: unavailable",
        ]
        parent_id = record.get("parent_generation_id")
        parent_detail = self._history_detail
        parent_record = (parent_detail.get("record")
                         if isinstance(parent_detail, dict) else None)
        recipe_diff = None
        if (isinstance(parent_id, str) and isinstance(parent_record, dict)
                and parent_record.get("run_id") == parent_id):
            from .ai_history import deterministic_recipe_diff
            summary.append(f"Refinement child of: {parent_id}")
            recipe_diff = deterministic_recipe_diff(
                parent_record.get("accepted_recipe", {}), recipe)
            summary.extend(recipe_diff.splitlines())
        self.result_summary.setPlainText("\n".join(summary))
        brief = record.get("accepted_brief")
        limitations = []
        if isinstance(brief, dict) and isinstance(brief.get("approximations"), list):
            limitations.extend(str(value) for value in brief["approximations"])
        if isinstance(check_report.get("limitations"), list):
            limitations.extend(str(value) for value in check_report["limitations"])
        self.limitations.setPlainText(
            "Limitations and approximations:\n" +
            ("\n".join(f"• {item}" for item in limitations) if limitations else "None recorded."))
        report = {
            "accepted_recipe": recipe,
            "check_report": check_report,
        }
        if recipe_diff is not None:
            report["deterministic_recipe_diff"] = recipe_diff
        self.source_report.setPlainText(_safe_json(report))
        return True

    def _on_copy_ready(self, project_path: str, history_available: bool):
        self._copying = False
        note = "" if history_available else "Full generation history is unavailable because its sidecar is missing. "
        if note:
            self.status_label.setText(note + "A verified writable copy is ready to open.")
        self.adoption_requested.emit(project_path, history_available)

    def adoption_finished(self, opened: bool, history_available: bool = True):
        if opened:
            if not history_available:
                self.status_label.setText(
                    "Opened an editable copy. Full generation history is unavailable because its sidecar is missing.")
            return
        self.status_label.setText(
            "Opening was cancelled. The current project and its edits remain active; the checked result is still available.")
        self.open_button.setEnabled(not self._showing_history)

    def _on_copy_failed(self, message: str):
        self._copying = False
        self.cancel_button.setEnabled(False)
        self.cancel_button.setText("Cancel")
        self.open_button.setEnabled(not self._showing_history)
        self.status_label.setText(str(message))
        self._update_history_actions()

    def _on_busy_changed(self, busy: bool):
        self.generate_button.setEnabled(not busy and bool(self.brief_edit.toPlainText().strip()))
        self.brief_edit.setReadOnly(busy)
        self.settings_button.setEnabled(not busy)
        self.back_button.setEnabled(not busy)
        self.history_list.setEnabled(not busy)
        self.refinement_edit.setReadOnly(busy)
        self.cancel_button.setEnabled(busy and not self.controller.closing)
        if not busy:
            self.cancel_button.setText("Cancel")
            if self._copying:
                self._copying = False
            if self.controller.closing:
                self.status_label.setText("Closing after the owned AI operation stopped.")
        self._update_history_actions()

    def _on_cancellation_changed(self, pending: bool):
        if pending:
            self.cancel_button.setEnabled(False)
            self.status_label.setText("Cancelling. Waiting for an actual owned-worker acknowledgement.")
        elif not self.controller.busy:
            self.cancel_button.setEnabled(False)

    def _update_elapsed(self):
        if self._started_at is not None:
            self.elapsed_label.setText(f"Elapsed: {time.monotonic() - self._started_at:.1f} s")

    def _show_message(self, text: str):
        box = QMessageBox(self)
        box.setWindowTitle("Create with AI")
        box.setIcon(QMessageBox.Information)
        box.setTextFormat(Qt.PlainText)
        box.setText(text)
        box.exec()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.controller.busy:
            self.brief_edit.setFocus()


def _safe_json(value) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)
    except Exception:
        return "Details are unavailable."
