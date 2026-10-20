"""Atomic, recoverable local records for checked V1 generations."""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
from datetime import datetime, timezone
import unicodedata
import uuid

from am3d.core.paths import (
    classify_portable_relative_path,
    extended_io_path,
    is_absolute_any_platform,
    split_segments,
)
from am3d.core.serializer import load_project, project_content_digest


_MAX_RECORD_BYTES = 2 * 1024 * 1024
_MAX_GENERATION_BYTES = 256 * 1024 * 1024
_MAX_FILES = 4096
_ARTIFACT_SUFFIXES = {".am3d", ".obj", ".glb", ".mtl", ".png", ".json"}
_PROTOCOL_FILES = {".ai_worker_input.json", ".ai_worker_result.json",
                   ".ai_worker_result.json.tmp"}
_ATTEMPT_STATUSES = {"running", "checking", "failed", "cancelled", "interrupted"}
_PRIVATE_STATUSES = _ATTEMPT_STATUSES | {"complete"}
_RECORD_METADATA = {"record.json", "recipe.json", "brief.json", "check-report.json"}
_CAPABILITY_VERSION = "recipe-v1-policy-v1-prompt-v1"


def application_identity() -> dict:
    """Return honest app/build identity for native provenance and run records.

    Frozen builds must ship ``am3d/build_identity.json`` to claim a build
    identity. Source runs instead hash runtime package sources, explicitly
    labeling that scope rather than implying a complete build-input digest.
    """
    import am3d

    version = str(getattr(am3d, "__version__", "unavailable"))[:256]
    identity_path = Path(__file__).resolve().parents[1] / "build_identity.json"
    if identity_path.is_file() and not _is_link(identity_path):
        try:
            raw = identity_path.read_bytes()
            if len(raw) <= 16 * 1024:
                value = json.loads(raw.decode("utf-8"))
                if (isinstance(value, dict)
                        and set(value) <= {"version", "build_id", "capability_version", "source_sha256"}
                        and isinstance(value.get("version"), str)
                        and isinstance(value.get("build_id"), str)
                        and isinstance(value.get("capability_version"), str)
                        and all(len(value[key]) <= 256 for key in ("version", "build_id", "capability_version"))
                        and ("source_sha256" not in value or
                             isinstance(value["source_sha256"], str)
                             and re.fullmatch(r"[0-9a-f]{64}", value["source_sha256"]))):
                    return {"version": value["version"],
                            "build_id": value["build_id"],
                            "capability_version": value["capability_version"]}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            pass
    if getattr(sys, "frozen", False) or hasattr(sys, "_MEIPASS"):
        return {"version": version, "build_id": "unavailable",
                "capability_version": _CAPABILITY_VERSION}

    package_root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    included = 0
    for path in sorted(package_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file() or path.suffix.casefold() not in {".py", ".qss"}:
            continue
        relative_parts = path.relative_to(package_root).parts
        if any(part in {"__pycache__", "tests", "test"} for part in relative_parts):
            continue
        if path.name.startswith("test_") or path.stem.endswith("_test"):
            continue
        if _is_link(path):
            continue
        relative = path.relative_to(package_root).as_posix().encode("utf-8")
        content = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
        included += 1
    # The recipe schema is shipped outside the Python package and is appended
    # verbatim to model context. Include its bytes and fixed context labels so
    # source-build identities change when the effective recipe vocabulary
    # changes, even if the runtime Python files do not.
    schema_path = package_root.parent / "docs" / "recipes" / "recipe-v1.schema.json"
    context = ("recipe-v1-policy-v1-prompt-v1\n"
               "recipe-v1-tested-vocabulary-v1\n"
               "phase2-prompts-v1\n"
               "docs/recipes/recipe-v1.schema.json\n").encode("utf-8")
    digest.update(len(context).to_bytes(4, "big"))
    digest.update(b"source-identity-context\0")
    digest.update(context)
    included += 1
    if schema_path.is_file() and not _is_link(schema_path):
        schema = schema_path.read_bytes()
        relative = b"docs/recipes/recipe-v1.schema.json"
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(schema).to_bytes(8, "big"))
        digest.update(schema)
    else:
        # A source checkout without its required prompt schema must not claim
        # the same identity as one with that shipped schema.
        digest.update(b"recipe-schema-unavailable")
    build_id = (f"source-code-sha256:{digest.hexdigest()}" if included
                else "unavailable")
    return {"version": version, "build_id": build_id,
            "capability_version": _CAPABILITY_VERSION}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_uuid(value: str | None = None) -> str:
    if value is None:
        return str(uuid.uuid4())
    try:
        parsed = uuid.UUID(value)
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError("generation id must be a UUID") from exc
    result = str(parsed)
    if result != value:
        raise ValueError("generation id must use canonical lowercase UUID text")
    return result


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _assert_no_links(path: Path, *, include_parents=False) -> Path:
    absolute = Path(extended_io_path(path))
    current = absolute
    while True:
        if current.exists() or current.is_symlink():
            if _is_link(current):
                raise ValueError("generation storage contains a symlink or junction")
        if current == current.parent or (not include_parents and current == absolute):
            break
        current = current.parent
    return absolute


def _assert_tree_has_no_links(root: Path) -> None:
    _assert_no_links(root, include_parents=True)
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        for name in [*dirs, *files]:
            if _is_link(base / name):
                raise ValueError("generation tree contains a symlink or junction")


def _atomic_json(path: Path, value: dict, *, limit=_MAX_RECORD_BYTES) -> None:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(payload) > limit:
        raise ValueError("generation record exceeds its size limit")
    path.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_links(path.parent, include_parents=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp",
                                     dir=os.fspath(path.parent))
    temp_path = Path(temporary)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
        try:
            directory_fd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except Exception:
            pass
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


def _read_json(path: Path) -> dict | None:
    try:
        if _is_link(path) or not path.is_file() or path.stat().st_size > _MAX_RECORD_BYTES:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        return None


def _relative_artifact(root: Path, raw: str) -> Path:
    if not isinstance(raw, str) or classify_portable_relative_path(raw) is not None:
        raise ValueError("manifest contains a non-portable relative path")
    parts = split_segments(raw)
    if not parts:
        raise ValueError("manifest path does not name an artifact")
    path = root.joinpath(*parts)
    _assert_no_links(path, include_parents=True)
    resolved_root = Path(os.path.realpath(root))
    resolved_path = Path(os.path.realpath(path))
    if os.path.commonpath((str(resolved_root), str(resolved_path))) != str(resolved_root):
        raise ValueError("manifest artifact resolves outside its candidate directory")
    return path


def _check_publish_interrupt(cancellation=None, deadline: float | None = None) -> None:
    from am3d.ai.contracts import DeadlineExceededError, GenerationCancelledError

    if cancellation is not None and cancellation.cancelled:
        raise GenerationCancelledError("Generation was cancelled before publication.")
    if deadline is not None:
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)):
            raise ValueError("deadline must be a finite monotonic timestamp")
        try:
            checked = float(deadline)
        except (OverflowError, ValueError):
            raise ValueError("deadline must be a finite monotonic timestamp") from None
        if not math.isfinite(checked):
            raise ValueError("deadline must be a finite monotonic timestamp")
        if time.monotonic() >= checked:
            raise DeadlineExceededError("The generation deadline expired before publication.")


def _artifact_manifest(root: Path, *, cancellation=None,
                       deadline: float | None = None) -> tuple[list[dict], int]:
    manifest = []
    total = 0
    portable_names = set()

    def register_portable(path: Path):
        relative = path.relative_to(root).as_posix()
        if classify_portable_relative_path(relative) is not None:
            raise ValueError("candidate contains a non-portable artifact path")
        key = unicodedata.normalize("NFC", relative).casefold()
        if key in portable_names:
            raise ValueError("candidate contains colliding portable paths")
        portable_names.add(key)

    _check_publish_interrupt(cancellation, deadline)
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        _check_publish_interrupt(cancellation, deadline)
        base = Path(current)
        dirs.sort()
        files.sort()
        for name in dirs:
            _check_publish_interrupt(cancellation, deadline)
            path = base / name
            _assert_no_links(path)
            register_portable(path)
        for name in files:
            _check_publish_interrupt(cancellation, deadline)
            path = base / name
            register_portable(path)
            if name in _PROTOCOL_FILES or path.relative_to(root).as_posix().startswith("tmp/"):
                continue
            if name == "record.json":
                continue  # A record cannot contain its own hash.
            _assert_no_links(path)
            if path.suffix.lower() not in _ARTIFACT_SUFFIXES or not path.is_file():
                raise ValueError("candidate contains an unapproved or non-file output")
            if path.suffix.lower() == ".json" and name not in _RECORD_METADATA:
                raise ValueError("candidate contains an unexpected JSON file")
            size = path.stat().st_size
            if size <= 0:
                raise ValueError("candidate contains an empty artifact")
            total += size
            if total > _MAX_GENERATION_BYTES:
                raise ValueError("candidate exceeds the 256 MiB output limit")
            manifest.append({"path": path.relative_to(root).as_posix(),
                             "sha256": _sha256(path, cancellation=cancellation,
                                               deadline=deadline), "bytes": size})
            if len(manifest) > _MAX_FILES:
                raise ValueError("candidate contains too many artifacts")
    return manifest, total


def _sha256(path: Path, *, cancellation=None,
            deadline: float | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while True:
            _check_publish_interrupt(cancellation, deadline)
            chunk = stream.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _copy_checked_artifact(source: Path, target: Path, item: dict, *,
                           cancellation=None, deadline: float | None = None) -> None:
    _check_publish_interrupt(cancellation, deadline)
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_links(target.parent, include_parents=True)
    digest = hashlib.sha256()
    copied = 0
    with source.open("rb") as src, target.open("xb") as dst:
        while True:
            _check_publish_interrupt(cancellation, deadline)
            chunk = src.read(1024 * 1024)
            if not chunk:
                break
            dst.write(chunk)
            digest.update(chunk)
            copied += len(chunk)
        dst.flush()
        os.fsync(dst.fileno())
    if copied != item["bytes"] or digest.hexdigest() != item["sha256"]:
        raise ValueError("checked artifact changed while creating the publication snapshot")
    _check_publish_interrupt(cancellation, deadline)


class GenerationAttempt:
    """A private run with isolated, never-overwritten candidate directories."""

    def __init__(self, store: "GenerationRecordStore", run_id: str,
                 parent_generation_id: str | None):
        self.store = store
        self.run_id = run_id
        self.parent_generation_id = parent_generation_id
        self.attempt_dir = store.attempts_root / run_id
        self.root = store.root
        self.final_dir = store.generations_root / run_id
        if self.final_dir.exists() or self.final_dir.is_symlink():
            raise FileExistsError("generation id already has a published record")
        self.attempt_dir.mkdir(mode=0o700, parents=False, exist_ok=False)
        self.candidates_dir = self.attempt_dir / "candidates"
        self.candidates_dir.mkdir(mode=0o700)
        self.write_state("running", {"parent_generation_id": parent_generation_id})

    def candidate_dir(self, candidate_id: str | int) -> Path:
        if isinstance(candidate_id, int) and not isinstance(candidate_id, bool):
            name = f"candidate-{candidate_id:02d}"
        else:
            name = str(candidate_id)
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", name):
                raise ValueError("candidate id must contain only letters, digits, '_' or '-'")
        path = self.candidates_dir / name
        _assert_no_links(self.candidates_dir, include_parents=True)
        path.mkdir(mode=0o700, exist_ok=False)
        return path

    def write_state(self, status: str, record: dict | None = None) -> Path:
        if status not in _PRIVATE_STATUSES:
            raise ValueError("private attempt status is invalid")
        if record is None:
            record = {}
        if not isinstance(record, dict):
            raise TypeError("attempt state must be a JSON object")
        value = {"run_id": self.run_id, "parent_generation_id": self.parent_generation_id,
                 "status": status, "updated_utc": _utc_now(), "record": record}
        path = self.attempt_dir / "state.json"
        _atomic_json(path, value)
        return path

    def publish(self, candidate_dir: str | Path, record: dict,
                check_report: dict, *, cancellation=None,
                deadline: float | None = None) -> Path:
        """Promote one checked candidate directory to immutable run history."""
        candidate = Path(extended_io_path(candidate_dir))
        try:
            candidate.relative_to(self.candidates_dir.resolve())
        except ValueError as exc:
            raise ValueError("published candidate must be a private child of this run") from exc
        _assert_no_links(candidate, include_parents=True)
        if not candidate.is_dir() or self.final_dir.exists() or self.final_dir.is_symlink():
            raise FileExistsError("candidate or final generation directory is unavailable")
        if not isinstance(check_report, dict) or check_report.get("status") != "passed" or check_report.get("ok") is not True:
            raise ValueError("only a checker-passed candidate can be published")
        if not isinstance(record, dict):
            raise TypeError("generation record must be an object")
        claimed = check_report.get("artifacts")
        if not isinstance(claimed, list) or not claimed:
            raise ValueError("checked candidate has no artifact manifest")
        claimed_by_path = {}
        for item in claimed:
            _check_publish_interrupt(cancellation, deadline)
            if not isinstance(item, dict):
                raise ValueError("checker artifact manifest is invalid")
            relative = item.get("path")
            if (set(item) != {"path", "sha256", "bytes"}
                    or not isinstance(relative, str)
                    or isinstance(item.get("bytes"), bool)
                    or not isinstance(item.get("bytes"), int)
                    or item["bytes"] <= 0
                    or not isinstance(item.get("sha256"), str)
                    or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                    or relative in claimed_by_path):
                raise ValueError("checker artifact manifest entry is invalid")
            path = _relative_artifact(candidate, relative)
            if not path.is_file() or path.stat().st_size != item.get("bytes"):
                raise ValueError("checked artifact size changed before publication")
            if _sha256(path, cancellation=cancellation, deadline=deadline) != item.get("sha256"):
                raise ValueError("checked artifact hash changed before publication")
            claimed_by_path[relative] = item
        claimed_manifest = sorted(claimed, key=lambda item: item["path"])
        # Re-scan the entire candidate using the exact byte/hash tuples from
        # the checker report. Path-set equality alone would let altered,
        # unchecked bytes become the record's new claimed contents.
        source_manifest, _source_bytes = _artifact_manifest(
            candidate, cancellation=cancellation, deadline=deadline)
        if source_manifest != claimed_manifest:
            raise ValueError("candidate artifacts differ from the checker-verified manifest")
        if len(check_report.get("checks", [])) > 4096:
            raise ValueError("checker report exceeds record limits")
        _check_publish_interrupt(cancellation, deadline)
        # Copy only the already-checked files into a host-private snapshot on
        # the same volume as final history. Worker output remains separate;
        # the checked hashes must match during the copy and in the final audit.
        staging = self.attempt_dir / f"publication-{uuid.uuid4().hex}"
        _assert_no_links(self.attempt_dir, include_parents=True)
        staging.mkdir(mode=0o700, exist_ok=False)
        try:
            for item in claimed_manifest:
                _check_publish_interrupt(cancellation, deadline)
                source = _relative_artifact(candidate, item["path"])
                target = _relative_artifact(staging, item["path"])
                _copy_checked_artifact(source, target, item,
                                       cancellation=cancellation, deadline=deadline)
            staged_manifest, total = _artifact_manifest(
                staging, cancellation=cancellation, deadline=deadline)
            if staged_manifest != claimed_manifest:
                raise ValueError("publication snapshot differs from checker-verified artifacts")

            complete_record = dict(record)
            complete_record.update({"run_id": self.run_id, "status": "complete",
                                    "parent_generation_id": self.parent_generation_id,
                                    "completed_utc": _utc_now(),
                                    "artifact_manifest": staged_manifest,
                                    "artifact_bytes": total,
                                    "check_report": check_report})
            sidecars = {}
            recipe = complete_record.get("accepted_recipe", complete_record.get("recipe"))
            brief = complete_record.get("accepted_brief", complete_record.get("brief"))
            if isinstance(recipe, dict):
                sidecars["recipe.json"] = recipe
            if brief is not None:
                sidecars["brief.json"] = brief
            sidecars["check-report.json"] = check_report
            for name, value in sidecars.items():
                _check_publish_interrupt(cancellation, deadline)
                _atomic_json(staging / name, value, limit=_MAX_RECORD_BYTES)
            sidecar_manifest, _sidecar_bytes = _artifact_manifest(
                staging, cancellation=cancellation, deadline=deadline)
            sidecars_by_path = {item["path"]: item for item in sidecar_manifest}
            if any(sidecars_by_path.get(item["path"]) != item for item in claimed_manifest):
                raise ValueError("publication sidecars changed checker-verified artifacts")
            complete_record["artifact_manifest"] = sidecar_manifest
            _check_publish_interrupt(cancellation, deadline)
            _atomic_json(staging / "record.json", complete_record)
            _check_publish_interrupt(cancellation, deadline)

            saved_record = _read_json(staging / "record.json")
            if (not saved_record or saved_record.get("run_id") != self.run_id
                    or saved_record.get("check_report") != check_report):
                raise OSError("generation record could not be read after atomic write")
            verify_manifest, _ = _artifact_manifest(
                staging, cancellation=cancellation, deadline=deadline)
            if verify_manifest != sidecar_manifest:
                raise OSError("publication snapshot changed during final verification")
            verify_by_path = {item["path"]: item for item in verify_manifest}
            if any(verify_by_path.get(item["path"]) != item for item in claimed_manifest):
                raise OSError("final snapshot no longer matches checker-verified artifacts")
            _assert_no_links(staging, include_parents=True)
            self.store.generations_root.mkdir(parents=True, exist_ok=True)
            _assert_no_links(self.store.generations_root, include_parents=True)
            _check_publish_interrupt(cancellation, deadline)
            promote = lambda: os.replace(staging, self.final_dir)
            if cancellation is None:
                if deadline is None:
                    promote()
                else:
                    from am3d.ai.contracts import CancellationToken
                    CancellationToken().commit(promote, deadline=deadline)
            else:
                cancellation.commit(promote, deadline=deadline)
        except Exception:
            if staging.exists() and not _is_link(staging):
                shutil.rmtree(staging)
            raise

        # The atomic rename is the commit point. A failure writing the
        # redundant attempt journal must never relabel an already-published
        # immutable generation as failed. Recovery deduplicates by run UUID.
        try:
            self.write_state("complete", {"published": True,
                                           "final_dir": self.final_dir.name,
                                           "status": "complete"})
        except Exception:
            pass
        return self.final_dir


class GenerationRecordStore:
    """Atomic generation snapshots plus rebuildable history from record files."""

    def __init__(self, root: str | Path):
        self.root = Path(extended_io_path(root))
        self.generations_root = self.root / "generations"
        self.attempts_root = self.root / ".generation-attempts"
        _assert_no_links(self.root, include_parents=True)
        self.root.mkdir(parents=True, exist_ok=True)
        self.generations_root.mkdir(parents=True, exist_ok=True)
        self.attempts_root.mkdir(parents=True, exist_ok=True)
        _assert_no_links(self.root, include_parents=True)

    def begin(self, run_id: str | None = None,
              parent_generation_id: str | None = None) -> GenerationAttempt:
        run_id = _canonical_uuid(run_id)
        if parent_generation_id is not None:
            parent_generation_id = _canonical_uuid(parent_generation_id)
        _assert_no_links(self.attempts_root, include_parents=True)
        return GenerationAttempt(self, run_id, parent_generation_id)

    def recover_interrupted(self) -> list[dict]:
        recovered = []
        for path in sorted(self.attempts_root.iterdir()):
            if _is_link(path) or not path.is_dir():
                continue
            state_path = path / "state.json"
            state = _read_json(state_path)
            run_id = path.name
            try:
                _canonical_uuid(run_id)
            except ValueError:
                continue
            if self.generations_root.joinpath(run_id).exists():
                # Promotion commits before its best-effort journal update.
                # A crash in that small window leaves a valid completed
                # record and a stale "checking" state; repair it from the
                # authoritative immutable snapshot.
                try:
                    self.get_record(run_id)
                    state = state or {"run_id": run_id, "record": {}}
                    state.update({"status": "complete", "updated_utc": _utc_now(),
                                  "record": {"published": True, "status": "complete"}})
                    _atomic_json(state_path, state)
                except (OSError, ValueError, FileNotFoundError):
                    pass
                continue
            if state is None:
                state = {"run_id": run_id, "status": "running", "record": {}}
            if state.get("status") in {"running", "checking"}:
                state["status"] = "interrupted"
                state["updated_utc"] = _utc_now()
                _atomic_json(state_path, state)
                recovered.append(state)
        return recovered

    def list_records(self) -> list[dict]:
        """Rebuild history from immutable record.json and bounded attempt states."""
        records = []
        complete_ids = set()
        for path in sorted(self.generations_root.iterdir()):
            if _is_link(path) or not path.is_dir():
                continue
            record = _read_json(path / "record.json")
            if (record is not None and record.get("status") == "complete"
                    and record.get("run_id") == path.name):
                complete_ids.add(path.name)
                record["run_root"] = str(path)
                record["project_path"] = str(path / "project.am3d")
                records.append(record)
        for path in sorted(self.attempts_root.iterdir()):
            if _is_link(path) or not path.is_dir():
                continue
            state = _read_json(path / "state.json")
            if (path.name in complete_ids or state is None
                    or state.get("status") not in _ATTEMPT_STATUSES):
                continue
            state["run_root"] = str(path)
            state["successful"] = False
            state["retryable"] = state.get("status") in {"failed", "cancelled", "interrupted"}
            records.append(state)
        return sorted(records, key=lambda item: str(item.get("completed_utc")
                                                     or item.get("updated_utc") or ""),
                       reverse=True)

    def get_record(self, run_id: str) -> dict:
        """Read one completed record and verify its immutable native project."""
        run_id = _canonical_uuid(run_id)
        run_root = self.generations_root / run_id
        _assert_no_links(run_root, include_parents=True)
        record = _read_json(run_root / "record.json")
        if not record or record.get("run_id") != run_id or record.get("status") != "complete":
            raise FileNotFoundError("completed generation record is missing")
        manifest = record.get("artifact_manifest")
        if not isinstance(manifest, list):
            raise ValueError("generation record has no artifact manifest")
        _assert_tree_has_no_links(run_root)
        actual, _total = _artifact_manifest(run_root)
        if actual != manifest:
            raise OSError("completed generation artifact manifest failed verification")
        native_entry = next((item for item in manifest
                             if isinstance(item, dict) and item.get("path") == "project.am3d"), None)
        if native_entry is None:
            raise FileNotFoundError("completed generation has no native project")
        native = _relative_artifact(run_root, "project.am3d")
        if not native.is_file() or native.stat().st_size != native_entry.get("bytes"):
            raise OSError("completed generation native project failed its size check")
        record["run_root"] = str(run_root)
        record["project_path"] = str(native)
        return record

    def delete(self, run_id: str, *, confirm_parent: bool = False) -> dict:
        run_id = _canonical_uuid(run_id)
        target = self.generations_root / run_id
        attempt = self.attempts_root / run_id
        if target.is_symlink() or attempt.is_symlink():
            raise ValueError("generation history contains a linked run directory")
        if target.exists():
            _assert_tree_has_no_links(target)
            children = []
            for record in self.list_records():
                if record.get("status") == "complete" and record.get("parent_generation_id") == run_id:
                    children.append(record.get("run_id"))
            if children and not confirm_parent:
                return {"deleted": False, "needs_parent_confirmation": True,
                        "child_generation_ids": children}
            shutil.rmtree(target)
            if attempt.exists():
                _assert_tree_has_no_links(attempt)
                shutil.rmtree(attempt)
            return {"deleted": True, "child_generation_ids": children}
        if attempt.exists():
            _assert_tree_has_no_links(attempt)
            shutil.rmtree(attempt)
            return {"deleted": True, "child_generation_ids": []}
        return {"deleted": False, "reason": "not_found", "child_generation_ids": []}

    def create_working_copy(self, record_or_path: dict | str | Path,
                            target_dir: str | Path) -> dict:
        return create_working_copy(record_or_path, target_dir)


def create_working_copy(record_or_path: dict | str | Path,
                        target_dir: str | Path) -> dict:
    """Create a writable, verified copy of a saved generation project.

    Copies native project-relative image resources (including generated atlas
    sidecars) while keeping the immutable history directory untouched.
    """
    if isinstance(record_or_path, dict):
        if record_or_path.get("status") != "complete" or not record_or_path.get("run_id"):
            raise ValueError("working copy source must be a completed generation record")
        run_id = _canonical_uuid(record_or_path.get("run_id"))
        source_value = record_or_path.get("run_root")
        if not source_value:
            raise ValueError("generation record does not identify a saved project")
        source = Path(extended_io_path(source_value))
        if source.name != run_id or source.parent.name != "generations":
            raise ValueError("generation record path is not an immutable history directory")
        _assert_no_links(source, include_parents=True)
        if not source.is_dir():
            raise FileNotFoundError("immutable generation directory is missing")
        disk_record = _read_json(source / "record.json")
        if not disk_record or disk_record.get("run_id") != run_id or disk_record.get("status") != "complete":
            raise ValueError("working copy source record does not match its saved authority")
        record_manifest = disk_record.get("artifact_manifest", [])
        if not isinstance(record_manifest, list):
            raise ValueError("working copy source has no valid artifact manifest")
        _assert_tree_has_no_links(source)
        actual_manifest, _ = _artifact_manifest(source)
        if actual_manifest != record_manifest:
            raise OSError("working copy source artifacts failed their recorded hashes")
        project_entry = next((item for item in record_manifest
                              if isinstance(item, dict) and item.get("path") == "project.am3d"), None)
        if not isinstance(project_entry, dict):
            raise ValueError("working copy source has no verified native project")
    else:
        source = Path(record_or_path)
    source = Path(extended_io_path(source))
    _assert_no_links(source, include_parents=True)
    if source.is_file():
        project_source = source
        source_root = source.parent
    else:
        source_root = source
        project_source = source_root / "project.am3d"
    if not project_source.is_file() or project_source.suffix.lower() != ".am3d":
        raise FileNotFoundError("saved generation project.am3d is missing")
    _assert_no_links(project_source, include_parents=True)
    if isinstance(record_or_path, dict):
        if (project_source.stat().st_size != project_entry.get("bytes")
                or _sha256(project_source) != project_entry.get("sha256")):
            raise OSError("working copy source project failed its recorded hash")
    target = Path(extended_io_path(target_dir))
    _assert_no_links(target.parent, include_parents=True)
    try:
        if os.path.commonpath((str(source_root.resolve()), str(target.resolve()))) == str(source_root.resolve()):
            raise ValueError("working copy must be outside the immutable generation directory")
    except ValueError as exc:
        if "working copy" in str(exc):
            raise
    if target.exists() or target.is_symlink():
        raise FileExistsError("working copy destination already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    _assert_no_links(target.parent, include_parents=True)
    staging = target.parent / f".{target.name}.copy-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    try:
        project = load_project(str(project_source))
        resources = set()
        for material in project.materials.values():
            for attr in ("texture", "bump_map", "transparency_map", "specular_map"):
                value = getattr(material, attr, None)
                if not isinstance(value, str) or not value:
                    continue
                if is_absolute_any_platform(value):
                    continue  # the native project keeps its existing external reference
                if classify_portable_relative_path(value) is not None:
                    raise ValueError("relative project resource path is unsafe")
                parts = split_segments(value)
                if not parts:
                    continue
                source_resource = source_root.joinpath(*parts)
                if not source_resource.exists():
                    raise FileNotFoundError(f"relative project resource is missing: {Path(value).name}")
                _assert_no_links(source_resource, include_parents=True)
                try:
                    source_resource.resolve().relative_to(source_root.resolve())
                except ValueError as exc:
                    raise ValueError("relative project resource escapes generation directory") from exc
                resources.add((source_resource, Path(*parts)))
        project_target = staging / project_source.name
        shutil.copy2(project_source, project_target)
        copied = []
        for source_resource, relative in sorted(resources, key=lambda pair: pair[1].as_posix()):
            target_resource = staging / relative
            target_resource.parent.mkdir(parents=True, exist_ok=True)
            _assert_no_links(target_resource.parent, include_parents=True)
            shutil.copy2(source_resource, target_resource)
            copied.append({"path": relative.as_posix(), "sha256": _sha256(target_resource),
                           "bytes": target_resource.stat().st_size})
        reopened = load_project(str(project_target))
        if (project_content_digest(project) != project_content_digest(reopened)):
            raise OSError("working copy changed native project content")
        if _sha256(project_source) != _sha256(project_target):
            raise OSError("working copy native project hash does not match its source")
        os.replace(staging, target)
        final_project = target / project_source.name
        return {"run_root": str(target), "project_path": str(final_project),
                "project_sha256": _sha256(final_project), "resources": copied}
    except Exception:
        if staging.exists() and not _is_link(staging):
            shutil.rmtree(staging)
        raise
