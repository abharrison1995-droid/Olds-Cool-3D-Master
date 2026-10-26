"""Generation workflow integration for the desktop window.

The window still owns Qt objects, document state and public action hooks.
This collaborator wires the two generation APIs without mixing their contracts.
"""
from __future__ import annotations

import copy
from PySide6.QtCore import QTimer, Qt


class GenerationIntegration:
    def __init__(self, window):
        self.window = window

    def setup_legacy(self):
        window = self.window
        from am3d.ai.m3.runner import GenerationRunner
        window._generation_runner = GenerationRunner()
        window._generation_poll_timer = QTimer(window)
        window._generation_poll_timer.setInterval(100)
        window._generation_poll_timer.timeout.connect(window._poll_generation_worker)
        window._generation_poll_timer.start()
        window._close_after_generation = False


    def setup_ai(self):
        window = self.window
        from .ai_controller import AIController
        from .ai_workspace import AIWorkspace
        window.ai_controller = AIController(window)
        window.ai_controller.busy_changed.connect(window._on_ai_busy_changed)
        window.ai_workspace = AIWorkspace(window.ai_controller, window)
        window.ai_workspace.back_home.connect(window.show_home)
        window.ai_workspace.settings_requested.connect(window._file_ai_settings)
        window.ai_workspace.adoption_requested.connect(window._adopt_ai_project)
        window.ai_workspace.refinement_requested.connect(
            window._prepare_ai_refinement)
        window.ai_controller.lifecycle_quiescent.connect(
            window._continue_deferred_close)


    def show_recipe_dialog(self):
        """Open the M2 local-generation bridge for an authored recipe-v1."""
        window = self.window
        from .generation_dialog import GenerationDialog
        dialog = GenerationDialog(window._generation_runner,
                                  window._open_generated_generation, window)
        dialog.exec()


    def poll_legacy_worker(self):
        """Keep child cleanup progressing even when its dialog is hidden."""
        window = self.window
        window._generation_runner.poll()
        if window._close_after_generation and not window._generation_runner.running:
            window._close_after_generation = False
            QTimer.singleShot(0, window.close)


    def open_legacy_generation(self, run_id: str) -> bool:
        """Open only a verified writable copy through the normal document path."""
        window = self.window
        working_copy = window._generation_runner.create_writable_project_copy(run_id)
        try:
            if not window.doc_ctrl.maybe_abandon_document():
                working_copy.unlink(missing_ok=True)
                return False
            window.doc_ctrl.do_open(str(working_copy))
            window.doc_ctrl.add_recent(str(working_copy))
            window._reset_document_ui_state()
            window._refresh_all()
            window._fit_viewport_to_scene()
            window.show_editor()
            return True
        except Exception:
            if window.doc_ctrl.path != str(working_copy):
                working_copy.unlink(missing_ok=True)
            raise


    def on_ai_busy_changed(self, busy: bool):
        """Keep provider configuration read-only during generation or copy."""
        window = self.window
        action = getattr(window, "_ai_settings_action", None)
        if action is not None:
            action.setEnabled(not busy)


    def adopt_ai_project(self, project_path: str, history_available: bool):
        """Adopt only a worker-created copy, after the normal dirty guard."""
        window = self.window
        if not window.doc_ctrl.maybe_abandon_document():
            window.ai_workspace.adoption_finished(False, history_available)
            return
        try:
            window.doc_ctrl.do_open(project_path)
        except Exception:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                window, "Open generated project failed",
                "The writable project copy could not be loaded. Your current project remains active.")
            window.ai_workspace.adoption_finished(False, history_available)
            return
        window.doc_ctrl.add_recent(project_path)
        window._reset_document_ui_state()
        window._refresh_all()
        window.ai_workspace.adoption_finished(True, history_available)
        window.show_editor()


    def prepare_ai_refinement(self, parent_id: str, instruction: str):
        """Resolve manual divergence before authorizing a recipe-only child."""
        window = self.window
        from PySide6.QtWidgets import QMessageBox
        detail = window.ai_workspace._history_detail
        record = detail.get("record") if isinstance(detail, dict) else None
        authority_digest = detail.get("project_digest") if isinstance(detail, dict) else None
        if (not isinstance(record, dict) or record.get("run_id") != parent_id
                or record.get("status") != "complete"
                or not isinstance(authority_digest, str)):
            window.ai_workspace.history_status.setText(
                "Select and verify the completed parent again before refining.")
            return
        try:
            from am3d.core.serializer import project_content_digest
            # Session.actions may contain unsaved action/keyframe edits that
            # are not yet mirrored onto Project.actions. Include the explicit
            # Session state in the authored digest.
            project = window.session.project
            generation_envelope = getattr(project, "generation", None)
            generation_before = (copy.deepcopy(generation_envelope)
                                 if isinstance(generation_envelope, dict)
                                 else generation_envelope)
            try:
                current_digest = project_content_digest(
                    project, actions=window.session.actions)
            finally:
                # The serializer's save path updates provenance divergence.
                # A comparison is read-only, including when the user cancels.
                if isinstance(generation_envelope, dict):
                    generation_envelope.clear()
                    generation_envelope.update(generation_before)
                project.generation = generation_envelope
        except Exception:
            window.ai_workspace.history_status.setText(
                "Current project changes could not be compared safely. No refinement was started.")
            return
        if current_digest != authority_digest:
            box = QMessageBox(window)
            box.setWindowTitle("Manual edits differ from the saved generation")
            box.setIcon(QMessageBox.Warning)
            box.setTextFormat(Qt.PlainText)
            box.setText(
                "Refinement uses the selected generation's saved recipe. It does not include or merge the current project's manual edits.")
            box.setInformativeText(
                "Save manual copy writes the current session through the ordinary Save As path, then refines the original saved generation. Refine original keeps the current session open and starts from the selected immutable recipe. Cancel leaves the session and undo history untouched.")
            save_copy = box.addButton("Save manual copy", QMessageBox.ActionRole)
            refine_original = box.addButton(
                "Refine original generation", QMessageBox.AcceptRole)
            cancel = box.addButton("Cancel", QMessageBox.RejectRole)
            box.setDefaultButton(cancel)
            box.exec()
            clicked = box.clickedButton()
            if clicked is save_copy:
                try:
                    saved_path = window.doc_ctrl.do_save_as()
                except Exception:
                    window.ai_workspace.history_status.setText(
                        "The manual copy could not be saved. The current session remains open and no refinement was started.")
                    return
                if saved_path is None:
                    window.ai_workspace.history_status.setText(
                        "Save As was cancelled. The current session and undo history remain active; no refinement was started.")
                    return
            elif clicked is not refine_original:
                window.ai_workspace.history_status.setText(
                    "Refinement cancelled. The current session and undo history are unchanged.")
                return
        window.ai_workspace.launch_refinement(parent_id, instruction)


    def continue_deferred_close(self):
        """Finish close on the GUI thread after the owned worker has stopped."""
        window = self.window
        if not window._close_after_ai:
            return
        window._close_after_ai = False
        window._allow_deferred_close = True
        QTimer.singleShot(0, window.close)
