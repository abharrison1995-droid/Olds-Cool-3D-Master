"""GUI-thread coordinator for the bounded AI creation lifecycle.

The controller owns one worker at a time. Qt widgets and document state remain
on the GUI thread; provider IO, generation, artifact verification, and editable
copy creation run in owned QThreads.
"""

from __future__ import annotations

import shutil
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QSettings, QStandardPaths, QThread, Signal


_APPROVED_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_CREDENTIAL_ALIAS = "default"


@dataclass(slots=True)
class _DesktopFailureOutcome:
    run_id: str
    status: str
    record: dict
    error: dict
    record_path: str | None = None
    check_report: dict | None = None
    published_path: str | None = None


class _GenerationThread(QThread):
    event_received = Signal(object)
    outcome_ready = Signal(object)

    def __init__(self, run_id: str, brief: str, endpoint: str, model: str,
                 credential_mode: str, session_credentials: Any,
                 store_root: str, cancellation: Any,
                 parent_generation_id: str | None = None,
                 refinement_request: str | None = None,
                 orchestrator_factory: Callable[..., Any] | None = None,
                 provider_factory: Callable[..., Any] | None = None,
                 store_factory: Callable[..., Any] | None = None,
                 parent=None):
        super().__init__(parent)
        self.run_id = run_id
        self.brief = brief
        self.endpoint = endpoint
        self.model = model
        self.credential_mode = credential_mode
        self.session_credentials = session_credentials
        self.store_root = store_root
        self.cancellation = cancellation
        self.parent_generation_id = parent_generation_id
        self.refinement_request = refinement_request
        self.orchestrator_factory = orchestrator_factory
        self.provider_factory = provider_factory
        self.store_factory = store_factory

    def run(self):
        try:
            from am3d.ai.contracts import ProviderConfig
            from am3d.ai.credentials import SessionCredentialStore, SystemCredentialStore
            from am3d.ai.orchestrator import GenerationOrchestrator
            from am3d.ai.orchestrator import GenerationOutcome
            from am3d.ai.providers import OpenAICompatibleProvider
            from am3d.ai.records import GenerationRecordStore

            config = ProviderConfig(
                endpoint=self.endpoint, model=self.model,
                credential_alias=_CREDENTIAL_ALIAS,
                allowed_hosts=("api.openai.com",),
            )
            if self.credential_mode == "session":
                credentials = self.session_credentials or SessionCredentialStore()
            else:
                credentials = SystemCredentialStore()
            provider_cls = self.provider_factory or OpenAICompatibleProvider
            store_cls = self.store_factory or GenerationRecordStore
            orchestrator_cls = self.orchestrator_factory or GenerationOrchestrator
            provider = provider_cls(config, credentials)
            store = store_cls(self.store_root)
            orchestrator = orchestrator_cls(provider, store)
            outcome = orchestrator.generate(
                self.brief,
                cancellation=self.cancellation,
                on_event=self.event_received.emit,
                run_id=self.run_id,
                parent_generation_id=self.parent_generation_id,
                refinement_request=self.refinement_request,
            )
            if getattr(outcome, "run_id", None) != self.run_id:
                raise RuntimeError("worker returned a mismatched generation id")
        except Exception:
            # Unexpected exceptions can contain paths, request details, or
            # credential data. Convert them to fixed user-facing evidence.
            outcome = _DesktopFailureOutcome(
                run_id=self.run_id,
                status="provider_error",
                record={"run_id": self.run_id, "status": "provider_error"},
                error={
                    "code": "desktop_generation_error",
                    "stage": "desktop",
                    "message": "Generation could not start or finish. Check the AI settings and local storage, then retry.",
                },
            )
        self.outcome_ready.emit(outcome)


class _HistoryThread(QThread):
    """One owned, non-GUI history read/delete operation."""

    result_ready = Signal(str, int, str, object)
    failed = Signal(str, int, str, str)

    def __init__(self, operation_id: str, selection_token: int,
                 operation: str, store_root: str, run_id: str | None,
                 confirm_parent: bool, store_factory=None, parent=None):
        super().__init__(parent)
        self.operation_id = operation_id
        self.selection_token = selection_token
        self.operation = operation
        self.store_root = store_root
        self.run_id = run_id
        self.confirm_parent = confirm_parent
        self.store_factory = store_factory
        self.cancel_requested = False
        self._started_operation = False

    def request_cancel(self):
        # Artifact verification and the store's bounded delete transaction do
        # not expose cancellation. Acknowledge only after that operation exits.
        self.cancel_requested = True

    def run(self):
        if self.cancel_requested:
            self.result_ready.emit(self.operation_id, self.selection_token,
                                   self.operation, {"cancelled": True})
            return
        self._started_operation = True
        try:
            from .ai_history import (delete_history, list_history,
                                     load_history_detail)
            if self.operation == "list":
                result = list_history(self.store_root, self.store_factory)
            elif self.operation == "detail":
                result = load_history_detail(
                    self.store_root, self.run_id or "", self.store_factory)
            elif self.operation == "delete":
                result = delete_history(
                    self.store_root, self.run_id or "",
                    confirm_parent=self.confirm_parent,
                    store_factory=self.store_factory)
            else:
                raise ValueError("unsupported history operation")
        except FileNotFoundError:
            if self.cancel_requested and self.operation != "delete":
                self.result_ready.emit(self.operation_id, self.selection_token,
                                       self.operation, {"cancelled": True})
            else:
                self.failed.emit(self.operation_id, self.selection_token,
                                 self.operation,
                                 "Verified history is unavailable. Manual File > Open remains available.")
        except Exception:
            if self.cancel_requested and self.operation != "delete":
                self.result_ready.emit(self.operation_id, self.selection_token,
                                       self.operation, {"cancelled": True})
            else:
                self.failed.emit(self.operation_id, self.selection_token,
                                 self.operation,
                                 "The selected history operation could not be verified. Existing projects remain unchanged.")
        else:
            if self.cancel_requested and self.operation != "delete":
                result = {"cancelled": True}
            self.result_ready.emit(self.operation_id, self.selection_token,
                                   self.operation, result)


class _WorkingCopyThread(QThread):
    copy_ready = Signal(object, bool)
    copy_failed = Signal(str)

    def __init__(self, run_id: str, store_root: str, target_dir: str,
                 store_factory: Callable[..., Any] | None = None,
                 copier: Callable[..., dict] | None = None,
                 parent=None):
        super().__init__(parent)
        self.run_id = run_id
        self.store_root = store_root
        self.target_dir = target_dir
        self.store_factory = store_factory
        self.copier = copier
        self.cancel_requested = False
        self._copy_root: str | None = None

    def request_cancel(self):
        # The copy API performs bounded file hashing/copying as one operation.
        # The owning thread remains alive until that operation acknowledges;
        # its result is then suppressed, so it can never reach the editor.
        self.cancel_requested = True

    def run(self):
        try:
            from am3d.ai.records import GenerationRecordStore, create_working_copy

            store_cls = self.store_factory or GenerationRecordStore
            store = store_cls(self.store_root)
            record = store.get_record(self.run_id)
            copy_fn = self.copier or store.create_working_copy
            result = copy_fn(record, self.target_dir)
            self._copy_root = result.get("run_root") if isinstance(result, dict) else None
            if self.cancel_requested:
                self._remove_unused_copy()
                return
            project_path = result.get("project_path") if isinstance(result, dict) else None
            if not isinstance(project_path, str) or not Path(project_path).is_file():
                raise OSError("working project was not created")
            self.copy_ready.emit(project_path, True)
        except FileNotFoundError:
            record_file = (Path(self.store_root) / "generations" /
                           self.run_id / "record.json")
            if not record_file.is_file():
                self.copy_failed.emit(
                    "The generation history sidecar is missing, so a verified handoff is unavailable. Manual File > Open remains available for AM3D projects.")
            else:
                self.copy_failed.emit(
                    "A required checked project file is missing. The current document is unchanged.")
        except Exception:
            self.copy_failed.emit(
                "The checked project copy could not be verified. The current document is unchanged.")

    def _remove_unused_copy(self):
        if not self._copy_root:
            return
        root = Path(self._copy_root)
        try:
            # The path is the unique target generated for this copy operation.
            if root.is_dir() and not root.is_symlink():
                shutil.rmtree(root)
        except OSError:
            pass


class AIController(QObject):
    """Own one active run or copy job and filter all late worker messages."""

    event_changed = Signal(object)
    outcome_ready = Signal(object)
    copy_ready = Signal(str, bool)
    copy_failed = Signal(str)
    busy_changed = Signal(bool)
    cancellation_changed = Signal(bool)
    lifecycle_quiescent = Signal()
    history_list_ready = Signal(object)
    history_detail_ready = Signal(object)
    history_failed = Signal(str)
    history_deleted = Signal(str, object)

    def __init__(self, parent=None, *, data_root: str | Path | None = None,
                 orchestrator_factory=None, provider_factory=None,
                 store_factory=None, copier=None):
        super().__init__(parent)
        self.data_root = Path(data_root) if data_root is not None else None
        self.orchestrator_factory = orchestrator_factory
        self.provider_factory = provider_factory
        self.store_factory = store_factory
        self.copier = copier
        self.session_credentials = None
        self.active_run_id: str | None = None
        self.last_sequence = -1
        self.active_started: float | None = None
        self.active_stage = ""
        self.active_attempt = 0
        self._thread: QThread | None = None
        self._thread_kind: str | None = None
        self._cancellation = None
        self._pending_outcome = None
        self._pending_copy: tuple[str | None, bool] | None = None
        self._copy_failure_message: str | None = None
        self._deferred_terminal: tuple[str, Any] | None = None
        self._last_outcome = None
        self._copy_cancelled = False
        self._suppress_results = False
        self._close_requested = False
        self._history_request: tuple[str, int, str, str | None] | None = None
        self._history_selection_token = 0
        self._selected_history_id: str | None = None
        self._pending_history = None
        self._verified_history_record: dict | None = None

    @property
    def busy(self) -> bool:
        return self._thread is not None

    @property
    def closing(self) -> bool:
        return self._close_requested

    @property
    def cancellation_pending(self) -> bool:
        if self._thread_kind == "generation" and self._cancellation is not None:
            return bool(self._cancellation.cancelled)
        if self._thread_kind == "copy":
            return self._copy_cancelled
        if self._thread_kind == "history" and self._thread is not None:
            return bool(getattr(self._thread, "cancel_requested", False))
        return False

    def app_data_root(self) -> Path:
        if self.data_root is not None:
            return self.data_root
        location = QStandardPaths.writableLocation(
            QStandardPaths.AppLocalDataLocation)
        return Path(location) / "ai"

    def settings_snapshot(self) -> dict[str, str]:
        settings = QSettings("3DMASTER2005", "app")
        return {
            "endpoint": str(settings.value("ai/endpoint", _APPROVED_ENDPOINT)),
            "model": str(settings.value("ai/model", "")),
            "credential_mode": str(settings.value("ai/credentialStorage", "system")),
        }

    def start_generation(self, brief: str, *,
                         parent_generation_id: str | None = None,
                         refinement_request: str | None = None) -> str | None:
        if self.busy or self._close_requested:
            return None
        snapshot = self.settings_snapshot()
        model = snapshot["model"].strip()
        endpoint = snapshot["endpoint"].strip()
        if not model:
            raise ValueError("Choose an explicit provider model in AI Settings before generating.")
        if snapshot["credential_mode"] not in {"system", "session"}:
            raise ValueError("Choose a supported credential storage option in AI Settings.")
        if refinement_request is not None:
            try:
                canonical_parent = str(uuid.UUID(parent_generation_id or ""))
            except (ValueError, TypeError, AttributeError):
                raise ValueError("Choose a verified saved generation before refining.") from None
            if canonical_parent != parent_generation_id:
                raise ValueError("Choose a verified saved generation before refining.")
            verified = self._verified_history_record
            if (parent_generation_id != self._selected_history_id
                    or not isinstance(verified, dict)
                    or verified.get("run_id") != parent_generation_id
                    or verified.get("status") != "complete"):
                raise ValueError("Select and verify a completed history record before refining.")
            if not isinstance(refinement_request, str) or not refinement_request.strip():
                raise ValueError("Enter a change request before refining.")
            if len(refinement_request) > 32 * 1024:
                raise ValueError("The refinement request exceeds the 32 KiB limit.")
            parent_generation_id = canonical_parent
            # The orchestrator reloads the verified parent from the store and
            # uses its accepted brief and recipe. Current Session data is never
            # appended to this request or merged into the replacement recipe.
            brief = ""
        elif parent_generation_id is not None:
            raise ValueError("A refinement requires an explicit change request.")
        elif not brief.strip():
            raise ValueError("Enter a brief before generating.")

        from am3d.ai.contracts import CancellationToken
        run_id = str(uuid.uuid4())
        self.active_run_id = run_id
        self.last_sequence = -1
        self.active_started = time.monotonic()
        self.active_stage = "starting"
        self.active_attempt = 0
        self._cancellation = CancellationToken()
        self._pending_outcome = None
        self._deferred_terminal = None
        self._last_outcome = None
        thread = _GenerationThread(
            run_id, brief, endpoint, model, snapshot["credential_mode"],
            self.session_credentials, str(self.app_data_root()), self._cancellation,
            parent_generation_id, refinement_request,
            orchestrator_factory=self.orchestrator_factory,
            provider_factory=self.provider_factory,
            store_factory=self.store_factory, parent=self,
        )
        self._own_thread(thread, "generation")
        thread.event_received.connect(self._on_event)
        thread.outcome_ready.connect(self._on_outcome)
        thread.start()
        return run_id

    def refresh_history(self) -> str | None:
        """Load local record summaries after the user enters the AI workspace."""
        self._verified_history_record = None
        return self._start_history_operation("list")

    def load_history_record(self, run_id: str) -> str | None:
        """Verify one selected immutable record and decode its checked preview."""
        self._history_selection_token += 1
        self._selected_history_id = run_id
        self._verified_history_record = None
        return self._start_history_operation("detail", run_id=run_id)

    def delete_history_record(self, run_id: str, *, confirm_parent=False) -> str | None:
        return self._start_history_operation(
            "delete", run_id=run_id, confirm_parent=confirm_parent)

    def _start_history_operation(self, operation: str, *, run_id=None,
                                 confirm_parent=False):
        if self.busy or self._close_requested:
            return None
        if operation not in {"list", "detail", "delete"}:
            raise ValueError("unsupported history operation")
        operation_id = str(uuid.uuid4())
        if operation != "detail":
            self._history_selection_token += 1
        token = self._history_selection_token
        self._history_request = (operation_id, token, operation, run_id)
        self._pending_history = None
        thread = _HistoryThread(
            operation_id, token, operation, str(self.app_data_root()), run_id,
            bool(confirm_parent), self.store_factory, self)
        thread.result_ready.connect(self._on_history_result)
        thread.failed.connect(self._on_history_failed)
        self._own_thread(thread, "history")
        thread.start()
        return operation_id

    def _on_history_result(self, operation_id, token, operation, payload):
        if self._thread_kind != "history":
            return
        self._pending_history = (operation_id, token, operation, payload, None)

    def _on_history_failed(self, operation_id, token, operation, message):
        if self._thread_kind != "history":
            return
        self._pending_history = (operation_id, token, operation, None,
                                 str(message))

    def _publish_history_terminal(self, terminal):
        if terminal is None:
            return
        operation_id, token, operation, payload, failure = terminal
        current = self._history_request
        if (current is None or current[0] != operation_id
                or current[1] != token or token != self._history_selection_token):
            return
        if failure:
            self.history_failed.emit(failure)
            return
        if isinstance(payload, dict) and payload.get("cancelled") is True:
            self.history_failed.emit(
                "History operation was cancelled after its worker acknowledged. Existing records and the current project are unchanged.")
            return
        if operation == "list":
            self.history_list_ready.emit(payload)
        elif operation == "detail":
            if current[3] == self._selected_history_id:
                self._verified_history_record = payload.get("record") if isinstance(payload, dict) else None
                self.history_detail_ready.emit(payload)
        elif operation == "delete":
            if (isinstance(payload, dict) and payload.get("deleted")
                    and self._selected_history_id == current[3]):
                self._selected_history_id = None
                self._verified_history_record = None
            self.history_deleted.emit(current[3] or "", payload)

    def _own_thread(self, thread: QThread, kind: str):
        self._thread = thread
        self._thread_kind = kind
        thread.finished.connect(self._on_thread_finished)
        self.busy_changed.emit(True)

    def _on_event(self, event):
        if self._thread_kind != "generation" or self._close_requested:
            return
        if getattr(event, "run_id", None) != self.active_run_id:
            return
        sequence = getattr(event, "sequence", None)
        if type(sequence) is not int or sequence <= self.last_sequence:
            return
        self.last_sequence = sequence
        self.active_stage = str(getattr(event, "stage", "working"))
        self.active_attempt = int(getattr(event, "attempt", 0))
        self.event_changed.emit(event)

    def _on_outcome(self, outcome):
        if self._thread_kind != "generation":
            return
        if getattr(outcome, "run_id", None) != self.active_run_id:
            return
        self._pending_outcome = outcome

    def cancel(self):
        if self._thread_kind == "generation" and self._cancellation is not None:
            if self._cancellation.cancel():
                self.cancellation_changed.emit(True)
                return True
            return False
        if self._thread_kind == "copy" and self._thread is not None:
            thread = self._thread
            thread.request_cancel()
            self._copy_cancelled = True
            self.cancellation_changed.emit(True)
            return True
        if self._thread_kind == "history" and self._thread is not None:
            self._thread.request_cancel()
            self.cancellation_changed.emit(True)
            return True
        return False

    def create_editor_copy(self):
        if self.busy or self._close_requested or self._last_outcome is None:
            return False
        if getattr(self._last_outcome, "status", None) != "completed":
            return False
        run_id = self.active_run_id
        if not run_id:
            return False
        return self._start_editor_copy(run_id)

    def restore_history_copy(self, run_id: str):
        """Make a guarded writable copy from one verified selected history run."""
        if self.busy or self._close_requested:
            return False
        try:
            canonical = str(uuid.UUID(run_id))
        except (ValueError, TypeError, AttributeError):
            return False
        if (canonical != run_id or run_id != self._selected_history_id
                or not isinstance(self._verified_history_record, dict)
                or self._verified_history_record.get("run_id") != run_id):
            return False
        return self._start_editor_copy(run_id)

    def _start_editor_copy(self, run_id: str):
        self._copy_cancelled = False
        self._pending_copy = None
        self._copy_failure_message = None
        self._deferred_terminal = None
        target = self.app_data_root() / "working-projects" / f"{run_id}-{uuid.uuid4().hex}"
        thread = _WorkingCopyThread(
            run_id, str(self.app_data_root()), str(target),
            self.store_factory, self.copier, self,
        )
        thread.copy_ready.connect(self._on_copy_ready)
        thread.copy_failed.connect(self._on_copy_failed)
        self._own_thread(thread, "copy")
        thread.start()
        return True

    def _on_copy_ready(self, project_path, history_available):
        if self._thread_kind == "copy":
            self._pending_copy = (project_path, bool(history_available))

    def _on_copy_failed(self, message):
        if self._thread_kind == "copy":
            self._pending_copy = (None, False)
            self._copy_failure_message = str(message)

    def request_shutdown(self):
        """Suppress result adoption and asynchronously quiesce owned work."""
        self._close_requested = True
        self._suppress_results = True
        if self._thread_kind == "generation" and self._cancellation is not None:
            self._cancellation.cancel()
            self.cancellation_changed.emit(True)
        elif self._thread_kind == "copy" and self._thread is not None:
            self._thread.request_cancel()
            self._copy_cancelled = True
            self.cancellation_changed.emit(True)
        elif self._thread_kind == "history" and self._thread is not None:
            self._thread.request_cancel()
            self.cancellation_changed.emit(True)
        elif not self.busy:
            self.lifecycle_quiescent.emit()

    def resume_after_close_cancelled(self):
        self._close_requested = False
        self._suppress_results = False
        if self.busy:
            return
        terminal = self._deferred_terminal
        self._deferred_terminal = None
        if terminal is None:
            return
        kind, payload = terminal
        if kind == "generation":
            if getattr(payload, "run_id", None) != self.active_run_id:
                return
            self._last_outcome = payload
            self.outcome_ready.emit(payload)
        elif kind == "copy_cancelled":
            # Never replay copy_ready after a deferred close: it immediately
            # triggers editor adoption. The checked result remains actionable.
            self._copy_cancelled = False
            self.copy_failed.emit(
                "Editor copy was cancelled. The current document is unchanged.")
        elif kind == "history":
            self._publish_history_terminal(payload)

    def _on_thread_finished(self):
        thread = self._thread
        kind = self._thread_kind
        if thread is None:
            return
        thread.wait(0)
        thread.deleteLater()
        self._thread = None
        self._thread_kind = None
        self.busy_changed.emit(False)
        self.cancellation_changed.emit(False)
        if kind == "generation":
            outcome = self._pending_outcome
            self._pending_outcome = None
            if (outcome is not None and
                    getattr(outcome, "run_id", None) == self.active_run_id):
                if self._close_requested or self._suppress_results:
                    self._deferred_terminal = ("generation", outcome)
                else:
                    self._last_outcome = outcome
                    self.outcome_ready.emit(outcome)
        elif kind == "copy":
            result = self._pending_copy
            self._pending_copy = None
            if self._close_requested or self._suppress_results:
                # request_shutdown always cancels a copy. Treat any copy result
                # queued just before shutdown as cancelled; never adopt it on
                # close-cancel resume.
                self._deferred_terminal = ("copy_cancelled", None)
            elif self._copy_cancelled:
                self.copy_failed.emit(
                    "Editor copy was cancelled. The current document is unchanged.")
            elif result and result[0]:
                self.copy_ready.emit(result[0], result[1])
            else:
                self.copy_failed.emit(self._copy_failure_message or
                    "The checked project copy could not be verified. The current document is unchanged.")
            self._copy_failure_message = None
        elif kind == "history":
            pending = self._pending_history
            self._pending_history = None
            if self._close_requested or self._suppress_results:
                self._deferred_terminal = ("history", pending)
            else:
                self._publish_history_terminal(pending)
        if self._close_requested:
            self.lifecycle_quiescent.emit()
