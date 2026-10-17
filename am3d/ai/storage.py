"""Private staging and immutable local-generation snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import uuid

from .contracts import (GenerationArtifact, GenerationRequest,
                        GenerationResult, GenerationStatus)
from .policy import MAX_RECIPE_BYTES, policy_snapshot
from am3d.recipes.resources import LIMITS


RECORD_VERSION = 1
_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_.])(?:[A-Za-z]:[\\/]|/)(?:[^\\/\s:'\"]+[\\/])*[^\\/\s:'\"]+")


def _safe_diagnostic(value, limit=600) -> str:
    return _ABSOLUTE_PATH.sub("<path>", str(value))[:limit]


def _safe_error_records(records) -> list[dict]:
    safe = []
    for item in list(records)[:100]:
        if not isinstance(item, dict):
            continue
        record = {
            "code": _safe_diagnostic(item.get("code", "generation_failed"), 80),
            "stage": _safe_diagnostic(item.get("stage", "worker"), 40),
            "path": _safe_diagnostic(item.get("path", "worker"), 200),
            "message": _safe_diagnostic(item.get("message", "Generation failed.")),
        }
        if item.get("hint"):
            record["hint"] = _safe_diagnostic(item["hint"])
        safe.append(record)
    return safe


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def application_data_root() -> Path:
    """Return the conventional per-user app-data directory without importing Qt."""
    override = os.environ.get("AM3D_DATA_HOME")
    if override:
        return Path(override).expanduser().resolve()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        return (Path(base or Path.home() / "AppData" / "Local") /
                "3DMASTER2005" / "3D MASTER 2005")
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support" /
                "3DMASTER2005" / "3D MASTER 2005")
    base = os.environ.get("XDG_DATA_HOME")
    return ((Path(base).expanduser() if base else
             Path.home() / ".local" / "share") /
            "3DMASTER2005" / "3D MASTER 2005")


@dataclass(frozen=True)
class GenerationAttempt:
    run_id: str
    worker_root: Path
    output_root: Path
    request_path: Path
    events_path: Path
    result_path: Path
    started_at: str


class GenerationStore:
    """Own run directories and publish successful snapshots atomically."""

    def __init__(self, data_root: str | os.PathLike | None = None):
        self.root = Path(data_root) if data_root is not None else application_data_root()
        self.root = self.root.expanduser().resolve()
        self.generations = self.root / "generations"
        self.failures = self.root / "generation-failures"
        self.private = self.root / ".generation-worker"

    def _prepare_roots(self) -> None:
        for path in (self.root, self.generations, self.failures, self.private,
                     self.generations / ".staging",
                     self.failures / ".staging"):
            if path.is_symlink():
                raise ValueError("generation data directories cannot be symlinks")
            path.mkdir(parents=True, exist_ok=True)
            try:
                path.chmod(0o700)
            except OSError:
                pass

    def new_attempt(self) -> GenerationAttempt:
        self._prepare_roots()
        for _ in range(8):
            run_id = uuid.uuid4().hex
            if ((self.generations / run_id).exists() or
                    (self.generations / run_id).is_symlink() or
                    (self.failures / run_id).exists() or
                    (self.failures / run_id).is_symlink()):
                continue
            worker_root = self.private / run_id
            try:
                worker_root.mkdir(mode=0o700)
            except FileExistsError:
                continue
            control = worker_root / ".control"
            output = worker_root / "output"
            control.mkdir(mode=0o700)
            (output / "exports").mkdir(parents=True, mode=0o700)
            return GenerationAttempt(
                run_id, worker_root, output / "exports",
                control / "request.json", control / "events.jsonl",
                control / "result.json", utc_now())
        raise FileExistsError("could not allocate a unique generation run id")

    @staticmethod
    def write_request(attempt: GenerationAttempt, recipe_json: str,
                      check_config: dict | None = None) -> GenerationRequest:
        request = GenerationRequest(
            run_id=attempt.run_id, recipe_json=recipe_json,
            output_root=str(attempt.output_root.resolve()),
            policy_snapshot=policy_snapshot(), check_config=check_config or {})
        raw = request.to_json().encode("utf-8")
        with attempt.request_path.open("xb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())
        return request

    @staticmethod
    def _write_json(path: Path, data: dict, max_bytes: int = 2 * 1024 * 1024) -> None:
        raw = json.dumps(data, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
        if len(raw) > max_bytes:
            raise ValueError("generation record exceeds its size limit")
        with path.open("xb") as fh:
            fh.write(raw)
            fh.flush()
            os.fsync(fh.fileno())

    @staticmethod
    def _hash(path: Path) -> str:
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for block in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(block)
        return h.hexdigest()

    @staticmethod
    def _safe_tree(root: Path) -> list[Path]:
        if root.is_symlink():
            raise ValueError("worker output root cannot be a symlink")
        resolved_root = root.resolve()
        files = []
        for current, dirs, names in os.walk(root, followlinks=False):
            current_path = Path(current)
            for name in list(dirs):
                item = current_path / name
                if item.is_symlink() or not _inside(resolved_root, item):
                    raise ValueError("worker output contains a symlink or escaped directory")
            for name in names:
                item = current_path / name
                if item.is_symlink():
                    raise ValueError("worker output contains a symlink artifact")
                if not item.is_file() or not _inside(resolved_root, item):
                    raise ValueError("worker output contains a non-file or escaped artifact")
                files.append(item)
        return files

    def publish_success(self, attempt: GenerationAttempt,
                        result: GenerationResult, recipe_json: str,
                        ended_at: str | None = None) -> GenerationResult:
        if result.run_id != attempt.run_id or result.status is not GenerationStatus.COMPLETE:
            raise ValueError("only the matching successful run can be published")
        output = attempt.worker_root / "output"
        if attempt.worker_root.is_symlink():
            raise ValueError("worker attempt root was replaced by a symlink")
        if (self.private.is_symlink() or
                attempt.worker_root.parent.resolve() != self.private.resolve()):
            raise ValueError("worker attempt escaped its private data directory")
        if output.is_symlink() or not _inside(attempt.worker_root, output):
            raise ValueError("worker output root escaped its private attempt directory")
        actual_files = self._safe_tree(output)
        declared = {}
        for item in result.artifacts:
            rel = Path(item.path)
            if rel.is_absolute() or ".." in rel.parts:
                raise ValueError("worker returned a non-relative artifact path")
            source = (output / rel).resolve()
            if not _inside(output, source) or not source.is_file() or source.is_symlink():
                raise ValueError("worker artifact is missing or escapes the output root")
            if source.stat().st_size != item.size_bytes or self._hash(source) != item.sha256:
                raise ValueError("worker artifact size or digest does not match its result")
            if item.path in declared:
                raise ValueError("worker returned duplicate artifact paths")
            declared[item.path] = (source, item)
        all_actual = {path.relative_to(output).as_posix() for path in actual_files}
        if all_actual != set(declared):
            raise ValueError("worker output contains undeclared or missing files")
        total = sum(item.size_bytes for _, item in declared.values())
        recipe_bytes = recipe_json.encode("utf-8")
        if len(recipe_bytes) > MAX_RECIPE_BYTES:
            raise ValueError("stored recipe exceeds the AI-mode limit")
        if total + len(recipe_bytes) > LIMITS["published_bytes"]:
            raise ValueError("generation artifacts exceed the publication byte ceiling")

        staging = self.generations / ".staging" / attempt.run_id
        final = self.generations / attempt.run_id
        if final.exists() or final.is_symlink():
            raise FileExistsError("generation run id already exists")
        staging.mkdir(mode=0o700)
        try:
            copied = []
            for rel, (source, item) in sorted(declared.items()):
                destination = staging / rel
                if not _inside(staging, destination):
                    raise ValueError("artifact path escapes generation staging")
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, destination)
                copied.append(GenerationArtifact(
                    rel, item.kind, destination.stat().st_size,
                    self._hash(destination), item.media_type))
            recipe_path = staging / "recipe.json"
            recipe_raw = recipe_bytes
            recipe_path.write_bytes(recipe_raw)
            recipe_hash = hashlib.sha256(recipe_raw).hexdigest()
            recipe_artifact = GenerationArtifact(
                "recipe.json", "recipe", len(recipe_raw), recipe_hash,
                "application/json")
            published_artifacts = (recipe_artifact, *copied)
            policy = policy_snapshot()
            record = {
                "record_version": RECORD_VERSION,
                "run_id": attempt.run_id,
                "parent_run_id": None,
                "started_at": attempt.started_at,
                "ended_at": ended_at or utc_now(),
                "application_version": self._app_version(),
                "build_identity": os.environ.get("AM3D_BUILD_ID") or None,
                "recipe_version": 1,
                "recipe_sha256": recipe_hash,
                "policy_version": policy["policy_version"],
                "policy_sha256": policy["sha256"],
                "check_version": 1,
                "status": "complete",
                "warnings": [_safe_diagnostic(item) for item in result.warnings[:100]],
                "error_records": [],
                "artifacts": [item.__dict__ for item in published_artifacts],
                "preview": {"path": "preview.png", "width": 512, "height": 512},
                "timing": {"elapsed_seconds": result.elapsed_seconds},
            }
            self._write_json(staging / "record.json", record)
            try:
                os.replace(staging, final)
            except FileExistsError:
                raise FileExistsError("generation destination appeared before publication")
            # The directory must remain writable while it is atomically
            # promoted on filesystems that require write access to the source
            # directory. Lock it immediately after the promotion completes.
            self._make_read_only(final)
        except BaseException:
            self._make_writable(staging)
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            self.cleanup_attempt(attempt)
        return GenerationResult(
            result.run_id, result.status, artifacts=tuple(published_artifacts),
            checks=result.checks, warnings=result.warnings,
            error_records=result.error_records,
            elapsed_seconds=result.elapsed_seconds,
            record_path=f"generations/{attempt.run_id}/record.json")

    def publish_failure(self, attempt: GenerationAttempt,
                        result: GenerationResult, recipe_json: str,
                        ended_at: str | None = None) -> GenerationResult:
        if result.run_id != attempt.run_id or result.status is GenerationStatus.COMPLETE:
            raise ValueError("failure result belongs to another run")
        staging = self.failures / ".staging" / attempt.run_id
        final = self.failures / attempt.run_id
        if final.exists() or final.is_symlink():
            raise FileExistsError("failed-generation destination already exists")
        staging.mkdir(mode=0o700)
        try:
            encoded_recipe = recipe_json.encode("utf-8")
            recipe_raw = encoded_recipe if len(encoded_recipe) <= MAX_RECIPE_BYTES else b""
            (staging / "recipe.json").write_bytes(recipe_raw)
            checks = {"check_version": 1,
                      "checks": [item.to_dict() for item in result.checks]}
            self._write_json(staging / "checks.json", checks, max_bytes=128 * 1024)
            record = {
                "record_version": RECORD_VERSION,
                "run_id": attempt.run_id,
                "started_at": attempt.started_at,
                "ended_at": ended_at or utc_now(),
                "application_version": self._app_version(),
                "recipe_sha256": hashlib.sha256(recipe_raw).hexdigest(),
                "recipe_omitted": len(encoded_recipe) > MAX_RECIPE_BYTES,
                "policy_version": policy_snapshot()["policy_version"],
                "policy_sha256": policy_snapshot()["sha256"],
                "check_version": 1,
                "status": result.status.value,
                "warnings": [_safe_diagnostic(item) for item in result.warnings[:100]],
                "error_records": _safe_error_records(result.error_records),
                "artifacts": [],
                "timing": {"elapsed_seconds": result.elapsed_seconds},
            }
            self._write_json(staging / "record.json", record, max_bytes=128 * 1024)
            try:
                os.replace(staging, final)
            except FileExistsError:
                raise FileExistsError("failed-generation destination already exists")
            self._make_read_only(final)
        except BaseException:
            self._make_writable(staging)
            shutil.rmtree(staging, ignore_errors=True)
            raise
        finally:
            self.cleanup_attempt(attempt)
        return GenerationResult(
            result.run_id, result.status, checks=result.checks,
            warnings=result.warnings, error_records=result.error_records,
            elapsed_seconds=result.elapsed_seconds,
            record_path=f"generation-failures/{attempt.run_id}/record.json")

    def create_writable_project_copy(self, run_id: str) -> Path:
        if not isinstance(run_id, str) or len(run_id) != 32 or any(
                char not in "0123456789abcdef" for char in run_id):
            raise ValueError("invalid generation run id")
        snapshot = self.generations / run_id
        if snapshot.is_symlink() or not _inside(self.generations, snapshot):
            raise ValueError("generation directory escaped its immutable storage root")
        record_path = snapshot / "record.json"
        if record_path.is_symlink() or not _inside(snapshot, record_path):
            raise ValueError("generation record escaped its immutable directory")
        record = json.loads(record_path.read_text(encoding="utf-8"))
        if record.get("run_id") != run_id or record.get("status") != "complete":
            raise ValueError("only a complete generation can be opened")
        artifact = next((item for item in record.get("artifacts", [])
                         if item.get("path") == "project.am3d"), None)
        if not artifact:
            raise ValueError("generation record has no native project")
        source = snapshot / artifact["path"]
        if (not source.is_file() or source.is_symlink() or
                source.stat().st_size != artifact.get("size_bytes") or
                self._hash(source) != artifact["sha256"]):
            raise ValueError("immutable generated project failed its integrity check")
        copies = self.root / "generated-working-copies"
        if copies.is_symlink() or not _inside(self.root, copies):
            raise ValueError("generated working-copy directory escaped app data")
        copies.mkdir(parents=True, exist_ok=True)
        if copies.is_symlink() or not copies.is_dir():
            raise ValueError("generated working-copy directory is unsafe")
        try:
            copies.chmod(0o700)
        except OSError:
            pass
        target = copies / f"{run_id}-{uuid.uuid4().hex}.am3d"
        temp = copies / f".{run_id}-{uuid.uuid4().hex}.tmp"
        try:
            with source.open("rb") as src, temp.open("xb") as dst:
                shutil.copyfileobj(src, dst, length=1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        try:
            target.chmod(stat.S_IRUSR | stat.S_IWUSR)
            from am3d.core.script import Session
            Session().load_project(str(target))
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        return target

    def cleanup_attempt(self, attempt: GenerationAttempt) -> None:
        self._make_writable(attempt.worker_root)
        shutil.rmtree(attempt.worker_root, ignore_errors=True)

    @staticmethod
    def _app_version() -> str:
        try:
            import am3d
            return str(am3d.__version__)
        except Exception:
            return "unknown"

    @classmethod
    def _make_read_only(cls, root: Path) -> None:
        for current, dirs, files in os.walk(root):
            current_path = Path(current)
            for name in files:
                try:
                    (current_path / name).chmod(0o444)
                except OSError:
                    pass
            for name in dirs:
                try:
                    (current_path / name).chmod(0o555)
                except OSError:
                    pass
        try:
            root.chmod(0o555)
        except OSError:
            pass

    @classmethod
    def _make_writable(cls, root: Path) -> None:
        if not root.exists():
            return
        for current, dirs, _ in os.walk(root):
            path = Path(current)
            try:
                path.chmod(0o700)
            except OSError:
                pass
            for name in dirs:
                try:
                    (path / name).chmod(0o700)
                except OSError:
                    pass


def _inside(root: Path, path: Path) -> bool:
    try:
        root = root.resolve()
        path = path.resolve()
        return os.path.commonpath((str(root), str(path))) == str(root)
    except (OSError, ValueError):
        return False
