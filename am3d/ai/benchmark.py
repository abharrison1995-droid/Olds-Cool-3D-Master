"""Frozen V1 benchmark manifests, run journals, and human score imports.

The runner deliberately treats every fixture as fixed caller-authored input.
Offline fake and replay runs exercise the same ledger, but can never qualify a
release gate.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import tempfile
import uuid
from typing import Any, Callable, Iterable, Mapping


RELEASE_IDS = tuple(f"{index:02d}" for index in range(1, 31))
DISCOVERY_IDS = tuple(f"D{index:02d}" for index in range(1, 9))
RELEASE_STATIC_IDS = tuple(f"{index:02d}" for index in range(1, 26))
RELEASE_RIG_IDS = tuple(f"{index:02d}" for index in range(26, 31))
RUN_SCHEMA_VERSION = 1
HUMAN_SCHEMA_VERSION = 1
GENERATION_RECEIPT_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_REVIEWER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@+-]{0,127}$")
_HUMAN_FIELDS = ("recognizable_silhouette", "essential_components",
                 "proportions_and_appearance", "editability")
_LIVE_DRIFT_DISCLOSURE = (
    "The configured provider/model identifier is frozen in the manifest. "
    "An upstream alias may change behavior over time; identical identifiers "
    "do not prove identical provider snapshots."
)
_COST_DISCLOSURE = (
    "Completion output tokens are reserved against the declared benchmark "
    "ceiling. Input/prompt token consumption and dollar cost cannot be bounded "
    "by this provider contract. No tariff is assumed; actual cost remains null "
    "unless the provider supplies a measured value."
)


class BenchmarkError(ValueError):
    """A bounded benchmark input, journal, or scoring file is invalid."""


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def sha256_text_file(path: str | Path) -> str:
    """Hash UTF-8 text with universal newlines for checkout-independent inputs."""
    raw = Path(path).read_bytes()
    return sha256_bytes(raw.replace(b"\r\n", b"\n"))


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def atomic_write_json(path: str | Path, value: Any) -> None:
    """Write one JSON snapshot through a same-directory atomic replacement."""
    target = Path(path)
    assert_no_links(target.parent)
    target.parent.mkdir(parents=True, exist_ok=True)
    assert_no_links(target.parent)
    assert_no_links(target, include_parents=False)
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                     allow_nan=False).encode("utf-8") + b"\n"
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                             0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        os.replace(temporary, target)
        if os.name != "nt":
            try:
                directory = os.open(target.parent, os.O_RDONLY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            except OSError:
                pass
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _read_json(path: str | Path) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise BenchmarkError("benchmark JSON could not be read") from None


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    attributes = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    )


def assert_no_links(path: str | Path, *, include_parents: bool = True) -> Path:
    absolute = Path(os.path.abspath(path))
    current = absolute
    while True:
        if (current.exists() or current.is_symlink()) and _is_link(current):
            raise BenchmarkError("benchmark storage contains a symlink or junction")
        if current == current.parent or (not include_parents and current == absolute):
            break
        current = current.parent
    return absolute


def _repo_root(path: str | Path) -> Path:
    candidate = Path(path).resolve()
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=candidate,
            check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        root = Path(os.fsdecode(result.stdout.strip())).resolve()
    except (OSError, subprocess.CalledProcessError):
        raise BenchmarkError("benchmark must run from a Git checkout") from None
    return root


def _git_bytes(root: Path, *arguments: str) -> bytes:
    try:
        return subprocess.run(["git", *arguments], cwd=root, check=True,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL).stdout
    except (OSError, subprocess.CalledProcessError):
        raise BenchmarkError("Git source identity could not be captured") from None


def _dirty_diff_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    digest.update(_git_bytes(root, "diff", "--binary", "HEAD", "--"))
    untracked = _git_bytes(root, "ls-files", "--others", "--exclude-standard", "-z")
    for encoded in sorted(item for item in untracked.split(b"\0") if item):
        relative = os.fsdecode(encoded)
        path = root / relative
        if not path.is_file() or _is_link(path):
            digest.update(b"untracked-unreadable\0")
            digest.update(encoded)
            continue
        digest.update(b"untracked\0")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
        content = path.read_bytes()
        digest.update(len(content).to_bytes(8, "big"))
        digest.update(content)
    return digest.hexdigest()


def _runtime_files(root: Path) -> dict[str, str]:
    selected: set[Path] = set()
    source_root = root / "am3d"
    if source_root.is_dir():
        selected.update(path for path in source_root.rglob("*")
                        if path.is_file() and not _is_link(path)
                        and "__pycache__" not in path.parts
                        and path.suffix not in {".pyc", ".pyo"})
    fixture_root = root / "benchmarks" / "v1"
    if fixture_root.is_dir():
        selected.update(path for path in fixture_root.iterdir()
                        if path.is_file() and not _is_link(path))
    for name in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
                 "requirements-lock.txt", "requirements-lock-linux.txt",
                 "requirements-lock-windows.txt", "requirements-lock-win.txt",
                 "Pipfile", "Pipfile.lock", "uv.lock", "poetry.lock"):
        path = root / name
        if path.is_file() and not _is_link(path):
            selected.add(path)
    schema = root / "docs" / "recipes" / "recipe-v1.schema.json"
    if schema.is_file() and not _is_link(schema):
        selected.add(schema)
    result: dict[str, str] = {}
    for path in sorted(selected, key=lambda item: item.relative_to(root).as_posix()):
        result[path.relative_to(root).as_posix()] = sha256_file(path)
    return result


def _package_versions() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for name in ("numpy", "msgpack", "PySide6", "Pillow", "httpx", "keyring", "pytest"):
        try:
            result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            result[name] = None
    return result


def source_snapshot(repo_root: str | Path) -> dict[str, Any]:
    root = _repo_root(repo_root)
    head = _git_bytes(root, "rev-parse", "HEAD").decode("ascii").strip()
    try:
        from .records import application_identity
        app_identity: Mapping[str, Any] = application_identity()
    except Exception:
        app_identity = {}
    return {
        "baseline_head": head,
        "dirty_diff_sha256": _dirty_diff_sha256(root),
        "runtime_build_inputs": _runtime_files(root),
        "application_identity": dict(app_identity),
        "python": {
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
            "cache_tag": getattr(sys.implementation, "cache_tag", None),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "package_versions": _package_versions(),
    }


def _file_hashes(repo_root: Path) -> dict[str, str]:
    return {
        "benchmarks/v1/prompts.json": sha256_text_file(repo_root / "benchmarks/v1/prompts.json"),
        "benchmarks/v1/discovery.json": sha256_text_file(repo_root / "benchmarks/v1/discovery.json"),
        "benchmarks/v1/rubric.md": sha256_text_file(repo_root / "benchmarks/v1/rubric.md"),
        "docs/recipes/recipe-v1.schema.json": sha256_text_file(
            repo_root / "docs/recipes/recipe-v1.schema.json"),
    }


def load_fixture_set(repo_root: str | Path, scope: str = "release") -> tuple[dict, list[dict]]:
    root = _repo_root(repo_root)
    if scope == "release":
        document = _read_json(root / "benchmarks/v1/prompts.json")
        rows = document.get("items") if isinstance(document, dict) else None
        expected_ids = RELEASE_IDS
        fixture_name = "v1-release"
    elif scope == "discovery":
        document = _read_json(root / "benchmarks/v1/discovery.json")
        rows = document.get("entries") if isinstance(document, dict) else None
        expected_ids = DISCOVERY_IDS
        fixture_name = "v1-discovery"
    else:
        raise BenchmarkError("scope must be release or discovery")
    if (not isinstance(document, dict) or document.get("frozen") is not True
            or document.get("fixture_set") != fixture_name
            or not isinstance(rows, list)):
        raise BenchmarkError("frozen fixture document has an invalid contract")
    identifiers = [item.get("id") for item in rows if isinstance(item, dict)]
    if len(rows) != len(expected_ids) or tuple(identifiers) != expected_ids:
        raise BenchmarkError("frozen fixtures do not match their fixed denominator")
    for item in rows:
        if not isinstance(item.get("prompt"), str) or not item["prompt"].strip():
            raise BenchmarkError("frozen fixture prompt is missing")
    if scope == "release":
        tiers = [item.get("tier") for item in rows]
        if tiers != ["static"] * 25 + ["rig"] * 5:
            raise BenchmarkError("release fixture tier allocation changed")
    return document, deepcopy(rows)


def fixture_requirements(fixture: Mapping[str, Any]) -> dict[str, Any]:
    """Return fixture-owned assertions in the existing independent-checker contract."""
    # The frozen entry already uses the checker's caller-authored contract,
    # including requirements.expected_disclosures. Preserve every assertion
    # as-is and remove only its prompt and identity metadata.
    return {key: deepcopy(value) for key, value in fixture.items()
            if key not in {"id", "tier", "prompt"}}


def prompt_metadata() -> dict[str, Any]:
    from .prompts import prompt_context_metadata
    result = prompt_context_metadata()
    expected = {"prompt_template_version", "prompt_template_sha256",
                "capability_context_version", "capability_context_sha256",
                "recipe_schema_sha256"}
    if set(result) != expected or any(not isinstance(value, str) for value in result.values()):
        raise BenchmarkError("prompt, capability, or schema identity is incomplete")
    return dict(result)


def _fixture_hashes(fixtures: list[dict]) -> dict[str, str]:
    return {item["id"]: sha256_bytes(canonical_json(item)) for item in fixtures}


def build_manifest(repo_root: str | Path, *, scope: str, mode: str,
                   provider: Mapping[str, Any], limits: Mapping[str, int],
                   run_uuid: str | None = None,
                   replay_sha256: str | None = None) -> dict[str, Any]:
    root = _repo_root(repo_root)
    if mode not in {"live", "fake", "replay"}:
        raise BenchmarkError("mode must be live, fake, or replay")
    document, fixtures = load_fixture_set(root, scope)
    if set(limits) != {"max_semantic_calls", "completion_output_tokens"}:
        raise BenchmarkError("run ceilings must declare semantic calls and completion output tokens")
    for name, value in limits.items():
        if type(value) is not int or value <= 0:
            raise BenchmarkError("run ceilings must be positive integers")
    if limits["max_semantic_calls"] > (150 if scope == "release" else 40):
        raise BenchmarkError("semantic-call ceiling exceeds the fixed per-scope bound")
    if limits["completion_output_tokens"] > limits["max_semantic_calls"] * 8192:
        raise BenchmarkError("completion output reservation exceeds the fixed per-call output caps")
    fixture_ids = RELEASE_IDS if scope == "release" else DISCOVERY_IDS
    if set(item["id"] for item in fixtures) != set(fixture_ids):
        raise BenchmarkError("fixture IDs do not match the fixed denominator")
    provider_data = dict(provider)
    if not isinstance(provider_data.get("provider_id"), str) or not provider_data["provider_id"]:
        raise BenchmarkError("provider identifier is required")
    if not isinstance(provider_data.get("model"), str) or not provider_data["model"]:
        raise BenchmarkError("explicit model identifier is required")
    if mode in {"fake", "replay"}:
        provider_data["provider_id"] = "offline-fake" if mode == "fake" else "offline-replay"
        provider_data["drift_disclosure"] = "Offline fixture provider; this execution cannot qualify a live benchmark."
    else:
        provider_data["drift_disclosure"] = _LIVE_DRIFT_DISCLOSURE
    fixture_paths = _file_hashes(root)
    if scope == "release":
        selected_fixture_path = "benchmarks/v1/prompts.json"
    else:
        selected_fixture_path = "benchmarks/v1/discovery.json"
    run_uuid = run_uuid or str(uuid.uuid4())
    if str(uuid.UUID(run_uuid)) != run_uuid:
        raise BenchmarkError("run UUID must use canonical lowercase text")
    frozen_inputs = {
        "source": source_snapshot(root),
        "fixture_files": fixture_paths,
        "selected_fixture_sha256": fixture_paths[selected_fixture_path],
        "fixture_item_sha256": _fixture_hashes(fixtures),
        "prompt_context": prompt_metadata(),
    }
    max_item_calls = 5
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_uuid": run_uuid,
        "created_utc": utc_now(),
        "scope": scope,
        "fixture_set": document["fixture_set"],
        "mode": mode,
        "qualifying_mode": mode == "live" and scope == "release",
        "qualification_label": "NONQUALIFYING" if mode != "live" or scope != "release" else "LIVE_UNQUALIFIED_PENDING_GATES",
        "denominator": len(fixtures),
        "fixture_ids": list(fixture_ids),
        "tiers": {"static_ids": list(RELEASE_STATIC_IDS), "rig_ids": list(RELEASE_RIG_IDS)}
        if scope == "release" else None,
        "provider": provider_data,
        "model_drift_disclosure": provider_data["drift_disclosure"],
        "token_and_cost_disclosure": _COST_DISCLOSURE,
        "limits": {
            "max_semantic_calls": limits["max_semantic_calls"],
            "completion_output_token_reservation": limits["completion_output_tokens"],
            "max_semantic_calls_per_item": max_item_calls,
            "max_candidates_per_item": 4,
            "max_http_attempts_per_semantic_call": 2 if mode == "live" else 0,
            "http_attempts_actual": None,
            "http_attempts_conservative_upper_bound": limits["max_semantic_calls"] * 2 if mode == "live" else 0,
            "http_attempts_upper_bound_basis": "provider contract and tested retry limit; actual transport attempts are not exposed by this adapter" if mode == "live" else "offline provider; no network requests",
            "input_token_budget": None,
            "dollar_cost_budget": None,
            "actual_cost_usd": None,
        },
        "replay_sha256": replay_sha256,
        "frozen_inputs": frozen_inputs,
    }


def manifest_sha256(manifest: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json(dict(manifest)))


def new_journal(manifest: dict, fixtures: list[dict]) -> dict:
    ids = RELEASE_IDS if manifest["scope"] == "release" else DISCOVERY_IDS
    by_id = {item["id"]: item for item in fixtures}
    if tuple(by_id) != tuple(ids):
        raise BenchmarkError("journal fixture order does not match its fixed IDs")
    digest = manifest_sha256(manifest)
    return {
        "schema_version": RUN_SCHEMA_VERSION,
        "run_uuid": manifest["run_uuid"],
        "manifest_sha256": digest,
        "manifest": manifest,
        "status": "created",
        "started_utc": None,
        "completed_utc": None,
        "resume_count": 0,
        "items": [
            {"id": item_id, "fixture_sha256": manifest["frozen_inputs"]["fixture_item_sha256"][item_id],
             "status": "pending", "started_utc": None, "completed_utc": None,
             "generation_id": None, "generation_receipt": None,
             "deterministic_pass": False,
             "failure_class": None, "failure_code": None,
             "checks": [],
             "candidate_count": 0, "validation_repairs": 0,
             "runtime_check_repairs": 0,
             "provider_calls": {"semantic_calls": 0, "semantic_call_attempts": 0,
                                "http_attempts_actual": None,
                                "http_attempts_upper_bound": 0,
                                "completion_output_tokens_reserved": 0},
             "usage": {"prompt_tokens": None, "completion_tokens": None,
                       "total_tokens": None, "cost_usd": None,
                       "wall_seconds": None},
             "integrity": {"native_roundtrip": False, "preview_verified": False,
                           "whole_scene_preview_verified": False,
                           "record_manifest_verified": False}}
            for item_id in ids
        ],
        "totals": {"semantic_calls": 0, "completion_output_tokens_reserved": 0,
                   "http_attempts_actual": None, "http_attempts_upper_bound": 0,
                   "prompt_tokens": None, "completion_tokens": None,
                   "total_tokens": None, "cost_usd": None},
        "gate": {"deterministic": "PENDING", "human": "PENDING",
                 "release_qualification": "PENDING"},
    }


def _validate_manifest(manifest: Any) -> dict:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != RUN_SCHEMA_VERSION:
        raise BenchmarkError("run manifest has an unsupported schema")
    scope = manifest.get("scope")
    mode = manifest.get("mode")
    expected_ids = RELEASE_IDS if scope == "release" else DISCOVERY_IDS if scope == "discovery" else None
    if expected_ids is None or mode not in {"live", "fake", "replay"}:
        raise BenchmarkError("run manifest scope or mode is invalid")
    if manifest.get("fixture_ids") != list(expected_ids) or manifest.get("denominator") != len(expected_ids):
        raise BenchmarkError("run manifest does not preserve its fixed denominator")
    provider = manifest.get("provider")
    if not isinstance(provider, dict) or not provider.get("provider_id") or not provider.get("model"):
        raise BenchmarkError("run manifest provider identity is incomplete")
    expected_provider_id = {"live": "openai-compatible", "fake": "offline-fake",
                            "replay": "offline-replay"}[mode]
    if provider.get("provider_id") != expected_provider_id:
        raise BenchmarkError("run mode and provider identity do not agree")
    frozen = manifest.get("frozen_inputs")
    if not isinstance(frozen, dict) or not isinstance(frozen.get("source"), dict):
        raise BenchmarkError("run manifest frozen input identity is missing")
    return manifest


def load_journal(run_root: str | Path) -> dict:
    root = assert_no_links(run_root)
    manifest_path = assert_no_links(root / "manifest.json")
    journal_path = assert_no_links(root / "run.json")
    manifest = _validate_manifest(_read_json(manifest_path))
    journal = _read_json(journal_path)
    if not isinstance(journal, dict):
        raise BenchmarkError("run journal has an invalid shape")
    if (journal.get("manifest_sha256") != manifest_sha256(manifest)
            or journal.get("manifest") != manifest
            or journal.get("run_uuid") != manifest.get("run_uuid")):
        raise BenchmarkError("frozen manifest integrity check failed")
    ids = manifest["fixture_ids"]
    items = journal.get("items")
    if not isinstance(items, list) or [item.get("id") for item in items if isinstance(item, dict)] != ids:
        raise BenchmarkError("run journal changed the fixed fixture denominator")
    for item in items:
        if not isinstance(item, dict) or item.get("status") not in {
            "pending", "running", "completed", "failed", "interrupted",
            "failed_input_drift", "not_run_input_drift", "failed_integrity",
        }:
            raise BenchmarkError("run journal contains an invalid item status")
    return journal


def _fixture_file_matches(root: Path, manifest: Mapping[str, Any]) -> bool:
    try:
        return _file_hashes(root) == manifest["frozen_inputs"]["fixture_files"]
    except (OSError, KeyError, TypeError):
        return False


def frozen_inputs_match(repo_root: str | Path, manifest: Mapping[str, Any]) -> bool:
    root = _repo_root(repo_root)
    try:
        current = source_snapshot(root)
        frozen = manifest["frozen_inputs"]
    except (BenchmarkError, OSError, KeyError, TypeError):
        return False
    return current == frozen.get("source") and _fixture_file_matches(root, manifest)


def _unique_run_root(parent: str | Path, repo_root: Path, run_uuid: str) -> Path:
    base = assert_no_links(parent)
    base.mkdir(parents=True, exist_ok=True)
    base = assert_no_links(base)
    try:
        os.chmod(base, 0o700)
    except OSError:
        pass
    repo = repo_root.resolve()
    try:
        base.relative_to(repo)
    except ValueError:
        pass
    else:
        raise BenchmarkError("benchmark output must live outside the source checkout")
    target = base / f"v1-benchmark-{run_uuid}"
    target.mkdir(mode=0o700, parents=False, exist_ok=False)
    try:
        os.chmod(target, 0o700)
    except OSError:
        pass
    return target


def initialize_run(repo_root: str | Path, output_parent: str | Path, *,
                   manifest: dict) -> tuple[Path, dict]:
    root = _repo_root(repo_root)
    manifest = _validate_manifest(manifest)
    if not frozen_inputs_match(root, manifest):
        raise BenchmarkError("source or fixture identity changed before the run was frozen")
    output = _unique_run_root(output_parent, root, manifest["run_uuid"])
    fixtures = load_fixture_set(root, manifest["scope"])[1]
    journal = new_journal(manifest, fixtures)
    atomic_write_json(output / "manifest.json", manifest)
    atomic_write_json(output / "run.json", journal)
    return output, journal


def persist_journal(run_root: str | Path, journal: dict) -> None:
    root = assert_no_links(run_root)
    target = assert_no_links(root / "run.json")
    atomic_write_json(target, journal)


def _number_or_none(value: Any) -> int | float | None:
    if type(value) is int and value >= 0:
        return value
    if type(value) is float and value >= 0 and value < float("inf"):
        return value
    return None


def _sum_known(values: Iterable[Any]) -> int | float | None:
    values = list(values)
    if not values or any(_number_or_none(value) is None for value in values):
        return None
    return sum(values)  # type: ignore[arg-type]


def _check_named(report: Any, name: str) -> bool:
    if not isinstance(report, dict) or not isinstance(report.get("checks"), list):
        return False
    return any(isinstance(item, dict) and item.get("id") == name
               and item.get("status") == "passed" for item in report["checks"])


def _record_for_item(run_root: Path, item: Mapping[str, Any]) -> dict | None:
    generation_id = item.get("generation_id")
    if not isinstance(generation_id, str):
        return None
    try:
        from .records import GenerationRecordStore
        record = GenerationRecordStore(run_root / "store").get_record(generation_id)
    except Exception:
        return None
    return record if isinstance(record, dict) else None


def _invalid_integrity() -> dict[str, Any]:
    return {"valid": False, "native_roundtrip": False,
            "preview_verified": False, "whole_scene_preview_verified": False,
            "record_manifest_verified": False, "provider_matches_manifest": False,
            "preview": None, "native_project": None}


def _json_bytes(path: Path, *, limit: int) -> tuple[bytes, Any]:
    if _is_link(path) or not path.is_file() or path.stat().st_size > limit:
        raise BenchmarkError("generation receipt input is missing, linked, or oversized")
    raw = path.read_bytes()
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BenchmarkError("generation receipt input is invalid JSON") from None
    return raw, value


def _artifact_file_entries(record: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest = record.get("artifact_manifest")
    if not isinstance(manifest, list):
        raise BenchmarkError("generation record has no artifact manifest")
    result: dict[str, dict[str, Any]] = {}
    for entry in manifest:
        if (not isinstance(entry, dict) or set(entry) != {"path", "sha256", "bytes"}
                or not isinstance(entry.get("path"), str)
                or not _SHA256_RE.fullmatch(str(entry.get("sha256", "")))
                or type(entry.get("bytes")) is not int or entry["bytes"] <= 0
                or entry["path"] in result):
            raise BenchmarkError("generation artifact manifest is malformed")
        result[entry["path"]] = dict(entry)
    return result


def _capture_generation_receipt(run_root: Path, item: Mapping[str, Any],
                                manifest: Mapping[str, Any], outcome: Any,
                                fixture: Mapping[str, Any] | None) -> dict[str, str]:
    """Capture an append-once host receipt at the returned completed outcome."""
    if not isinstance(fixture, Mapping) or fixture.get("id") != item.get("id"):
        raise BenchmarkError("trusted frozen fixture context is required for a receipt")
    fixture_hash = sha256_bytes(canonical_json(dict(fixture)))
    if (fixture_hash != item.get("fixture_sha256")
            or fixture_hash != manifest.get("frozen_inputs", {}).get(
                "fixture_item_sha256", {}).get(item.get("id"))):
        raise BenchmarkError("returned fixture context does not match the frozen item")
    generation_id = getattr(outcome, "run_id", None)
    try:
        canonical_id = str(uuid.UUID(generation_id))
    except (ValueError, TypeError, AttributeError):
        raise BenchmarkError("completed outcome has no canonical generation ID") from None
    if canonical_id != generation_id or item.get("generation_id") != generation_id:
        raise BenchmarkError("completed outcome identity changed before receipt capture")

    manifest_raw, saved_manifest = _json_bytes(run_root / "manifest.json", limit=2 * 1024 * 1024)
    manifest_digest = sha256_bytes(canonical_json(dict(manifest)))
    if saved_manifest != dict(manifest) or sha256_bytes(canonical_json(saved_manifest)) != manifest_digest:
        raise BenchmarkError("run manifest changed before receipt capture")

    generation_root = run_root / "store" / "generations" / generation_id
    record_path = generation_root / "record.json"
    record_raw, disk_record = _json_bytes(record_path, limit=4 * 1024 * 1024)
    sidecar_raw, disk_check_report = _json_bytes(generation_root / "check-report.json",
                                                 limit=512 * 1024)
    returned_record = getattr(outcome, "record", None)
    returned_check_report = getattr(outcome, "check_report", None)
    if (not bool(getattr(outcome, "ok", False))
            or getattr(outcome, "status", None) != "completed"
            or not isinstance(returned_record, dict)
            or not isinstance(returned_check_report, dict)
            or not isinstance(disk_record, dict)
            or not isinstance(disk_check_report, dict)):
        raise BenchmarkError("only a complete returned outcome can anchor a receipt")
    # The orchestrator uses "completed" in memory and "complete" on disk.
    # Compare every generation field available from the returned object and
    # require the checker report itself to match its committed sidecar bytes.
    for key in ("run_id", "provider", "accepted_brief", "accepted_recipe", "check_report"):
        if returned_record.get(key) != disk_record.get(key):
            raise BenchmarkError("returned generation identity differs from its stored record")
    if (disk_record.get("run_id") != generation_id
            or disk_record.get("status") != "complete"
            or returned_record.get("status") != "completed"
            or returned_check_report != disk_record.get("check_report")
            or disk_check_report != disk_record.get("check_report")):
        raise BenchmarkError("returned checker outcome differs from committed generation data")
    actual_provider = disk_record.get("provider")
    expected_provider = manifest.get("provider", {})
    expected_id = expected_provider.get("provider_id") if isinstance(expected_provider, Mapping) else None
    mapped_provider = {"openai-compatible": "openai-compatible",
                       "offline-fake": "offline-fake",
                       "offline-replay": "offline-fake"}.get(expected_id)
    if (not isinstance(actual_provider, dict) or not mapped_provider
            or actual_provider.get("provider") != mapped_provider
            or actual_provider.get("model") != expected_provider.get("model")):
        raise BenchmarkError("returned provider/model does not match the frozen run")

    record_for_store = _record_for_item(run_root, item)
    if not isinstance(record_for_store, dict):
        raise BenchmarkError("generation store did not verify the committed record")
    entries = _artifact_file_entries(disk_record)
    if entries != {entry["path"]: entry for entry in record_for_store["artifact_manifest"]}:
        raise BenchmarkError("committed artifact manifest changed during receipt capture")
    reported_artifacts = disk_check_report.get("artifacts")
    if not isinstance(reported_artifacts, list):
        raise BenchmarkError("committed checker report has no artifact observations")
    for entry in reported_artifacts:
        if (not isinstance(entry, dict) or entries.get(entry.get("path")) != entry):
            raise BenchmarkError("committed checker artifacts differ from the stored snapshot")
    if not {"project.am3d", "preview.png", "recipe.json", "check-report.json"}.issubset(entries):
        raise BenchmarkError("generation snapshot is missing required receipt inputs")
    artifact_root = generation_root
    artifact_hashes = {}
    for relative, entry in sorted(entries.items()):
        path = artifact_root / Path(relative)
        assert_no_links(path)
        if (not path.is_file() or path.stat().st_size != entry["bytes"]
                or sha256_file(path) != entry["sha256"]):
            raise BenchmarkError("generation artifact changed during receipt capture")
        artifact_hashes[relative] = {"sha256": entry["sha256"], "bytes": entry["bytes"]}
    recipe_hash = sha256_bytes(canonical_json(disk_record.get("accepted_recipe")))
    recipe_sidecar_raw, recipe_sidecar = _json_bytes(generation_root / "recipe.json", limit=512 * 1024)
    if recipe_sidecar != disk_record.get("accepted_recipe"):
        raise BenchmarkError("accepted recipe sidecar differs from the returned outcome")

    receipt = {
        "schema_version": GENERATION_RECEIPT_SCHEMA_VERSION,
        "run_uuid": manifest.get("run_uuid"),
        "source_run_manifest_sha256": manifest_digest,
        "source_run_manifest_file_sha256": sha256_bytes(manifest_raw),
        "item_id": item.get("id"),
        "fixture_sha256": fixture_hash,
        "fixture": deepcopy(dict(fixture)),
        "fixture_assertions": fixture_requirements(fixture),
        "generation_id": generation_id,
        "provider": deepcopy(actual_provider),
        "check_report": deepcopy(disk_check_report),
        "check_report_sha256": sha256_bytes(canonical_json(disk_check_report)),
        "record_sha256": sha256_bytes(record_raw),
        "check_report_sidecar_sha256": sha256_bytes(sidecar_raw),
        "accepted_recipe_sha256": recipe_hash,
        "recipe_sidecar_sha256": sha256_bytes(recipe_sidecar_raw),
        "artifact_manifest": deepcopy(disk_record["artifact_manifest"]),
        "artifact_hashes": artifact_hashes,
    }
    canonical_receipt = canonical_json(receipt)
    raw = canonical_receipt + b"\n"
    receipt_dir = assert_no_links(run_root / "generation-receipts")
    receipt_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert_no_links(receipt_dir)
    try:
        os.chmod(receipt_dir, 0o700)
    except OSError:
        pass
    path = assert_no_links(receipt_dir / f"{generation_id}.json", include_parents=True)
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise BenchmarkError("generation receipt is append-once and already exists") from None
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {"path": path.relative_to(run_root).as_posix(),
            "sha256": sha256_bytes(canonical_receipt)}


def _verify_physical_preview(path: Path) -> bool:
    try:
        from PIL import Image
        import numpy as np
        if not path.is_file() or path.stat().st_size <= 0 or path.stat().st_size > 16 * 1024 * 1024:
            return False
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (512, 512):
                return False
            image.verify()
        with Image.open(path) as image:
            rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8)
        if rgba.shape != (512, 512, 4):
            return False
        alpha = rgba[..., 3]
        foreground = alpha > 8
        occupancy = float(foreground.mean())
        rgb = rgba[..., :3][foreground]
        if not len(rgb):
            return False
        color_contrast = float(np.max(rgb.max(axis=0) - rgb.min(axis=0))) / 255.0
        background = ~foreground
        alpha_contrast = (float(alpha[foreground].mean() - alpha[background].mean()) / 255.0
                          if foreground.any() and background.any() else 0.0)
        return bool(np.isfinite(rgba).all() and 0.005 <= occupancy <= 0.95
                    and max(color_contrast, alpha_contrast) >= 0.05)
    except Exception:
        return False


def _verify_physical_native(path: Path) -> bool:
    try:
        from am3d.core.script import Session
        from am3d.core.serializer import project_content_digest
        if not path.is_file() or path.stat().st_size <= 0 or path.stat().st_size > 32 * 1024 * 1024:
            return False
        with tempfile.TemporaryDirectory(prefix="v1-native-receipt-") as tmp:
            original = Path(tmp) / "original.am3d"
            roundtrip_path = Path(tmp) / "roundtrip.am3d"
            original.write_bytes(path.read_bytes())
            first = Session()
            first.load_project(str(original))
            first_digest = project_content_digest(first.project, first.actions)
            first.save_project(str(roundtrip_path))
            second = Session()
            second.load_project(str(roundtrip_path))
            second_digest = project_content_digest(second.project, second.actions)
            return first_digest == second_digest
    except Exception:
        return False


def verify_success_artifacts(run_root: str | Path, item: Mapping[str, Any],
                             manifest: Mapping[str, Any] | None = None) -> dict[str, Any]:
    root = assert_no_links(run_root)
    if manifest is None:
        try:
            manifest = load_journal(root)["manifest"]
        except BenchmarkError:
            manifest = {}
    anchor = item.get("generation_receipt")
    generation_id = item.get("generation_id")
    if (not isinstance(anchor, dict)
            or set(anchor) != {"path", "sha256"}
            or not isinstance(generation_id, str)
            or anchor.get("path") != f"generation-receipts/{generation_id}.json"
            or not _SHA256_RE.fullmatch(str(anchor.get("sha256", "")))):
        return _invalid_integrity()
    try:
        receipt_path = assert_no_links(root / anchor["path"])
        receipt_raw, receipt = _json_bytes(receipt_path, limit=8 * 1024 * 1024)
        if (not isinstance(receipt, dict)
                or sha256_bytes(canonical_json(receipt)) != anchor["sha256"]):
            return _invalid_integrity()
        expected_fields = {
            "schema_version", "run_uuid", "source_run_manifest_sha256",
            "source_run_manifest_file_sha256", "item_id", "fixture_sha256",
            "fixture", "fixture_assertions", "generation_id", "provider",
            "check_report", "check_report_sha256", "record_sha256",
            "check_report_sidecar_sha256", "accepted_recipe_sha256",
            "recipe_sidecar_sha256", "artifact_manifest", "artifact_hashes",
        }
        if (set(receipt) != expected_fields
                or receipt.get("schema_version") != GENERATION_RECEIPT_SCHEMA_VERSION
                or receipt.get("run_uuid") != manifest.get("run_uuid")
                or receipt.get("source_run_manifest_sha256") != manifest_sha256(manifest)
                or receipt.get("item_id") != item.get("id")
                or receipt.get("generation_id") != generation_id
                or receipt.get("fixture_sha256") != item.get("fixture_sha256")
                or not isinstance(receipt.get("fixture"), dict)
                or receipt["fixture"].get("id") != item.get("id")
                or sha256_bytes(canonical_json(receipt["fixture"])) != item.get("fixture_sha256")
                or receipt.get("fixture_assertions") != fixture_requirements(receipt["fixture"])):
            return _invalid_integrity()
        manifest_raw, disk_manifest = _json_bytes(root / "manifest.json", limit=2 * 1024 * 1024)
        if (disk_manifest != dict(manifest)
                or sha256_bytes(manifest_raw) != receipt.get("source_run_manifest_file_sha256")):
            return _invalid_integrity()
        record_root = root / "store" / "generations" / generation_id
        record_raw, record = _json_bytes(record_root / "record.json", limit=4 * 1024 * 1024)
        check_raw, check_sidecar = _json_bytes(record_root / "check-report.json", limit=512 * 1024)
        recipe_raw, recipe_sidecar = _json_bytes(record_root / "recipe.json", limit=512 * 1024)
        if (not isinstance(record, dict)
                or sha256_bytes(record_raw) != receipt.get("record_sha256")
                or sha256_bytes(check_raw) != receipt.get("check_report_sidecar_sha256")
                or sha256_bytes(recipe_raw) != receipt.get("recipe_sidecar_sha256")
                or record.get("run_id") != generation_id
                or record.get("status") != "complete"
                or record.get("provider") != receipt.get("provider")
                or record.get("check_report") != receipt.get("check_report")
                or check_sidecar != receipt.get("check_report")
                or sha256_bytes(canonical_json(receipt.get("check_report"))) != receipt.get("check_report_sha256")
                or record.get("accepted_recipe") != recipe_sidecar
                or sha256_bytes(canonical_json(record.get("accepted_recipe"))) != receipt.get("accepted_recipe_sha256")
                or _artifact_file_entries(record) != {
                    entry["path"]: entry for entry in receipt.get("artifact_manifest", [])
                    if isinstance(entry, dict) and isinstance(entry.get("path"), str)}):
            return _invalid_integrity()
        record_from_store = _record_for_item(root, item)
        if not record_from_store or record_from_store.get("artifact_manifest") != receipt.get("artifact_manifest"):
            return _invalid_integrity()
        entries = _artifact_file_entries(record)
        if receipt.get("artifact_hashes") != {
                path: {"sha256": entry["sha256"], "bytes": entry["bytes"]}
                for path, entry in sorted(entries.items())}:
            return _invalid_integrity()
        report_artifacts = receipt["check_report"].get("artifacts")
        if (not isinstance(report_artifacts, list)
                or any(not isinstance(entry, dict)
                       or entries.get(entry.get("path")) != entry
                       for entry in report_artifacts)):
            return _invalid_integrity()
        for relative, entry in entries.items():
            artifact_path = assert_no_links(record_root / Path(relative))
            if (not artifact_path.is_file() or artifact_path.stat().st_size != entry["bytes"]
                    or sha256_file(artifact_path) != entry["sha256"]):
                return _invalid_integrity()
    except (BenchmarkError, OSError, ValueError, TypeError, KeyError):
        return _invalid_integrity()

    check_report = receipt["check_report"]
    by_path = {entry["path"]: entry for entry in receipt["artifact_manifest"]}
    preview_entry = by_path.get("preview.png")
    project_entry = by_path.get("project.am3d")
    preview_path = root / "store" / "generations" / generation_id / "preview.png"
    project_path = root / "store" / "generations" / generation_id / "project.am3d"
    preview_ok = bool(preview_entry and _verify_physical_preview(preview_path))
    project_ok = bool(project_entry and _verify_physical_native(project_path))
    roundtrip = _check_named(check_report, "native_roundtrip") and project_ok
    preview_content = _check_named(check_report, "whole_scene_preview") and preview_ok
    check_ok = (record.get("status") == "complete"
                and isinstance(check_report, dict)
                and check_report.get("ok") is True
                and check_report.get("status") == "passed")
    if manifest is None:
        manifest = {}
    expected_provider = manifest.get("provider", {}) if isinstance(manifest, Mapping) else {}
    actual_provider = receipt.get("provider", {})
    expected_id = expected_provider.get("provider_id") if isinstance(expected_provider, Mapping) else None
    expected_record_id = {"openai-compatible": "openai-compatible",
                          "offline-fake": "offline-fake",
                          "offline-replay": "offline-fake"}.get(expected_id)
    provider_matches = bool(
        expected_record_id and isinstance(actual_provider, dict)
        and actual_provider.get("provider") == expected_record_id
        and actual_provider.get("model") == expected_provider.get("model")
    )
    return {
        "valid": bool(check_ok and roundtrip and preview_content and preview_ok
                       and project_ok and provider_matches),
        "native_roundtrip": bool(roundtrip),
        "preview_verified": bool(preview_ok),
        "whole_scene_preview_verified": bool(preview_content),
        "record_manifest_verified": True,
        "provider_matches_manifest": provider_matches,
        "preview": {"path": str(preview_path), "sha256": preview_entry.get("sha256"),
                    "bytes": preview_entry.get("bytes")} if preview_ok else None,
        "native_project": {"path": str(project_path), "sha256": project_entry.get("sha256"),
                           "bytes": project_entry.get("bytes")} if project_ok else None,
    }


def _provider_failure_class(outcome: Any) -> tuple[str, str | None]:
    status = str(getattr(outcome, "status", "failed"))
    record = getattr(outcome, "record", {})
    error = getattr(outcome, "error", None)
    if not isinstance(error, dict):
        errors = record.get("errors") if isinstance(record, dict) else None
        error = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    safe_code = code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_]{1,64}", code) else None
    if status in {"provider_error", "provider_refused", "timed_out", "cancelled"}:
        return "provider_or_infrastructure", safe_code
    if status in {"record_error", "worker_error", "execution_failed", "resource_limit"}:
        return "infrastructure_or_resource", safe_code
    if status in {"policy_error", "validation_failed", "check_failed", "user_choice_required"}:
        return "policy_or_deterministic_check", safe_code
    return "generation_failure", safe_code


def apply_outcome(journal: dict, item_id: str, outcome: Any, *,
                  provider_stats: Mapping[str, Any], wall_seconds: float,
                  run_root: str | Path,
                  fixture: Mapping[str, Any] | None = None) -> dict:
    items = {item["id"]: item for item in journal["items"]}
    item = items[item_id]
    if item["status"] != "running":
        raise BenchmarkError("a terminal benchmark item cannot be overwritten")
    record = getattr(outcome, "record", {})
    record = record if isinstance(record, dict) else {}
    usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
    status = str(getattr(outcome, "status", "failed"))
    success = bool(getattr(outcome, "ok", False)) and status == "completed"
    item["status"] = "completed" if success else "failed"
    item["completed_utc"] = utc_now()
    item["generation_id"] = getattr(outcome, "run_id", None)
    item["candidate_outcome"] = status
    item["deterministic_pass"] = False
    item["candidate_count"] = record.get("candidate_count", 0)
    item["validation_repairs"] = record.get("validation_repairs", 0)
    item["runtime_check_repairs"] = record.get("runtime_check_repairs", 0)
    report = getattr(outcome, "check_report", None)
    item["checks"] = [
        {"id": entry.get("id"), "status": entry.get("status"),
         "severity": entry.get("severity")}
        for entry in report.get("checks", [])
        if isinstance(entry, dict)
        and isinstance(entry.get("id"), str)
        and entry.get("status") in {"passed", "failed"}
    ][:256] if isinstance(report, dict) and isinstance(report.get("checks"), list) else []
    item["attempt_state_path"] = getattr(outcome, "record_path", None)
    failure_class, failure_code = _provider_failure_class(outcome)
    item["failure_class"] = None if success else failure_class
    item["failure_code"] = None if success else failure_code
    calls_forwarded = int(provider_stats.get("semantic_calls_forwarded", 0))
    call_attempts = int(provider_stats.get("semantic_call_attempts", 0))
    http_attempt_limit = int(journal["manifest"]["limits"]["max_http_attempts_per_semantic_call"])
    item["provider_calls"] = {
        "semantic_calls": calls_forwarded,
        "semantic_call_attempts": call_attempts,
        "http_attempts_actual": None,
        "http_attempts_upper_bound": calls_forwarded * http_attempt_limit,
        "completion_output_tokens_reserved": int(provider_stats.get("output_tokens_reserved", 0)),
        "budget_stop_reason": provider_stats.get("budget_stop_reason"),
        "run_http_attempt_ceiling": journal["manifest"]["limits"]["http_attempts_conservative_upper_bound"],
    }
    observed_usage = provider_stats.get("usage")
    observed_usage = observed_usage if isinstance(observed_usage, dict) else {}

    def usage_value(name: str) -> int | float | None:
        observed = _number_or_none(observed_usage.get(name))
        return observed if observed is not None else _number_or_none(usage.get(name))

    item["usage"] = {
        "prompt_tokens": usage_value("prompt_tokens"),
        "completion_tokens": usage_value("completion_tokens"),
        "total_tokens": usage_value("total_tokens"),
        "cost_usd": usage_value("cost_usd"),
        "wall_seconds": _number_or_none(wall_seconds),
    }
    item["record_integrity"] = None
    if success:
        try:
            item["generation_receipt"] = _capture_generation_receipt(
                assert_no_links(run_root), item, journal["manifest"], outcome, fixture)
        except (BenchmarkError, OSError, ValueError, TypeError, KeyError):
            item["generation_receipt"] = None
        integrity = verify_success_artifacts(run_root, item, journal["manifest"])
        item["record_integrity"] = integrity
        item["integrity"] = {
            "native_roundtrip": integrity["native_roundtrip"],
            "preview_verified": integrity["preview_verified"],
            "whole_scene_preview_verified": integrity["whole_scene_preview_verified"],
            "record_manifest_verified": integrity["record_manifest_verified"],
            "provider_matches_manifest": integrity["provider_matches_manifest"],
        }
        item["deterministic_pass"] = bool(integrity["valid"])
        if not integrity["valid"]:
            item["status"] = "failed_integrity"
            item["failure_class"] = "artifact_integrity"
            item["failure_code"] = "artifact_integrity_failed"
    return item


def _sum_optional_by_key(items: list[dict], section: str, key: str) -> int | float | None:
    return _sum_known(item.get(section, {}).get(key) for item in items)


def refresh_totals(journal: dict) -> None:
    items = journal["items"]
    journal["totals"] = {
        "semantic_calls": sum(int(item.get("provider_calls", {}).get("semantic_calls", 0)) for item in items),
        "completion_output_tokens_reserved": sum(int(item.get("provider_calls", {}).get("completion_output_tokens_reserved", 0)) for item in items),
        "http_attempts_actual": None,
        "http_attempts_upper_bound": sum(int(item.get("provider_calls", {}).get("http_attempts_upper_bound", 0)) for item in items),
        "prompt_tokens": _sum_optional_by_key(items, "usage", "prompt_tokens"),
        "completion_tokens": _sum_optional_by_key(items, "usage", "completion_tokens"),
        "total_tokens": _sum_optional_by_key(items, "usage", "total_tokens"),
        "cost_usd": _sum_optional_by_key(items, "usage", "cost_usd"),
    }


def mark_interrupted_items(journal: dict) -> bool:
    changed = False
    for item in journal["items"]:
        if item["status"] == "running":
            item["status"] = "interrupted"
            item["completed_utc"] = utc_now()
            item["failure_class"] = "interrupted"
            item["failure_code"] = "process_interrupted"
            item["deterministic_pass"] = False
            changed = True
    if changed:
        journal["resume_count"] = int(journal.get("resume_count", 0)) + 1
    return changed


def item_passes(journal: Mapping[str, Any], item: Mapping[str, Any]) -> bool:
    if (journal.get("manifest", {}).get("scope") != "release"
            or item.get("status") != "completed"
            or item.get("deterministic_pass") is not True):
        return False
    integrity = item.get("record_integrity")
    return bool(isinstance(integrity, dict) and integrity.get("valid") is True
                and integrity.get("native_roundtrip") is True
                and integrity.get("preview_verified") is True
                and integrity.get("whole_scene_preview_verified") is True
                and integrity.get("record_manifest_verified") is True
                and integrity.get("provider_matches_manifest") is True)


def deterministic_result(journal: Mapping[str, Any]) -> dict[str, Any]:
    if journal.get("manifest", {}).get("scope") != "release":
        return {"status": "NOT_APPLICABLE_DISCOVERY", "passes": 0,
                "static_passes": None, "rig_passes": None,
                "denominator": journal.get("manifest", {}).get("denominator")}
    items = journal.get("items", [])
    passing = [item for item in items if item_passes(journal, item)]
    static = sum(1 for item in passing if item.get("id") in RELEASE_STATIC_IDS)
    rig = sum(1 for item in passing if item.get("id") in RELEASE_RIG_IDS)
    complete = (len(items) == 30
                and all(item.get("status") not in {"pending", "running"} for item in items)
                and [item.get("id") for item in items] == list(RELEASE_IDS))
    passed = complete and len(passing) >= 27 and static >= 20 and rig >= 4
    return {
        "status": "PASS" if passed else "FAIL" if complete else "INCOMPLETE",
        "passes": len(passing), "denominator": 30,
        "static_passes": static, "static_denominator": 25,
        "rig_passes": rig, "rig_denominator": 5,
        "thresholds": {"all": 27, "static": 20, "rig": 4},
        "complete": complete,
        "failed_item_ids": [item.get("id") for item in items if not item_passes(journal, item)],
    }


def _load_human_submission(path: str | Path) -> tuple[dict, bytes]:
    original = Path(path).read_bytes()
    try:
        value = json.loads(original.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise BenchmarkError("human score file is not valid UTF-8 JSON") from None
    if not isinstance(value, dict):
        raise BenchmarkError("human score file must be a JSON object")
    return value, original


def _human_template_shape(value: Mapping[str, Any], manifest: Mapping[str, Any]) -> None:
    expected_top = {"schema_version", "review_kind", "run_uuid", "manifest_sha256",
                    "reviewer_id", "items"}
    if set(value) != expected_top:
        raise BenchmarkError("human score file fields do not match the blank scoring template")
    if value.get("schema_version") != HUMAN_SCHEMA_VERSION or value.get("review_kind") != "v1_visual_native_review":
        raise BenchmarkError("human score file schema or review type is invalid")
    if value.get("run_uuid") != manifest.get("run_uuid"):
        raise BenchmarkError("human score file belongs to another run")
    if value.get("manifest_sha256") != manifest_sha256(manifest):
        raise BenchmarkError("human score file manifest identity does not match")
    reviewer_id = value.get("reviewer_id")
    if not isinstance(reviewer_id, str) or not _REVIEWER_RE.fullmatch(reviewer_id):
        raise BenchmarkError("reviewer ID must be a non-empty stable identifier")
    expected_ids = RELEASE_IDS
    items = value.get("items")
    if not isinstance(items, list) or [item.get("id") for item in items if isinstance(item, dict)] != list(expected_ids):
        raise BenchmarkError("human score file must contain each release item exactly once")
    for item in items:
        if not isinstance(item, dict) or set(item) != {"id", "preview", "native_project", "scores"}:
            raise BenchmarkError("human score item fields do not match the exported template")
        scores = item.get("scores")
        if not isinstance(scores, dict) or set(scores) != set(_HUMAN_FIELDS):
            raise BenchmarkError("each item requires exactly four rubric scores")
        if any(type(scores[field]) is not int or scores[field] not in (0, 1, 2)
               for field in _HUMAN_FIELDS):
            raise BenchmarkError("rubric scores must be integers from 0 through 2")
        for artifact in (item.get("preview"), item.get("native_project")):
            if artifact is None:
                continue
            if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256", "bytes"}:
                raise BenchmarkError("score template artifact references are malformed")
            if not isinstance(artifact.get("path"), str) or not _SHA256_RE.fullmatch(str(artifact.get("sha256"))):
                raise BenchmarkError("score template artifact references are malformed")
            if type(artifact.get("bytes")) is not int or artifact["bytes"] <= 0:
                raise BenchmarkError("score template artifact size is malformed")


def export_human_template(run_root: str | Path, output_path: str | Path) -> dict:
    root = assert_no_links(run_root)
    journal = load_journal(root)
    manifest = journal["manifest"]
    if manifest["scope"] != "release":
        raise BenchmarkError("human score templates are only available for release runs")
    if journal.get("status") != "complete":
        raise BenchmarkError("human templates require a complete 30-item run ledger")
    items = []
    for item in journal["items"]:
        if item.get("status") in {"pending", "running"}:
            raise BenchmarkError("all 30 release items must be terminal before exporting human templates")
        integrity = (verify_success_artifacts(root, item)
                     if item.get("generation_id") else {})
        items.append({
            "id": item["id"],
            "preview": integrity.get("preview") if integrity.get("valid") else None,
            "native_project": integrity.get("native_project") if integrity.get("valid") else None,
            "scores": {name: None for name in _HUMAN_FIELDS},
        })
    template = {
        "schema_version": HUMAN_SCHEMA_VERSION,
        "review_kind": "v1_visual_native_review",
        "run_uuid": manifest["run_uuid"],
        "manifest_sha256": journal["manifest_sha256"],
        "reviewer_id": "",
        "items": items,
    }
    # The blank reviewer and score values are expected in a template, so write
    # directly here; import requires all four scores and an actual reviewer ID.
    target = Path(output_path)
    if target.exists() or target.is_symlink():
        raise BenchmarkError("human template output already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, template)
    return template


def _expected_human_artifacts(run_root: Path, journal: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
    expected = {}
    for item in journal["items"]:
        integrity = (verify_success_artifacts(run_root, item, journal["manifest"])
                     if item.get("generation_id") else {})
        expected[item["id"]] = (
            integrity.get("preview") if integrity.get("valid") else None,
            integrity.get("native_project") if integrity.get("valid") else None,
        )
    return expected


def import_human_scores(run_root: str | Path, score_path: str | Path) -> dict:
    root = assert_no_links(run_root)
    journal = load_journal(root)
    manifest = journal["manifest"]
    if manifest["scope"] != "release":
        raise BenchmarkError("human review applies only to release runs")
    if journal.get("status") != "complete" or deterministic_result(journal)["complete"] is not True:
        raise BenchmarkError("human reviews may be imported only after all release items are terminal")
    value, original = _load_human_submission(score_path)
    _human_template_shape(value, manifest)
    expected_artifacts = _expected_human_artifacts(root, journal)
    for item in value["items"]:
        expected_preview, expected_native = expected_artifacts[item["id"]]
        if item.get("preview") != expected_preview or item.get("native_project") != expected_native:
            raise BenchmarkError("human score artifact references differ from verified run artifacts")
    reviewer = value["reviewer_id"]
    review_root = root / "human-review"
    submissions_root = review_root / "original-score-files"
    assert_no_links(review_root)
    assert_no_links(submissions_root)
    submissions_root.mkdir(parents=True, exist_ok=True)
    assert_no_links(submissions_root)
    for prior in submissions_root.glob("*.json"):
        old, _raw = _load_human_submission(prior)
        if old.get("reviewer_id") == reviewer:
            raise BenchmarkError("a reviewer score file already exists; original submissions are never overwritten")
    if len(_load_review_analyses(root, manifest, journal)) >= 2:
        raise BenchmarkError("this run already has two independent evaluator score files")
    digest = sha256_bytes(original)
    target = submissions_root / f"{digest}.json"
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise BenchmarkError("this exact original score file has already been imported") from None
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    scores_by_id = {item["id"]: item["scores"] for item in value["items"]}
    derived = {
        "schema_version": 1,
        "run_uuid": manifest["run_uuid"],
        "manifest_sha256": journal["manifest_sha256"],
        "reviewer_id": reviewer,
        "original_sha256": digest,
        "original_file": str(target),
        "items": [],
        "counts": {"human_acceptable": 0, "denominator": 30},
    }
    for item_id in RELEASE_IDS:
        scores = scores_by_id[item_id]
        total = sum(scores[field] for field in _HUMAN_FIELDS)
        acceptable = total >= 6 and scores["essential_components"] > 0
        derived["items"].append({"id": item_id, "scores": scores,
                                 "total": total,
                                 "human_acceptable": acceptable})
        derived["counts"]["human_acceptable"] += int(acceptable)
    derived["status"] = "PASS" if derived["counts"]["human_acceptable"] >= 24 else "FAIL"
    derived["analysis_path"] = str(review_root / "derived" / f"{digest}.json")
    atomic_write_json(derived["analysis_path"], derived)
    return derived


def _load_review_analyses(run_root: Path, manifest: Mapping[str, Any],
                          journal: Mapping[str, Any] | None = None) -> list[dict]:
    """Rebuild score summaries from preserved originals; derived files are display-only."""
    folder = run_root / "human-review" / "original-score-files"
    if not folder.is_dir():
        return []
    assert_no_links(folder)
    journal = journal if journal is not None else load_journal(run_root)
    if journal.get("manifest_sha256") != manifest_sha256(manifest):
        raise BenchmarkError("human score imports do not match the frozen run manifest")
    expected_artifacts = _expected_human_artifacts(run_root, journal)
    reviews = []
    seen_reviewers = set()
    for path in sorted(folder.glob("*.json")):
        if _is_link(path) or not path.is_file():
            raise BenchmarkError("human score archive contains an unsafe file")
        value, original = _load_human_submission(path)
        digest = sha256_bytes(original)
        if path.stem != digest:
            raise BenchmarkError("human score archive integrity check failed")
        _human_template_shape(value, manifest)
        reviewer_id = value["reviewer_id"]
        if reviewer_id in seen_reviewers:
            raise BenchmarkError("human score archive contains duplicate reviewer IDs")
        seen_reviewers.add(reviewer_id)
        for item in value["items"]:
            preview, native_project = expected_artifacts[item["id"]]
            if item["preview"] != preview or item["native_project"] != native_project:
                raise BenchmarkError("archived human score artifact references no longer verify")
        analyzed_items = []
        acceptable_count = 0
        for item in value["items"]:
            scores = deepcopy(item["scores"])
            total = sum(scores[field] for field in _HUMAN_FIELDS)
            acceptable = total >= 6 and scores["essential_components"] > 0
            acceptable_count += int(acceptable)
            analyzed_items.append({"id": item["id"], "scores": scores,
                                   "total": total,
                                   "human_acceptable": acceptable})
        reviews.append({
            "schema_version": 1,
            "run_uuid": manifest["run_uuid"],
            "manifest_sha256": manifest_sha256(manifest),
            "reviewer_id": reviewer_id,
            "original_sha256": digest,
            "original_file": str(path),
            "items": analyzed_items,
            "counts": {"human_acceptable": acceptable_count, "denominator": 30},
            "status": "PASS" if acceptable_count >= 24 else "FAIL",
        })
    if len(reviews) > 2:
        raise BenchmarkError("human score archive contains more than two evaluator files")
    return reviews


def _human_result(run_root: Path, journal: Mapping[str, Any]) -> dict[str, Any]:
    manifest = journal["manifest"]
    reviews = _load_review_analyses(run_root, manifest, journal)
    if len(reviews) < 2:
        return {"status": "PENDING", "reviewers": [item["reviewer_id"] for item in reviews],
                "distinct_reviewers": len({item["reviewer_id"] for item in reviews}),
                "human_acceptable": None, "denominator": 30}
    reviews = sorted(reviews, key=lambda item: item["reviewer_id"])[:2]
    by_reviewer = [{item["id"]: item for item in review["items"]} for review in reviews]
    accepted = []
    exact_matches = 0
    comparisons = 0
    disagreement_item_ids = []
    for item_id in RELEASE_IDS:
        left = by_reviewer[0].get(item_id, {}).get("scores", {})
        right = by_reviewer[1].get(item_id, {}).get("scores", {})
        disagrees = False
        for field in _HUMAN_FIELDS:
            if field in left and field in right:
                comparisons += 1
                same = left[field] == right[field]
                exact_matches += int(same)
                disagrees = disagrees or not same
        if disagrees:
            disagreement_item_ids.append(item_id)
        accepted_by_both = all(
            isinstance(review_items.get(item_id), dict)
            and review_items[item_id].get("human_acceptable") is True
            for review_items in by_reviewer
        )
        if accepted_by_both:
            accepted.append(item_id)
    resolution = _resolution_result(run_root, manifest, reviews)
    disagreements = set(disagreement_item_ids)
    resolved = set()
    unresolved = set()
    for entry in resolution["files"]:
        resolved.update(entry.get("item_ids", []))
        unresolved.update(entry.get("unresolved_item_ids", []))
    unresolved_disagreements = sorted(disagreements - resolved | (disagreements & unresolved))
    passed = len(accepted) >= 24 and not unresolved_disagreements
    return {
        "status": ("PASS" if passed else "PENDING_RESOLUTION"
                   if len(accepted) >= 24 and unresolved_disagreements else "FAIL"),
        "reviewers": [item["reviewer_id"] for item in reviews],
        "distinct_reviewers": len({item["reviewer_id"] for item in reviews}),
        "human_acceptable": len(accepted), "denominator": 30,
        "threshold": 24,
        "accepted_item_ids": accepted,
        "agreement": {
            "exact_score_matches": exact_matches,
            "score_comparisons": comparisons,
            "exact_agreement_fraction": exact_matches / comparisons if comparisons else None,
            "disagreement_item_ids": disagreement_item_ids,
        },
        "resolution": resolution,
        "unresolved_disagreement_item_ids": unresolved_disagreements,
    }


def single_run_report(run_root: str | Path, repo_root: str | Path | None = None) -> dict[str, Any]:
    root = assert_no_links(run_root)
    journal = load_journal(root)
    manifest = journal["manifest"]
    previous_statuses = [item.get("status") for item in journal["items"]]
    verify_journal_successes(root, journal)
    if previous_statuses != [item.get("status") for item in journal["items"]]:
        refresh_totals(journal)
        persist_journal(root, journal)
    input_match = frozen_inputs_match(repo_root or Path(__file__).resolve().parents[2], manifest)
    deterministic = deterministic_result(journal)
    human = _human_result(root, journal) if manifest["scope"] == "release" else {
        "status": "NOT_APPLICABLE_DISCOVERY", "human_acceptable": None,
        "denominator": manifest["denominator"],
    }
    live_qualified = bool(
        manifest["mode"] == "live" and manifest["provider"].get("provider_id") == "openai-compatible"
        and manifest["scope"] == "release"
        and journal.get("status") == "complete" and input_match
        and deterministic.get("status") == "PASS" and human.get("status") == "PASS"
    )
    qualification = "PASS" if live_qualified else (
        "NONQUALIFYING" if manifest["mode"] != "live" or manifest["scope"] != "release"
        or manifest["provider"].get("provider_id") != "openai-compatible"
        else "PENDING_OR_FAIL"
    )
    return {
        "qualification": qualification,
        "label": "NONQUALIFYING" if qualification == "NONQUALIFYING" else "LIVE_GATE_PENDING_OR_FAILED",
        "run_uuid": manifest["run_uuid"],
        "manifest_sha256": journal["manifest_sha256"],
        "mode": manifest["mode"], "scope": manifest["scope"],
        "journal_status": journal.get("status"),
        "frozen_inputs_match": input_match,
        "deterministic": deterministic,
        "human": human,
        "totals": journal.get("totals"),
        "disclosures": {
            "provider_model_drift": manifest.get("model_drift_disclosure"),
            "token_and_cost": manifest.get("token_and_cost_disclosure"),
        },
    }


def two_run_gate(first_root: str | Path, second_root: str | Path,
                 repo_root: str | Path | None = None) -> dict[str, Any]:
    first_report = single_run_report(first_root, repo_root)
    second_report = single_run_report(second_root, repo_root)
    first = load_journal(first_root)
    second = load_journal(second_root)
    same_config = all(first["manifest"]["provider"].get(key)
                      == second["manifest"]["provider"].get(key)
                      for key in ("provider_id", "model", "endpoint_host", "endpoint_path",
                                  "endpoint_sha256", "credential_source", "credential_alias"))
    distinct = first["manifest"]["run_uuid"] != second["manifest"]["run_uuid"]
    live = all(j["manifest"]["mode"] == "live"
               and j["manifest"]["provider"].get("provider_id") == "openai-compatible"
               and j["manifest"]["scope"] == "release"
               for j in (first, second))
    deterministic_pass = (first_report["deterministic"]["status"] == "PASS"
                          and second_report["deterministic"]["status"] == "PASS")
    human_pass = first_report["human"]["status"] == "PASS" and second_report["human"]["status"] == "PASS"
    inputs_match = first_report["frozen_inputs_match"] and second_report["frozen_inputs_match"]
    passed = bool(live and distinct and same_config and deterministic_pass and human_pass and inputs_match)
    return {
        "qualification": "PASS" if passed else "NONQUALIFYING" if not live else "PENDING_OR_FAIL",
        "label": "LIVE TWO-RUN GATE PASS" if passed else "NONQUALIFYING" if not live else "LIVE GATE PENDING_OR_FAILED",
        "release_gate": "PASS" if passed else "FAIL_OR_PENDING",
        "same_provider_and_model_configuration": same_config,
        "distinct_run_ledgers": distinct,
        "live_release_runs": live,
        "both_deterministic_gates_pass": deterministic_pass,
        "both_human_review_sets_pass": human_pass,
        "both_frozen_input_snapshots_match": inputs_match,
        "runs": [first_report, second_report],
    }


def update_completion_state(journal: dict) -> None:
    items = journal["items"]
    if any(item.get("status") in {"pending", "running"} for item in items):
        journal["status"] = "running"
        return
    if any(item.get("status") in {"failed_input_drift", "not_run_input_drift"} for item in items):
        journal["status"] = "aborted_input_drift"
        journal["completed_utc"] = utc_now()
    else:
        journal["status"] = "complete"
        journal["completed_utc"] = utc_now()
    refresh_totals(journal)
    if journal["manifest"]["scope"] == "release":
        result = deterministic_result(journal)
        journal["gate"]["deterministic"] = result["status"]
        if journal["manifest"]["mode"] != "live":
            journal["gate"]["release_qualification"] = "NONQUALIFYING"


def verify_journal_successes(run_root: str | Path, journal: dict) -> None:
    """Recheck native project, preview, and store hashes before reports/imports."""
    for item in journal["items"]:
        if item.get("status") != "completed" or not item.get("generation_id"):
            continue
        integrity = verify_success_artifacts(run_root, item, journal["manifest"])
        if not integrity["valid"]:
            item["status"] = "failed_integrity"
            item["deterministic_pass"] = False
            item["failure_class"] = "artifact_integrity"
            item["failure_code"] = "artifact_integrity_failed"
            item["record_integrity"] = integrity
            item["integrity"] = {
                "native_roundtrip": integrity["native_roundtrip"],
                "preview_verified": integrity["preview_verified"],
                "whole_scene_preview_verified": integrity["whole_scene_preview_verified"],
                "record_manifest_verified": integrity["record_manifest_verified"],
                "provider_matches_manifest": integrity["provider_matches_manifest"],
            }


def _expected_disagreement_ids(reviews: list[Mapping[str, Any]]) -> list[str]:
    review_items = [{item["id"]: item for item in review["items"]}
                    for review in reviews]
    return [item_id for item_id in RELEASE_IDS
            if any(review_items[0].get(item_id, {}).get("scores", {}).get(field)
                   != review_items[1].get(item_id, {}).get("scores", {}).get(field)
                   for field in _HUMAN_FIELDS)]


def _validate_resolution_submission(value: Mapping[str, Any],
                                   manifest: Mapping[str, Any],
                                   reviews: list[Mapping[str, Any]]) -> list[dict]:
    expected_top = {"schema_version", "review_kind", "run_uuid", "manifest_sha256",
                    "reviewer_ids", "items"}
    if (set(value) != expected_top or value.get("schema_version") != 1
            or value.get("review_kind") != "v1_disagreement_resolution"):
        raise BenchmarkError("resolution file does not match the separate resolution template")
    reviewer_ids = value.get("reviewer_ids")
    expected_reviewers = sorted(review["reviewer_id"] for review in reviews)
    if (value.get("run_uuid") != manifest["run_uuid"]
            or value.get("manifest_sha256") != manifest_sha256(manifest)
            or reviewer_ids != expected_reviewers):
        raise BenchmarkError("resolution file does not identify this run and its two evaluators")
    rows = value.get("items")
    expected_disagreements = _expected_disagreement_ids(reviews)
    if (not isinstance(rows, list)
            or [row.get("id") for row in rows if isinstance(row, dict)]
            != expected_disagreements):
        raise BenchmarkError("resolution file must cover every disagreement exactly once in fixture order")
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {"id", "resolution", "note"}
                or row.get("id") not in RELEASE_IDS or row["id"] in seen
                or row.get("resolution") not in {"accepted", "rejected", "unresolved"}
                or not isinstance(row.get("note"), str) or len(row["note"]) > 2048):
            raise BenchmarkError("resolution item is malformed or duplicated")
        seen.add(row["id"])
    if rows != sorted(rows, key=lambda item: RELEASE_IDS.index(item["id"])):
        raise BenchmarkError("resolution entries must follow frozen fixture order")
    return deepcopy(rows)


def import_human_resolution(run_root: str | Path, resolution_path: str | Path) -> dict:
    """Preserve an evaluator disagreement resolution as a separate original."""
    root = assert_no_links(run_root)
    journal = load_journal(root)
    manifest = journal["manifest"]
    if manifest["scope"] != "release" or journal.get("status") != "complete":
        raise BenchmarkError("resolution records require a complete release run")
    reviews = _load_review_analyses(root, manifest, journal)
    if len(reviews) != 2 or reviews[0]["reviewer_id"] == reviews[1]["reviewer_id"]:
        raise BenchmarkError("exactly two distinct human score imports are required before resolution")
    directory = root / "human-review" / "original-resolution-files"
    assert_no_links(directory)
    if directory.exists() and any(directory.glob("*.json")):
        raise BenchmarkError("a resolution original already exists; it cannot be overwritten")
    value, original = _load_human_submission(resolution_path)
    rows = _validate_resolution_submission(value, manifest, reviews)
    directory.mkdir(parents=True, exist_ok=True)
    assert_no_links(directory)
    digest = sha256_bytes(original)
    target = directory / f"{digest}.json"
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise BenchmarkError("this original resolution file has already been imported") from None
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(original)
        stream.flush()
        os.fsync(stream.fileno())
    derived = {"schema_version": 1, "run_uuid": manifest["run_uuid"],
               "manifest_sha256": journal["manifest_sha256"],
               "original_sha256": digest, "original_file": str(target),
               "items": rows,
               "resolved_items": sum(row["resolution"] != "unresolved" for row in rows)}
    analysis_path = root / "human-review" / "resolutions" / f"{digest}.json"
    atomic_write_json(analysis_path, derived)
    derived["analysis_path"] = str(analysis_path)
    return derived


def _resolution_result(run_root: Path, manifest: Mapping[str, Any],
                       reviews: list[Mapping[str, Any]]) -> dict:
    directory = run_root / "human-review" / "original-resolution-files"
    files = []
    if directory.is_dir():
        assert_no_links(directory)
        for path in sorted(directory.glob("*.json")):
            if _is_link(path) or not path.is_file():
                raise BenchmarkError("resolution archive contains an unsafe file")
            value, original = _load_human_submission(path)
            digest = sha256_bytes(original)
            if path.stem != digest:
                raise BenchmarkError("resolution archive integrity check failed")
            rows = _validate_resolution_submission(value, manifest, reviews)
            files.append({"original_sha256": digest, "items": rows,
                          "resolved_items": sum(row["resolution"] != "unresolved" for row in rows),
                          "original_file": str(path)})
    resolutions = []
    for value in files:
        rows = value.get("items", [])
        resolutions.append({"original_sha256": value.get("original_sha256"),
                            "resolved_items": value.get("resolved_items", 0),
                            "item_ids": [row.get("id") for row in rows if isinstance(row, dict)],
                            "unresolved_item_ids": [row.get("id") for row in rows
                                                     if isinstance(row, dict)
                                                     and row.get("resolution") == "unresolved"]})
    return {"status": "RECORDED" if files else "NOT_RECORDED", "files": resolutions}


def export_human_resolution_template(run_root: str | Path, output_path: str | Path) -> dict:
    root = assert_no_links(run_root)
    journal = load_journal(root)
    manifest = journal["manifest"]
    reviews = _load_review_analyses(root, manifest, journal)
    if journal.get("status") != "complete" or len(reviews) != 2:
        raise BenchmarkError("resolution templates require a complete run and two distinct evaluator imports")
    ids = _expected_disagreement_ids(reviews)
    template = {
        "schema_version": 1,
        "review_kind": "v1_disagreement_resolution",
        "run_uuid": manifest["run_uuid"],
        "manifest_sha256": journal["manifest_sha256"],
        "reviewer_ids": sorted(review["reviewer_id"] for review in reviews),
        "items": [{"id": item_id, "resolution": "unresolved", "note": ""}
                  for item_id in ids],
    }
    target = Path(output_path)
    assert_no_links(target.parent)
    if target.exists() or target.is_symlink():
        raise BenchmarkError("resolution template output already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target, template)
    return template


def safe_provider_error(error: Any) -> dict[str, str | None] | None:
    """Keep only the orchestrator's fixed class/code fields; never messages/bodies."""
    if not isinstance(error, dict):
        return None
    code = error.get("code")
    stage = error.get("stage")
    return {
        "code": code if isinstance(code, str) and re.fullmatch(r"[A-Za-z0-9_]{1,64}", code) else None,
        "stage": stage if isinstance(stage, str) and re.fullmatch(r"[A-Za-z0-9_-]{1,32}", stage) else None,
    }


def runtime_progress(journal: Mapping[str, Any]) -> dict[str, int]:
    statuses = [item.get("status") for item in journal.get("items", [])]
    return {"pending": statuses.count("pending"), "running": statuses.count("running"),
            "completed": statuses.count("completed"), "failed": statuses.count("failed"),
            "interrupted": statuses.count("interrupted"),
            "input_drift": statuses.count("failed_input_drift") + statuses.count("not_run_input_drift"),
            "failed_integrity": statuses.count("failed_integrity")}
