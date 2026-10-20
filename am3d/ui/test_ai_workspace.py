"""Offline lifecycle and UI acceptance checks for Create with AI."""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox


@pytest.fixture(autouse=True)
def _restore_qsettings_scope(tmp_path):
    """Keep every model/key fixture inside this test's temporary INI file."""
    old_format = QSettings.defaultFormat()
    old_ini_file = QSettings(QSettings.IniFormat, QSettings.UserScope,
                             "3DMASTER2005", "app").fileName()
    old_system_ini_file = QSettings(QSettings.IniFormat, QSettings.SystemScope,
                                    "3DMASTER2005", "app").fileName()
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    yield
    QSettings.setDefaultFormat(old_format)
    if old_ini_file:
        QSettings.setPath(QSettings.IniFormat, QSettings.UserScope,
                          str(Path(old_ini_file).parent.parent))
        assert QSettings(QSettings.IniFormat, QSettings.UserScope,
                         "3DMASTER2005", "app").fileName() == old_ini_file
    if old_system_ini_file:
        QSettings.setPath(QSettings.IniFormat, QSettings.SystemScope,
                          str(Path(old_system_ini_file).parent.parent))
        assert QSettings(QSettings.IniFormat, QSettings.SystemScope,
                         "3DMASTER2005", "app").fileName() == old_system_ini_file


def _app():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _settings(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    QSettings.setPath(QSettings.IniFormat, QSettings.UserScope, str(tmp_path))
    QSettings.setDefaultFormat(QSettings.IniFormat)
    settings = QSettings("3DMASTER2005", "app")
    settings.clear()
    settings.sync()
    settings.setValue("ai/endpoint", "https://api.openai.com/v1/chat/completions")
    settings.setValue("ai/model", "explicit-test-model")
    settings.setValue("ai/credentialStorage", "session")
    settings.sync()
    return settings


def _wait(app, predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


def _checked_ui_outcome(tmp_path, run_id="checked-close-race"):
    from PySide6.QtGui import QImage

    published = tmp_path / "checked-ui-result"
    published.mkdir(parents=True, exist_ok=True)
    preview = QImage(8, 8, QImage.Format.Format_RGB32)
    preview.fill(0xFF336699)
    assert preview.save(str(published / "preview.png"), "PNG")
    return SimpleNamespace(
        run_id=run_id,
        status="completed",
        record={"run_id": run_id, "accepted_recipe": {"objects": [], "materials": []},
                "manifest": [], "accepted_brief": {"approximations": []}},
        error=None,
        check_report={"ok": True, "limitations": []},
        published_path=str(published),
    )


class _Provider:
    def __init__(self, *_args):
        self.calls = 0

    def generate(self, *_args):
        self.calls += 1
        return object()


class _FakeOrchestrator:
    """Deterministic stand-in for controller lifecycle tests only."""

    outcomes = []
    entered = None
    wait_for_cancel = False
    after_cancel_status = "cancelled"
    outcome_factory = None

    def __init__(self, _provider, _store):
        pass

    def generate(self, brief, *, cancellation, on_event, run_id, **_kwargs):
        from am3d.ai.orchestrator import GenerationOutcome
        from am3d.ai.contracts import GenerationEvent

        on_event(GenerationEvent(run_id, 0, "interpreting", 0,
                                 "Interpreting within the shared deadline."))
        if self.entered is not None:
            self.entered.set()
        if self.wait_for_cancel:
            while not cancellation.cancelled:
                time.sleep(0.01)
            on_event(GenerationEvent(run_id, 1, "checking", 1,
                                     "Late in-flight stage after cancel."))
            status = self.after_cancel_status
        else:
            status = "failed"
        if type(self).outcome_factory is not None:
            result = type(self).outcome_factory(run_id, brief, status)
        else:
            result = GenerationOutcome(
                run_id, status, {"run_id": run_id, "brief": brief},
                error={"code": status, "stage": "test",
                       "message": "Fixed test result."})
        self.outcomes.append(result)
        return result


def _controller(tmp_path, **overrides):
    from am3d.ui.ai_controller import AIController
    options = dict(
        data_root=tmp_path / "app-data",
        orchestrator_factory=_FakeOrchestrator,
        provider_factory=_Provider,
        store_factory=lambda _root: object(),
    )
    options.update(overrides)
    controller = AIController(**options)
    from am3d.ai.credentials import SessionCredentialStore
    controller.session_credentials = SessionCredentialStore()
    return controller


def test_home_primary_action_opens_offline_workspace_without_provider_activity(
        tmp_path, monkeypatch):
    _app()
    _settings(tmp_path)
    from am3d.ai.credentials import SystemCredentialStore
    from am3d.ui.test_operators import _make_main_window

    def unexpected_system_store(*_args, **_kwargs):
        raise AssertionError("offline workspace must not inspect credentials")

    monkeypatch.setattr(SystemCredentialStore, "__init__", unexpected_system_store)
    win = _make_main_window()
    try:
        assert win.home._create_ai_btn.text() == "Create with &AI..."
        win.home.action_create_ai.emit()
        assert win.stack.currentWidget() is win.ai_workspace
        assert not win.ai_controller.busy
        assert win.ai_workspace.brief_edit.isReadOnly() is False
        assert win.ai_workspace.preview_label.pixmap().isNull()
    finally:
        win.viewport._timer.stop()
        win.close()


def test_controller_filters_stale_run_ids_and_nonincreasing_sequences(tmp_path):
    _app()
    from am3d.ai.contracts import GenerationEvent
    controller = _controller(tmp_path)
    controller.active_run_id = str(uuid.uuid4())
    controller._thread_kind = "generation"
    accepted = []
    controller.event_changed.connect(accepted.append)

    controller._on_event(GenerationEvent(controller.active_run_id, 0,
        "building", 1, "Actual stage"))
    controller._on_event(GenerationEvent(controller.active_run_id, 0,
        "checking", 2, "Duplicate sequence"))
    controller._on_event(GenerationEvent(str(uuid.uuid4()), 1,
        "completed", 2, "Stale run"))

    assert len(accepted) == 1
    assert accepted[0].stage == "building"
    assert controller.last_sequence == 0

    pending = []
    controller._pending_outcome = None
    controller.active_run_id = str(uuid.uuid4())
    controller._on_outcome(SimpleNamespace(run_id=str(uuid.uuid4()), status="completed"))
    assert controller._pending_outcome is None
    controller._on_outcome(SimpleNamespace(run_id=controller.active_run_id,
                                           status="failed"))
    assert controller._pending_outcome.status == "failed"
    assert pending == []


def test_cancel_waits_for_terminal_worker_ack_and_retry_uses_new_uuid(tmp_path):
    app = _app()
    _settings(tmp_path)
    from am3d.ai.orchestrator import GenerationOutcome

    _FakeOrchestrator.outcomes = []
    _FakeOrchestrator.entered = None
    _FakeOrchestrator.wait_for_cancel = True
    controller = _controller(tmp_path)
    from am3d.ui.ai_workspace import AIWorkspace
    workspace = AIWorkspace(controller)
    workspace.show()
    events = []
    controller.event_changed.connect(events.append)
    outcomes = []
    controller.outcome_ready.connect(outcomes.append)
    first_id = controller.start_generation("a small test asset")
    assert first_id
    assert _wait(app, lambda: bool(events))
    assert workspace.stage_label.text() == "Stage: interpreting", (
        repr(events[0]), controller.active_stage,
        repr(workspace.stage_label.text()))
    assert workspace.brief_edit.tabChangesFocus() is True
    time.sleep(0.1)
    app.processEvents()
    workspace._update_elapsed()
    assert float(workspace.elapsed_label.text().split()[1]) >= 0.1
    assert controller.cancel() is True
    assert controller.busy  # remains occupied until the worker returns
    from am3d.ai.contracts import GenerationEvent
    controller._on_event(GenerationEvent(first_id, 1, "checking", 1,
        "Late in-flight stage after cancel."))
    app.processEvents()
    assert workspace.stage_label.text() == "Stage: checking"
    assert workspace.status_label.text().startswith("Cancelling.")
    assert _wait(app, lambda: not controller.busy)
    assert outcomes[-1].status == "cancelled"
    assert outcomes[-1].run_id == first_id

    _FakeOrchestrator.wait_for_cancel = False
    workspace.brief_edit.setPlainText("a small test asset")
    confirmations = []
    workspace._confirm_transmission = lambda endpoint, model: (
        confirmations.append((endpoint, model)) or True)
    workspace.retry_button.click()
    second_id = controller.active_run_id
    assert confirmations == [("https://api.openai.com/v1/chat/completions",
                              "explicit-test-model")]
    assert second_id and second_id != first_id
    assert _wait(app, lambda: not controller.busy)
    assert outcomes[-1].run_id == second_id
    assert outcomes[-1].status == "failed"
    workspace.close()


def test_working_copy_thread_copies_project_resources_outside_history(tmp_path):
    app = _app()
    from am3d.ai.records import GenerationRecordStore
    from am3d.ai.test_records import _publish
    store = GenerationRecordStore(tmp_path / "history")
    _attempt, immutable_root, record = _publish(store, texture=True)
    immutable_hash = hashlib.sha256(
        (immutable_root / "project.am3d").read_bytes()).hexdigest()
    from am3d.ui.ai_controller import AIController
    controller = AIController(data_root=store.root, store_factory=lambda _root: store)
    controller.active_run_id = record["run_id"]
    controller._last_outcome = SimpleNamespace(status="completed")
    copies = []
    controller.copy_ready.connect(lambda path, history: copies.append((path, history)))

    assert controller.create_editor_copy() is True
    assert _wait(app, lambda: not controller.busy)

    assert copies and copies[0][1] is True
    project_path = copies[0][0]
    copied_root = __import__("pathlib").Path(project_path).parent
    assert copied_root.is_relative_to(store.root / "working-projects")
    assert copied_root != immutable_root
    assert (copied_root / "atlas.png").is_file()
    assert hashlib.sha256((immutable_root / "project.am3d").read_bytes()).hexdigest() == immutable_hash


def test_missing_history_sidecar_keeps_copy_integrity_and_manual_open_message(tmp_path):
    app = _app()
    from am3d.ui.ai_controller import AIController

    copier_called = []

    class MissingHistoryStore:
        def __init__(self, _root):
            pass

        def get_record(self, _run_id):
            raise FileNotFoundError("sidecar fixture")

    def forbidden_copier(*_args):
        copier_called.append(True)
        raise AssertionError("copy must not bypass verified history")

    controller = AIController(data_root=tmp_path / "missing-history",
                              store_factory=MissingHistoryStore,
                              copier=forbidden_copier)
    controller.active_run_id = str(uuid.uuid4())
    controller._last_outcome = SimpleNamespace(status="completed")
    failures = []
    controller.copy_failed.connect(failures.append)

    assert controller.create_editor_copy() is True
    assert _wait(app, lambda: not controller.busy)
    assert not copier_called
    assert len(failures) == 1
    assert "history sidecar is missing" in failures[0]
    assert "Manual File > Open remains available" in failures[0]


def test_copy_cancel_waits_for_ack_and_removes_unadopted_copy(tmp_path):
    app = _app()
    from pathlib import Path
    from PySide6.QtCore import QThread
    from am3d.ui.ai_controller import AIController

    entered = threading.Event()
    release = threading.Event()
    worker_threads = []
    target_roots = []

    class Store:
        def __init__(self, _root):
            pass

        def get_record(self, run_id):
            return {"run_id": run_id}

    def copier(_record, target_dir):
        worker_threads.append(QThread.currentThread())
        entered.set()
        assert release.wait(5.0)
        run_root = Path(target_dir)
        target_roots.append(run_root)
        run_root.mkdir(parents=True)
        project_path = run_root / "project.am3d"
        project_path.write_bytes(b"verified offline fixture")
        return {"run_root": str(run_root), "project_path": str(project_path)}

    controller = AIController(data_root=tmp_path / "history",
                              store_factory=Store, copier=copier)
    controller.active_run_id = str(uuid.uuid4())
    controller._last_outcome = SimpleNamespace(status="completed")
    adopted, failures = [], []
    controller.copy_ready.connect(lambda *args: adopted.append(args))
    controller.copy_failed.connect(failures.append)

    assert controller.create_editor_copy() is True
    assert entered.wait(5.0)
    assert worker_threads and worker_threads[0] != app.thread()
    assert controller.cancel() is True
    assert controller.busy
    release.set()
    assert _wait(app, lambda: not controller.busy)

    assert not adopted
    assert failures == ["Editor copy was cancelled. The current document is unchanged."]
    assert target_roots and not target_roots[0].exists()


def test_copy_close_suppresses_late_adoption_until_thread_quiescent(tmp_path):
    app = _app()
    from pathlib import Path
    from am3d.ui.ai_controller import AIController

    entered = threading.Event()
    release = threading.Event()

    class Store:
        def __init__(self, _root):
            pass

        def get_record(self, run_id):
            return {"run_id": run_id}

    def copier(_record, target_dir):
        entered.set()
        assert release.wait(5.0)
        run_root = Path(target_dir)
        run_root.mkdir(parents=True)
        project_path = run_root / "project.am3d"
        project_path.write_bytes(b"verified offline fixture")
        return {"run_root": str(run_root), "project_path": str(project_path)}

    controller = AIController(data_root=tmp_path / "history",
                              store_factory=Store, copier=copier)
    controller.active_run_id = str(uuid.uuid4())
    controller._last_outcome = SimpleNamespace(status="completed")
    adopted, quiescent = [], []
    controller.copy_ready.connect(lambda *args: adopted.append(args))
    controller.lifecycle_quiescent.connect(lambda: quiescent.append(True))

    assert controller.create_editor_copy() is True
    assert entered.wait(5.0)
    controller.request_shutdown()
    assert controller.busy
    release.set()
    assert _wait(app, lambda: not controller.busy)

    assert not adopted
    assert quiescent == [True]


def test_close_cancel_restores_copy_cancelled_state_without_late_adoption(
        tmp_path, monkeypatch):
    app = _app()
    _settings(tmp_path)
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ui.test_operators import _make_main_window

    entered = threading.Event()
    release = threading.Event()
    target_roots = []

    class Store:
        def __init__(self, _root):
            pass

        def get_record(self, run_id):
            return {"run_id": run_id}

    def copier(_record, target_dir):
        assert threading.current_thread() is not threading.main_thread()
        entered.set()
        assert release.wait(5.0)
        run_root = Path(target_dir)
        target_roots.append(run_root)
        run_root.mkdir(parents=True)
        project_path = run_root / "project.am3d"
        project_path.write_bytes(b"late verified copy")
        return {"run_root": str(run_root), "project_path": str(project_path)}

    win = _make_main_window()
    run_id = str(uuid.uuid4())
    outcome = _checked_ui_outcome(tmp_path, run_id)
    controller = win.ai_controller
    controller.data_root = tmp_path / "app-data"
    controller.store_factory = Store
    controller.copier = copier
    controller.active_run_id = run_id
    controller._last_outcome = outcome
    controller.session_credentials = SessionCredentialStore()
    win.ai_workspace._on_outcome(outcome)
    win.show()
    win.show_ai_workspace()
    original_session = win.session
    original_path = win.doc_ctrl.path
    original_summary = win.ai_workspace.result_summary.toPlainText()
    adoptions = []
    win.ai_workspace.adoption_requested.connect(
        lambda *args: adoptions.append(args))
    monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: False)

    try:
        assert not win.ai_workspace.preview_label.pixmap().isNull()
        assert win.ai_workspace.open_button.isEnabled()
        win.ai_workspace.open_button.click()
        assert entered.wait(5.0)
        assert not win.ai_workspace.open_button.isEnabled()

        assert win.close() is False
        release.set()
        assert _wait(app, lambda: not controller.busy and not controller.closing,
                     timeout=8.0)

        assert win.isVisible()
        assert not adoptions
        assert win.session is original_session
        assert win.doc_ctrl.path == original_path
        assert controller._last_outcome is outcome
        assert win.ai_workspace.open_button.isEnabled()
        assert win.ai_workspace.result_summary.toPlainText() == original_summary
        assert not win.ai_workspace.preview_label.pixmap().isNull()
        assert win.ai_workspace.status_label.text() == (
            "Editor copy was cancelled. The current document is unchanged.")
        assert target_roots and not target_roots[0].exists()
    finally:
        release.set()
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: True)
        win.viewport._timer.stop()
        win.close()


def test_safe_worker_exception_and_unsupported_choice_states(tmp_path):
    app = _app()
    _settings(tmp_path)
    controller = _controller(tmp_path)

    def secret_exception(*_args):
        raise RuntimeError("private-provider-key-value")

    controller.provider_factory = secret_exception
    from am3d.ui.ai_workspace import AIWorkspace
    workspace = AIWorkspace(controller)
    outcomes = []
    controller.outcome_ready.connect(outcomes.append)
    controller.start_generation("offline exception fixture")
    assert _wait(app, lambda: not controller.busy)
    assert outcomes and outcomes[-1].status == "provider_error"
    assert outcomes[-1].error["message"] == (
        "Generation could not start or finish. Check the AI settings and local storage, then retry.")
    assert "private-provider-key-value" not in str(outcomes[-1].error)

    workspace.retry_button.setEnabled(True)
    workspace.open_button.setEnabled(True)
    workspace._on_outcome(SimpleNamespace(
        status="user_choice_required",
        record={},
        error={"code": "unsupported_requirements", "stage": "planning",
               "message": "Revise the unsupported choices before retrying.",
               "hint": "Choose fewer repeated objects."},
        check_report=None))
    assert workspace.retry_button.isEnabled() is False
    assert workspace.open_button.isEnabled() is False
    assert "Revise the unsupported choices" in workspace.status_label.text()
    workspace.close()


def test_dirty_guard_cancel_preserves_current_session_and_undo_stack(tmp_path,
                                                                       monkeypatch):
    _app()
    from am3d.ui.test_operators import _make_main_window
    from am3d.ui.operators import CreatePrimitiveCommand
    win = _make_main_window()
    try:
        win.push_command(CreatePrimitiveCommand(
            win.session, "box", "box",
            {"width": 1.0, "height": 1.0, "depth": 1.0}))
        objects = tuple(win.session.project.objects)
        undo_count = win.undo_stack.count()
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: False)

        win._adopt_ai_project(str(tmp_path / "unused-copy.am3d"), True)

        assert tuple(win.session.project.objects) == objects
        assert win.doc_ctrl.dirty is True
        assert win.undo_stack.count() == undo_count
    finally:
        win.viewport._timer.stop()
        win.close()


def test_failed_editor_load_preserves_current_session_and_undo_stack(tmp_path,
                                                                       monkeypatch):
    _app()
    from PySide6.QtWidgets import QMessageBox
    from am3d.ui.test_operators import _make_main_window
    from am3d.ui.operators import CreatePrimitiveCommand

    win = _make_main_window()
    try:
        win.push_command(CreatePrimitiveCommand(
            win.session, "box", "box",
            {"width": 1.0, "height": 1.0, "depth": 1.0}))
        original_session = win.session
        original_project = win.session.project
        objects = tuple(win.session.project.objects)
        undo_count = win.undo_stack.count()
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: True)
        monkeypatch.setattr(win.doc_ctrl, "do_open",
                            lambda _path: (_ for _ in ()).throw(OSError("fixture")))
        monkeypatch.setattr(QMessageBox, "critical", lambda *_args, **_kwargs: None)

        win._adopt_ai_project(str(tmp_path / "invalid-copy.am3d"), True)

        assert win.session is original_session
        assert win.session.project is original_project
        assert tuple(win.session.project.objects) == objects
        assert win.doc_ctrl.dirty is True
        assert win.undo_stack.count() == undo_count
    finally:
        win.viewport._timer.stop()
        win.close()


def test_close_suppresses_late_result_and_waits_for_owned_worker(tmp_path):
    app = _app()
    _settings(tmp_path)
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ui.test_operators import _make_main_window

    _FakeOrchestrator.outcomes = []
    _FakeOrchestrator.wait_for_cancel = True
    _FakeOrchestrator.after_cancel_status = "cancelled"
    _FakeOrchestrator.outcome_factory = None
    _FakeOrchestrator.entered = threading.Event()
    win = _make_main_window()
    win.ai_controller.data_root = tmp_path / "app-data"
    win.ai_controller.orchestrator_factory = _FakeOrchestrator
    win.ai_controller.provider_factory = _Provider
    win.ai_controller.store_factory = lambda _root: object()
    win.ai_controller.session_credentials = SessionCredentialStore()
    win.show()
    received = []
    win.ai_controller.outcome_ready.connect(received.append)
    win.ai_controller.start_generation("close during a test run")
    assert _wait(app, lambda: win.ai_controller.busy)
    assert win._ai_settings_action.isEnabled() is False
    assert win.ai_workspace.settings_button.isEnabled() is False

    assert win.close() is False
    assert win._close_after_ai is True
    assert _wait(app, lambda: not win.ai_controller.busy, timeout=5.0)
    assert _wait(app, lambda: not win.isVisible(), timeout=5.0)
    assert received == []
    assert not win.isVisible()
    win.viewport._timer.stop()


@pytest.mark.parametrize("terminal_status", ["failed", "cancelled"])
def test_close_cancel_restores_generation_failure_or_cancel_state(
        tmp_path, monkeypatch, terminal_status):
    app = _app()
    _settings(tmp_path)
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ui.test_operators import _make_main_window

    _FakeOrchestrator.outcomes = []
    _FakeOrchestrator.wait_for_cancel = True
    _FakeOrchestrator.after_cancel_status = terminal_status
    _FakeOrchestrator.outcome_factory = None
    _FakeOrchestrator.entered = threading.Event()
    win = _make_main_window()
    controller = win.ai_controller
    controller.data_root = tmp_path / "app-data"
    controller.orchestrator_factory = _FakeOrchestrator
    controller.provider_factory = _Provider
    controller.store_factory = lambda _root: object()
    controller.session_credentials = SessionCredentialStore()
    win.show()
    win.show_ai_workspace()
    original_session = win.session
    original_path = win.doc_ctrl.path
    received = []
    controller.outcome_ready.connect(received.append)
    monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: False)

    try:
        controller.start_generation("close cancel terminal fixture")
        assert _FakeOrchestrator.entered.wait(5.0)
        assert win.close() is False
        assert _wait(app, lambda: not controller.busy and not controller.closing,
                     timeout=8.0)

        assert win.isVisible()
        assert len(received) == 1
        assert received[0].status == terminal_status
        assert controller._last_outcome is received[0]
        assert win.ai_workspace.status_label.text() == "Fixed test result."
        assert win.ai_workspace.stage_label.text() == f"Stage: {terminal_status}"
        assert win.ai_workspace.retry_button.isEnabled()
        assert not win.ai_workspace.open_button.isEnabled()
        assert win.session is original_session
        assert win.doc_ctrl.path == original_path
    finally:
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: True)
        win.viewport._timer.stop()
        win.close()


def test_close_cancel_restores_late_committed_success_without_auto_adoption(
        tmp_path, monkeypatch):
    app = _app()
    _settings(tmp_path)
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ui.test_operators import _make_main_window

    _FakeOrchestrator.outcomes = []
    _FakeOrchestrator.wait_for_cancel = True
    _FakeOrchestrator.after_cancel_status = "completed"
    _FakeOrchestrator.outcome_factory = lambda run_id, _brief, _status: (
        _checked_ui_outcome(tmp_path, run_id))
    _FakeOrchestrator.entered = threading.Event()
    win = _make_main_window()
    controller = win.ai_controller
    controller.data_root = tmp_path / "app-data"
    controller.orchestrator_factory = _FakeOrchestrator
    controller.provider_factory = _Provider
    controller.store_factory = lambda _root: object()
    controller.session_credentials = SessionCredentialStore()
    win.show()
    win.show_ai_workspace()
    original_session = win.session
    original_path = win.doc_ctrl.path
    received = []
    controller.outcome_ready.connect(received.append)
    monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: False)

    try:
        controller.start_generation("late completed close fixture")
        assert _FakeOrchestrator.entered.wait(5.0)
        assert win.close() is False
        assert _wait(app, lambda: not controller.busy and not controller.closing,
                     timeout=8.0)

        assert win.isVisible()
        assert len(received) == 1
        assert received[0].status == "completed"
        assert controller._last_outcome is received[0]
        assert win.ai_workspace.status_label.text() == (
            "Complete. The generated project passed deterministic checks.")
        assert not win.ai_workspace.preview_label.pixmap().isNull()
        assert win.ai_workspace.open_button.isEnabled()
        assert win.session is original_session
        assert win.doc_ctrl.path == original_path
    finally:
        _FakeOrchestrator.outcome_factory = None
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: True)
        win.viewport._timer.stop()
        win.close()


@pytest.mark.parametrize("rotate", [False, True])
def test_settings_reject_secret_in_model_or_preferences_before_rotation(
        tmp_path, monkeypatch, rotate):
    _app()
    secret = "sentinel-provider-key-never-persist"
    settings = _settings(tmp_path)
    settings.setValue("ai/model", "safe-explicit-model")
    settings.sync()
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ui.ai_settings import AISettingsDialog

    store = SessionCredentialStore()
    original_store_value = secret if rotate else None
    if original_store_value:
        store.set("default", original_store_value)
    captured = []
    monkeypatch.setattr(AISettingsDialog, "_fixed_error",
                        lambda self, message: captured.append(message))
    dialog = AISettingsDialog(store)
    if rotate:
        dialog.model_edit.setText(secret)
        dialog.key_edit.setText("replacement-provider-key")
    else:
        dialog.model_edit.setText(secret)
        dialog.key_edit.setText(secret)
    before = {key: settings.value(key) for key in settings.allKeys()}

    dialog._save()

    after = {key: settings.value(key) for key in settings.allKeys()}
    assert after == before
    assert store.get("default") == original_store_value
    assert captured and secret not in captured[0]
    assert dialog.key_edit.text() in {secret, "replacement-provider-key"}
    dialog.close()


@pytest.mark.parametrize("key_position", ["current", "rotated-old", "rotated-new"])
@pytest.mark.parametrize("location", ["endpoint", "model"])
def test_settings_reject_percent_encoded_current_or_rotated_key_before_mutation(
        tmp_path, monkeypatch, key_position, location):
    _app()
    settings = _settings(tmp_path)
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ui.ai_settings import AISettingsDialog

    secret = "settings-path-credential-sentinel"
    replacement = "replacement-provider-key"
    store = SessionCredentialStore()
    if key_position == "current":
        previous = None
        entered = secret
        path_secret = secret
    elif key_position == "rotated-old":
        previous = secret
        entered = replacement
        path_secret = secret
        store.set("default", previous)
    else:
        previous = "old-provider-key"
        entered = secret
        path_secret = secret
        store.set("default", previous)

    encoded = "".join(f"%{byte:02X}" for byte in path_secret.encode("utf-8"))
    endpoint = (
        f"https://api.openai.com/v1/{encoded}/chat/completions"
        if location == "endpoint"
        else "https://api.openai.com/v1/chat/completions"
    )
    captured = []
    monkeypatch.setattr(AISettingsDialog, "_fixed_error",
                        lambda self, message: captured.append(message))
    dialog = AISettingsDialog(store)
    dialog.endpoint_edit.setText(endpoint)
    dialog.model_edit.setText(
        encoded if location == "model" else "safe-explicit-model")
    dialog.key_edit.setText(entered)
    before = {key: settings.value(key) for key in settings.allKeys()}

    dialog._save()

    after = {key: settings.value(key) for key in settings.allKeys()}
    if before != after:
        raise AssertionError("preferences changed after credential path rejection")
    if store.get("default") != previous:
        raise AssertionError("credential store changed after path rejection")
    if not captured:
        raise AssertionError("settings accepted a percent-encoded active credential")
    diagnostic = "".join(captured)
    if secret in diagnostic or encoded in diagnostic:
        raise AssertionError("settings error exposed credential material")
    if settings.value("ai/endpoint") != "https://api.openai.com/v1/chat/completions":
        raise AssertionError("credential-bearing endpoint was persisted")
    dialog.close()


def test_settings_rejects_encoded_current_key_in_existing_preference(
        tmp_path, monkeypatch):
    _app()
    settings = _settings(tmp_path)
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ui.ai_settings import AISettingsDialog

    secret = "saved-preference-credential-sentinel"
    encoded = "".join(f"%{byte:02X}" for byte in secret.encode("utf-8"))
    settings.setValue("ai/legacyNote", f"retained text {encoded}")
    settings.sync()
    store = SessionCredentialStore()
    store.set("default", secret)
    captured = []
    monkeypatch.setattr(AISettingsDialog, "_fixed_error",
                        lambda self, message: captured.append(message))
    dialog = AISettingsDialog(store)
    dialog.model_edit.setText("safe-explicit-model")
    dialog.key_edit.setText("replacement-provider-key")
    before = {key: settings.value(key) for key in settings.allKeys()}

    dialog._save()

    after = {key: settings.value(key) for key in settings.allKeys()}
    if before != after:
        raise AssertionError("preferences changed after encoded-key rejection")
    if store.get("default") != secret:
        raise AssertionError("credential store changed after encoded-key rejection")
    if not captured:
        raise AssertionError("settings accepted a key encoded in a saved preference")
    if secret in "".join(captured) or encoded in "".join(captured):
        raise AssertionError("settings error exposed credential material")
    dialog.close()


def test_ai_settings_accepts_a_valid_percent_escaped_endpoint_path(
        tmp_path, monkeypatch):
    _app()
    settings = _settings(tmp_path)
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ui.ai_settings import AISettingsDialog

    endpoint = "https://api.openai.com/v1/teams%2Fblue/chat/completions"
    store = SessionCredentialStore()
    dialog = AISettingsDialog(store)
    dialog.endpoint_edit.setText(endpoint)
    dialog.model_edit.setText("explicit-test-model")
    dialog.key_edit.setText("settings-valid-session-key")
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)

    dialog._save()

    if dialog.result() != QDialog.Accepted:
        raise AssertionError("valid escaped endpoint was not accepted")
    if settings.value("ai/endpoint") != endpoint:
        raise AssertionError("valid escaped endpoint was not persisted")
    if store.get("default") != "settings-valid-session-key":
        raise AssertionError("valid settings did not save the session key")
    dialog.close()


def test_ai_settings_save_key_only_to_selected_session_store_and_clear_input(
        tmp_path, monkeypatch):
    _app()
    settings = _settings(tmp_path)
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ui.ai_settings import AISettingsDialog

    store = SessionCredentialStore()
    dialog = AISettingsDialog(store)
    dialog.storage_combo.setCurrentIndex(dialog.storage_combo.findData("session"))
    dialog.model_edit.setText("user-selected-model")
    dialog.key_edit.setText("new-session-key-sentinel")
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.Ok)

    dialog._save()

    assert dialog.result() == QDialog.Accepted
    assert store.get("default") == "new-session-key-sentinel"
    assert dialog.key_edit.text() == ""
    assert "new-session-key-sentinel" not in str(
        [settings.value(key) for key in settings.allKeys()])
    dialog.close()


def test_real_worker_checked_generation_adoption_and_manual_edit_round_trip(
        tmp_path, monkeypatch):
    """Use the offline source pipeline, then edit its writable copy.

    The CP operation edits the generated object's separate guide spline. It
    does not claim to reshape the executor's generated surface; transforms
    and material color are edited on the checked object itself.
    """
    app = _app()
    settings = _settings(tmp_path / "settings")
    settings.setValue("ai/model", "offline-fixture-model")
    settings.sync()

    from am3d.ai import orchestrator as orch
    from am3d.ai.contracts import AssetBrief
    from am3d.ai.records import GenerationRecordStore
    from am3d.core.serializer import load_project
    from am3d.ui.operators import (
        MoveCPCommand, SetMaterialColorCommand, SetObjectTransformCommand,
    )
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ui.test_operators import _make_main_window

    recipe = {
        "version": 1,
        "name": "manual-edit-fixture",
        "objects": [{
            "name": "body", "primitive": "sphere",
            "params": {"radius": 0.75, "sections": 12, "rings": 8},
            "splines": [{"name": "guide", "degree": 3, "closed": False,
                         "points": [[0, 0, 0], [0.2, 0.0, 0],
                                    [0.4, 0.2, 0], [0.6, 0.4, 0]]}],
        }],
        "materials": [{"name": "coat", "color": [0.2, 0.4, 0.8],
                       "objects": ["body"]}],
        "exports": [],
    }

    class PipelineProvider:
        def __init__(self, *_args):
            pass

        def generate(self, *_args):
            return None

    def interpret(provider, raw_request, deadline, cancellation):
        provider.generate(None, deadline, cancellation)
        return AssetBrief(brief=raw_request)

    def build(provider, _brief, deadline, cancellation, **_kwargs):
        provider.generate(None, deadline, cancellation)
        return recipe

    monkeypatch.setattr(orch, "interpret_brief", interpret)
    monkeypatch.setattr(orch, "build_candidate", build)

    win = _make_main_window()
    win.ai_controller.data_root = tmp_path / "actual-ai-data"
    win.ai_controller.provider_factory = PipelineProvider
    win.ai_controller.store_factory = GenerationRecordStore
    win.ai_controller.session_credentials = SessionCredentialStore()
    outcomes = []
    win.ai_controller.outcome_ready.connect(outcomes.append)
    try:
        win.ai_controller.start_generation("Build a simple round body with one editable spline guide.")
        assert _wait(app, lambda: not win.ai_controller.busy, timeout=150.0)
        assert outcomes and outcomes[-1].status == "completed", (
            outcomes[-1].error if outcomes else "no terminal result")
        outcome = outcomes[-1]
        print(f"offline fixture generation id: {outcome.run_id}")
        assert outcome.check_report["ok"] is True
        store = GenerationRecordStore(win.ai_controller.data_root)
        record = store.get_record(outcome.run_id)
        immutable_project = __import__("pathlib").Path(record["project_path"])
        immutable_hash = hashlib.sha256(immutable_project.read_bytes()).hexdigest()

        assert win.ai_controller.create_editor_copy() is True
        assert _wait(app, lambda: not win.ai_controller.busy, timeout=60.0)
        assert win.doc_ctrl.path is not None
        working_project = __import__("pathlib").Path(win.doc_ctrl.path)
        assert working_project != immutable_project
        working_root = Path(str(working_project.parent).removeprefix("\\\\?\\"))
        assert working_root.resolve().is_relative_to(
            (win.ai_controller.data_root / "working-projects").resolve())
        assert hashlib.sha256(working_project.read_bytes()).hexdigest() == immutable_hash

        body = win.session.project.objects["body"]
        spline = body.splines["guide"]
        cp_before = spline.cps[1].position.copy()
        cp_after = cp_before + np.array([0.0, 0.12, 0.0])
        transform_before = body.transform.copy()
        transform_after = transform_before.copy()
        transform_after[:3, 3] = [0.25, 0.5, -0.1]
        color_before = tuple(win.session.project.materials["coat"].color)
        color_after = (0.1, 0.65, 0.25, 1.0)

        win.push_command(MoveCPCommand(win.session, "body", "guide", 1,
                                       cp_before, cp_after))
        win.push_command(SetObjectTransformCommand(
            win.session, "body", transform_before, transform_after))
        win.push_command(SetMaterialColorCommand(win.session, "coat", color_after))
        assert win.doc_ctrl.dirty is True
        assert np.array_equal(spline.cps[1].position, cp_after)
        assert np.array_equal(body.transform, transform_after)
        assert tuple(win.session.project.materials["coat"].color) == color_after

        win.undo_stack.undo()
        win.undo_stack.undo()
        win.undo_stack.undo()
        assert np.array_equal(spline.cps[1].position, cp_before)
        assert np.array_equal(body.transform, transform_before)
        assert tuple(win.session.project.materials["coat"].color) == color_before
        win.undo_stack.redo()
        win.undo_stack.redo()
        win.undo_stack.redo()
        assert np.array_equal(spline.cps[1].position, cp_after)
        assert np.array_equal(body.transform, transform_after)
        assert tuple(win.session.project.materials["coat"].color) == color_after

        assert win.doc_ctrl.do_save() == str(working_project)
        saved_hash = hashlib.sha256(working_project.read_bytes()).hexdigest()
        assert saved_hash != immutable_hash
        win.doc_ctrl.do_open(str(working_project))
        reopened = load_project(str(working_project))
        assert reopened.generation is not None
        assert np.array_equal(win.session.project.objects["body"].splines[
            "guide"].cps[1].position, cp_after)
        assert np.array_equal(win.session.project.objects["body"].transform,
                              transform_after)
        assert tuple(win.session.project.materials["coat"].color) == color_after
        assert hashlib.sha256(immutable_project.read_bytes()).hexdigest() == immutable_hash
        assert store.get_record(outcome.run_id)["artifact_manifest"] == record["artifact_manifest"]
    finally:
        win.viewport._timer.stop()
        win.close()
