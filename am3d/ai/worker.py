"""Fixed, Qt-free process entry point for local recipe generation.

The parent supplies a versioned JSON request in a private control directory.
No command, module name, output path, or callback comes from recipe content.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
import uuid

from .contracts import (GenerationArtifact, GenerationCheckResult,
                        GenerationEvent, GenerationResult, GenerationStatus)
from .policy import (PolicyRejected, authorize_recipe, policy_snapshot)


_MAX_CONTROL_FILE = 2 * 1024 * 1024
_MAX_EVENT_LOG = 64 * 1024
_MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
_ABS_PATH = re.compile(r"(?<![A-Za-z0-9_.])(?:[A-Za-z]:[\\/]|/)(?:[^\\/\s:'\"]+[\\/])*[^\\/\s:'\"]+")


def _safe_message(value: str, limit: int = 600) -> str:
    value = _ABS_PATH.sub("<path>", str(value))
    return value[:limit]


def _write_json_atomic(path: Path, value: dict, *, limit: int) -> None:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(raw) > limit:
        raise ValueError("worker control output exceeded its size limit")
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("wb") as fh:
        fh.write(raw)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _apply_memory_limit() -> None:
    """Bound additional Linux address-space use without changing Windows CI."""
    if sys.platform != "linux":
        return
    try:
        import resource
        statm = Path("/proc/self/statm").read_text().split()
        current = int(statm[0]) * os.sysconf("SC_PAGE_SIZE")
        headroom = 1024 * 1024 * 1024
        _, hard = resource.getrlimit(resource.RLIMIT_AS)
        target = current + headroom
        if hard != resource.RLIM_INFINITY:
            target = min(target, hard)
        resource.setrlimit(resource.RLIMIT_AS, (target, hard))
    except (OSError, ValueError, ImportError, AttributeError):
        # Resource accounting and process deadlines remain active if this
        # platform/kernel does not expose an address-space limit.
        return


class _Reporter:
    def __init__(self, request, events_path: Path, start: float):
        self.request = request
        self.path = events_path
        self.start = start

    def event(self, stage: GenerationStatus, message: str = "") -> None:
        item = GenerationEvent(self.request.run_id, stage,
                              max(0.0, time.monotonic() - self.start),
                              _safe_message(message, 240))
        raw = json.dumps(item.to_dict(), separators=(",", ":")) + "\n"
        data = raw.encode("utf-8")
        try:
            if self.path.stat().st_size + len(data) > _MAX_EVENT_LOG:
                return
        except FileNotFoundError:
            pass
        with self.path.open("ab") as fh:
            fh.write(data)
            fh.flush()


def _validate_control_paths(request_path: Path, events_path: Path,
                             result_path: Path, request) -> tuple[Path, Path]:
    if (request_path.is_symlink() or request_path.parent.is_symlink() or
            events_path.is_symlink() or result_path.is_symlink()):
        raise ValueError("worker control files cannot be symlinks")
    control = request_path.parent.resolve()
    attempt = control.parent.resolve()
    if (control.name != ".control" or attempt.name != request.run_id or
            request_path.name != "request.json" or
            events_path.resolve().parent != control or
            result_path.resolve().parent != control):
        raise ValueError("worker control files must use the fixed private layout")
    if events_path.name != "events.jsonl" or result_path.name != "result.json":
        raise ValueError("worker control filenames are invalid")
    output = attempt / "output"
    expected_root = (output / "exports").resolve()
    supplied_root = Path(request.output_root).resolve()
    if supplied_root != expected_root:
        raise ValueError("worker output root differs from its host-selected private directory")
    if not output.is_dir() or not expected_root.is_dir():
        raise ValueError("worker output directory was not prepared by the host")
    if output.is_symlink() or expected_root.is_symlink():
        raise ValueError("worker output directory cannot be a symlink")
    return output, expected_root


def _artifact(path: Path, relative_to: Path, kind: str, media_type: str | None = None):
    size = path.stat().st_size
    if size > _MAX_ARTIFACT_BYTES:
        raise ValueError("generated artifact exceeds its publication size limit")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return GenerationArtifact(path.relative_to(relative_to).as_posix(), kind,
                              size, digest, media_type)


def _collect_artifacts(output: Path, manifest) -> tuple[GenerationArtifact, ...]:
    paths: dict[str, tuple[Path, str, str | None]] = {
        "project.am3d": (output / "project.am3d", "native_project", "application/x-am3d"),
        "preview.png": (output / "preview.png", "preview", "image/png"),
        "checks.json": (output / "checks.json", "checks", "application/json"),
    }
    export_root = output / "exports"
    for item in manifest:
        path = Path(item["path"]).resolve()
        try:
            rel = path.relative_to(export_root.resolve()).as_posix()
        except ValueError as exc:
            raise ValueError("export artifact escaped the private output root") from exc
        fmt = str(item.get("format", "artifact"))
        media = "image/png" if path.suffix.lower() == ".png" else None
        paths[f"exports/{rel}"] = (path, fmt, media)
    artifacts = []
    total = 0
    for rel, (path, kind, media) in sorted(paths.items()):
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"expected generated artifact is missing: {rel}")
        artifact = _artifact(path, output, kind, media)
        total += artifact.size_bytes
        artifacts.append(artifact)
    if total > _MAX_ARTIFACT_BYTES:
        raise ValueError("combined generated artifacts exceed the publication size limit")
    return tuple(artifacts)


def _error_records(records, *, stage="execution"):
    cleaned = []
    for item in records:
        if not isinstance(item, dict):
            continue
        cleaned.append({
            "code": _safe_message(item.get("code", "execution_error"), 80),
            "stage": _safe_message(item.get("stage", stage), 40),
            "path": _safe_message(item.get("path", "recipe"), 200),
            "message": _safe_message(item.get("message", "Generation failed.")),
            **({"hint": _safe_message(item["hint"])} if item.get("hint") else {}),
        })
    return cleaned


def _run_request(request, reporter: _Reporter, output: Path) -> GenerationResult:
    started = time.monotonic()
    try:
        if request.policy_snapshot != policy_snapshot():
            return GenerationResult(
                request.run_id, GenerationStatus.FAILED,
                error_records=({"code": "policy_snapshot_mismatch", "stage": "policy",
                                "path": "policy_snapshot",
                                "message": "Worker policy does not match the host snapshot."},))
        if request.check_config not in ({}, {"preview_size": 512}):
            return GenerationResult(
                request.run_id, GenerationStatus.FAILED,
                error_records=({"code": "check_config_rejected", "stage": "policy",
                                "path": "check_config",
                                "message": "Worker check configuration is not supported."},))
        reporter.event(GenerationStatus.VALIDATING, "Applying strict local recipe policy")
        decision = authorize_recipe(request.recipe_json, request.output_root)

        from am3d.core.script import Session
        from am3d.recipes.executor import RecipeExecutor

        session = Session()
        reporter.event(GenerationStatus.BUILDING, "Building validated recipe")
        execution = RecipeExecutor(session=session, output_root=request.output_root,
                                   ai_mode=True).execute(decision.recipe)
        if not execution.ok:
            return GenerationResult(
                request.run_id, GenerationStatus.FAILED,
                warnings=tuple(_safe_message(item) for item in execution.warnings),
                error_records=tuple(_error_records(execution.error_records)))

        project_path = output / "project.am3d"
        try:
            session.save_project(str(project_path))
        except MemoryError:
            return GenerationResult(request.run_id, GenerationStatus.FAILED,
                                    error_records=({"code": "resource_exhausted",
                                                    "stage": "resource", "path": "recipe",
                                                    "message": "Native project save exceeded available memory."},))
        except Exception as exc:
            return GenerationResult(request.run_id, GenerationStatus.FAILED,
                                    error_records=({"code": "project_save_failed",
                                                    "stage": "execution", "path": "recipe",
                                                    "message": f"Native project save failed ({type(exc).__name__})."},))

        reporter.event(GenerationStatus.CHECKING, "Reopening project and checking generated artifacts")
        from am3d.core.script import Session as ProjectSession
        reopened = ProjectSession()
        try:
            reopened.load_project(str(project_path))
            expected_names = {item.name for item in decision.recipe.objects}
            if not expected_names.issubset(reopened.project.objects):
                raise ValueError("saved project is missing recipe objects")
        except Exception as exc:
            check = {"name": "native_project_reopen", "ok": False,
                     "code": "project_reopen_failed",
                     "message": f"Saved project did not reopen ({type(exc).__name__}).",
                     "details": {}}
            return GenerationResult(request.run_id, GenerationStatus.FAILED,
                                    checks=(GenerationCheckResult.from_dict(check),),
                                    error_records=({"code": check["code"], "stage": "check",
                                                    "path": "project.am3d", "message": check["message"]},))

        checks_path = output / "checks.json"
        preview_path = output / "preview.png"
        from .checks import run_generation_checks
        check_output = run_generation_checks(
            reopened, execution.manifest, request.output_root, preview_path,
            on_preview=lambda: reporter.event(GenerationStatus.RENDERING_PREVIEW,
                                               "Rendering whole-scene preview"))
        checks = list(check_output.checks)
        checks.insert(0, GenerationCheckResult("native_project_reopen", True))
        _write_json_atomic(checks_path,
                           {"check_version": 1,
                            "checks": [item.to_dict() for item in checks]},
                           limit=64 * 1024)
        failed = [item for item in checks if not item.ok]
        if failed:
            errors = [{"code": item.code or "check_failed", "stage": "check",
                       "path": item.name, "message": _safe_message(item.message)}
                      for item in failed]
            return GenerationResult(request.run_id, GenerationStatus.FAILED,
                                    checks=tuple(checks),
                                    warnings=tuple(_safe_message(item) for item in execution.warnings),
                                    error_records=tuple(errors),
                                    elapsed_seconds=max(0.0, time.monotonic() - started))

        reporter.event(GenerationStatus.PUBLISHING, "Preparing immutable generation artifacts")
        artifacts = _collect_artifacts(output, execution.manifest)
        return GenerationResult(
            request.run_id, GenerationStatus.COMPLETE, artifacts=artifacts,
            checks=tuple(checks),
            warnings=tuple(_safe_message(item) for item in execution.warnings),
            elapsed_seconds=max(0.0, time.monotonic() - started))
    except PolicyRejected as exc:
        errors = [{"code": item.code, "stage": item.stage, "path": item.path,
                   "message": _safe_message(item.message),
                   **({"hint": _safe_message(item.hint)} if item.hint else {})}
                  for item in exc.errors]
        return GenerationResult(request.run_id, GenerationStatus.FAILED,
                                error_records=tuple(errors),
                                elapsed_seconds=max(0.0, time.monotonic() - started))
    except MemoryError:
        return GenerationResult(request.run_id, GenerationStatus.FAILED,
                                error_records=({"code": "resource_exhausted",
                                                "stage": "resource", "path": "recipe",
                                                "message": "Generation exceeded the available memory limit."},),
                                elapsed_seconds=max(0.0, time.monotonic() - started))
    except Exception as exc:
        return GenerationResult(request.run_id, GenerationStatus.FAILED,
                                error_records=({"code": "worker_operation_failed",
                                                "stage": "worker", "path": "recipe",
                                                "message": f"Generation failed ({type(exc).__name__})."},),
                                elapsed_seconds=max(0.0, time.monotonic() - started))


def _worker_main(request_path: Path, events_path: Path, result_path: Path) -> int:
    from .contracts import GenerationRequest

    if request_path.stat().st_size > _MAX_CONTROL_FILE:
        raise ValueError("request file exceeds the control size limit")
    request = GenerationRequest.from_json(request_path.read_bytes())
    output, _ = _validate_control_paths(request_path, events_path,
                                        result_path, request)
    started = time.monotonic()
    reporter = _Reporter(request, events_path, started)
    reporter.event(GenerationStatus.VALIDATING, "Worker accepted structured request")
    _apply_memory_limit()
    result = _run_request(request, reporter, output)
    if result.status == GenerationStatus.COMPLETE:
        reporter.event(GenerationStatus.COMPLETE, "Local generation checks passed")
    _write_json_atomic(result_path, result.to_dict(), limit=_MAX_CONTROL_FILE)
    return 0 if result.status == GenerationStatus.COMPLETE else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--request", required=True)
    parser.add_argument("--events", required=True)
    parser.add_argument("--result", required=True)
    args = parser.parse_args(argv)
    request_path = Path(args.request)
    events_path = Path(args.events)
    result_path = Path(args.result)
    try:
        return _worker_main(request_path, events_path, result_path)
    except BaseException as exc:
        # The parent treats the absent/malformed result as a worker crash.
        # Only a bounded exception class is written; no traceback or paths.
        try:
            request_id = uuid.UUID(hex=request_path.parent.parent.name).hex
            result = GenerationResult(
                request_id, GenerationStatus.FAILED,
                error_records=({"code": "worker_crash", "stage": "worker",
                                "path": "worker",
                                "message": f"Worker startup failed ({type(exc).__name__})."},))
            _write_json_atomic(result_path, result.to_dict(), limit=_MAX_CONTROL_FILE)
        except BaseException:
            pass
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
