"""Fixed offline acceptance flow for source and frozen V1 packages.

The command accepts only a host-selected output directory. It has no model,
provider, module, callback, or command override. Provider-shaped responses and
the credential used below exist only inside this trusted acceptance module.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Any


class AcceptanceError(RuntimeError):
    """A fixed acceptance condition failed."""


_BRIEF = (
    "Create a simple blue cube, save an editable native project, and produce "
    "OBJ, GLB, and a preview sprite sheet."
)
_REFINEMENT = "Make the cube taller."
_ENDPOINT = "https://api.openai.com/v1/chat/completions"


def _qt_loaded() -> bool:
    return any(name == "PySide6" or name.startswith("PySide6.")
               for name in sys.modules)


def _linklike(path: Path) -> bool:
    from am3d.core.paths import extended_io_path

    path = Path(extended_io_path(path))
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return (stat.S_ISLNK(info.st_mode)
            or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def _assert_no_link_components(path: Path) -> None:
    from am3d.core.paths import extended_io_path

    current = Path(extended_io_path(path))
    while True:
        if _linklike(current):
            raise AcceptanceError("unsafe_output_path")
        if current.parent == current:
            return
        current = current.parent


def _make_output_root(raw: str) -> Path:
    return _make_output_directory(raw, "phase10-ai-self-test")


def _make_output_directory(raw: str, child_name: str) -> Path:
    from am3d.core.paths import extended_io_path

    if not isinstance(raw, str) or not raw.strip():
        raise AcceptanceError("invalid_output_path")
    supplied = Path(extended_io_path(raw))
    _assert_no_link_components(supplied)
    supplied.mkdir(parents=True, exist_ok=True)
    _assert_no_link_components(supplied)
    if not supplied.is_dir():
        raise AcceptanceError("invalid_output_path")
    root = supplied / child_name
    _assert_no_link_components(root.parent)
    if root.exists() or _linklike(root):
        raise AcceptanceError("output_already_exists")
    root.mkdir()
    _assert_no_link_components(root)
    return root


def _sha256(path: Path) -> str:
    from am3d.core.paths import extended_io_path

    digest = hashlib.sha256()
    with Path(extended_io_path(path)).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _assert_no_sentinel_files(root: Path, sentinel: str) -> None:
    from am3d.core.paths import extended_io_path

    needle = sentinel.encode("ascii")
    root = Path(extended_io_path(root))
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        base = Path(current)
        for name in [*dirs, *files]:
            path = base / name
            if _linklike(path):
                raise AcceptanceError("unsafe_output_tree")
        for name in files:
            path = Path(extended_io_path(base / name))
            tail = b""
            with path.open("rb") as stream:
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    combined = tail + block
                    if needle in combined:
                        raise AcceptanceError("credential_sentinel_written")
                    tail = combined[-max(0, len(needle) - 1):]


def _brief_response(text: str, *, height: float = 1.0) -> dict[str, Any]:
    return {
        "brief": text,
        "style": "simple geometric",
        "intended_use": "offline package acceptance",
        "dimensions": {"width": 1.0, "height": height, "depth": 1.0, "units": "m"},
        "materials": [{
            "name": "blue",
            "appearance": "matte blue",
            "color_srgb": [0.08, 0.24, 0.9],
        }],
        "animation": None,
        "exports": ["am3d", "obj", "glb", "spritesheet"],
        "required_components": [{
            "name": "blue_cube",
            "description": "single box primitive",
            "required": True,
        }],
        "approximations": [],
        "unsupported_requirements": [],
    }


def _recipe_response(height: float) -> dict[str, Any]:
    return {
        "version": 1,
        "name": "phase10_acceptance_cube",
        "objects": [{
            "name": "blue_cube",
            "primitive": "box",
            "params": {"width": 1.0, "height": height, "depth": 1.0},
        }],
        "materials": [{
            "name": "blue",
            "color": [0.08, 0.24, 0.9],
            "objects": ["blue_cube"],
        }],
        "actions": [],
        "exports": [
            {"format": "am3d", "path": "ignored-native"},
            {"format": "obj", "path": "ignored-obj"},
            {"format": "glb", "path": "ignored-glb"},
            {"format": "spritesheet", "path": "ignored-sheet",
             "params": {"views": 4, "size": 48}},
        ],
    }


def _responses() -> list[dict[str, Any]]:
    refinement_brief = _BRIEF + "\n\nRequested refinement: " + _REFINEMENT
    return [
        _brief_response(_BRIEF),
        _recipe_response(1.0),
        _brief_response(refinement_brief, height=1.5),
        _recipe_response(1.5),
    ]


def _verify_ca_and_keyring() -> str:
    import certifi

    ca_path = Path(certifi.where())
    if not ca_path.is_file() or ca_path.stat().st_size <= 0:
        raise AcceptanceError("ca_bundle_missing")

    if sys.platform == "win32":
        from keyring.backends.Windows import WinVaultKeyring  # noqa: F401

        backend = "windows-vault-imported"
    elif sys.platform.startswith("linux"):
        from keyring.backends.SecretService import Keyring  # noqa: F401

        backend = "secret-service-imported"
    else:
        raise AcceptanceError("unsupported_credential_backend_platform")
    return backend


def _run_fixed_generation(root: Path, fake_secret: str) -> dict[str, Any]:
    from am3d.core.paths import extended_io_path

    import httpx

    from am3d.ai.contracts import CancellationToken, ProviderConfig
    from am3d.ai.credentials import SessionCredentialStore
    from am3d.ai.orchestrator import GenerationOrchestrator
    from am3d.ai.providers import HttpxTransport, OpenAICompatibleProvider
    from am3d.ai.records import GenerationRecordStore, application_identity

    responses = _responses()
    transport_state = {"requests": 0}
    identity = application_identity()
    if set(identity) != {"version", "build_id", "capability_version"}:
        raise AcceptanceError("runtime_identity_shape_invalid")
    if not identity["version"] or identity["build_id"] == "unavailable":
        raise AcceptanceError("runtime_identity_unavailable")

    async def handler(request):
        if request.method != "POST" or str(request.url) != _ENDPOINT:
            raise AssertionError("fixed_mock_received_unexpected_request")
        if request.headers.get("authorization") != f"Bearer {fake_secret}":
            raise AssertionError("fixed_mock_credential_not_used")
        body = await request.aread()
        if fake_secret.encode("ascii") in body:
            raise AssertionError("credential_in_provider_payload")
        index = transport_state["requests"]
        if index >= len(responses):
            raise AssertionError("fixed_mock_received_unexpected_call")
        transport_state["requests"] += 1
        content = json.dumps(responses[index], ensure_ascii=False,
                             separators=(",", ":"), allow_nan=False)
        envelope = {
            "id": f"phase10-self-test-{index + 1}",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }],
            "usage": {
                "prompt_tokens": 12,
                "completion_tokens": 18,
                "total_tokens": 30,
            },
        }
        return httpx.Response(
            200,
            headers={"content-type": "application/json",
                     "x-request-id": f"phase10-self-test-{index + 1}"},
            content=json.dumps(envelope, separators=(",", ":")).encode("utf-8"),
            request=request,
        )

    credentials = SessionCredentialStore()
    alias = "phase10-" + secrets.token_hex(8)
    credentials.set(alias, fake_secret)
    provider = OpenAICompatibleProvider(
        ProviderConfig(model="fixed-phase10-acceptance",
                       credential_alias=alias),
        credentials,
        HttpxTransport(httpx.MockTransport(handler)),
    )
    store = GenerationRecordStore(root / "records")
    subject = GenerationOrchestrator(provider, store)
    requirements = {
        "required_components": ["blue_cube"],
        "required_exports": ["am3d", "obj", "glb"],
        "target_dimensions_m": {"width": 1.0, "height": 1.0, "depth": 1.0},
        "dimension_tolerance_fraction": 0.05,
        "materials": [{
            "component": "blue_cube",
            "color_srgb": [0.08, 0.24, 0.9],
            "tolerance_per_channel": 0.01,
        }],
    }

    parent = subject.generate(_BRIEF, cancellation=CancellationToken(),
                              requirements=requirements)
    if parent.status != "completed":
        raise AcceptanceError("initial_generation_failed")
    parent_record = store.get_record(parent.run_id)
    parent_project = Path(parent_record["project_path"])
    if not parent_project.is_file():
        raise AcceptanceError("parent_native_project_missing")
    parent_hash_before = _sha256(parent_project)

    child_requirements = dict(requirements)
    child_requirements["target_dimensions_m"] = {
        "width": 1.0, "height": 1.5, "depth": 1.0,
    }
    child = subject.generate(
        "ignored source text",
        parent_generation_id=parent.run_id,
        refinement_request=_REFINEMENT,
        cancellation=CancellationToken(),
        requirements=child_requirements,
    )
    if child.status != "completed" or child.run_id == parent.run_id:
        raise AcceptanceError("refinement_generation_failed")
    if child.record.get("parent_generation_id") != parent.run_id:
        raise AcceptanceError("refinement_parent_link_missing")
    child_record = store.get_record(child.run_id)
    if child_record.get("parent_generation_id") != parent.run_id:
        raise AcceptanceError("refinement_record_parent_link_missing")
    if _sha256(parent_project) != parent_hash_before:
        raise AcceptanceError("refinement_changed_parent_project")
    if transport_state["requests"] != 4:
        raise AcceptanceError("unexpected_provider_call_count")

    # Reopen and resave both accepted native projects outside immutable history.
    from am3d.core.script import Session
    from am3d.core.serializer import project_content_digest

    reopen_root = root / "native-roundtrip"
    reopen_root.mkdir()
    dimensions = {}
    for label, record in (("parent", parent_record), ("child", child_record)):
        session = Session()
        session.load_project(record["project_path"])
        if "blue_cube" not in session.project.objects:
            raise AcceptanceError("native_project_object_missing")
        first_digest = project_content_digest(session.project, session.actions)
        target = reopen_root / f"{label}.am3d"
        session.save_project(str(target))
        reopened = Session()
        reopened.load_project(str(target))
        second_digest = project_content_digest(reopened.project, reopened.actions)
        if first_digest != second_digest:
            raise AcceptanceError("native_roundtrip_content_changed")
        scene = reopened.evaluate_scene(visible_only=True, apply_transforms=True,
                                        nu=16, nv=16)
        mesh = scene.meshes["blue_cube"]
        import numpy as np

        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        dimensions[label] = (vertices.max(axis=0) - vertices.min(axis=0)).tolist()
    if dimensions["child"][1] <= dimensions["parent"][1] + 0.2:
        raise AcceptanceError("refinement_geometry_did_not_change")

    # Parse exports again outside the worker's fixed checker.
    from am3d.export.validate import validate_glb, validate_obj
    from PIL import Image

    child_root = Path(extended_io_path(child_record["run_root"]))
    manifest = child_record.get("artifact_manifest", [])
    by_path = {entry["path"]: entry for entry in manifest
               if isinstance(entry, dict) and isinstance(entry.get("path"), str)}
    obj_rel = next((name for name in by_path if name.endswith(".obj")), None)
    glb_rel = next((name for name in by_path if name.endswith(".glb")), None)
    sheet_specs = [spec for spec in child_record.get("accepted_recipe", {}).get("exports", [])
                   if isinstance(spec, dict) and spec.get("format") == "spritesheet"]
    sheet_paths = [name for name in by_path
                   if re.fullmatch(r"export_03_object_000_[0-9a-f]{8}\.png", name)]
    preview_rel = "preview.png" if "preview.png" in by_path else None
    if not obj_rel or not glb_rel or len(sheet_specs) != 1 \
            or len(sheet_paths) != 1 or not preview_rel:
        raise AcceptanceError("independent_export_missing")
    obj_path, glb_path = child_root / obj_rel, child_root / glb_rel
    sheet_path, preview_path = child_root / sheet_paths[0], child_root / preview_rel
    obj_issues = validate_obj(extended_io_path(obj_path),
                              root=extended_io_path(child_root))
    glb_issues = validate_glb(extended_io_path(glb_path))
    if obj_issues or glb_issues:
        raise AcceptanceError("independent_export_parse_failed")
    with Image.open(extended_io_path(sheet_path)) as image:
        image.verify()
    with Image.open(extended_io_path(sheet_path)) as image:
        image.load()
        if image.width < 2 or image.height < 2:
            raise AcceptanceError("spritesheet_dimensions_invalid")
        extrema = image.convert("RGB").getextrema()
        if all(low == high for low, high in extrema):
            raise AcceptanceError("spritesheet_is_blank")
    with Image.open(extended_io_path(preview_path)) as image:
        image.verify()
    with Image.open(extended_io_path(preview_path)) as image:
        image.load()
        if image.width < 2 or image.height < 2:
            raise AcceptanceError("preview_dimensions_invalid")
        extrema = image.convert("RGB").getextrema()
        if all(low == high for low, high in extrema):
            raise AcceptanceError("preview_is_blank")

    credentials.clear()
    return {
        "identity": identity,
        "provider_requests": transport_state["requests"],
        "live_network_used": False,
        "transport": "httpx.MockTransport",
        "parent_run_id": parent.run_id,
        "child_run_id": child.run_id,
        "refinement_parent_id": child_record["parent_generation_id"],
        "parent_project_sha256": parent_hash_before,
        "child_project_sha256": _sha256(Path(child_record["project_path"])),
        "reopened_dimensions": dimensions,
        "export_checks": {
            "obj_parse": "passed",
            "glb_parse": "passed",
            "spritesheet_png": "passed",
            "preview_png": "passed",
            "preview_nonblank": True,
        },
        "worker_and_checks": "passed",
        "history_store": "passed",
        "refinement": "passed",
    }


def run_acceptance(output_dir: str) -> dict[str, Any]:
    qt_at_entry = _qt_loaded()
    if qt_at_entry:
        raise AcceptanceError("qt_loaded_before_fixed_dispatch")
    backend = _verify_ca_and_keyring()
    root = _make_output_root(output_dir)
    fake_secret = "phase10-fake-" + secrets.token_hex(24)
    result = _run_fixed_generation(root, fake_secret)
    _assert_no_sentinel_files(root, fake_secret)
    report = {
        "ok": True,
        "mode": "frozen" if getattr(sys, "frozen", False) else "source",
        "qualification": "offline-fixed-mock-transport",
        "live_provider_or_network_qualification": False,
        "qt_loaded_before_dispatch": qt_at_entry,
        "ca_bundle": "present",
        "credential_backend_import": backend,
        "credential_sentinel_written": False,
        "output_files_are_confined_to_fixed_self_test_directory": True,
        **result,
    }
    report_path = root / "acceptance.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    return report


_CREDENTIAL_FAILURE_CODES = {
    "backend_unavailable",
    "secure_store_unavailable",
    "alias_not_absent",
    "store_read_mismatch",
    "store_rotate_mismatch",
    "store_delete_failed",
    "absence_check_failed",
    "cleanup_failed",
    "unsafe_output_path",
    "qt_loaded_before_dispatch",
}


class CredentialProbeFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        if code not in _CREDENTIAL_FAILURE_CODES:
            code = "secure_store_unavailable"
        self.code = code
        super().__init__(code)


def _credential_probe_report(
    *,
    crud_failure_code: str | None,
    cleanup_failure_code: str | None,
    cleanup_required: bool,
) -> dict[str, Any]:
    return {
        "ok": crud_failure_code is None and cleanup_failure_code is None,
        "mode": "frozen" if getattr(sys, "frozen", False) else "source",
        "qualification": "explicit-system-credential-store-sentinel-crud",
        "platform": ("windows" if sys.platform.startswith("win") else
                     "linux" if sys.platform.startswith("linux") else "unsupported"),
        "secure_store_backend": "explicit-platform-backend",
        "real_provider_or_network_used": False,
        "credential_alias_exposed": False,
        "sentinel_values_exposed": False,
        "qt_loaded_before_dispatch": _qt_loaded(),
        "crud_status": "passed" if crud_failure_code is None else "unpassed",
        "crud_failure_code": crud_failure_code,
        "cleanup_status": ("not_required" if not cleanup_required else
                           "unpassed" if cleanup_failure_code else "passed"),
        "cleanup_failure_code": cleanup_failure_code,
    }


def run_credential_store_check(output_dir: str) -> dict[str, Any]:
    """Exercise CRUD only for a random alias created by this invocation.

    This is deliberately separate from the offline fixed mock-transport
    acceptance. It never reads a caller-selected or default credential alias,
    never contacts a provider, and never exposes the random alias or values.
    """
    output_root = _make_output_directory(
        output_dir, "phase10-credential-store-check")
    alias = "phase10-self-test-" + secrets.token_hex(24)
    first_value = "phase10-sentinel-" + secrets.token_urlsafe(32)
    rotated_value = "phase10-rotated-" + secrets.token_urlsafe(32)
    store = None
    mutation_attempted = False
    crud_failure_code: str | None = None
    cleanup_failure_code: str | None = None

    if _qt_loaded():
        crud_failure_code = "qt_loaded_before_dispatch"
    else:
        try:
            from am3d.ai.credentials import SystemCredentialStore

            store = SystemCredentialStore()
        except Exception:
            crud_failure_code = "backend_unavailable"

    if crud_failure_code is None and store is not None:
        try:
            try:
                existing = store.get(alias)
            except Exception:
                raise CredentialProbeFailure("secure_store_unavailable") from None
            if existing is not None:
                raise CredentialProbeFailure("alias_not_absent")

            mutation_attempted = True
            try:
                store.set(alias, first_value)
            except Exception:
                raise CredentialProbeFailure("secure_store_unavailable") from None
            try:
                if store.get(alias) != first_value:
                    raise CredentialProbeFailure("store_read_mismatch")
            except CredentialProbeFailure:
                raise
            except Exception:
                raise CredentialProbeFailure("secure_store_unavailable") from None

            try:
                store.set(alias, rotated_value)
            except Exception:
                raise CredentialProbeFailure("secure_store_unavailable") from None
            try:
                if store.get(alias) != rotated_value:
                    raise CredentialProbeFailure("store_rotate_mismatch")
            except CredentialProbeFailure:
                raise
            except Exception:
                raise CredentialProbeFailure("secure_store_unavailable") from None

            try:
                store.delete(alias)
            except Exception:
                raise CredentialProbeFailure("store_delete_failed") from None
            try:
                if store.get(alias) is not None:
                    raise CredentialProbeFailure("absence_check_failed")
            except CredentialProbeFailure:
                raise
            except Exception:
                raise CredentialProbeFailure("secure_store_unavailable") from None
        except CredentialProbeFailure as exc:
            crud_failure_code = exc.code
        finally:
            if mutation_attempted:
                try:
                    # delete() is idempotent for an absent item in the
                    # approved keyring adapter; the following read verifies
                    # cleanup even after a failed or partially completed set.
                    store.delete(alias)
                    if store.get(alias) is not None:
                        cleanup_failure_code = "cleanup_failed"
                except Exception:
                    cleanup_failure_code = "cleanup_failed"

    report = _credential_probe_report(
        crud_failure_code=crud_failure_code,
        cleanup_failure_code=cleanup_failure_code,
        cleanup_required=mutation_attempted)
    report_path = output_root / "credential-store-check.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="3D MASTER 2005 --ai-self-test",
        description="Run a fixed offline AI check or an explicit secure-store sentinel check.")
    parser.add_argument("--out", required=True,
                        help="host-selected directory for fixed acceptance outputs")
    parser.add_argument("--credential-store-check", action="store_true",
                        help="explicitly probe system-store CRUD with a temporary sentinel")
    args = parser.parse_args(argv)
    if args.credential_store_check:
        try:
            report = run_credential_store_check(args.out)
        except Exception:
            report = _credential_probe_report(
                crud_failure_code="unsafe_output_path",
                cleanup_failure_code=None,
                cleanup_required=False)
            print(json.dumps(report, sort_keys=True))
            return 1
        print(json.dumps({
            "ok": report["ok"],
            "mode": report["mode"],
            "platform": report["platform"],
            "credential_store_crud": report["crud_status"],
            "cleanup": report["cleanup_status"],
        }, sort_keys=True))
        return 0 if report["ok"] else 1
    try:
        report = run_acceptance(args.out)
    except Exception as exc:
        report = {
            "ok": False,
            "mode": "frozen" if getattr(sys, "frozen", False) else "source",
            "qualification": "offline-fixed-mock-transport",
            "error_code": (exc.args[0] if isinstance(exc, AcceptanceError)
                           and exc.args and isinstance(exc.args[0], str)
                           else type(exc).__name__),
            "live_provider_or_network_qualification": False,
            "qt_loaded_before_dispatch": _qt_loaded(),
        }
        print(json.dumps(report, sort_keys=True))
        return 1
    print(json.dumps({"ok": True, "mode": report["mode"],
                      "acceptance": "phase10-ai-self-test/acceptance.json",
                      "provider_requests": report["provider_requests"],
                      "live_network_used": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
