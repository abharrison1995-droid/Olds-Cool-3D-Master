"""Offline history, refinement and restore behavior for the AI workspace."""

from __future__ import annotations

import hashlib
import copy
import threading
import time
import uuid
from pathlib import Path

import pytest
from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox


@pytest.fixture(autouse=True)
def _settings_scope(tmp_path):
    old_format = QSettings.defaultFormat()
    old_user = QSettings(QSettings.IniFormat, QSettings.UserScope,
                         "3DMASTER2005", "app").fileName()
    old_system = QSettings(QSettings.IniFormat, QSettings.SystemScope,
                           "3DMASTER2005", "app").fileName()
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    yield
    QSettings.setDefaultFormat(old_format)
    if old_user:
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                          str(Path(old_user).parent.parent))
        assert QSettings(QSettings.IniFormat, QSettings.UserScope,
                         "3DMASTER2005", "app").fileName() == old_user
    if old_system:
        QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope,
                          str(Path(old_system).parent.parent))
        assert QSettings(QSettings.IniFormat, QSettings.SystemScope,
                         "3DMASTER2005", "app").fileName() == old_system


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _wait(app, predicate, timeout=30.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def _settings():
    settings = QSettings("3DMASTER2005", "app")
    settings.clear()
    settings.setValue("ai/endpoint", "https://api.openai.com/v1/chat/completions")
    settings.setValue("ai/model", "offline-history-fixture")
    settings.setValue("ai/credentialStorage", "session")
    settings.sync()


def _recipe(color=(0.2, 0.4, 0.8)):
    return {
        "version": 1,
        "name": "phase7-history-fixture",
        "objects": [{
            "name": "body", "primitive": "sphere",
            "params": {"radius": 0.75, "sections": 12, "rings": 8},
            "splines": [{"name": "guide", "degree": 3, "closed": False,
                         "points": [[0, 0, 0], [0.2, 0, 0],
                                    [0.4, 0.2, 0], [0.6, 0.4, 0]]}],
        }],
        "materials": [{"name": "coat", "color": list(color),
                       "objects": ["body"]}],
        "exports": [],
    }


def _build_window(tmp_path, monkeypatch):
    _settings()
    from am3d.ai import orchestrator as orch
    from am3d.ai.contracts import AssetBrief
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ai.orchestrator import GenerationOrchestrator
    from am3d.ai.records import GenerationRecordStore
    from am3d.ui.test_operators import _make_main_window

    class OfflineProvider:
        def __init__(self, *_args):
            pass

        def generate(self, *_args):
            return None

    parent_recipe = _recipe()
    child_recipe = _recipe((0.05, 0.28, 0.08))
    observed_refinements = []

    def interpret(provider, raw_request, deadline, cancellation):
        provider.generate(None, deadline, cancellation)
        return AssetBrief(brief=raw_request)

    def build(provider, _brief, deadline, cancellation, *,
              refinement_request=None, previous_recipe=None, **_kwargs):
        provider.generate(None, deadline, cancellation)
        if refinement_request is None:
            return parent_recipe
        observed_refinements.append((refinement_request, previous_recipe))
        return child_recipe

    monkeypatch.setattr(orch, "interpret_brief", interpret)
    monkeypatch.setattr(orch, "build_candidate", build)
    win = _make_main_window()
    controller = win.ai_controller
    controller.data_root = tmp_path / "history"
    controller.provider_factory = OfflineProvider
    controller.store_factory = GenerationRecordStore
    controller.orchestrator_factory = GenerationOrchestrator
    controller.session_credentials = SessionCredentialStore()
    return win, parent_recipe, child_recipe, observed_refinements


def test_offline_worker_history_refinement_restore_and_manual_action_divergence(
        tmp_path, monkeypatch):
    """A real source worker publishes a child; history restores only a copy."""
    app = _app()
    win, parent_recipe, child_recipe, observed_refinements = _build_window(
        tmp_path, monkeypatch)
    controller = win.ai_controller
    workspace = win.ai_workspace
    from am3d.ai.records import GenerationRecordStore
    from am3d.core.animation import Action
    from am3d.core.serializer import project_content_digest
    from am3d.ui.operators import ImportActionCommand

    outcomes = []
    controller.outcome_ready.connect(outcomes.append)
    try:
        assert controller.start_generation("A small blue round body.")
        assert _wait(app, lambda: not controller.busy, timeout=150.0)
        assert outcomes and outcomes[-1].status == "completed", (
            outcomes[-1].error if outcomes else "no offline source outcome")
        parent_id = outcomes[-1].run_id
        store = GenerationRecordStore(controller.data_root)
        parent_record = store.get_record(parent_id)
        canonical_parent_recipe = parent_record["accepted_recipe"]
        parent_path = Path(parent_record["project_path"])
        parent_before = parent_path.read_bytes()
        parent_hash = hashlib.sha256(parent_before).hexdigest()

        # History is loaded only by explicit user action; record verification,
        # native reopen and preview decoding happen on the owned worker.
        workspace.refresh_history()
        assert _wait(app, lambda: not controller.busy)
        parent_item = next(
            workspace.history_list.item(i)
            for i in range(workspace.history_list.count())
            if workspace.history_list.item(i).data(256) == parent_id)
        workspace.history_list.setCurrentItem(parent_item)
        assert _wait(app, lambda: not controller.busy)
        assert workspace._history_detail["record"]["run_id"] == parent_id
        assert not workspace.preview_label.pixmap().isNull()
        assert controller._verified_history_record["accepted_recipe"] == canonical_parent_recipe

        # Refinement re-verifies this exact parent in the source orchestrator,
        # records a new child UUID and never writes into the parent snapshot.
        child_id = controller.start_generation(
            "", parent_generation_id=parent_id,
            refinement_request="Change the body to dark green.")
        assert child_id and child_id != parent_id
        assert _wait(app, lambda: not controller.busy, timeout=150.0)
        assert outcomes[-1].status == "completed", outcomes[-1].error
        child_record = store.get_record(child_id)
        assert child_record["parent_generation_id"] == parent_id
        assert child_record["accepted_recipe"]["materials"][0]["color"] == list(child_recipe["materials"][0]["color"])
        assert observed_refinements == [(
            "Change the body to dark green.", canonical_parent_recipe)]
        assert parent_path.read_bytes() == parent_before
        assert hashlib.sha256(parent_path.read_bytes()).hexdigest() == parent_hash

        workspace.refresh_history()
        assert _wait(app, lambda: not controller.busy)
        assert workspace.history_list.count() == 2
        child_item = next(
            workspace.history_list.item(i)
            for i in range(workspace.history_list.count())
            if workspace.history_list.item(i).data(256) == child_id)
        workspace.history_list.setCurrentItem(child_item)
        assert _wait(app, lambda: not controller.busy)
        assert workspace._history_detail["parent_record"]["run_id"] == parent_id
        assert "Materials changed: coat (color)" in workspace._history_detail["recipe_diff"]

        # Restore the immutable parent through the UI's separate writable-copy
        # worker and normal MainWindow adoption path.
        parent_item = next(
            workspace.history_list.item(i)
            for i in range(workspace.history_list.count())
            if workspace.history_list.item(i).data(256) == parent_id)
        workspace.history_list.setCurrentItem(parent_item)
        assert _wait(app, lambda: not controller.busy)
        assert workspace.restore_history_button.isEnabled()
        workspace.restore_history_button.click()
        assert _wait(app, lambda: not controller.busy, timeout=60.0)
        assert win.doc_ctrl.path is not None
        assert Path(win.doc_ctrl.path) != parent_path
        working_path = Path(str(win.doc_ctrl.path).removeprefix("\\\\?\\"))
        assert working_path.resolve().is_relative_to(
            (controller.data_root / "working-projects").resolve())
        assert win.session.project.generation["run_id"] == parent_id
        assert parent_path.read_bytes() == parent_before

        # An unsaved Session action is not synchronized to Project.actions.
        # The divergence check explicitly includes Session.actions even when
        # the editable envelope continues to claim diverged=false.
        action = Action("unsaved action")
        action.add_channel("root").add_key(0.0, [0.0, 0.0, 0.0])
        win.push_command(ImportActionCommand(win.session, action))
        assert win.session.project.generation.get("diverged") is False
        generation_before = copy.deepcopy(win.session.project.generation)
        session_digest = project_content_digest(
            win.session.project, actions=win.session.actions)
        # project_content_digest currently shares the serializer's provenance
        # mutation behavior; restore the fixture value to exercise an editable
        # envelope that still says diverged=false at the UI comparison point.
        win.session.project.generation.clear()
        win.session.project.generation.update(generation_before)
        assert win.session.project.generation.get("diverged") is False
        assert session_digest != workspace._history_detail["project_digest"]
        original_session = win.session
        original_project = win.session.project
        original_undo_count = win.undo_stack.count()
        launch_calls = []
        monkeypatch.setattr(workspace, "launch_refinement",
                            lambda parent, request: launch_calls.append((parent, request)) or True)
        original_clicked_button = QMessageBox.clickedButton

        def choose(title):
            def fake_exec(box):
                if box.windowTitle() == "Manual edits differ from the saved generation":
                    box._phase7_choice = next(
                        button for button in box.buttons()
                        if button.text() == title)
                return 0
            monkeypatch.setattr(QMessageBox, "exec", fake_exec)
            monkeypatch.setattr(
                QMessageBox, "clickedButton",
                lambda box: getattr(box, "_phase7_choice", None)
                if hasattr(box, "_phase7_choice") else original_clicked_button(box))

        # Cancel must preserve the live Session, current project, dirty flag,
        # and undo history. Refine Original uses the same saved parent only.
        choose("Cancel")
        win._prepare_ai_refinement(parent_id, "Keep the body, change its color.")
        assert not launch_calls
        assert win.session is original_session and win.session.project is original_project
        assert win.doc_ctrl.dirty is True
        assert win.undo_stack.count() == original_undo_count
        assert "unsaved action" in win.session.actions
        assert len(win.session.actions["unsaved action"].channels[0].keys) == 1
        assert win.session.project.generation == generation_before

        choose("Refine original generation")
        win._prepare_ai_refinement(parent_id, "Keep the body, change its color.")
        assert launch_calls == [(parent_id, "Keep the body, change its color.")]
        assert win.session is original_session and win.undo_stack.count() == original_undo_count
        assert win.session.project.generation == generation_before

        # A second restore reaches the ordinary dirty-document guard. Cancel
        # there keeps the Session and its undoable manual action untouched.
        win.show_ai_workspace()
        workspace.refresh_history()
        assert _wait(app, lambda: not controller.busy)
        parent_item = next(
            workspace.history_list.item(i)
            for i in range(workspace.history_list.count())
            if workspace.history_list.item(i).data(256) == parent_id)
        workspace.history_list.setCurrentItem(parent_item)
        assert _wait(app, lambda: not controller.busy)
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: False)
        workspace.restore_history_button.click()
        assert _wait(app, lambda: not controller.busy, timeout=60.0)
        assert win.session is original_session and win.session.project is original_project
        assert win.doc_ctrl.dirty is True
        assert win.undo_stack.count() == original_undo_count
        assert parent_path.read_bytes() == parent_before

        # Save manual copy follows the ordinary Save As path, then the
        # explicitly selected original recipe remains the refinement source.
        manual_path = tmp_path / "manual-copy.am3d"
        monkeypatch.setattr(QFileDialog, "getSaveFileName",
                            lambda *_args, **_kwargs: (str(manual_path), ""))
        choose("Save manual copy")
        win._prepare_ai_refinement(parent_id, "Keep the body, change its color.")
        assert manual_path.is_file()
        assert win.doc_ctrl.path == str(manual_path)
        assert launch_calls[-1] == (parent_id, "Keep the body, change its color.")
        assert win.session is original_session
        assert parent_path.read_bytes() == parent_before
    finally:
        win.viewport._timer.stop()
        win.close()


def test_history_parent_delete_warns_and_never_cascades_children(
        tmp_path, monkeypatch):
    app = _app()
    _settings()
    from am3d.ai.records import GenerationRecordStore
    from am3d.ai.test_records import _publish
    from am3d.ui.ai_controller import AIController
    from am3d.ui.ai_workspace import AIWorkspace

    store = GenerationRecordStore(tmp_path / "delete-history")
    _attempt, parent_root, parent = _publish(store)
    child_attempt = store.begin(parent_generation_id=parent["run_id"])
    from am3d.ai.test_records import _candidate
    candidate, child_metadata, report = _candidate(child_attempt)
    child_root = child_attempt.publish(candidate, child_metadata, report)
    child_id = child_attempt.run_id
    parent_bytes = (parent_root / "project.am3d").read_bytes()
    child_bytes = (child_root / "project.am3d").read_bytes()
    controller = AIController(data_root=store.root,
                              store_factory=GenerationRecordStore)
    workspace = AIWorkspace(controller)
    try:
        workspace.refresh_history()
        assert _wait(app, lambda: not controller.busy)
        parent_item = next(
            workspace.history_list.item(i)
            for i in range(workspace.history_list.count())
            if workspace.history_list.item(i).data(256) == parent["run_id"])
        workspace.history_list.setCurrentItem(parent_item)
        assert _wait(app, lambda: not controller.busy)

        choices = iter(["Delete history", "Delete parent only"])
        original_exec = QMessageBox.exec
        original_clicked_button = QMessageBox.clickedButton

        def choose_next(box):
            if box.windowTitle() in {"Delete saved generation", "Delete refinement parent"}:
                desired = next(choices)
                box._phase7_choice = next(button for button in box.buttons()
                                          if button.text() == desired)
                return 0
            return original_exec(box)

        monkeypatch.setattr(QMessageBox, "exec", choose_next)
        monkeypatch.setattr(
            QMessageBox, "clickedButton",
            lambda box: getattr(box, "_phase7_choice", None)
            if hasattr(box, "_phase7_choice") else original_clicked_button(box))
        workspace.delete_history_button.click()
        assert _wait(app, lambda: not controller.busy)
        # Parent confirmation was granted, but its child is not cascaded.
        assert not (parent_root / "record.json").exists()
        assert store.get_record(child_id)["run_id"] == child_id
        assert (child_root / "project.am3d").read_bytes() == child_bytes
        assert not parent_root.exists()
    finally:
        workspace.close()


def test_restart_rebuilds_parent_child_and_interrupted_history(tmp_path):
    app = _app()
    _settings()
    from am3d.ai.records import GenerationRecordStore
    from am3d.ai.test_records import _publish
    from am3d.ui.ai_controller import AIController
    from am3d.ui.ai_workspace import AIWorkspace

    root = tmp_path / "restart-history"
    first_store = GenerationRecordStore(root)
    _attempt, _parent_root, parent = _publish(first_store)
    child_attempt = first_store.begin(parent_generation_id=parent["run_id"])
    from am3d.ai.test_records import _candidate
    candidate, metadata, report = _candidate(child_attempt)
    child_attempt.publish(candidate, metadata, report)
    first_store.begin().write_state("running", {"brief": "interrupted on restart"})
    first_store.begin().write_state("failed", {"brief": "failed attempt"})
    first_store.begin().write_state("cancelled", {"brief": "cancelled attempt"})

    # A fresh controller/workspace reconstructs records from the existing
    # on-disk store, recovering only running/checking attempts as interrupted.
    restarted_store = GenerationRecordStore(root)
    controller = AIController(data_root=root,
                              store_factory=GenerationRecordStore)
    workspace = AIWorkspace(controller)
    try:
        workspace.refresh_history()
        assert _wait(app, lambda: not controller.busy)
        statuses = {
            row["brief"]: row["status"] for row in workspace._history_rows.values()
        }
        assert statuses["interrupted on restart"] == "interrupted"
        assert statuses["failed attempt"] == "failed"
        assert statuses["cancelled attempt"] == "cancelled"
        assert any(row.get("parent_generation_id") == parent["run_id"]
                   for row in workspace._history_rows.values())
        assert len(restarted_store.list_records()) == 5
    finally:
        workspace.close()


def test_stale_history_selection_and_close_cancel_wait_for_owned_worker(tmp_path):
    app = _app()
    entered_first = threading.Event()
    release_first = threading.Event()
    entered_second = threading.Event()
    release_second = threading.Event()
    call_count = []

    class SlowStore:
        def __init__(self, _root):
            pass

        def get_record(self, run_id):
            call_count.append(run_id)
            if len(call_count) == 1:
                entered_first.set()
                assert release_first.wait(5.0)
            else:
                entered_second.set()
                assert release_second.wait(5.0)
            raise FileNotFoundError("fixture sidecar")

    from am3d.ui.ai_controller import AIController
    controller = AIController(data_root=tmp_path / "slow-history",
                              store_factory=SlowStore)
    failures = []
    controller.history_failed.connect(failures.append)
    first, second = str(uuid.uuid4()), str(uuid.uuid4())
    assert controller.load_history_record(first)
    assert entered_first.wait(5.0)

    # Selecting another row while the first verification is busy invalidates
    # the first request token. No stale missing-record message may surface.
    assert controller.load_history_record(second) is None
    release_first.set()
    assert _wait(app, lambda: not controller.busy)
    assert failures == []

    # The next request is owned until its worker acknowledges close-cancel.
    assert controller.load_history_record(second)
    assert entered_second.wait(5.0)
    controller.request_shutdown()
    assert controller.closing is True
    release_second.set()
    assert _wait(app, lambda: not controller.busy)
    assert controller.closing is True
    assert failures == []
    controller.resume_after_close_cancelled()
    assert controller.closing is False
    assert len(failures) == 1
    assert "cancelled after its worker acknowledged" in failures[0]


def test_refinement_retry_creates_new_failed_child_and_keeps_parent(tmp_path):
    app = _app()
    _settings()
    from am3d.ai.orchestrator import GenerationOutcome
    from am3d.ai.records import GenerationRecordStore
    from am3d.ai.test_records import _publish
    from am3d.ui.ai_controller import AIController
    from am3d.ui.ai_workspace import AIWorkspace

    store = GenerationRecordStore(tmp_path / "retry-history")
    _attempt, parent_root, parent = _publish(store)
    parent_hash = hashlib.sha256((parent_root / "project.am3d").read_bytes()).hexdigest()
    calls = []

    class RetryOrchestrator:
        def __init__(self, _provider, record_store):
            self.store = record_store

        def generate(self, _brief, *, run_id, parent_generation_id,
                     refinement_request, **_kwargs):
            calls.append((run_id, parent_generation_id, refinement_request))
            attempt = self.store.begin(
                run_id=run_id, parent_generation_id=parent_generation_id)
            attempt.write_state("failed", {
                "accepted_brief": "fixture request",
                "refinement_request": refinement_request,
            })
            return GenerationOutcome(
                run_id, "failed",
                {"run_id": run_id, "status": "failed",
                 "parent_generation_id": parent_generation_id},
                error={"code": "fixture_failure", "stage": "worker",
                       "message": "Fixed offline failure."})

    class Provider:
        def __init__(self, *_args):
            pass

    controller = AIController(
        data_root=store.root,
        store_factory=lambda _root: store,
        provider_factory=Provider,
        orchestrator_factory=RetryOrchestrator)
    from am3d.ai.credentials import SessionCredentialStore
    controller.session_credentials = SessionCredentialStore()
    controller._selected_history_id = parent["run_id"]
    controller._verified_history_record = parent
    workspace = AIWorkspace(controller)
    workspace._history_detail = {"record": parent, "project_digest": "fixture-digest"}
    workspace._confirm_transmission = lambda *_args, **_kwargs: True
    instruction = "Keep the body and lengthen both arms."
    try:
        assert workspace.launch_refinement(parent["run_id"], instruction)
        first_id = controller.active_run_id
        assert _wait(app, lambda: not controller.busy)
        assert controller._last_outcome.status == "failed"
        assert workspace.retry_button.isEnabled()

        workspace.retry_button.click()
        second_id = controller.active_run_id
        assert second_id and first_id and second_id != first_id
        assert _wait(app, lambda: not controller.busy)
        assert controller._last_outcome.status == "failed"
        assert calls == [
            (first_id, parent["run_id"], instruction),
            (second_id, parent["run_id"], instruction),
        ]
        saved = {row["run_id"]: row for row in store.list_records()}
        assert saved[first_id]["status"] == "failed"
        assert saved[second_id]["status"] == "failed"
        assert saved[first_id]["parent_generation_id"] == parent["run_id"]
        assert saved[second_id]["parent_generation_id"] == parent["run_id"]
        assert hashlib.sha256((parent_root / "project.am3d").read_bytes()).hexdigest() == parent_hash
    finally:
        workspace.close()
