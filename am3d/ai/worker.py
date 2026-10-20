"""Fixed child-process recipe worker for AI policy execution.

The process boundary protects lifecycle and resource budgets for untrusted
data-only recipes. It is deliberately not described as an OS sandbox.
"""

from __future__ import annotations

import ctypes
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
from typing import Any

from .contracts import CancellationToken, MAX_CANCEL_ACK_SECONDS
from .policy import (
    MAX_OUTPUT_BYTES,
    MAX_RECIPE_BYTES,
    MAX_WORKER_SECONDS,
    PolicyError,
    RecipeValidationError,
    _check_data_tree,
    prepare_recipe,
)
from am3d.core.paths import extended_io_path


_PROTOCOL_VERSION = 1
_MAX_RESULT_BYTES = 1024 * 1024
_MAX_CHECK_REPORT_BYTES = 256 * 1024
_MAX_CHECK_OPTIONS_BYTES = 256 * 1024
_PROTOCOL_OVERHEAD = 2 * 1024 * 1024
_MAX_INPUT_BYTES = 1024 * 1024
_MEMORY_LIMIT = 1024 * 1024 * 1024
_ALLOWED_OUTPUT_SUFFIXES = {".am3d", ".obj", ".glb", ".mtl", ".png"}
_SERIALIZER_TEMP_RE = re.compile(r"\.am3d_tmp_[a-z0-9_]{8}\Z")
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _result(status: str, *, error: dict | None = None,
            manifest: list[dict] | None = None, attempt_id: str | None = None,
            counts: dict | None = None, output_bytes: int | None = None,
            check_report: dict | None = None,
            checks_status: str = "not_run",
            error_records: list[dict] | None = None) -> dict:
    return {
        "protocol_version": _PROTOCOL_VERSION,
        "status": status,
        "ok": status in {"execution_ok", "checked_ok"},
        "attempt_id": attempt_id,
        "manifest": manifest or [],
        "counts": counts or {},
        "output_bytes": output_bytes,
        "error_records": error_records[:32] if error_records else ([error] if error else []),
        "checks_status": checks_status,
        "check_report": check_report,
    }


def _safe_error(code: str, stage: str, path: str = "recipe") -> dict[str, str]:
    allowed = {"policy", "policy-preflight", "schema", "runtime", "write", "resource", "worker", "check"}
    safe_code = "".join(c for c in str(code) if c.isalnum() or c == "_")[:64] or "worker_error"
    safe_stage = stage if stage in allowed else "worker"
    if not isinstance(path, str) or not path.startswith("recipe"):
        path = "recipe"
    # Reject paths containing attacker-supplied object/property labels. Error
    # locations are schema fields only and never include machine paths.
    if any(not (char.isalnum() or char in "._[]") for char in path):
        path = "recipe"
    return {"code": safe_code, "stage": safe_stage, "path": path,
            "message": _message_for(safe_code, safe_stage)}


def _message_for(code: str, stage: str) -> str:
    messages = {
        "output_path_denied": "The recipe contains an unsafe export path. The host assigns export destinations.",
        "resource_access_denied": "File and URL resources are disabled for AI recipes.",
        "unsupported_code": "Executable code and commands are not accepted in recipes.",
        "unsupported_verb": "The recipe requested an unsupported command or resource operation.",
        "resource_limit": "The recipe exceeds a fixed resource limit.",
        "response_too_large": "The recipe exceeds the 512 KiB policy limit.",
        "cancelled": "Recipe execution was cancelled.",
        "deadline_exceeded": "Recipe execution exceeded its time limit.",
        "memory_limit": "Recipe execution exceeded the 1 GiB worker memory limit.",
        "output_limit": "Recipe execution exceeded the 256 MiB output limit.",
        "worker_died": "The recipe worker exited without a valid result.",
        "worker_protocol": "The recipe worker returned an invalid bounded result.",
        "unsafe_output_tree": "The worker output tree contains an unsafe path or link.",
        "worker_launch_error": "The recipe worker could not be started safely.",
        "native_project_invalid": "The worker did not produce a readable native project.",
        "checks_failed": "The artifact checks did not pass. Review the check report and correct the recipe.",
        "checker_error": "The fixed artifact checker did not complete.",
        "execution_error": "Recipe execution failed. Review the bounded validation report and correct the recipe.",
    }
    if code in messages:
        return messages[code]
    return "Recipe validation failed." if stage in {"schema", "policy-preflight", "policy"} else "Recipe execution failed."


def _record_from_exception(exc: BaseException) -> dict[str, str]:
    if isinstance(exc, (PolicyError, RecipeValidationError)):
        return _safe_error(getattr(exc, "code", "validation_error"),
                           getattr(exc, "stage", "policy-preflight"),
                           getattr(exc, "path", "recipe"))
    return _safe_error("worker_launch_error", "worker")


def _has_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    reparse = getattr(info, "st_file_attributes", 0) & getattr(
        __import__("stat"), "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return path.is_symlink() or bool(reparse)


def _assert_no_link_components(path: Path, *, allow_missing_leaf: bool = False) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    parts = [absolute]
    current = absolute
    while current.parent != current:
        current = current.parent
        parts.append(current)
    for part in reversed(parts):
        try:
            exists = part.exists() or part.is_symlink()
        except OSError:
            exists = False
        if not exists:
            if part == absolute and allow_missing_leaf:
                continue
            continue
        if _has_reparse_point(part):
            raise PolicyError("unsafe_output_tree", "output root contains a symlink or junction")
    return absolute


def _verify_tree(root: Path, *, include_protocol: bool = False,
                 include_scratch: bool = False,
                 scratch_root: bool = False) -> tuple[list[dict], int]:
    root = _assert_no_link_components(root)
    # ``ntpath.realpath`` can return an extended-length path for one lookup
    # while returning an ordinary drive path for another. This can happen if
    # a temporary file disappears between its two final-path probes. Normalize
    # both sides to the same host-I/O spelling before ``commonpath``; otherwise
    # Windows reports a false different-drive ValueError for a contained file.
    # This is comparison-only normalization: portable/model-authored paths are
    # still validated by policy, and the post-exit audit remains strict.
    root_real = extended_io_path(os.path.realpath(root))
    manifest: list[dict] = []
    total = 0
    count = 0
    portable_paths: dict[str, str] = {}

    def audit_component(component: str, relative: str) -> None:
        if (component in {"", ".", ".."}
                or component[-1:] in {" ", "."}
                or any(char in component for char in '<>:"/\\|?*')
                or any(unicodedata.category(char) == "Cc" for char in component)):
            raise PolicyError("unsafe_output_tree", "worker output contains a non-portable path")
        stem = component.split(".", 1)[0].upper()
        if stem in _WINDOWS_RESERVED_NAMES:
            raise PolicyError("unsafe_output_tree", "worker output contains a reserved path")
        key = unicodedata.normalize("NFC", relative).casefold()
        if key in portable_paths:
            raise PolicyError("unsafe_output_tree", "worker output paths collide on a portable filesystem")
        portable_paths[key] = relative

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        _assert_no_link_components(current_path)
        kept_dirs = []
        for dirname in dirs:
            candidate = current_path / dirname
            relative_dir = candidate.relative_to(root).as_posix()
            audit_component(dirname, relative_dir)
            if _has_reparse_point(candidate):
                raise PolicyError("unsafe_output_tree", "worker output tree contains a symlink or junction")
            resolved = extended_io_path(os.path.realpath(candidate))
            if os.path.commonpath((root_real, resolved)) != root_real:
                raise PolicyError("unsafe_output_tree", "worker output escaped its private attempt root")
            kept_dirs.append(dirname)
        dirs[:] = kept_dirs
        for filename in files:
            candidate = current_path / filename
            if not include_protocol and filename in {".ai_worker_input.json", ".ai_worker_result.json", ".ai_worker_result.json.tmp"}:
                continue
            if _has_reparse_point(candidate):
                raise PolicyError("unsafe_output_tree", "worker output tree contains a symlink or junction")
            resolved = extended_io_path(os.path.realpath(candidate))
            if os.path.commonpath((root_real, resolved)) != root_real:
                raise PolicyError("unsafe_output_tree", "worker output escaped its private attempt root")
            relative = candidate.relative_to(root).as_posix()
            if not relative or relative.startswith("../"):
                raise PolicyError("unsafe_output_tree", "worker output path escaped its private attempt root")
            audit_component(filename, relative)
            is_scratch = scratch_root or relative.startswith("tmp/")
            serializer_stage = include_scratch and bool(
                _SERIALIZER_TEMP_RE.fullmatch(filename))
            if candidate.suffix.lower() not in _ALLOWED_OUTPUT_SUFFIXES:
                # Protocol and bounded temporary scratch files are ignored;
                # scratch bytes still count against the live disk budget.
                if filename in {".ai_worker_input.json", ".ai_worker_result.json", ".ai_worker_result.json.tmp"}:
                    continue
                if is_scratch or serializer_stage:
                    if include_scratch:
                        try:
                            total += candidate.stat().st_size
                        except FileNotFoundError:
                            # Scratch files are routinely replaced while the
                            # live parent audit runs. The final audit is strict.
                            continue
                        count += 1
                        if count > 4096:
                            raise PolicyError("output_limit", "worker produced too many temporary files")
                    continue
                raise PolicyError("unsafe_output_tree", "worker produced an unapproved output file")
            try:
                size = candidate.stat().st_size
            except FileNotFoundError:
                # The fixed executor creates and removes private staging
                # files while the parent polls its tree. A vanished entry is
                # harmless during live accounting; the post-exit audit is
                # strict and will see the complete output tree.
                if include_scratch:
                    continue
                raise
            total += size
            count += 1
            if count > 4096:
                raise PolicyError("output_limit", "worker produced too many files")
            if is_scratch:
                continue
            manifest.append({
                "path": relative,
                "format": candidate.suffix.lower().lstrip("."),
                "size_bytes": size,
            })
    manifest.sort(key=lambda item: item["path"])
    return manifest, total


def _atomic_json(path: Path, value: dict) -> None:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    if len(payload) > _MAX_RESULT_BYTES:
        payload = json.dumps(_result("worker_protocol_error",
                                     error=_safe_error("worker_protocol", "worker")),
                             separators=(",", ":")).encode("utf-8")
    temporary = path.with_name(path.name + ".tmp")
    with open(temporary, "wb") as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def _strict_json(payload: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def constant(_value):
        raise ValueError("non-finite JSON value")

    return json.loads(payload.decode("utf-8", errors="strict"),
                       object_pairs_hook=pairs, parse_constant=constant)


def internal_worker_main(argv: list[str] | None = None) -> int:
    """Trusted fixed child entry used by both source and frozen GUI builds."""
    if argv is None:
        argv = sys.argv[1:]
    if len(argv) != 2:
        return 64
    input_path = Path(extended_io_path(argv[0]))
    result_path = Path(extended_io_path(argv[1]))
    cwd = Path(extended_io_path(os.getcwd()))
    # A malformed or oversized fixed-protocol request may fail before the
    # host-selected output root has been parsed. Keep diagnostics independent
    # of untrusted request fields in that case.
    attempt_id: str | None = None
    try:
        if input_path.name != ".ai_worker_input.json" or result_path.name != ".ai_worker_result.json":
            return 64
        if os.path.commonpath((str(cwd), str(Path(os.path.abspath(input_path))))) != str(cwd):
            return 64
        if os.path.commonpath((str(cwd), str(Path(os.path.abspath(result_path))))) != str(cwd):
            return 64
        _assert_no_link_components(cwd)
        input_path = cwd / input_path.name
        result_path = cwd / result_path.name
        if input_path.stat().st_size > _MAX_INPUT_BYTES:
            raise PolicyError("response_too_large", "worker input exceeds the bounded protocol limit")
        try:
            request = _strict_json(input_path.read_bytes())
        except (ValueError, RecursionError):
            raise PolicyError("worker_protocol", "worker input JSON is invalid") from None
        if not isinstance(request, dict) or request.get("protocol_version") != _PROTOCOL_VERSION:
            raise PolicyError("worker_protocol", "worker input protocol is invalid")
        if set(request) - {"protocol_version", "recipe", "check_options", "output_root"}:
            raise PolicyError("worker_protocol", "worker input contains an unsupported field")
        output_root_value = request.get("output_root")
        if not isinstance(output_root_value, str) or len(output_root_value) > 32767:
            raise PolicyError("worker_protocol", "worker output root is invalid")
        output_root = Path(extended_io_path(output_root_value))
        _assert_no_link_components(output_root)
        if not output_root.is_dir():
            raise PolicyError("unsafe_output_tree", "worker output root is unavailable")
        if not re.fullmatch(r"attempt-[0-9a-f]{32}", output_root.name):
            raise PolicyError("worker_protocol", "worker output root identity is invalid")
        attempt_id = output_root.name
        options = request.get("check_options")
        if options is not None:
            if (not isinstance(options, dict)
                    or set(options) - {"brief", "generation", "requirements"}):
                raise PolicyError("worker_protocol", "check options use unsupported fields")
            _check_data_tree(options)
            option_bytes = json.dumps(options, ensure_ascii=False,
                                      separators=(",", ":"),
                                      allow_nan=False).encode("utf-8")
            if len(option_bytes) > _MAX_CHECK_OPTIONS_BYTES:
                raise PolicyError("response_too_large", "check options exceed the bounded protocol limit")
        recipe = prepare_recipe(request.get("recipe"))
        from am3d.core.script import Session
        from am3d.core.serializer import load_project
        from am3d.recipes.executor import RecipeExecutor

        session = Session()
        executor = RecipeExecutor(session=session, output_root=str(output_root),
                                  safe_artifact_names=True)
        execution = executor.execute(recipe)
        if not execution.ok:
            records = execution.error_records or [{"code": "execution_error", "stage": "runtime", "path": "recipe"}]
            errors = [_safe_error(rec.get("code", "execution_error"),
                                  rec.get("stage", "runtime"),
                                  rec.get("path", "recipe"))
                      for rec in records[:32]]
            _atomic_json(result_path, _result(
                "execution_failed", error=errors[0], attempt_id=attempt_id,
                counts={"objects": len(execution.objects),
                        "materials": len(execution.materials),
                        "actions": len(execution.actions)}))
            return 1

        native = output_root / "project.am3d"
        if not native.is_file():
            raise ValueError("native project output is missing")
        loaded = load_project(str(native))
        if not loaded.objects and recipe.get("objects"):
            raise ValueError("native project did not reopen with its recipe objects")

        # The checker is fixed host code and is optional until Phase 4 lands.
        # Absence means execution completed, not that it passed artifact checks.
        checks_status = "not_requested" if options is None else "unavailable"
        report = None
        status = "execution_ok"
        error_records = None
        if options is not None:
            try:
                from am3d.ai import checks as checks_module
            except ImportError:
                checks_module = None
            checker = getattr(checks_module, "check_artifacts", None) if checks_module else None
            if checker is not None:
                try:
                    report = checker(
                        recipe, output_dir=output_root,
                        brief=options.get("brief"),
                        generation=options.get("generation"),
                        requirements=options.get("requirements"))
                    if not isinstance(report, dict):
                        raise ValueError("invalid checker result")
                    report_payload = json.dumps(report, ensure_ascii=False,
                                                separators=(",", ":"),
                                                allow_nan=False).encode("utf-8")
                    if len(report_payload) > _MAX_CHECK_REPORT_BYTES:
                        raise ValueError("checker result exceeds its bounded report limit")
                    report_ok = report.get("ok") is True and report.get("status") == "passed"
                    checks_status = "passed" if report_ok else "failed"
                    if report_ok:
                        status = "checked_ok"
                    else:
                        status = "check_failed"
                        error_records = [_safe_error("checks_failed", "check")]
                except Exception:
                    checks_status = "failed"
                    status = "check_failed"
                    report = {"status": "failed", "ok": False, "checks": [],
                              "limitations": ["The fixed artifact checker did not complete."]}
                    error_records = [_safe_error("checker_error", "check")]

        manifest, total_bytes = _verify_tree(output_root)
        if total_bytes > MAX_OUTPUT_BYTES:
            raise PolicyError("output_limit", "worker outputs exceed 256 MiB")
        if not any(item["path"] == "project.am3d" for item in manifest):
            raise ValueError("native project is missing from the verified manifest")
        _atomic_json(result_path, _result(
            status, manifest=manifest, attempt_id=attempt_id,
            counts={"objects": len(loaded.objects),
                    "materials": len(loaded.materials),
                    "actions": len(getattr(loaded, "actions", {}))},
            output_bytes=total_bytes, check_report=report,
            checks_status=checks_status, error_records=error_records))
        return 0
    except (PolicyError, RecipeValidationError) as exc:
        _atomic_json(result_path, _result(
            "policy_error" if isinstance(exc, PolicyError) else "validation_error",
            error=_record_from_exception(exc), attempt_id=attempt_id))
        return 2
    except Exception:
        _atomic_json(result_path, _result(
            "execution_failed", error=_safe_error("execution_error", "runtime"),
            attempt_id=attempt_id))
        return 1


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _minimal_environment(temp_root: Path) -> dict[str, str]:
    """A small environment; user credentials, prompts and proxy variables are omitted."""
    env = {
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONNOUSERSITE": "1",
        "TEMP": extended_io_path(temp_root),
        "TMP": extended_io_path(temp_root),
        "TMPDIR": extended_io_path(temp_root),
    }
    if os.name == "nt":
        system_root = os.environ.get("SystemRoot", r"C:\Windows")
        env["SYSTEMROOT"] = system_root
        env["WINDIR"] = system_root
        system32 = str(Path(system_root) / "System32")
        executable_dir = str(Path(sys.executable).resolve().parent)
        env["PATH"] = os.pathsep.join(dict.fromkeys((executable_dir, system32, system_root)))
    else:
        env["PATH"] = "/usr/bin:/bin"
        env["LANG"] = "C.UTF-8"
    if not getattr(sys, "frozen", False):
        env["PYTHONPATH"] = str(_source_root())
    return env


def _cleanup_private_workspace(context, workspace: Path | None) -> None:
    """Remove only a verified, per-run scratch directory after the child stops."""
    if context is None or workspace is None:
        return
    try:
        if Path(context.name) != workspace or not workspace.name.startswith("am3d_ai_"):
            return
        parent_real = os.path.realpath(workspace.parent)
        workspace_real = os.path.realpath(workspace)
        if os.path.commonpath((parent_real, workspace_real)) != parent_real:
            return
        if Path(workspace_real).parent != Path(parent_real):
            return
        _verify_tree(workspace, include_protocol=True, include_scratch=True,
                     scratch_root=True)
        context.cleanup()
    except Exception:
        # Never recursively clean a workspace whose link/confinement audit
        # failed. It is private temporary state, not a returned artifact.
        return


class _WindowsJob:
    """Kill-on-close Job Object, so a fixed worker's descendants die too."""

    def __init__(self, process: subprocess.Popen):
        self.handle = None
        if os.name != "nt":
            return
        from ctypes import wintypes

        class BasicLimit(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_longlong),
                ("PerJobUserTimeLimit", ctypes.c_longlong),
                ("LimitFlags", wintypes.DWORD),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", wintypes.DWORD),
                ("SchedulingClass", wintypes.DWORD),
            ]

        class IoCounters(ctypes.Structure):
            _fields_ = [(name, ctypes.c_ulonglong) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", BasicLimit),
                ("IoInfo", IoCounters),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel.SetInformationJobObject.argtypes = (
            wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel.TerminateJobObject.restype = wintypes.BOOL
        job = kernel.CreateJobObjectW(None, None)
        if not job:
            raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
        limits = ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not kernel.SetInformationJobObject(
                job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            error = ctypes.get_last_error()
            kernel.CloseHandle(job)
            raise OSError(error, "SetInformationJobObject failed")
        if not kernel.AssignProcessToJobObject(job, wintypes.HANDLE(process._handle)):
            error = ctypes.get_last_error()
            kernel.CloseHandle(job)
            raise OSError(error, "AssignProcessToJobObject failed")
        self.handle = job
        self.kernel = kernel

    def terminate(self, process: subprocess.Popen) -> None:
        if os.name == "nt" and self.handle:
            self.kernel.TerminateJobObject(self.handle, 1)
            return
        if os.name == "nt":
            root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
            taskkill = root / "System32" / "taskkill.exe"
            try:
                subprocess.run([str(taskkill), "/PID", str(process.pid), "/T", "/F"],
                               stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=1.0,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                               env=_minimal_environment(Path(tempfile.gettempdir())))
            except Exception:
                try:
                    process.kill()
                except OSError:
                    pass
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=0.15)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            try:
                process.kill()
            except OSError:
                pass

    def close(self) -> None:
        if os.name == "nt" and self.handle:
            # KILL_ON_JOB_CLOSE is the final descendant cleanup guarantee.
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _memory_bytes(process: subprocess.Popen) -> int | None:
    if os.name == "nt":
        try:
            from ctypes import wintypes

            class ProcessMemoryCounters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in (
                        "PeakWorkingSetSize", "WorkingSetSize",
                        "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                        "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
                        "PagefileUsage", "PeakPagefileUsage")]

            counters = ProcessMemoryCounters()
            counters.cb = ctypes.sizeof(counters)
            psapi = ctypes.WinDLL("psapi", use_last_error=True)
            psapi.GetProcessMemoryInfo.argtypes = (
                wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD)
            psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            if psapi.GetProcessMemoryInfo(
                    wintypes.HANDLE(process._handle), ctypes.byref(counters),
                    counters.cb):
                return int(counters.WorkingSetSize)
        except Exception:
            return None
    statm = Path(f"/proc/{process.pid}/statm")
    try:
        resident_pages = int(statm.read_text(encoding="ascii").split()[1])
        return resident_pages * int(os.sysconf("SC_PAGE_SIZE"))
    except Exception:
        return None


def _worker_command(input_path: Path, result_path: Path) -> tuple[list[str], Path | None]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--internal-ai-worker", str(input_path), str(result_path)], None
    return [sys.executable, "-m", "am3d.ai.worker", str(input_path), str(result_path)], _source_root()


def run_worker(recipe: Any, output_dir: str | os.PathLike[str], deadline: float,
               cancellation: CancellationToken | None, *,
               check_options: dict | None = None) -> dict:
    """Execute one canonical recipe in a fresh bounded worker process.

    ``deadline`` is an absolute ``time.monotonic()`` timestamp. ``output_dir``
    is host-selected; all artifacts land in a new ``attempt-<id>`` child and
    manifests contain only paths relative to that output directory.
    """
    attempt_id = uuid.uuid4().hex
    token = cancellation or CancellationToken()
    try:
        canonical = prepare_recipe(recipe)
    except (PolicyError, RecipeValidationError) as exc:
        status = "policy_error" if isinstance(exc, PolicyError) else "validation_error"
        return _result(status, error=_record_from_exception(exc), attempt_id=attempt_id)
    except Exception:
        return _result("validation_error", error=_safe_error("validation_error", "schema"), attempt_id=attempt_id)

    try:
        if check_options is not None:
            if (not isinstance(check_options, dict)
                    or set(check_options) - {"brief", "generation", "requirements"}):
                raise PolicyError("worker_protocol", "check options use unsupported fields")
            _check_data_tree(check_options)
            encoded_options = json.dumps(check_options, ensure_ascii=False,
                                         separators=(",", ":"),
                                         allow_nan=False).encode("utf-8")
            if len(encoded_options) > _MAX_CHECK_OPTIONS_BYTES:
                raise PolicyError("response_too_large", "check options exceed the bounded protocol limit")
        protocol = {"protocol_version": _PROTOCOL_VERSION,
                    "recipe": canonical, "check_options": check_options}
    except PolicyError as exc:
        return _result("policy_error", error=_record_from_exception(exc), attempt_id=attempt_id)
    except Exception:
        return _result("validation_error", error=_safe_error("worker_protocol", "policy-preflight"), attempt_id=attempt_id)

    workspace_context = None
    workspace = None
    try:
        base = _assert_no_link_components(
            Path(extended_io_path(output_dir)), allow_missing_leaf=True)
        base.mkdir(parents=True, exist_ok=True)
        _assert_no_link_components(base)
        if not base.is_dir():
            raise PolicyError("unsafe_output_tree", "output root is not a directory")
        attempt_root = base / f"attempt-{attempt_id}"
        attempt_root.mkdir(mode=0o700)
        _assert_no_link_components(attempt_root)
        temp_parent = Path(tempfile.gettempdir())
        if os.name == "nt" and len(str(temp_parent)) > 180:
            system_temp = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "Temp"
            if system_temp.is_dir() and len(str(system_temp)) < len(str(temp_parent)):
                temp_parent = system_temp
        _assert_no_link_components(temp_parent)
        workspace_context = tempfile.TemporaryDirectory(
            prefix="am3d_ai_", dir=str(temp_parent))
        workspace = Path(workspace_context.name)
        if os.name == "nt" and len(str(workspace)) >= 240:
            raise OSError("private worker directory is too long for a process cwd")
        _assert_no_link_components(workspace)
        temp_root = workspace / "tmp"
        temp_root.mkdir(mode=0o700)
        input_path = workspace / ".ai_worker_input.json"
        result_path = workspace / ".ai_worker_result.json"
        protocol["output_root"] = str(attempt_root)
        payload = json.dumps(protocol, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
        if len(payload) > _MAX_INPUT_BYTES:
            raise PolicyError("response_too_large", "worker input exceeds the bounded protocol limit")
        input_path.write_bytes(payload)
        if os.name != "nt":
            try:
                os.chmod(attempt_root, 0o700)
                os.chmod(temp_root, 0o700)
                os.chmod(input_path, 0o600)
            except OSError:
                pass
        _assert_no_link_components(attempt_root)
        _assert_no_link_components(workspace)
    except PolicyError as exc:
        _cleanup_private_workspace(workspace_context, workspace)
        error_status = ("policy_error" if exc.code == "response_too_large"
                        else "worker_error")
        return _result(error_status, error=_record_from_exception(exc), attempt_id=attempt_id)
    except (OSError, ValueError):
        _cleanup_private_workspace(workspace_context, workspace)
        return _result("worker_error", error=_safe_error("unsafe_output_tree", "worker"), attempt_id=attempt_id)

    if token.cancelled:
        _cleanup_private_workspace(workspace_context, workspace)
        return _result("cancelled", error=_safe_error("cancelled", "worker"), attempt_id=attempt_id)

    now = time.monotonic()
    try:
        requested_deadline = (float(deadline)
                              if not isinstance(deadline, bool)
                              and isinstance(deadline, (int, float)) else None)
    except (OverflowError, ValueError):
        requested_deadline = None
    if requested_deadline is None or not math.isfinite(requested_deadline):
        worker_deadline = now + MAX_WORKER_SECONDS
    else:
        worker_deadline = min(requested_deadline, now + MAX_WORKER_SECONDS)
    if worker_deadline <= now:
        _cleanup_private_workspace(workspace_context, workspace)
        return _result("timed_out", error=_safe_error("deadline_exceeded", "worker"), attempt_id=attempt_id)

    command, source_root = _worker_command(input_path, result_path)
    environment = _minimal_environment(temp_root)
    if source_root is not None:
        environment["PYTHONPATH"] = str(source_root)
    creationflags = 0
    startupinfo = None
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        creationflags |= getattr(subprocess, "CREATE_NO_WINDOW", 0)
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = subprocess.SW_HIDE
    try:
        process = subprocess.Popen(
            command, cwd=str(workspace), env=environment,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
            creationflags=creationflags, startupinfo=startupinfo,
            start_new_session=(os.name != "nt"))
    except Exception:
        _cleanup_private_workspace(workspace_context, workspace)
        return _result("worker_error", error=_safe_error("worker_launch_error", "worker"), attempt_id=attempt_id)

    tree = None
    try:
        if os.name == "nt":
            try:
                tree = _WindowsJob(process)
            except OSError:
                # A fixed worker has no shell or user-selected child process.
                # The taskkill /T fallback still terminates the exact tree.
                tree = _WindowsJob.__new__(_WindowsJob)
                tree.handle = None
                tree.kernel = None
        else:
            tree = _WindowsJob(process)

        failure = None
        while process.poll() is None:
            if token.cancelled:
                failure = ("cancelled", _safe_error("cancelled", "worker"))
                break
            if time.monotonic() >= worker_deadline:
                failure = ("timed_out", _safe_error("deadline_exceeded", "worker"))
                break
            try:
                _, output_size = _verify_tree(
                    attempt_root, include_protocol=True, include_scratch=True)
                _, scratch_size = _verify_tree(
                    workspace, include_protocol=True, include_scratch=True,
                    scratch_root=True)
                current_size = output_size + scratch_size
            except PolicyError:
                failure = ("worker_error", _safe_error("unsafe_output_tree", "worker"))
                break
            if token.cancelled:
                failure = ("cancelled", _safe_error("cancelled", "worker"))
                break
            if time.monotonic() >= worker_deadline:
                failure = ("timed_out", _safe_error("deadline_exceeded", "worker"))
                break
            if current_size > 2 * MAX_OUTPUT_BYTES + _PROTOCOL_OVERHEAD:
                failure = ("resource_limit", _safe_error("output_limit", "worker"))
                break
            memory = _memory_bytes(process)
            if memory is not None and memory > _MEMORY_LIMIT:
                failure = ("resource_limit", _safe_error("memory_limit", "worker"))
                break
            time.sleep(0.05)
        if failure is not None:
            terminate_started = time.monotonic()
            tree.terminate(process)
            remaining = max(0.0, MAX_CANCEL_ACK_SECONDS -
                            (time.monotonic() - terminate_started))
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                try:
                    process.kill()
                except OSError:
                    pass
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            return _result(failure[0], error=failure[1], attempt_id=attempt_id)

        exit_code = process.wait(timeout=max(0.1, min(1.0, worker_deadline - time.monotonic())))
        if token.cancelled:
            return _result("cancelled", error=_safe_error("cancelled", "worker"), attempt_id=attempt_id)
        if time.monotonic() > worker_deadline:
            return _result("timed_out", error=_safe_error("deadline_exceeded", "worker"), attempt_id=attempt_id)
        if not result_path.is_file() or result_path.stat().st_size > _MAX_RESULT_BYTES:
            return _result("worker_error", error=_safe_error("worker_died", "worker"), attempt_id=attempt_id)
        child_result = _strict_json(result_path.read_bytes())
        if (not isinstance(child_result, dict)
                or child_result.get("protocol_version") != _PROTOCOL_VERSION
                or child_result.get("status") not in {"execution_ok", "checked_ok", "check_failed", "execution_failed", "policy_error", "validation_error", "worker_protocol_error"}
                or not isinstance(child_result.get("manifest", []), list)):
            return _result("worker_error", error=_safe_error("worker_protocol", "worker"), attempt_id=attempt_id)
        child_status = child_result["status"]
        if exit_code != 0 and child_status in {"execution_ok", "checked_ok", "check_failed"}:
            return _result("worker_error", error=_safe_error("worker_died", "worker"), attempt_id=attempt_id)
        if child_status == "worker_protocol_error":
            return _result("worker_error", error=_safe_error("worker_protocol", "worker"), attempt_id=attempt_id)
        input_path.unlink(missing_ok=True)
        result_path.unlink(missing_ok=True)
        (workspace / ".ai_worker_result.json.tmp").unlink(missing_ok=True)
        manifest, output_bytes = _verify_tree(attempt_root)
        _, scratch_bytes = _verify_tree(
            workspace, include_scratch=True, scratch_root=True)
        if scratch_bytes > 2 * MAX_OUTPUT_BYTES:
            return _result("resource_limit", error=_safe_error("output_limit", "worker"), attempt_id=attempt_id)
        if token.cancelled:
            return _result("cancelled", error=_safe_error("cancelled", "worker"), attempt_id=attempt_id)
        if output_bytes > MAX_OUTPUT_BYTES:
            return _result("resource_limit", error=_safe_error("output_limit", "worker"), attempt_id=attempt_id)
        if child_status in {"execution_ok", "checked_ok", "check_failed"}:
            # Parent independently audits extension, containment, sizes and
            # required native file instead of trusting the child manifest.
            if not any(entry["path"] == "project.am3d" for entry in manifest):
                return _result("worker_error", error=_safe_error("native_project_invalid", "worker"), attempt_id=attempt_id)
            checks_status = child_result.get("checks_status", "not_run")
            report = child_result.get("check_report")
            if child_status == "checked_ok" and not (
                    checks_status == "passed" and isinstance(report, dict)
                    and report.get("ok") is True and report.get("status") == "passed"):
                return _result("worker_error", error=_safe_error("worker_protocol", "worker"), attempt_id=attempt_id)
            if child_status == "check_failed" and not (
                    checks_status == "failed" and isinstance(report, dict)
                    and report.get("ok") is not True):
                return _result("worker_error", error=_safe_error("worker_protocol", "worker"), attempt_id=attempt_id)
            if child_status == "execution_ok" and checks_status not in {"not_run", "not_requested", "unavailable"}:
                return _result("worker_error", error=_safe_error("worker_protocol", "worker"), attempt_id=attempt_id)
            if token.cancelled:
                return _result("cancelled", error=_safe_error("cancelled", "worker"), attempt_id=attempt_id)
            final_manifest = [{**entry, "path": f"attempt-{attempt_id}/{entry['path']}"}
                              for entry in manifest]
            if child_status == "check_failed":
                records = child_result.get("error_records", [])
                safe_records = []
                for record in records[:32] if isinstance(records, list) else []:
                    if isinstance(record, dict):
                        safe_records.append(_safe_error(record.get("code", "checks_failed"),
                                                        "check", record.get("path", "recipe")))
                return _result(
                    "check_failed",
                    error=(safe_records[0] if safe_records else _safe_error("checks_failed", "check")),
                    error_records=safe_records or None, manifest=final_manifest,
                    attempt_id=attempt_id,
                    counts=child_result.get("counts") if isinstance(child_result.get("counts"), dict) else {},
                    output_bytes=output_bytes, check_report=report,
                    checks_status="failed")
            return _result(
                child_status, manifest=final_manifest,
                attempt_id=attempt_id,
                counts=child_result.get("counts") if isinstance(child_result.get("counts"), dict) else {},
                output_bytes=output_bytes,
                check_report=report if isinstance(report, dict) else None,
                checks_status=checks_status if checks_status in {"not_run", "not_requested", "unavailable", "passed", "failed"} else "not_run")
        error_records = child_result.get("error_records", [])
        if not isinstance(error_records, list) or not error_records:
            error = _safe_error("execution_error", "runtime")
        else:
            first = error_records[0]
            error = _safe_error(first.get("code", "execution_error"),
                                first.get("stage", "runtime"),
                                first.get("path", "recipe")) if isinstance(first, dict) else _safe_error("execution_error", "runtime")
        errors = []
        for record in error_records[:32] if isinstance(error_records, list) else []:
            if isinstance(record, dict):
                errors.append(_safe_error(record.get("code", "execution_error"),
                                          record.get("stage", "runtime"),
                                          record.get("path", "recipe")))
        return _result(child_result["status"], error=error,
                       error_records=errors or None, attempt_id=attempt_id)
    except Exception:
        if tree is not None and process.poll() is None:
            tree.terminate(process)
        return _result("worker_error", error=_safe_error("worker_protocol", "worker"), attempt_id=attempt_id)
    finally:
        if tree is not None:
            tree.close()
        _cleanup_private_workspace(workspace_context, workspace)


def main(argv: list[str] | None = None) -> int:
    return internal_worker_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
