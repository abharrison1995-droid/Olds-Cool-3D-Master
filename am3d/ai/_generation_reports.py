"""Bounded, sanitized generation errors and worker evidence.

This module has no orchestrator state, persistence or provider transport.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from am3d.recipes.schema import RecipeValidationError
from .contracts import (
    DeadlineExceededError, GenerationCancelledError, ProviderAuthenticationError,
    ProviderConfigurationError, ProviderCredentialError, ProviderError,
    ProviderModelError, ProviderRateLimitError, ProviderRefusalError,
    ProviderRequestError, ProviderTransientError,
)
from .policy import PolicyError
from .prompts import BriefRequiresUserChoiceError, _known_user_choice_limitations

MAX_ERROR_RECORDS = 32
MAX_ERROR_TEXT = 256
_SAFE_FIELD = re.compile(r"^[A-Za-z0-9_.\[\]]{1,192}$")
_SAFE_CODE = re.compile(r"^[A-Za-z0-9_]{1,64}$")

class _BudgetExceeded(Exception):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _short_optional(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    safe = "".join(c for c in value if c.isalnum() or c in "_-.")[:limit]
    return safe or None


def _safe_error(code: str, stage: str, path: str = "recipe",
                hint: str | None = None) -> dict[str, str]:
    match = _SAFE_CODE.fullmatch(str(code))
    safe_code = match.group(0) if match else "generation_error"
    allowed_stages = {"record", "brief", "candidate", "policy", "worker",
                      "runtime", "check", "publication", "provider",
                      "orchestrator", "refinement", "resource", "schema",
                      "write", "policy-preflight"}
    safe_stage = stage if stage in allowed_stages else "orchestrator"
    safe_path = path if isinstance(path, str) and _SAFE_FIELD.fullmatch(path) else "recipe"
    result = {"code": safe_code, "stage": safe_stage, "path": safe_path,
              "message": _message(safe_code, safe_stage)}
    if isinstance(hint, str):
        clean_hint = "".join(c for c in hint if c.isprintable() and c not in "\\/")[:MAX_ERROR_TEXT]
        if clean_hint:
            result["hint"] = clean_hint
    return result


def _brief_choice_error(exc: BriefRequiresUserChoiceError,
                        raw_request: str) -> dict[str, str]:
    """Map only host-recognized limitations to fixed, actionable UI copy.

    Model-authored limitation strings are deliberately never copied into the
    error record. Known categories are accepted only when the prompt layer's
    deterministic scanner independently found the same marker in the caller's
    original text. Everything else receives a fixed generic edit-or-cancel
    instruction.
    """
    known = set(_known_user_choice_limitations(raw_request))
    matched = [item for item in getattr(exc, "limitations", ())
               if isinstance(item, str) and item in known]
    mappings = (
        ("Would a native editable project and animation sheet meet your need, or do you need an animated interchange file?",
         "animated_glb_unsupported",
         "V1 GLB exports are static pose snapshots and cannot carry animation.",
         "Choose a native AM3D project plus animation sheet, revise the request for a static GLB, or cancel."),
        ("Are opaque tinted panels acceptable, or do you require physically transparent glass?",
         "physical_glass_unsupported",
         "V1 supports stylized opaque or tinted glass-like panels, not physically accurate transparent glass.",
         "Choose stylized opaque or tinted panels, revise the brief for another supported material, or cancel."),
        ("Would you like a new asset built from supported recipe geometry, or do you need an import workflow?",
         "external_import_unsupported",
         "The V1 recipe workflow creates assets from supported geometry and does not import external models.",
         "Choose a new asset built from supported geometry, revise the brief, or cancel."),
        ("Would a composition made from supported primitives and profiles work, or do you need another modeling workflow?",
         "advanced_topology_unsupported",
         "V1 recipe generation does not provide arbitrary sculpting, topology, or Boolean/CSG operations.",
         "Choose a composition from supported primitives and profiles, revise the brief, or cancel."),
        ("Would a simplified head with a basic supported body action work, or do you need facial animation?",
         "facial_animation_unsupported",
         "V1 does not provide expressive facial topology or lip-sync workflows.",
         "Choose a simplified head with a supported body action, revise the brief, or cancel."),
        ("Would explicit positive-scale mirrored parts be acceptable, or should this wait for a verified negative-scale workflow?",
         "negative_scale_unqualified",
         "Negative-scale mirrored texture and export behavior is not qualified for V1.",
         "Choose explicit positive-scale mirrored parts, revise the brief, or cancel."),
        ("Would placing the geometry in the shared rig frame be acceptable, or do you need independent object transforms?",
         "rig_frame_required",
         "V1 requires skinned geometry to share the rig coordinate frame with identity object transforms.",
         "Choose geometry in the shared rig frame, revise the brief, or cancel."),
        ("What smaller maximum count or supported grouped approximation would you accept?",
         "part_count_limit",
         "The requested count of separate parts may exceed configured V1 recipe or execution limits.",
         "Choose a smaller maximum count or a supported grouped approximation, revise the brief, or cancel."),
    )
    for signature, code, _message_text, hint in mappings:
        if any(signature in item for item in matched):
            return _safe_error(code, "brief", hint=hint)

    if _has_unsupported_export_request(raw_request):
        return _safe_error(
            "unsupported_export_format", "brief",
            hint="Supported choices are OBJ, static GLB, native AM3D, spritesheet, toon sheet, and animation sheet; revise the brief or cancel.")
    return _safe_error(
        "unsupported_requirement", "brief",
        hint="Review or revise the brief to choose a supported alternative, or cancel. Unsupported requirements are never silently dropped.")


def _has_unsupported_export_request(text: str) -> bool:
    """Recognize an unsupported export category without retaining its name."""
    matches = re.finditer(
        r"\bexport(?:\s+[A-Za-z][A-Za-z0-9_-]*){0,4}\s+(?:as|to|in)\s+([A-Za-z0-9_.+-]{1,32})\b",
        text, flags=re.IGNORECASE)
    supported = {"obj", "glb", "gltf", "spritesheet", "toon_sheet",
                 "am3d", "animation_sheet"}
    return any(match.group(1).casefold() not in supported for match in matches)


def _message(code: str, stage: str) -> str:
    messages = {
        "cancelled": "Generation was cancelled.",
        "deadline_exceeded": "The shared generation time limit expired.",
        "provider_authentication": "The provider rejected the configured credential.",
        "provider_credential": "The provider credential is unavailable or invalid.",
        "provider_configuration": "The provider configuration is invalid.",
        "provider_model": "The explicitly configured model is unavailable.",
        "provider_refusal": "The provider refused the generation request.",
        "provider_protocol": "The provider response did not match the structured response contract.",
        "provider_transient": "The bounded provider request failed after its retry.",
        "provider_request": "The provider request could not be completed.",
        "unsupported_choice": "The request needs a user choice before generation can continue.",
        "animated_glb_unsupported": "Animated GLB is unsupported; choose a native project and animation sheet or revise the request.",
        "physical_glass_unsupported": "Physical transparent glass is unsupported; choose a stylized material or revise the request.",
        "external_import_unsupported": "External model import is outside the V1 recipe workflow.",
        "advanced_topology_unsupported": "Arbitrary topology and Boolean/CSG operations are outside the V1 recipe workflow.",
        "facial_animation_unsupported": "Expressive facial animation is outside the V1 recipe workflow.",
        "negative_scale_unqualified": "Negative-scale mirrored export behavior is not qualified for V1.",
        "rig_frame_required": "Skinned geometry must use the shared rig coordinate frame in V1.",
        "part_count_limit": "The requested separate-part count may exceed configured V1 limits.",
        "unsupported_export_format": "The requested export format is outside the supported V1 choices.",
        "unsupported_requirement": "The request includes an unsupported capability that needs a user decision.",
        "policy_denied": "The candidate violates the host recipe policy.",
        "validation_failed": "The recipe remained invalid after bounded repair.",
        "check_failed": "The deterministic checks did not pass after bounded repair.",
        "execution_failed": "The recipe could not be executed after bounded repair.",
        "resource_limit": "The host checker stopped the candidate at a configured resource limit.",
        "publication_failed": "The checked output could not be published atomically.",
        "parent_not_successful": "The selected parent run has no checked successful recipe.",
        "parent_record_unavailable": "The selected parent run record is unavailable.",
        "parent_record_invalid": "The selected parent run record is incomplete.",
    }
    return messages.get(code, "The generation run failed at the " + stage + " stage.")


def _classify_exception(exc: BaseException, *, stage: str) -> tuple[str, dict]:
    if isinstance(exc, GenerationCancelledError):
        return "cancelled", _safe_error("cancelled", "provider")
    if isinstance(exc, DeadlineExceededError):
        return "timed_out", _safe_error("deadline_exceeded", "provider")
    if isinstance(exc, ProviderAuthenticationError):
        return "provider_error", _safe_error("provider_authentication", "provider")
    if isinstance(exc, ProviderCredentialError):
        return "provider_error", _safe_error("provider_credential", "provider")
    if isinstance(exc, ProviderConfigurationError):
        return "provider_error", _safe_error("provider_configuration", "provider")
    if isinstance(exc, ProviderModelError):
        return "provider_error", _safe_error("provider_model", "provider")
    if isinstance(exc, ProviderRefusalError):
        return "provider_refused", _safe_error("provider_refusal", "provider")
    if isinstance(exc, (ProviderRateLimitError, ProviderTransientError)):
        return "provider_error", _safe_error("provider_transient", "provider")
    if isinstance(exc, ProviderRequestError):
        return "provider_error", _safe_error("provider_request", "provider")
    if isinstance(exc, BriefRequiresUserChoiceError):
        return "user_choice_required", _safe_error("unsupported_requirement", "brief")
    if isinstance(exc, PolicyError):
        return "policy_error", _policy_error(exc)
    if isinstance(exc, RecipeValidationError):
        return "validation_failed", _validation_error(exc)
    if isinstance(exc, _BudgetExceeded):
        return "budget_exhausted", _safe_error(exc.code, "orchestrator")
    if isinstance(exc, ProviderError):
        return "provider_error", _safe_error("provider_request", "provider")
    return "failed", _safe_error("generation_error", stage)


def _policy_error(exc: PolicyError) -> dict[str, str]:
    return _safe_error(getattr(exc, "code", "policy_denied"), "policy",
                        getattr(exc, "path", "recipe"))


def _validation_error(exc: RecipeValidationError) -> dict[str, str]:
    return _safe_error(getattr(exc, "code", "validation_error"), "candidate",
                        getattr(exc, "path", "recipe"),
                        getattr(exc, "hint", None))


def _checks_passed(result: Any) -> bool:
    return (isinstance(result, dict)
            and result.get("checks_status") == "passed"
            and isinstance(result.get("check_report"), dict)
            and result["check_report"].get("ok") is True
            and result["check_report"].get("status") == "passed")


def _worker_terminal(status: str, result: dict) -> tuple[str, dict]:
    if status == "cancelled":
        return "cancelled", _safe_error("cancelled", "worker")
    if status == "timed_out":
        return "timed_out", _safe_error("deadline_exceeded", "worker")
    if status == "policy_error":
        return "policy_error", _result_error(result, status)
    if status == "validation_error":
        return "validation_failed", _result_error(result, status)
    if status == "resource_limit":
        return "resource_limit", _result_error(result, status)
    return "worker_error", _result_error(result, status)


def _result_error(result: dict, status: str) -> dict[str, str]:
    errors = result.get("error_records") if isinstance(result, dict) else None
    first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    code = first.get("code", {
        "check_failed": "check_failed", "execution_failed": "execution_failed",
        "policy_error": "policy_denied", "validation_error": "validation_failed",
    }.get(status, "worker_error"))
    stage = first.get("stage", "check" if status == "check_failed" else
                      "runtime" if status == "execution_failed" else "worker")
    path = first.get("path", "recipe")
    return _safe_error(code, stage, path, first.get("hint"))


def _result_repair_errors(result: dict, status: str) -> list[dict[str, str]]:
    errors = result.get("error_records") if isinstance(result, dict) else None
    safe = []
    for item in errors[:MAX_ERROR_RECORDS] if isinstance(errors, list) else []:
        if isinstance(item, dict):
            safe.append(_safe_error(item.get("code", "execution_error"),
                                    item.get("stage", "check" if status == "check_failed" else "runtime"),
                                    item.get("path", "recipe"), item.get("hint")))
    if status == "check_failed" and isinstance(result.get("check_report"), dict):
        report = result["check_report"]
        for check in report.get("checks", [])[:MAX_ERROR_RECORDS]:
            if isinstance(check, dict) and check.get("status") == "failed":
                check_id = _short_optional(check.get("id"), 64) or "check_failed"
                safe.append(_safe_error(check_id, "check"))
    return safe[:MAX_ERROR_RECORDS] or [_safe_error("execution_error", "runtime")]


def _safe_worker_summary(result: Any) -> dict:
    if not isinstance(result, dict):
        return {"status": "worker_error", "attempt_id": None,
                "checks_status": "not_run", "manifest": []}
    status = result.get("status")
    statuses = {"checked_ok", "check_failed", "execution_failed", "execution_ok",
                "policy_error", "validation_error", "worker_error", "cancelled",
                "timed_out", "resource_limit"}
    summary = {"status": status if status in statuses else "worker_error",
            "attempt_id": _short_optional(result.get("attempt_id"), 64),
            "checks_status": result.get("checks_status") if result.get("checks_status") in
            {"not_run", "not_requested", "unavailable", "passed", "failed"} else "not_run",
            "artifact_count": len(result.get("manifest", []))
            if isinstance(result.get("manifest"), list) else 0}
    errors = result.get("error_records")
    first = errors[0] if isinstance(errors, list) and errors and isinstance(errors[0], dict) else {}
    # Worker metadata is untrusted at this persistence boundary too. Only
    # fixed reason/phase pairs survive; no raw messages or paths are copied.
    if (status == "worker_error" and isinstance(first.get("audit_reason"), str)
            and isinstance(first.get("audit_phase"), str) and first.get("audit_reason") in
            {"path_syntax", "reserved_name", "collision", "link", "containment",
             "unexpected_file", "file_count", "audit_policy"}
            and first.get("audit_phase") in {"live", "final"}):
        summary["audit_reason"] = first["audit_reason"]
        summary["audit_phase"] = first["audit_phase"]
    return summary


def _safe_manifest(value: Any) -> list[dict[str, Any]]:
    result = []
    for item in value[:256] if isinstance(value, list) else []:
        if not isinstance(item, dict):
            continue
        path = item.get("path")
        digest = item.get("sha256")
        size = item.get("bytes")
        if (isinstance(path, str) and len(path) <= 512 and not Path(path).is_absolute()
                and ".." not in Path(path).parts and isinstance(digest, str)
                and re.fullmatch(r"[0-9a-f]{64}", digest)
                and type(size) is int and size >= 0):
            result.append({"path": path.replace("\\", "/"),
                           "sha256": digest, "bytes": size})
    return result


def _bounded_check_report(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) <= 256 * 1024:
            return value
    except (TypeError, ValueError, UnicodeEncodeError):
        pass
    return {"ok": False, "status": "failed", "checks": [],
            "artifacts": [], "measurements": {},
            "limitations": ["check report exceeded its record size limit"]}


def _bounded_candidate(value: Any) -> dict | None:
    """Copy a policy-approved candidate without retaining arbitrary objects."""
    try:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")
        if len(encoded) > 512 * 1024:
            return None
        copied = json.loads(encoded.decode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        return None
    return copied if isinstance(copied, dict) else None


def _status_message(status: str) -> str:
    return {
        "completed": "The checked project is published.",
        "cancelled": "Generation was cancelled.",
        "timed_out": "The generation time limit expired.",
        "policy_error": "The candidate was blocked by recipe policy.",
        "check_failed": "The candidate did not pass deterministic checks.",
        "execution_failed": "The candidate could not be executed.",
        "publication_failed": "The checked candidate could not be published.",
    }.get(status, "Generation finished with a recorded failure.")
