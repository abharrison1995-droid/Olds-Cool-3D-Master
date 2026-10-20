"""Versioned, Qt-independent contracts for local recipe generation."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
import json
import math
import re
from typing import Any


CONTRACT_VERSION = 1
RUN_ID_RE = re.compile(r"^[0-9a-f]{32}$")
MAX_CONTRACT_BYTES = 2 * 1024 * 1024


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate generation-contract field")
        result[key] = value
    return result


def _strict_json_loads(payload: bytes):
    return json.loads(
        payload.decode("utf-8"), object_pairs_hook=_unique_pairs,
        parse_constant=lambda value: (_ for _ in ()).throw(
            ValueError(f"invalid JSON constant {value}")))


class GenerationStatus(StrEnum):
    PREPARING = "preparing"
    VALIDATING = "validating"
    STARTING_WORKER = "starting_worker"
    BUILDING = "building"
    CHECKING = "checking"
    RENDERING_PREVIEW = "rendering_preview"
    PUBLISHING = "publishing"
    COMPLETE = "complete"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class GenerationRequest:
    """Only the recipe, immutable policy snapshot and private output root."""

    run_id: str
    recipe_json: str
    output_root: str
    policy_snapshot: dict[str, Any]
    check_config: dict[str, Any] = field(default_factory=dict)
    schema_version: int = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        if not RUN_ID_RE.fullmatch(self.run_id):
            raise ValueError("run_id must be a host-generated 32-character UUID hex value")
        return asdict(self)

    def to_json(self) -> str:
        raw = json.dumps(self.to_dict(), ensure_ascii=False,
                         separators=(",", ":"))
        if len(raw.encode("utf-8")) > MAX_CONTRACT_BYTES:
            raise ValueError("generation request exceeds the IPC size limit")
        return raw

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GenerationRequest":
        if (not isinstance(value, dict) or
                type(value.get("schema_version")) is not int or
                value.get("schema_version") != CONTRACT_VERSION):
            raise ValueError("unsupported generation request schema")
        if set(value) != {"schema_version", "run_id", "recipe_json",
                          "output_root", "policy_snapshot", "check_config"}:
            raise ValueError("generation request contains unknown or missing fields")
        request = cls(
            schema_version=value["schema_version"],
            run_id=value["run_id"],
            recipe_json=value["recipe_json"],
            output_root=value["output_root"],
            policy_snapshot=value["policy_snapshot"],
            check_config=value["check_config"],
        )
        if not isinstance(request.run_id, str) or not RUN_ID_RE.fullmatch(request.run_id):
            raise ValueError("invalid generation run id")
        if not isinstance(request.recipe_json, str):
            raise ValueError("recipe_json must be a string")
        if len(request.recipe_json.encode("utf-8")) > 128 * 1024:
            raise ValueError("recipe_json exceeds the AI policy limit")
        if not isinstance(request.output_root, str) or not request.output_root:
            raise ValueError("output_root must be a non-empty host path")
        if not isinstance(request.policy_snapshot, dict):
            raise ValueError("policy_snapshot must be an object")
        if not isinstance(request.check_config, dict):
            raise ValueError("check_config must be an object")
        return request

    @classmethod
    def from_json(cls, raw: str | bytes) -> "GenerationRequest":
        payload = raw.encode("utf-8") if isinstance(raw, str) else raw
        if not isinstance(payload, bytes) or len(payload) > MAX_CONTRACT_BYTES:
            raise ValueError("generation request exceeds the IPC size limit")
        value = _strict_json_loads(payload)
        return cls.from_dict(value)


@dataclass(frozen=True)
class GenerationArtifact:
    path: str
    kind: str
    size_bytes: int
    sha256: str
    media_type: str | None = None


@dataclass(frozen=True)
class GenerationCheckResult:
    name: str
    ok: bool
    code: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GenerationCheckResult":
        if not isinstance(value, dict) or set(value) != {
                "name", "ok", "code", "message", "details"}:
            raise ValueError("invalid generation check record")
        if not isinstance(value["name"], str) or not isinstance(value["ok"], bool):
            raise ValueError("invalid generation check name or status")
        if not all(isinstance(value[key], str) for key in ("code", "message")):
            raise ValueError("invalid generation check diagnostic")
        if not isinstance(value["details"], dict):
            raise ValueError("invalid generation check details")
        return cls(**value)


@dataclass(frozen=True)
class GenerationEvent:
    run_id: str
    stage: GenerationStatus
    elapsed_seconds: float | None = None
    message: str = ""
    schema_version: int = CONTRACT_VERSION

    def to_dict(self) -> dict[str, Any]:
        if not RUN_ID_RE.fullmatch(self.run_id):
            raise ValueError("invalid generation event run id")
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "stage": self.stage.value,
            "elapsed_seconds": self.elapsed_seconds,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GenerationEvent":
        if not isinstance(value, dict) or set(value) != {
                "schema_version", "run_id", "stage", "elapsed_seconds", "message"}:
            raise ValueError("invalid generation event")
        if type(value["schema_version"]) is not int or value["schema_version"] != CONTRACT_VERSION:
            raise ValueError("unsupported generation event schema")
        if not isinstance(value["run_id"], str) or not RUN_ID_RE.fullmatch(value["run_id"]):
            raise ValueError("invalid generation event run id")
        elapsed = value["elapsed_seconds"]
        if elapsed is not None and (isinstance(elapsed, bool) or
                                    not isinstance(elapsed, (int, float)) or
                                    not math.isfinite(elapsed) or elapsed < 0):
            raise ValueError("invalid generation event elapsed time")
        if not isinstance(value["message"], str) or len(value["message"]) > 240:
            raise ValueError("invalid generation event message")
        return cls(value["run_id"], GenerationStatus(value["stage"]),
                   float(elapsed) if elapsed is not None else None,
                   value["message"], value["schema_version"])


@dataclass(frozen=True)
class GenerationResult:
    run_id: str
    status: GenerationStatus
    artifacts: tuple[GenerationArtifact, ...] = ()
    checks: tuple[GenerationCheckResult, ...] = ()
    warnings: tuple[str, ...] = ()
    error_records: tuple[dict[str, Any], ...] = ()
    elapsed_seconds: float = 0.0
    record_path: str | None = None
    schema_version: int = CONTRACT_VERSION

    @property
    def ok(self) -> bool:
        return self.status is GenerationStatus.COMPLETE

    def to_dict(self) -> dict[str, Any]:
        if not RUN_ID_RE.fullmatch(self.run_id):
            raise ValueError("invalid generation run id")
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "status": self.status.value,
            "artifacts": [asdict(item) for item in self.artifacts],
            "checks": [asdict(item) for item in self.checks],
            "warnings": list(self.warnings),
            "error_records": list(self.error_records),
            "elapsed_seconds": self.elapsed_seconds,
            "record_path": self.record_path,
        }

    def to_json(self) -> str:
        raw = json.dumps(self.to_dict(), ensure_ascii=False,
                         separators=(",", ":"))
        if len(raw.encode("utf-8")) > MAX_CONTRACT_BYTES:
            raise ValueError("generation result exceeds the IPC size limit")
        return raw

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "GenerationResult":
        if (not isinstance(value, dict) or
                type(value.get("schema_version")) is not int or
                value.get("schema_version") != CONTRACT_VERSION):
            raise ValueError("unsupported generation result schema")
        if set(value) != {"schema_version", "run_id", "status", "artifacts",
                          "checks", "warnings", "error_records",
                          "elapsed_seconds", "record_path"}:
            raise ValueError("generation result contains unknown or missing fields")
        if not isinstance(value["run_id"], str) or not RUN_ID_RE.fullmatch(value["run_id"]):
            raise ValueError("invalid generation result run id")
        if not isinstance(value["artifacts"], list) or not isinstance(value["checks"], list):
            raise ValueError("generation result artifacts and checks must be lists")
        if not isinstance(value["warnings"], list) or not all(
                isinstance(item, str) for item in value["warnings"]):
            raise ValueError("generation result warnings must be strings")
        if not isinstance(value["error_records"], list) or not all(
                isinstance(item, dict) for item in value["error_records"]):
            raise ValueError("generation result errors must be records")
        artifacts = []
        for item in value["artifacts"]:
            if not isinstance(item, dict) or set(item) != {
                    "path", "kind", "size_bytes", "sha256", "media_type"}:
                raise ValueError("invalid generation artifact record")
            if (not isinstance(item["path"], str) or not isinstance(item["kind"], str) or
                    type(item["size_bytes"]) is not int or item["size_bytes"] < 0 or
                    not isinstance(item["sha256"], str) or
                    not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]) or
                    (item["media_type"] is not None and
                     not isinstance(item["media_type"], str))):
                raise ValueError("invalid generation artifact fields")
            artifacts.append(GenerationArtifact(**item))
        artifacts = tuple(artifacts)
        checks = tuple(GenerationCheckResult.from_dict(item)
                       for item in value["checks"])
        elapsed = value["elapsed_seconds"]
        if (isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or
                not math.isfinite(elapsed) or elapsed < 0):
            raise ValueError("generation result elapsed time is invalid")
        if value["record_path"] is not None and not isinstance(value["record_path"], str):
            raise ValueError("generation result record path is invalid")
        return cls(
            schema_version=value["schema_version"],
            run_id=value["run_id"],
            status=GenerationStatus(value["status"]),
            artifacts=artifacts,
            checks=checks,
            warnings=tuple(value.get("warnings", [])),
            error_records=tuple(value.get("error_records", [])),
            elapsed_seconds=float(value.get("elapsed_seconds", 0.0)),
            record_path=value.get("record_path"),
        )

    @classmethod
    def from_json(cls, raw: str | bytes) -> "GenerationResult":
        payload = raw.encode("utf-8") if isinstance(raw, str) else raw
        if not isinstance(payload, bytes) or len(payload) > MAX_CONTRACT_BYTES:
            raise ValueError("generation result exceeds the IPC size limit")
        return cls.from_dict(_strict_json_loads(payload))
