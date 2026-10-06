"""Parent-side worker lifecycle, deadlines, cancellation, and stale-run gate."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

from .contracts import (GenerationEvent, GenerationResult, GenerationStatus)
from .policy import PolicyRejected, authorize_recipe
from .storage import GenerationAttempt, GenerationStore, utc_now


DEFAULT_WORKER_DEADLINE_SECONDS = 20 * 60
_MAX_CONTROL_BYTES = 2 * 1024 * 1024
_MAX_EVENT_BYTES = 64 * 1024
_ABS_PATH = re.compile(r"(?<![A-Za-z0-9_.])(?:[A-Za-z]:[\\/]|/)(?:[^\\/\s:'\"]+[\\/])*[^\\/\s:'\"]+")


class GenerationRunner:
    """Run exactly one active generation worker for a desktop task.

    The process receives a minimal environment and fixed application entry
    point. Polling this object never blocks for worker execution.
    """

    def __init__(self, store: GenerationStore | None = None, *,
                 timeout_seconds: float = DEFAULT_WORKER_DEADLINE_SECONDS):
        if not isinstance(timeout_seconds, (int, float)) or not 0.05 <= timeout_seconds <= DEFAULT_WORKER_DEADLINE_SECONDS:
            raise ValueError("worker deadline must be between 0.05 seconds and 20 minutes")
        self.store = store or GenerationStore()
        self.timeout_seconds = float(timeout_seconds)
        self.latest_run_id: str | None = None
        self.last_result: GenerationResult | None = None
        self.current_status = GenerationStatus.PREPARING
        self._attempt: GenerationAttempt | None = None
        self._process: subprocess.Popen | None = None
        self._recipe_json = ""
        self._started_monotonic = 0.0
        self._termination_status: GenerationStatus | None = None
        self._termination_time = 0.0
        self._event_offset = 0
        self._events: list[GenerationEvent] = []
        self._result_delivered = True

    @property
    def running(self) -> bool:
        return self._process is not None

    @property
    def cancelling(self) -> bool:
        return self._termination_status is not None

    def start(self, recipe_input) -> str:
        if self.running:
            raise RuntimeError("a generation worker is already running")
        self._events = []
        self.last_result = None
        self._result_delivered = False
        attempt = self.store.new_attempt()
        self._attempt = attempt
        self.latest_run_id = attempt.run_id
        self._started_monotonic = time.monotonic()
        self._termination_status = None
        self._event_offset = 0
        self._append_event(GenerationStatus.PREPARING, "Preparing local generation")
        self._append_event(GenerationStatus.VALIDATING, "Applying strict AI recipe policy")
        try:
            self._recipe_json = _recipe_text(recipe_input)
        except Exception as exc:
            self._recipe_json = "{}"
            result = GenerationResult(
                attempt.run_id, GenerationStatus.FAILED,
                error_records=({"code": "invalid_recipe_input", "stage": "policy",
                                "path": "recipe",
                                "message": f"Recipe input could not be serialized ({type(exc).__name__})."},))
            self._complete_failure(result)
            return attempt.run_id
        try:
            decision = authorize_recipe(self._recipe_json, attempt.output_root)
        except PolicyRejected as exc:
            result = GenerationResult(
                attempt.run_id, GenerationStatus.FAILED,
                error_records=tuple({"code": _bounded(item.code, 80),
                                     "stage": _bounded(item.stage, 40),
                                     "path": _bounded(item.path, 200),
                                     "message": _bounded(item.message, 600),
                                     **({"hint": _bounded(item.hint, 600)} if item.hint else {})}
                                    for item in exc.errors),
                elapsed_seconds=max(0.0, time.monotonic() - self._started_monotonic))
            self._complete_failure(result)
            return attempt.run_id
        except Exception as exc:
            result = GenerationResult(
                attempt.run_id, GenerationStatus.FAILED,
                error_records=({"code": "policy_failure", "stage": "policy",
                                "path": "recipe",
                                "message": f"Recipe could not be checked ({type(exc).__name__})."},),
                elapsed_seconds=max(0.0, time.monotonic() - self._started_monotonic))
            self._complete_failure(result)
            return attempt.run_id

        self._recipe_json = decision.recipe_json
        try:
            self.store.write_request(attempt, decision.recipe_json)
            self._append_event(GenerationStatus.STARTING_WORKER,
                               "Starting isolated recipe worker")
            self._process = subprocess.Popen(
                self._command(attempt), cwd=self._repo_root(),
                env=self._worker_environment(), stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                close_fds=True, **self._process_group_options())
        except Exception as exc:
            result = GenerationResult(
                attempt.run_id, GenerationStatus.FAILED,
                error_records=({"code": "worker_start_failed", "stage": "worker",
                                "path": "worker",
                                "message": f"Worker could not start ({type(exc).__name__})."},),
                elapsed_seconds=max(0.0, time.monotonic() - self._started_monotonic))
            self._complete_failure(result)
        return attempt.run_id

    def poll(self) -> GenerationResult | None:
        attempt = self._attempt
        if attempt is None or self._process is None:
            if self.last_result is not None and not self._result_delivered:
                self._result_delivered = True
                return self.last_result
            return None
        self._read_events(attempt)
        now = time.monotonic()
        if self._termination_status is None and now - self._started_monotonic >= self.timeout_seconds:
            self._terminate(GenerationStatus.TIMED_OUT)
        if self._termination_status is not None and self._process.poll() is None:
            # Popen.terminate is immediate on Windows and cooperative on POSIX;
            # kill is the bounded fallback if the child ignores it.
            if now - self._termination_time >= 1.0:
                try:
                    self._process.kill()
                except OSError:
                    pass
            return None
        returncode = self._process.poll()
        if returncode is None:
            return None

        if self._termination_status is not None:
            status = self._termination_status
            code, message = (("generation_cancelled", "Generation was cancelled.")
                             if status is GenerationStatus.CANCELLED else
                             ("generation_timed_out", "Generation exceeded its time limit."))
            result = GenerationResult(
                attempt.run_id, status,
                error_records=({"code": code, "stage": "worker", "path": "worker",
                                "message": message},),
                elapsed_seconds=max(0.0, now - self._started_monotonic))
            self._complete_failure(result)
            return self._deliver_result()

        raw_result = self._read_result(attempt)
        if raw_result is None:
            result = self._failure(attempt.run_id, "worker_crash",
                                   "Worker exited without a valid structured result.")
            self._complete_failure(result)
            return self._deliver_result()
        try:
            result = GenerationResult.from_json(raw_result)
        except Exception:
            result = self._failure(attempt.run_id, "malformed_worker_response",
                                   "Worker returned a malformed structured result.")
            self._complete_failure(result)
            return self._deliver_result()
        if result.run_id != attempt.run_id or result.run_id != self.latest_run_id:
            result = self._failure(attempt.run_id, "stale_worker_result",
                                   "Worker result identity did not match the active run.")
            self._complete_failure(result)
            return self._deliver_result()
        if (result.status is GenerationStatus.COMPLETE and returncode != 0) or (
                result.status is not GenerationStatus.COMPLETE and returncode == 0):
            result = self._failure(attempt.run_id, "worker_exit_mismatch",
                                   "Worker exit status disagreed with its result record.")
            self._complete_failure(result)
            return self._deliver_result()
        if result.status is GenerationStatus.COMPLETE:
            if not self.is_current(attempt.run_id):
                result = self._failure(attempt.run_id, "stale_generation",
                                       "A superseded run cannot be published.")
                self._complete_failure(result)
                return self._deliver_result()
            try:
                result = self.store.publish_success(attempt, result,
                                                    self._recipe_json, utc_now())
                self._attempt = None
                self._process = None
                self._set_final(result)
            except Exception as exc:
                failed = self._failure(attempt.run_id, "publication_failed",
                                       f"Generation snapshot could not be published ({type(exc).__name__}).",
                                       stage="publication")
                self._complete_failure(failed)
        else:
            self._complete_failure(result)
        return self._deliver_result()

    def cancel(self) -> bool:
        if self._process is None:
            return False
        self._terminate(GenerationStatus.CANCELLED)
        return True

    def drain_events(self) -> list[GenerationEvent]:
        events, self._events = self._events, []
        return events

    def is_current(self, run_id: str) -> bool:
        return run_id == self.latest_run_id

    def create_writable_project_copy(self, run_id: str) -> Path:
        if (not self.is_current(run_id) or self.last_result is None or
                self.last_result.run_id != run_id or not self.last_result.ok):
            raise ValueError("only the latest successful generation may be opened")
        return self.store.create_writable_project_copy(run_id)

    def _deliver_result(self) -> GenerationResult | None:
        if self.last_result is None or self._result_delivered:
            return None
        self._result_delivered = True
        return self.last_result

    def _set_final(self, result: GenerationResult) -> None:
        self.last_result = result
        self.current_status = result.status
        self._append_event(result.status, "Generation complete" if result.ok else "Generation failed")

    def _append_event(self, stage: GenerationStatus, message: str) -> None:
        run_id = self.latest_run_id
        if run_id is None:
            return
        self.current_status = stage
        self._events.append(GenerationEvent(
            run_id, stage, max(0.0, time.monotonic() - self._started_monotonic),
            message[:240]))

    def _complete_failure(self, result: GenerationResult) -> None:
        attempt = self._attempt
        self._process = None
        if attempt is not None:
            try:
                result = self.store.publish_failure(attempt, result,
                                                    self._recipe_json, utc_now())
            except Exception as exc:
                self.store.cleanup_attempt(attempt)
                if not result.error_records:
                    result = self._failure(attempt.run_id, "failure_record_failed",
                                           f"Failure details could not be recorded ({type(exc).__name__}).",
                                           stage="publication")
            self._attempt = None
        self._set_final(result)

    def _failure(self, run_id: str, code: str, message: str,
                 stage: str = "worker") -> GenerationResult:
        return GenerationResult(
            run_id, GenerationStatus.FAILED,
            error_records=({"code": code, "stage": stage, "path": "worker",
                            "message": message},),
            elapsed_seconds=max(0.0, time.monotonic() - self._started_monotonic))

    def _terminate(self, status: GenerationStatus) -> None:
        if self._termination_status is not None or self._process is None:
            return
        self._termination_status = status
        self._termination_time = time.monotonic()
        self.current_status = status
        try:
            if self._process.poll() is None:
                self._process.terminate()
        except OSError:
            try:
                self._process.kill()
            except OSError:
                pass

    def _read_events(self, attempt: GenerationAttempt) -> None:
        try:
            size = attempt.events_path.stat().st_size
            if size > _MAX_EVENT_BYTES:
                return
            with attempt.events_path.open("rb") as fh:
                fh.seek(self._event_offset)
                data = fh.read()
                self._event_offset += len(data)
        except FileNotFoundError:
            return
        for line in data.splitlines():
            try:
                event = GenerationEvent.from_dict(json.loads(line))
            except Exception:
                continue
            if event.run_id != attempt.run_id:
                continue
            self.current_status = event.stage
            self._events.append(event)

    @staticmethod
    def _read_result(attempt: GenerationAttempt) -> bytes | None:
        try:
            if attempt.result_path.stat().st_size > _MAX_CONTROL_BYTES:
                return None
            return attempt.result_path.read_bytes()
        except OSError:
            return None

    @staticmethod
    def _repo_root() -> str:
        return str(Path(__file__).resolve().parents[2])

    @staticmethod
    def _command(attempt: GenerationAttempt) -> list[str]:
        args = ["--request", str(attempt.request_path),
                "--events", str(attempt.events_path),
                "--result", str(attempt.result_path)]
        if getattr(sys, "frozen", False):
            return [sys.executable, "--am3d-generation-worker", *args]
        return [sys.executable, "-m", "am3d.ai.worker", *args]

    @staticmethod
    def _worker_environment() -> dict[str, str]:
        # In particular, do not inherit arbitrary API/login/credential env vars
        # into the worker process. Only runtime and temporary-directory
        # variables needed to import/run the fixed application entry point pass.
        allowed = {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "TMPDIR",
                   "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"}
        env = {key: value for key, value in os.environ.items() if key in allowed}
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    @staticmethod
    def _process_group_options() -> dict:
        if os.name == "nt":
            return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
        return {"start_new_session": True}


def _recipe_text(value) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                      allow_nan=False)


def _bounded(value, limit: int) -> str:
    return _ABS_PATH.sub("<path>", str(value))[:limit]
