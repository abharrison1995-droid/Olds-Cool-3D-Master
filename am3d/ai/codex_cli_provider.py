"""Bounded subscription-backed Codex CLI provider.

The CLI is used only to propose the accepted M3.1 response envelope.  Model
tools are disabled, the remaining sandbox is read-only, and all output is
treated as untrusted bytes by the existing provider parser.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import threading
import time
from typing import Any

from .prompt import MAX_PROMPT_BYTES
from .provider_contracts import (FailureCode, MAX_PROVIDER_RESPONSE_BYTES,
                                 provider_response_schema)
from .providers import (AdapterKind, ProviderCallStatus, ProviderRequest,
                        ProviderResult, UsageMetadata)


DEFAULT_CODEX_DEADLINE_SECONDS = 10 * 60
MAX_EVENT_STREAM_BYTES = 1024 * 1024
MAX_DIAGNOSTIC_BYTES = 64 * 1024
_CAPABILITY_TIMEOUT_SECONDS = 5.0
_MODEL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,119}$")
_EVENT_KIND_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")

# These feature identifiers were checked against the installed Codex CLI's
# `features list`; each becomes a host-owned `--disable FEATURE` argv pair.
# The read-only sandbox and never-approve policy remain in force as defense in
# depth if a future CLI adds another local tool behind one of these switches.
DISABLED_TOOL_FEATURES = (
    "apps",
    "auth_elicitation",
    "browser_use",
    "browser_use_external",
    "browser_use_full_cdp_access",
    "code_mode",
    "computer_use",
    "image_generation",
    "in_app_browser",
    "in_app_local_automation",
    "memories",
    "multi_agent",
    "multi_agent_v2",
    "hooks",
    "plugin_sharing",
    "plugins",
    "remote_plugin",
    "shell_snapshot",
    "shell_snapshot_v2",
    "shell_tool",
    "skill_mcp_dependency_install",
    "skill_search",
    "tool_search",
    "tool_call_mcp_elicitation",
    "tool_suggest",
    "realtime_conversation",
    "view_image",
    "workspace_dependencies",
    "worktrees",
)

_REQUIRED_ROOT_HELP = ("--ask-for-approval",)
_REQUIRED_EXEC_HELP = (
    "--model", "--sandbox", "--cd",
    "--skip-git-repo-check", "--ephemeral", "--ignore-user-config",
    "--ignore-rules", "--output-schema", "--output-last-message",
    "--json", "--color", "--disable", "stdin",
)

_ENV_ALLOWLIST = frozenset({
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL",
    "LC_CTYPE", "XDG_RUNTIME_DIR", "CODEX_HOME", "TMPDIR", "TEMP", "TMP",
    "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE",
    "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "SSL_CERT_FILE",
    "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
})


@dataclass(frozen=True)
class CodexCliConfig:
    """Host-only Codex settings; none are derived from model output."""

    executable: str | None = None
    model: str | None = None
    deadline_seconds: float = DEFAULT_CODEX_DEADLINE_SECONDS

    def __post_init__(self):
        if self.model is not None and (
                not isinstance(self.model, str) or
                not _MODEL_ID_RE.fullmatch(self.model)):
            raise ValueError("Codex model must be a bounded host-selected identifier")
        if (isinstance(self.deadline_seconds, bool) or
                not isinstance(self.deadline_seconds, (int, float)) or
                not math.isfinite(self.deadline_seconds) or
                not 0.1 <= self.deadline_seconds <= DEFAULT_CODEX_DEADLINE_SECONDS):
            raise ValueError("Codex deadline must be between 0.1 seconds and 10 minutes")
        if self.executable is not None and (
                not isinstance(self.executable, str) or not self.executable.strip()):
            raise ValueError("Codex executable must be a host-selected path")


class _BoundedPipeReader(threading.Thread):
    """Drain a child pipe continuously while retaining only a fixed prefix."""

    def __init__(self, stream, limit: int, *, terminate_on_overflow: bool):
        super().__init__(daemon=True)
        self.stream = stream
        self.limit = limit
        self.terminate_on_overflow = terminate_on_overflow
        self.data = bytearray()
        self.overflowed = threading.Event()
        self.truncated = False

    def run(self):
        try:
            while True:
                chunk = self.stream.read(8192)
                if not chunk:
                    return
                room = self.limit - len(self.data)
                if room > 0:
                    self.data.extend(chunk[:room])
                if len(chunk) > max(0, room):
                    self.truncated = True
                    if self.terminate_on_overflow:
                        self.overflowed.set()
        except (OSError, ValueError):
            return
        finally:
            try:
                self.stream.close()
            except OSError:
                pass


class CodexCliProvider:
    """A single `codex exec` provider using the user's existing ChatGPT login.

    `argv_prefix_for_tests` is a private subprocess-harness seam. Production
    configuration consists only of a resolved executable and optional model.
    """

    provider_id = "openai/codex"
    adapter_kind = AdapterKind.AGENT_CLI

    def __init__(self, config: CodexCliConfig | None = None, *,
                 argv_prefix_for_tests: tuple[str, ...] = ()):
        self.config = config or CodexCliConfig()
        self._argv_prefix_for_tests = tuple(argv_prefix_for_tests)
        self.executable: str | None = None
        self.version: str | None = None
        self._setup_failure: FailureCode | None = None
        self._setup_message = ""
        self._state_lock = threading.Lock()
        self._active_process: subprocess.Popen | None = None
        self._call_active = False
        self._cancel_requested = threading.Event()
        self.last_event_kinds: tuple[str, ...] = ()
        self.last_workspace_entries: tuple[str, ...] = ()
        self._verify_local_cli()

    @property
    def model_id(self) -> str:
        return self.config.model or "unknown"

    @property
    def ready(self) -> bool:
        return self._setup_failure is None

    def _verify_local_cli(self):
        candidate = self.config.executable or shutil.which("codex")
        if not candidate:
            self._setup_failure = FailureCode.UNAVAILABLE_PROVIDER
            self._setup_message = "Codex CLI executable was not found."
            return
        try:
            resolved = str(Path(candidate).expanduser().resolve(strict=True))
            if not Path(resolved).is_file():
                raise OSError("not a file")
        except (OSError, RuntimeError):
            self._setup_failure = FailureCode.UNAVAILABLE_PROVIDER
            self._setup_message = "Codex CLI executable is unavailable."
            return
        self.executable = resolved
        env = self._base_environment()

        version = self._probe([resolved, "--version"], env)
        if version is None:
            self._setup_failure = FailureCode.UNSUPPORTED_ADAPTER
            self._setup_message = "Installed Codex CLI version could not be verified."
            return
        version_text = version[0].decode("utf-8", "replace").strip().splitlines()
        if not version_text or not version_text[0].startswith("codex-cli "):
            self._setup_failure = FailureCode.UNSUPPORTED_ADAPTER
            self._setup_message = "Installed executable is not a supported Codex CLI."
            return
        self.version = version_text[0][len("codex-cli "):][:80]

        root_help = self._probe(
            [resolved, "--help"], env)
        if (root_help is None or root_help[2] != 0 or
                any(option not in root_help[0].decode("utf-8", "replace")
                    for option in _REQUIRED_ROOT_HELP)):
            self._setup_failure = FailureCode.UNSUPPORTED_ADAPTER
            self._setup_message = "Codex CLI lacks a noninteractive approval policy option."
            return

        help_result = self._probe(
            [resolved, "exec", "--help"], env)
        if help_result is None:
            self._setup_failure = FailureCode.UNSUPPORTED_ADAPTER
            self._setup_message = "Codex CLI exec capabilities could not be verified."
            return
        help_text = help_result[0].decode("utf-8", "replace")
        if any(option not in help_text for option in _REQUIRED_EXEC_HELP):
            self._setup_failure = FailureCode.UNSUPPORTED_ADAPTER
            self._setup_message = "Installed Codex CLI lacks required safe exec options."
            return

        # The local status command reports auth *type*, not credential data.
        # Requiring this explicit status prevents a stored API-key login from
        # silently turning the subscription adapter into a paid API adapter.
        auth_status = self._probe([resolved, "login", "status"], env)
        if auth_status is None:
            self._setup_failure = FailureCode.AUTHENTICATION_FAILURE
            self._setup_message = "Codex CLI subscription login could not be verified."
            return
        auth_text = (auth_status[0] + b"\n" + auth_status[1]).decode(
            "utf-8", "replace").strip().lower()
        if auth_status[2] != 0 or "logged in using chatgpt" not in auth_text:
            self._setup_failure = FailureCode.AUTHENTICATION_FAILURE
            self._setup_message = "Codex CLI is not authenticated with a ChatGPT login."
            return

        # Verify that the installed feature registry recognizes each required
        # tool-disable switch.  The generation request repeats these switches;
        # this local probe does not contact a model.
        feature_argv = [resolved]
        for feature in DISABLED_TOOL_FEATURES:
            feature_argv.extend(("--disable", feature))
        feature_argv.extend(("features", "list"))
        feature_result = self._probe(feature_argv, env)
        if feature_result is None or feature_result[2] != 0:
            self._setup_failure = FailureCode.UNSUPPORTED_ADAPTER
            self._setup_message = "Codex CLI tool-isolation flags could not be verified."
            return
        feature_text = feature_result[0].decode("utf-8", "replace")
        states = {}
        for line in feature_text.splitlines():
            parts = line.split()
            if len(parts) >= 3:
                states[parts[0]] = parts[-1].lower()
        if any(states.get(feature) != "false" for feature in DISABLED_TOOL_FEATURES):
            self._setup_failure = FailureCode.UNSUPPORTED_ADAPTER
            self._setup_message = "Codex CLI cannot disable every configured model tool."
            return

    def _probe(self, argv: list[str], env: dict[str, str]):
        try:
            completed = subprocess.run(
                self._command(argv), cwd=tempfile.gettempdir(), env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                close_fds=True, timeout=_CAPABILITY_TIMEOUT_SECONDS, check=False)
        except (OSError, subprocess.TimeoutExpired):
            return None
        if (len(completed.stdout) > MAX_DIAGNOSTIC_BYTES or
                len(completed.stderr) > MAX_DIAGNOSTIC_BYTES):
            return None
        return completed.stdout, completed.stderr, completed.returncode

    def _test_prefix(self) -> list[str]:
        return list(self._argv_prefix_for_tests)

    def _command(self, argv: list[str]) -> list[str]:
        if not self._argv_prefix_for_tests:
            return argv
        return [argv[0], *self._test_prefix(), *argv[1:]]

    def _environment(self, temporary_root: Path) -> dict[str, str]:
        env = self._base_environment()
        scratch = temporary_root / "tmp"
        scratch.mkdir(mode=0o700, exist_ok=True)
        for key in ("TMPDIR", "TEMP", "TMP"):
            env[key] = str(scratch)
        return env

    @staticmethod
    def _base_environment() -> dict[str, str]:
        # Inherit the CLI's normal user identity/home so it can use its own
        # subscription login, but do not pass arbitrary API/cloud/service
        # secrets or proxy credentials into the subprocess.
        env = {key: value for key, value in os.environ.items()
               if key in _ENV_ALLOWLIST and "\x00" not in value}
        env["PYTHONNOUSERSITE"] = "1"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return env

    def _argv(self, request: ProviderRequest, workspace: Path,
              schema_path: Path, result_path: Path) -> list[str]:
        if self.executable is None:
            raise RuntimeError("Codex executable is not resolved")
        # This release defines --ask-for-approval at the root parser, so it
        # must precede the `exec` subcommand.  The supported placement was
        # verified with the installed binary's root and exec help.
        argv = [self.executable, "--ask-for-approval", "never", "exec"]
        if self.config.model is not None:
            argv.extend(("--model", self.config.model))
        argv.extend((
            "--sandbox", "read-only",
            "--cd", str(workspace),
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--output-schema", str(schema_path),
            "--output-last-message", str(result_path),
            "--json",
            "--color", "never",
        ))
        for feature in DISABLED_TOOL_FEATURES:
            argv.extend(("--disable", feature))
        argv.append("-")
        return argv

    def generate(self, request: ProviderRequest) -> ProviderResult:
        started = time.monotonic()
        process = None
        self.last_event_kinds = ()
        self.last_workspace_entries = ()
        if self._setup_failure is not None:
            return self._failure(self._setup_failure, 0.0, "setup_failed")
        if not isinstance(request, ProviderRequest):
            return self._failure(FailureCode.UNSUPPORTED_ADAPTER, 0.0,
                                 "invalid_provider_request")
        if request.response_schema != provider_response_schema():
            return self._failure(FailureCode.UNSUPPORTED_ADAPTER, 0.0,
                                 "unexpected_response_schema")
        try:
            prompt = (request.system_prompt + "\n\n" + request.user_prompt).encode(
                "utf-8", errors="strict")
        except (UnicodeEncodeError, TypeError):
            return self._failure(FailureCode.INVALID_BRIEF, 0.0,
                                 "invalid_prompt_text")
        if len(prompt) > MAX_PROMPT_BYTES:
            return self._failure(FailureCode.PROMPT_TOO_LARGE, 0.0,
                                 "prompt_too_large")
        if request.max_response_bytes != MAX_PROVIDER_RESPONSE_BYTES:
            return self._failure(FailureCode.UNSUPPORTED_ADAPTER, 0.0,
                                 "unexpected_response_limit")
        with self._state_lock:
            if self._call_active:
                return self._failure(FailureCode.UNAVAILABLE_PROVIDER, 0.0,
                                     "provider_busy")
            self._call_active = True
            cancelled_before_launch = self._cancel_requested.is_set()
        if cancelled_before_launch:
            self._finish_call()
            return self._failure(FailureCode.CANCELLED, 0.0, "cancelled")

        try:
            with tempfile.TemporaryDirectory(prefix="am3d-codex-") as raw_workspace:
                workspace = Path(raw_workspace)
                try:
                    workspace.chmod(0o700)
                except OSError:
                    pass
                scratch = workspace / "tmp"
                scratch.mkdir(mode=0o700)
                schema_path = workspace / "response.schema.json"
                result_path = workspace / "final-response.json"
                schema_path.write_text(
                    json.dumps(provider_response_schema(), ensure_ascii=False,
                               separators=(",", ":")),
                    encoding="utf-8")
                if self._cancel_requested.is_set():
                    return self._failure(FailureCode.CANCELLED,
                                         time.monotonic() - started, "cancelled")
                env = self._environment(workspace)
                argv = self._argv(request, workspace, schema_path, result_path)
                try:
                    process = subprocess.Popen(
                        self._command(argv), cwd=workspace, env=env,
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, shell=False, close_fds=True,
                        **_process_group_options())
                except FileNotFoundError:
                    return self._failure(FailureCode.UNAVAILABLE_PROVIDER,
                                         time.monotonic() - started,
                                         "executable_not_found")
                except OSError:
                    return self._failure(FailureCode.UNAVAILABLE_PROVIDER,
                                         time.monotonic() - started,
                                         "process_start_failed")
                with self._state_lock:
                    self._active_process = process

                stdout = _BoundedPipeReader(
                    process.stdout, MAX_EVENT_STREAM_BYTES,
                    terminate_on_overflow=True)
                stderr = _BoundedPipeReader(
                    process.stderr, MAX_DIAGNOSTIC_BYTES,
                    terminate_on_overflow=False)
                stdout.start()
                stderr.start()
                writer = threading.Thread(
                    target=_write_prompt, args=(process.stdin, prompt), daemon=True)
                writer.start()
                deadline = min(float(request.deadline_seconds),
                               float(self.config.deadline_seconds))
                terminal: FailureCode | None = None
                while process.poll() is None:
                    if self._cancel_requested.is_set():
                        terminal = FailureCode.CANCELLED
                        _terminate_process_tree(process)
                        break
                    if stdout.overflowed.is_set():
                        terminal = FailureCode.RESPONSE_TOO_LARGE
                        _terminate_process_tree(process)
                        break
                    if time.monotonic() - started >= deadline:
                        terminal = FailureCode.TIMEOUT
                        _terminate_process_tree(process)
                        break
                    time.sleep(0.02)
                try:
                    process.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    _force_kill_process_tree(process)
                    try:
                        process.wait(timeout=2.0)
                    except subprocess.TimeoutExpired:
                        pass
                writer.join(timeout=1.0)
                stdout.join(timeout=1.0)
                stderr.join(timeout=1.0)
                with self._state_lock:
                    self._active_process = None

                latency = time.monotonic() - started
                if terminal is not None:
                    return self._failure(terminal, latency,
                                         "cancelled" if terminal is FailureCode.CANCELLED else
                                         "deadline_expired" if terminal is FailureCode.TIMEOUT else
                                         "event_stream_limit")
                returncode = process.returncode
                events = bytes(stdout.data)
                model_id, usage, event_failure, event_kinds = _event_metadata(
                    events, self.config.model)
                self.last_event_kinds = event_kinds
                if returncode != 0:
                    code = event_failure or _classify_diagnostic_failure(
                        bytes(stderr.data)) or FailureCode.NONZERO_EXIT
                    return self._failure(
                        code, latency, "process_exit_nonzero", usage=usage,
                        model_id=model_id,
                        transport_code=(returncode if -(2**31) <= returncode < 2**31
                                        else None))
                self.last_workspace_entries = tuple(sorted(
                    child.name for child in workspace.iterdir()))
                allowed_entries = {
                    "tmp", "response.schema.json", "final-response.json"}
                if any(name not in allowed_entries
                       for name in self.last_workspace_entries):
                    return self._failure(
                        FailureCode.TRANSPORT_FAILURE, latency,
                        "unexpected_workspace_artifact", usage=usage,
                        model_id=model_id)
                if not result_path.is_file() or result_path.is_symlink():
                    return self._failure(
                        event_failure or FailureCode.INVALID_STRUCTURED_RESPONSE,
                        latency, "final_response_missing", usage=usage,
                        model_id=model_id)
                try:
                    with result_path.open("rb") as stream:
                        response_bytes = stream.read(MAX_PROVIDER_RESPONSE_BYTES + 1)
                except OSError:
                    return self._failure(
                        FailureCode.INVALID_STRUCTURED_RESPONSE, latency,
                        "final_response_unreadable", usage=usage,
                        model_id=model_id)
                if len(response_bytes) > MAX_PROVIDER_RESPONSE_BYTES:
                    return self._failure(
                        FailureCode.RESPONSE_TOO_LARGE, latency,
                        "final_response_limit", usage=usage,
                        model_id=model_id)
                return ProviderResult(
                    provider_id=self.provider_id,
                    model_id=model_id or self.model_id,
                    adapter_kind=self.adapter_kind,
                    status=ProviderCallStatus.SUCCEEDED,
                    response_bytes=response_bytes,
                    latency_ms=latency * 1000,
                    usage=usage,
                    transport_status="response_received")
        except Exception:
            # Never surface exception text: paths/environment details are not
            # suitable provider diagnostics.
            if process is not None and process.poll() is None:
                _terminate_process_tree(process)
            return self._failure(FailureCode.TRANSPORT_FAILURE,
                                 time.monotonic() - started,
                                 "provider_process_error")
        finally:
            with self._state_lock:
                self._active_process = None
            self._finish_call()

    def cancel(self) -> bool:
        """Request cancellation of the active Codex process tree."""
        with self._state_lock:
            if not self._call_active:
                return False
            self._cancel_requested.set()
            return True

    def _finish_call(self):
        with self._state_lock:
            self._active_process = None
            self._call_active = False
            self._cancel_requested.clear()

    def _failure(self, code: FailureCode, latency_seconds: float,
                 transport_status: str, *,
                 usage: UsageMetadata | None = None,
                 model_id: str | None = None,
                 transport_code: int | None = None) -> ProviderResult:
        return ProviderResult(
            provider_id=self.provider_id,
            model_id=model_id or self.model_id,
            adapter_kind=self.adapter_kind,
            status=ProviderCallStatus.FAILED,
            latency_ms=max(0.0, latency_seconds * 1000),
            usage=usage or UsageMetadata(),
            failure_code=code,
            quota_or_rate_limited=(True if code is FailureCode.QUOTA_RATE_LIMIT
                                   else None),
            transport_status=transport_status,
            transport_code=transport_code)


def _write_prompt(stream, prompt: bytes):
    try:
        stream.write(prompt)
        stream.flush()
    except (BrokenPipeError, OSError, ValueError):
        pass
    finally:
        try:
            stream.close()
        except OSError:
            pass


def _process_group_options() -> dict[str, Any]:
    if os.name == "nt":
        return {"creationflags": getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)}
    return {"start_new_session": True}


def _terminate_process_tree(process: subprocess.Popen):
    if os.name == "nt":
        try:
            if process.poll() is None:
                process.send_signal(getattr(signal, "CTRL_BREAK_EVENT", signal.SIGTERM))
        except OSError:
            pass
        try:
            process.wait(timeout=0.25)
        except subprocess.TimeoutExpired:
            pass
        # Ask Windows to terminate descendants even if the parent exited after
        # CTRL_BREAK but left a child running in its process tree.
        _force_kill_process_tree(process)
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        try:
            process.terminate()
        except OSError:
            pass
    try:
        process.wait(timeout=0.25)
    except subprocess.TimeoutExpired:
        pass
    # A parent can exit on SIGTERM while a descendant ignores it. Kill the
    # process group even when Popen.poll() already reports the parent gone.
    _force_kill_process_tree(process)


def _force_kill_process_tree(process: subprocess.Popen):
    if os.name == "nt":
        taskkill = shutil.which("taskkill")
        if taskkill:
            try:
                subprocess.run(
                    [taskkill, "/PID", str(process.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env={key: value for key, value in os.environ.items()
                         if key in _ENV_ALLOWLIST},
                    shell=False, close_fds=True,
                    timeout=5, check=False)
            except (OSError, subprocess.TimeoutExpired):
                pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def _event_metadata(raw: bytes, requested_model: str | None
                    ) -> tuple[str | None, UsageMetadata, FailureCode | None,
                               tuple[str, ...]]:
    model = requested_model
    usage = UsageMetadata()
    failure = None
    kinds: list[str] = []
    for raw_line in raw.splitlines():
        if not raw_line or len(raw_line) > MAX_DIAGNOSTIC_BYTES:
            continue
        try:
            event = json.loads(raw_line)
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if isinstance(kind, str) and _EVENT_KIND_RE.fullmatch(kind):
            kinds.append(kind)
        item = event.get("item")
        if isinstance(item, dict):
            item_kind = item.get("type")
            if isinstance(item_kind, str) and _EVENT_KIND_RE.fullmatch(item_kind):
                kinds.append("item:" + item_kind)
        if kind in {"turn.started", "model.selected", "thread.started"}:
            reported = event.get("model")
            if isinstance(reported, str) and _MODEL_ID_RE.fullmatch(reported):
                model = reported
        if kind == "turn.completed":
            value = event.get("usage")
            if not isinstance(value, dict):
                turn = event.get("turn")
                value = turn.get("usage") if isinstance(turn, dict) else None
            if isinstance(value, dict):
                try:
                    usage = UsageMetadata(
                        input_tokens=_nullable_counter(value.get("input_tokens")),
                        output_tokens=_nullable_counter(value.get("output_tokens")),
                        total_tokens=_nullable_counter(value.get("total_tokens")))
                except ValueError:
                    usage = UsageMetadata()
        if kind in {"turn.failed", "response.failed", "error"}:
            detail = event.get("error")
            if not isinstance(detail, dict):
                detail = event
            code = detail.get("code") or detail.get("type") or detail.get("codex_error_info")
            if isinstance(code, str):
                failure = _failure_from_code(code)
    return model, usage, failure, tuple(kinds[:256])


def _nullable_counter(value) -> int | None:
    if value is None:
        return None
    if type(value) is int and value >= 0:
        return value
    raise ValueError("invalid provider token count")


def _failure_from_code(value: str) -> FailureCode | None:
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"auth", "authentication", "authentication_required",
                      "authentication_error", "unauthorized", "invalid_api_key",
                      "login_required"}:
        return FailureCode.AUTHENTICATION_FAILURE
    if normalized in {"quota", "rate_limit", "rate_limit_exceeded",
                      "quota_exceeded", "insufficient_quota"}:
        return FailureCode.QUOTA_RATE_LIMIT
    if normalized in {"refusal", "refused", "safety_refusal"}:
        return FailureCode.REFUSAL
    if normalized in {"timeout", "deadline_exceeded"}:
        return FailureCode.TIMEOUT
    if normalized in {"transport", "connection_error", "network_error"}:
        return FailureCode.TRANSPORT_FAILURE
    return None


def _classify_diagnostic_failure(diagnostics: bytes) -> FailureCode | None:
    # Use only coarse, bounded phrases for common CLI errors. Unknown text is
    # never copied into a user-facing result or record.
    sample = diagnostics.decode("utf-8", "ignore").lower()
    if any(term in sample for term in (
            "not logged in", "login required", "authentication required",
            "unauthorized", "invalid api key")):
        return FailureCode.AUTHENTICATION_FAILURE
    if any(term in sample for term in (
            "rate limit", "rate_limit", "quota exceeded", "insufficient_quota")):
        return FailureCode.QUOTA_RATE_LIMIT
    if "refusal" in sample or "content_filter" in sample:
        return FailureCode.REFUSAL
    return None
