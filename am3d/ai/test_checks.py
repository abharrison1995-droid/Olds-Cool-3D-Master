"""Focused offline tests for Phase 4 deterministic artifact checks."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from am3d.ai import checks
from am3d.ai.checks import check_artifacts
from am3d.core.script import Session
from am3d.recipes.executor import RecipeExecutor


def _recipe(*, objects=None, materials=None, exports=None):
    return {
        "name": "checker fixture",
        "objects": objects if objects is not None else [
            {"name": "body", "primitive": "box",
             "params": {"width": 1.0, "height": 1.0, "depth": 0.8}}],
        "materials": materials if materials is not None else [
            {"name": "blue_enamel", "color": [0.04, 0.16, 0.92],
             "objects": ["body"]}],
        "exports": exports if exports is not None else [],
    }


def _candidate(tmp_path, recipe=None, *, empty=False, rig=False, bind=True):
    output = tmp_path / "candidate"
    output.mkdir(parents=True)
    recipe = recipe or _recipe()
    session = Session()
    if not empty:
        result = RecipeExecutor(session, output_root=str(output),
                                safe_artifact_names=True).execute(recipe)
        assert result.ok, result.errors
    if rig:
        if not session.project.objects:
            session.create_object("body")
        session.add_bone("body", "root", [0, 0, 0], [0, 0.5, 0])
        if bind:
            session.bind_geometry("body")
    session.save_project(str(output / "project.am3d"))
    generation = {"run_id": str(uuid.uuid4()),
                  "accepted_brief": {"brief": "A blue enamel test body."}}
    return output, recipe, generation


def test_checker_reopens_native_and_checks_independent_material_intent(tmp_path):
    output, recipe, generation = _candidate(tmp_path)
    report = check_artifacts(
        recipe, output, brief={"brief": "A blue enamel test body."},
        generation=generation,
        requirements={"required_components": ["body"],
                      "materials": [{"name": "blue_enamel",
                                     "color_srgb": [0.04, 0.16, 0.92]}]},
    )

    assert report["ok"] is True
    assert report["status"] == "passed"
    assert report["resource_limit"] is False
    statuses = {item["id"]: item["status"] for item in report["checks"]}
    assert statuses["native_roundtrip"] == "passed"
    assert statuses["required_components"] == "passed"
    assert statuses["material_assignments_and_color"] == "passed"
    assert statuses["artifact_manifest"] == "passed"
    assert any(item["path"] == "preview.png" for item in report["artifacts"])

    pixels = np.asarray(Image.open(output / "preview.png").convert("RGB"))
    foreground = pixels[pixels[..., 3] if pixels.ndim == 4 else pixels.sum(axis=2) > 24]
    assert len(foreground)
    assert float(foreground[:, 2].mean()) > float(foreground[:, 0].mean()) * 2.0


def test_output_tree_byte_preflight_stops_native_loading(tmp_path, monkeypatch):
    output, recipe, generation = _candidate(tmp_path)
    monkeypatch.setattr(checks, "_MAX_TREE_BYTES", 1)
    calls = []

    def forbidden_load(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("over-budget output must fail before native loading")

    monkeypatch.setattr(Session, "load_project", forbidden_load)
    report = check_artifacts(recipe, output, generation=generation)
    assert report["status"] == "failed"
    preflight = next(item for item in report["checks"]
                     if item["id"] == "output_tree_preflight")
    assert preflight["status"] == "failed"
    assert report["resource_limit"] is True
    assert report["resource_limit_details"] == [{
        "kind": "output_file_bytes", "actual": Path(output / "project.am3d").stat().st_size,
        "limit": 1, "unit": "bytes"}]
    assert calls == []


def test_export_preflight_stops_glb_parser_reads(tmp_path, monkeypatch):
    import am3d.export.validate as validator

    recipe = _recipe(exports=[{"format": "glb", "path": "mesh.glb"}])
    output, recipe, _generation = _candidate(tmp_path, recipe)
    monkeypatch.setattr(checks, "_MAX_TREE_BYTES", 1)
    calls = []

    def forbidden_read(*_args, **_kwargs):
        calls.append(True)
        raise AssertionError("over-budget GLB must not be read")

    monkeypatch.setattr(validator, "read_glb", forbidden_read)
    monkeypatch.setattr(validator, "validate_glb", forbidden_read)
    report = {"checks": []}
    assert checks._verify_exports(output, recipe, report) == []
    assert report["checks"][0]["id"] == "requested_exports"
    assert report["checks"][0]["status"] == "failed"
    assert report["resource_limit"] is True
    assert calls == []


def test_checker_marks_strict_obj_byte_guard_as_terminal_resource_limit(tmp_path, monkeypatch):
    import am3d.ai.policy as policy

    recipe = _recipe(exports=[{"format": "obj", "path": "mesh.obj"}])
    output, recipe, generation = _candidate(tmp_path, recipe)
    monkeypatch.setattr(policy, "MAX_OUTPUT_BYTES", 1)
    report = check_artifacts(recipe, output, generation=generation)
    assert report["status"] == "failed"
    assert report["resource_limit"] is True
    assert report["resource_limit_details"] == [{
        "kind": "obj_input_bytes", "actual": (output / "mesh.obj").stat().st_size,
        "limit": 1, "unit": "bytes"}]


def test_empty_or_rig_only_project_cannot_pass_surface_and_preview_checks(tmp_path):
    output, recipe, generation = _candidate(tmp_path, _recipe(objects=[], materials=[]),
                                            empty=True)
    empty_report = check_artifacts(recipe, output, brief={"brief": "empty"},
                                   generation=generation)
    assert empty_report["status"] == "failed"
    assert {c["id"] for c in empty_report["checks"] if c["status"] == "failed"} >= {
        "surface_geometry", "whole_scene_preview"}

    rig_only_path = tmp_path / "rig-only"
    rig_only_path.mkdir()
    rig_only = Session()
    rig_only.create_object("character")
    rig_only.add_bone("character", "root", [0, 0, 0], [0, 1, 0])
    rig_only.save_project(str(rig_only_path / "project.am3d"))
    rig_recipe = {"name": "rig only", "objects": [{"name": "character"}],
                  "materials": [], "exports": []}
    report = check_artifacts(
        rig_recipe, rig_only_path,
        generation={"run_id": str(uuid.uuid4()), "accepted_brief": "a rig"},
        requirements={"rig": {"required": True, "expected_bones": []}},
    )
    assert report["status"] == "failed"
    assert any(c["id"] == "surface_geometry" and c["status"] == "failed"
               for c in report["checks"])


def test_named_empty_required_component_and_one_leg_cannot_satisfy_pairs(tmp_path):
    output, recipe, generation = _candidate(tmp_path)
    session = Session()
    session.load_project(str(output / "project.am3d"))
    session.create_object("handle")
    session.save_project(str(output / "project.am3d"))
    report = check_artifacts(
        recipe, output, brief={"brief": "body with a handle"},
        generation=generation,
        requirements={"required_components": ["body", "handle"]},
    )
    component_check = next(c for c in report["checks"] if c["id"] == "required_components")
    assert component_check["status"] == "failed"
    assert report["resource_limit"] is False
    assert component_check["details"]["missing"] == ["handle"]

    one_leg_recipe = _recipe(objects=[{"name": "leg", "primitive": "box"}],
                             materials=[])
    one_leg, one_leg_recipe, generation = _candidate(
        tmp_path / "paired", one_leg_recipe)
    report = check_artifacts(
        one_leg_recipe, one_leg, brief={"brief": "two legs"},
        generation=generation,
        requirements={"required_components": ["leg_l", "leg_r"]},
    )
    pair_check = next(c for c in report["checks"] if c["id"] == "required_components")
    assert pair_check["status"] == "failed"
    assert pair_check["details"]["missing"] == ["leg_l", "leg_r"]


def test_missing_requested_export_fails_independent_export_check(tmp_path):
    recipe = _recipe(exports=[{"format": "obj", "path": "mesh.obj"}])
    output, recipe, generation = _candidate(tmp_path, recipe)
    # The fixture executor confines the requested export to output_root; remove
    # that exact file to exercise the checker's missing-artifact failure path.
    (Path(output) / "mesh.obj").unlink()
    report = check_artifacts(
        recipe, output, brief={"brief": "blue box"}, generation=generation,
        requirements={"required_exports": ["obj"]},
    )
    exports = next(c for c in report["checks"] if c["id"] == "requested_exports")
    assert exports["status"] == "failed"
    assert any("missing" in issue.casefold() for issue in exports["details"]["issues"])


def test_requested_obj_material_must_match_reopened_native_material(tmp_path):
    recipe = _recipe(exports=[{"format": "obj", "path": "mesh.obj"}])
    output, recipe, generation = _candidate(tmp_path, recipe)
    obj_path = output / "mesh.obj"
    mtl_path = output / "mesh.mtl"
    obj_text = obj_path.read_text(encoding="utf-8")
    material_name = next(line.split()[1] for line in obj_text.splitlines()
                         if line.startswith("usemtl "))
    obj_path.write_text(obj_text.replace(material_name, "mat_wrong"), encoding="utf-8")
    mtl_text = mtl_path.read_text(encoding="utf-8")
    old = f"newmtl {material_name}"
    assert old in mtl_text
    mtl_path.write_text(mtl_text.replace(old, "newmtl mat_wrong").replace(
        "Kd 0.040000 0.160000 0.920000", "Kd 0.920000 0.040000 0.040000"),
        encoding="utf-8")

    report = check_artifacts(
        recipe, output, brief={"brief": "blue box"}, generation=generation,
        requirements={"required_components": ["body"],
                      "materials": [{"name": "blue_enamel",
                                     "color_srgb": [0.04, 0.16, 0.92]}]},
    )
    exports = next(c for c in report["checks"] if c["id"] == "requested_exports")
    assert exports["status"] == "failed"
    assert any("material" in issue.casefold()
               for issue in exports["details"]["issues"])
    assert report["resource_limit"] is False


def test_requested_glb_material_must_match_reopened_native_material(tmp_path):
    import struct
    from am3d.export.validate import read_glb

    recipe = _recipe(exports=[{"format": "glb", "path": "mesh.glb"}])
    output, recipe, generation = _candidate(tmp_path, recipe)
    path = output / "mesh.glb"
    gltf, _binary, _offset = read_glb(str(path))
    material = gltf["materials"][0]
    material["name"] = "x" * len(material["name"])
    material["pbrMetallicRoughness"]["baseColorFactor"] = [0.92, 0.04, 0.04, 1.0]
    import json as _json
    blob = bytearray(path.read_bytes())
    json_size = struct.unpack_from("<I", blob, 12)[0]
    encoded = _json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    assert len(encoded) <= json_size
    encoded += b" " * (json_size - len(encoded))
    blob[20:20 + json_size] = encoded
    path.write_bytes(blob)

    report = check_artifacts(
        recipe, output, brief={"brief": "blue box"}, generation=generation,
        requirements={"required_components": ["body"],
                      "materials": [{"name": "blue_enamel",
                                     "color_srgb": [0.04, 0.16, 0.92]}]},
    )
    exports = next(c for c in report["checks"] if c["id"] == "requested_exports")
    assert exports["status"] == "failed"
    assert any("material" in issue.casefold()
               for issue in exports["details"]["issues"])


def test_checker_sanitizes_untrusted_glb_parser_names_but_valid_export_passes(tmp_path):
    import struct
    from am3d.export.validate import read_glb, validate_glb

    def build_report(folder, *, malformed=False):
        recipe = _recipe(exports=[{"format": "glb", "path": "mesh.glb"}])
        output, recipe, generation = _candidate(folder, recipe)
        path = output / "mesh.glb"
        if malformed:
            gltf, binary, _offset = read_glb(str(path))
            gltf["meshes"][0]["name"] = "private-sentinel-untrusted-name"
            gltf["meshes"][0]["primitives"][0]["attributes"].pop("POSITION")
            encoded_json = json.dumps(gltf, separators=(",", ":"),
                                      ensure_ascii=False).encode("utf-8")
            encoded_json += b" " * ((-len(encoded_json)) % 4)
            total = 12 + 8 + len(encoded_json) + 8 + len(binary)
            blob = (struct.pack("<III", 0x46546C67, 2, total)
                    + struct.pack("<II", len(encoded_json), 0x4E4F534A)
                    + encoded_json
                    + struct.pack("<II", len(binary), 0x004E4942) + binary)
            path.write_bytes(blob)
            legacy_issues = validate_glb(str(path))
            assert any("private-sentinel-untrusted-name" in issue
                       for issue in legacy_issues)
        report = check_artifacts(
            recipe, output, brief={"brief": "blue box"}, generation=generation,
            requirements={"required_components": ["body"],
                          "materials": [{"name": "blue_enamel",
                                         "color_srgb": [0.04, 0.16, 0.92]}]},
        )
        return report

    valid = build_report(tmp_path / "valid")
    assert valid["status"] == "passed"
    valid_export = next(c for c in valid["checks"] if c["id"] == "requested_exports")
    assert valid_export["status"] == "passed"

    malformed = build_report(tmp_path / "malformed", malformed=True)
    malformed_export = next(c for c in malformed["checks"]
                            if c["id"] == "requested_exports")
    assert malformed_export["status"] == "failed"
    serialized = json.dumps(malformed, ensure_ascii=False)
    assert "private-sentinel-untrusted-name" not in serialized


def test_glb_checker_rejects_external_or_out_of_range_texture_references():
    external = checks._verify_glb_materials(
        {"images": [{"uri": "../private-sentinel.png"}],
         "textures": [{"source": 0}], "materials": [], "meshes": []},
        {}, {}, b"12345678")
    assert any("external image" in issue for issue in external)
    assert all("private-sentinel" not in issue for issue in external)

    malformed = checks._verify_glb_materials(
        {"images": [{"bufferView": 0, "mimeType": "image/png"}], "bufferViews": [
             {"buffer": 0, "byteOffset": 4, "byteLength": 12}],
         "buffers": [{"byteLength": 8}], "textures": [{"source": 4}],
         "materials": [{"pbrMetallicRoughness": {
             "baseColorTexture": {"index": 5}}}], "meshes": []},
        {}, {}, b"12345678")
    assert any("range is invalid" in issue for issue in malformed)
    assert any("invalid embedded image" in issue for issue in malformed)
    assert any("invalid texture" in issue for issue in malformed)


def test_glb_resource_caps_report_host_measurements(monkeypatch):
    count_gltf = {"images": [{}, {}]}
    monkeypatch.setattr(checks, "_MAX_GLB_IMAGES", 1)
    details = {}
    issues = checks._verify_glb_images(count_gltf, b"", resource_info=details)
    assert issues == ["GLB contains too many embedded images"]
    assert details == {"kind": "glb_image_count", "actual": 2,
                       "limit": 1, "unit": "count"}

    monkeypatch.setattr(checks, "_MAX_GLB_IMAGES", 128)
    monkeypatch.setattr(checks, "_MAX_GLB_IMAGE_BYTES", 3)
    image_gltf = {"images": [{"bufferView": 0, "mimeType": "image/png"}],
                  "bufferViews": [{"buffer": 0, "byteLength": 4}],
                  "buffers": [{"byteLength": 4}]}
    details = {}
    issues = checks._verify_glb_images(image_gltf, b"1234", resource_info=details)
    assert issues == ["GLB embedded images exceed the bounded byte limit"]
    assert details == {"kind": "glb_image_bytes", "actual": 4,
                       "limit": 3, "unit": "bytes"}

    from io import BytesIO
    from PIL import Image as PILImage
    encoded = BytesIO()
    PILImage.new("RGBA", (2, 2), (20, 40, 60, 255)).save(encoded, format="PNG")
    binary = encoded.getvalue()
    pixel_gltf = {"images": [{"bufferView": 0, "mimeType": "image/png"}],
                  "bufferViews": [{"buffer": 0, "byteLength": len(binary)}],
                  "buffers": [{"byteLength": len(binary)}]}
    monkeypatch.setattr(checks, "_MAX_GLB_IMAGE_BYTES", 256 * 1024 * 1024)
    monkeypatch.setattr(checks, "_MAX_GLB_IMAGE_PIXELS", 1)
    details = {}
    issues = checks._verify_glb_images(pixel_gltf, binary, resource_info=details)
    assert any("pixel limit" in issue for issue in issues)
    assert details == {"kind": "glb_image_pixels", "actual": 4,
                       "limit": 1, "unit": "pixels"}


def test_checker_validates_baked_glb_png_mime_crc_and_header_bounds(tmp_path, monkeypatch):
    import copy
    import struct
    import zlib
    from PIL import Image as PILImage
    from am3d.export.validate import read_glb

    recipe = _recipe(exports=[{"format": "glb", "path": "mesh.glb"}])
    recipe["materials"][0]["pattern"] = "checker"
    output, recipe, generation = _candidate(tmp_path, recipe)
    path = output / "mesh.glb"
    original_glb = path.read_bytes()
    original_gltf, original_binary, _ = read_glb(str(path))
    assert original_gltf.get("images")
    assert original_gltf["images"][0].get("mimeType") == "image/png"

    def write_glb(gltf, binary):
        encoded_json = json.dumps(gltf, separators=(",", ":"),
                                  ensure_ascii=False).encode("utf-8")
        encoded_json += b" " * ((-len(encoded_json)) % 4)
        total = 12 + 8 + len(encoded_json) + 8 + len(binary)
        blob = (struct.pack("<III", 0x46546C67, 2, total)
                + struct.pack("<II", len(encoded_json), 0x4E4F534A)
                + encoded_json
                + struct.pack("<II", len(binary), 0x004E4942) + binary)
        path.write_bytes(blob)

    def checker_report():
        return check_artifacts(
            recipe, output, brief={"brief": "blue patterned box"},
            generation=generation,
            requirements={"required_components": ["body"],
                          "materials": [{"name": "blue_enamel",
                                         "color_srgb": [0.04, 0.16, 0.92]}]},
        )

    def assert_export_failed(report):
        check = next(item for item in report["checks"]
                     if item["id"] == "requested_exports")
        assert check["status"] == "failed"

    valid = checker_report()
    assert valid["status"] == "passed", valid["checks"]
    assert valid["resource_limit"] is False

    wrong_mime = copy.deepcopy(original_gltf)
    wrong_mime["images"][0]["mimeType"] = "text/html"
    write_glb(wrong_mime, original_binary)
    mime_report = checker_report()
    assert_export_failed(mime_report)
    assert mime_report["resource_limit"] is False

    corrupt = bytearray(original_binary)
    view = original_gltf["bufferViews"][original_gltf["images"][0]["bufferView"]]
    offset = int(view.get("byteOffset", 0))
    corrupt[offset:offset + 8] = b"BADIMAGE"
    path.write_bytes(original_glb)
    corrupt_gltf, _binary, _ = read_glb(str(path))
    write_glb(corrupt_gltf, bytes(corrupt))
    corrupt_report = checker_report()
    assert_export_failed(corrupt_report)
    assert corrupt_report["resource_limit"] is False

    oversized = bytearray(original_binary)
    # Keep the PNG IHDR CRC valid while declaring an over-limit width. The
    # checker must reject this header before verify/load allocates pixels.
    struct.pack_into(">I", oversized, offset + 16, checks._MAX_IMAGE_DIMENSION + 1)
    crc = zlib.crc32(oversized[offset + 12:offset + 29]) & 0xffffffff
    struct.pack_into(">I", oversized, offset + 29, crc)
    calls = []
    original_load = PILImage.Image.load

    def no_oversized_load(image, *args, **kwargs):
        if image.size[0] > checks._MAX_IMAGE_DIMENSION:
            calls.append(image.size)
            raise AssertionError("oversized image must fail before pixel allocation")
        return original_load(image, *args, **kwargs)

    oversized_gltf = copy.deepcopy(original_gltf)
    monkeypatch.setattr(PILImage.Image, "load", no_oversized_load)
    resource_info = {}
    issues = checks._verify_glb_images(oversized_gltf, bytes(oversized),
                                       resource_info=resource_info)
    assert any("dimensions exceed limits" in issue for issue in issues)
    assert resource_info == {"kind": "glb_image_dimension",
                             "actual": checks._MAX_IMAGE_DIMENSION + 1,
                             "limit": checks._MAX_IMAGE_DIMENSION,
                             "unit": "pixels"}
    assert calls == []
    write_glb(oversized_gltf, bytes(oversized))
    oversized_report = checker_report()
    assert_export_failed(oversized_report)
    assert oversized_report["resource_limit"] is True
    assert oversized_report["resource_limit_details"] == [{
        "kind": "glb_image_dimension",
        "actual": checks._MAX_IMAGE_DIMENSION + 1,
        "limit": checks._MAX_IMAGE_DIMENSION, "unit": "pixels"}]

    path.write_bytes(original_glb)
    monkeypatch.setattr(checks, "_MAX_GLB_IMAGE_PIXELS", 1)
    pixel_report = checker_report()
    assert_export_failed(pixel_report)
    assert pixel_report["resource_limit"] is True
    assert pixel_report["resource_limit_details"][0]["kind"] == "glb_image_pixels"
    assert pixel_report["resource_limit_details"][0]["actual"] > 1
    assert pixel_report["resource_limit_details"][0]["unit"] == "pixels"


def _two_rig_animation_recipe(*, explicit_shared=False):
    target = {"name": "target", "primitive": "box",
              "params": {"width": 1.0, "height": 1.0, "depth": 0.8}}
    if explicit_shared:
        target["params"]["skeleton"] = "driver"
    else:
        target["bones"] = [{"name": "root", "head": [0, 0, 0],
                            "tail": [0, 0.5, 0]}]
    return {
        "name": "two rig animation",
        "objects": [
            {"name": "driver", "primitive": "box",
             "params": {"width": 1.0, "height": 1.0, "depth": 0.8},
             "bones": [{"name": "root", "head": [0, 0, 0],
                        "tail": [0, 0.5, 0]}]},
            target,
        ],
        "materials": [],
        "actions": [{"name": "turn", "kind": "custom", "duration": 1.0,
                     "character": "driver",
                     "channels": [{"bone": "root", "property": "rotate",
                                   "keys": [{"time": 0, "value": [0, 0, 0]},
                                            {"time": 0.5, "value": [0, 0, 60]},
                                            {"time": 1, "value": [0, 0, 0]}]}]}],
        "exports": [],
    }


def _check_two_rig_animation(tmp_path, *, explicit_shared=False):
    recipe = _two_rig_animation_recipe(explicit_shared=explicit_shared)
    output = tmp_path / "candidate"
    output.mkdir(parents=True)
    session = Session()
    result = RecipeExecutor(session, output_root=str(output),
                            safe_artifact_names=True).execute(recipe)
    assert result.ok, result.errors
    session.save_project(str(output / "project.am3d"))
    report = check_artifacts(
        recipe, output, brief={"brief": "two boxes with a turning target"},
        generation={"run_id": str(uuid.uuid4())},
        requirements={"rig": {"required": True, "action_kind": "custom",
                               "expected_bones": ["root"],
                               "bound_components": ["target"],
                               "must_deform_components": ["target"]}},
    )
    return report


def test_action_must_be_assigned_per_intended_geometry_or_explicit_shared_rig(tmp_path):
    unbound = _check_two_rig_animation(tmp_path / "unbound")
    animation = next(c for c in unbound["checks"]
                     if c["id"] == "animation_and_deformation")
    assert animation["status"] == "failed"
    assert any("not assigned" in issue
               for issue in animation["details"]["assignment_issues"])

    shared = _check_two_rig_animation(tmp_path / "shared", explicit_shared=True)
    animation = next(c for c in shared["checks"]
                     if c["id"] == "animation_and_deformation")
    assert animation["status"] == "passed", animation["details"]


def test_native_failure_report_does_not_persist_untrusted_exception_text(tmp_path, monkeypatch):
    output, recipe, generation = _candidate(tmp_path)

    class ExplodingSession:
        def load_project(self, _path):
            raise RuntimeError(r"C:\private\sentinel\credential-like-text")

    monkeypatch.setattr(checks, "Session", ExplodingSession)
    report = check_artifacts(recipe, output, generation=generation)
    encoded = json.dumps(report)
    assert report["status"] == "failed"
    assert "sentinel" not in encoded.casefold()
    assert report["resource_limit"] is False
    preflight = next(c for c in report["checks"]
                     if c["id"] == "output_tree_preflight")
    assert preflight["status"] == "passed"
    native_check = next(c for c in report["checks"]
                        if c["id"] == "native_roundtrip")
    assert native_check["status"] == "failed"
    assert native_check["details"]["reason"] == "native_project_or_provenance_verification_failed"


def test_basic_bound_rig_needs_no_animation_but_unweighted_rig_fails(tmp_path):
    recipe = _recipe()
    output, recipe, generation = _candidate(tmp_path, recipe, rig=True, bind=True)
    report = check_artifacts(
        recipe, output, brief={"brief": "a simple bound rig"},
        generation=generation,
        requirements={"rig": {"required": True, "expected_bones": [],
                               "bound_components": ["body"]}},
    )
    assert report["status"] == "passed"
    assert any(c["id"] == "rig_binding" and c["status"] == "passed"
               for c in report["checks"])
    assert not any(c["id"] == "animated_motion" for c in report["checks"])

    unweighted, recipe, generation = _candidate(tmp_path / "unweighted", recipe,
                                                rig=True, bind=False)
    report = check_artifacts(
        recipe, unweighted, brief={"brief": "a simple bound rig"},
        generation=generation,
        requirements={"rig": {"required": True, "expected_bones": [],
                               "bound_components": ["body"]}},
    )
    rig_check = next(c for c in report["checks"] if c["id"] == "rig_binding")
    assert rig_check["status"] == "failed"
    assert any("weights" in issue for issue in rig_check["details"]["issues"])


def test_animation_shares_samples_without_changing_frames_or_logical_counts(tmp_path, monkeypatch):
    from am3d.ai._animation_checks import _check_animation
    from am3d import render_job
    from am3d.core.scene import EvaluatedScene
    from am3d.gpu import scene_camera

    recipe = _two_rig_animation_recipe(explicit_shared=True)
    session = Session()
    assert RecipeExecutor(session, output_root=str(tmp_path)).execute(recipe).ok
    scene = session.evaluate_scene()
    camera = scene_camera(list(scene.meshes.values()))
    original_render = render_job.render_frame_image
    expected = [original_render(session, camera, 128, 128, time=t,
                               action_name="turn", force_software=True)
                for t in (0, .25, .5, .75)]
    original_evaluate = session.evaluate_scene
    evaluations, frames = [], []

    def evaluate(**kwargs):
        evaluations.append(kwargs["time"])
        return original_evaluate(**kwargs)

    def render(source, camera, width, height, **kwargs):
        assert isinstance(source, EvaluatedScene)
        image = original_render(source, camera, width, height, **kwargs)
        frames.append(image)
        return image

    monkeypatch.setattr(session, "evaluate_scene", evaluate)
    monkeypatch.setattr(render_job, "render_frame_image", render)
    report = {"checks": []}
    _check_animation(report, recipe, {"rig": {"must_deform_components": ["driver", "target"]}},
                     {}, session, scene, 2.)
    check = report["checks"][-1]
    assert check["status"] == "passed", check
    assert evaluations == [0, .25, .5, .75]
    assert len(frames) == 4
    assert all(np.array_equal(a, b) for a, b in zip(frames, expected))
    assert check["details"]["rendered_sample_frames"] == 8


@pytest.mark.parametrize("failure", ["exception", "invalid_image"])
def test_shared_animation_render_failure_keeps_component_order_and_stops(tmp_path, monkeypatch, failure):
    from am3d.ai._animation_checks import _check_animation
    from am3d import render_job

    recipe = _two_rig_animation_recipe(explicit_shared=True)
    session = Session()
    assert RecipeExecutor(session, output_root=str(tmp_path)).execute(recipe).ok
    scene = session.evaluate_scene()
    calls = []

    def fail(*args, **kwargs):
        calls.append(kwargs["time"])
        if failure == "invalid_image":
            return np.zeros((1, 1, 4))
        raise RuntimeError("private diagnostic must not enter report")

    monkeypatch.setattr(render_job, "render_frame_image", fail)
    report = {"checks": []}
    _check_animation(report, recipe,
                     {"rig": {"must_deform_components": ["driver", "missing", "target"]}},
                     {}, session, scene, 2.)
    details = report["checks"][-1]["details"]
    assert calls == [0.]
    assert details["rendered_sample_frames"] == 0
    assert details["issues"] == [
        "driver: fixed-camera sample render failed", "driver: motion did not exceed threshold",
        "missing: intended object missing",
        "target: fixed-camera sample render failed", "target: motion did not exceed threshold"]
    assert "private diagnostic" not in json.dumps(report)


@pytest.mark.parametrize("defect", ["nonfinite", "missing", "shape"])
def test_shared_animation_keeps_invalid_component_failures(tmp_path, monkeypatch, defect):
    from am3d.ai._animation_checks import _check_animation
    from am3d import render_job
    recipe = _two_rig_animation_recipe(explicit_shared=True)
    session = Session()
    assert RecipeExecutor(session, output_root=str(tmp_path)).execute(recipe).ok
    scene = session.evaluate_scene()
    evaluate = session.evaluate_scene
    renders = []

    def nonfinite(**kwargs):
        sampled = evaluate(**kwargs)
        if defect == "nonfinite":
            sampled.meshes["target"].vertices[0, 0] = np.nan
        elif defect == "missing":
            del sampled.meshes["target"]
        else:
            sampled.meshes["target"].vertices = sampled.meshes["target"].vertices[:1]
        return sampled

    def render(*args, **kwargs):
        renders.append(kwargs["time"])
        return np.zeros((128, 128, 4))

    monkeypatch.setattr(session, "evaluate_scene", nonfinite)
    monkeypatch.setattr(render_job, "render_frame_image", render)
    report = {"checks": []}
    _check_animation(report, recipe, {"rig": {"must_deform_components": ["driver", "target"]}},
                     {}, session, scene, 2.)
    check = report["checks"][-1]
    assert check["status"] == "failed"
    assert renders == [0, .25, .5, .75]
    assert check["details"]["rendered_sample_frames"] == 4
    issue = ("target: sampled non-finite geometry" if defect == "nonfinite" else
             "target: sampled mesh changed shape or disappeared")
    assert check["details"]["issues"] == [issue] * 4 + [
        "target: motion did not exceed threshold"]


def test_shared_animation_preserves_motion_check_without_camera(tmp_path, monkeypatch):
    from am3d.ai._animation_checks import _check_animation
    from am3d import gpu, render_job
    recipe = _two_rig_animation_recipe(explicit_shared=True)
    session = Session()
    assert RecipeExecutor(session, output_root=str(tmp_path)).execute(recipe).ok
    scene = session.evaluate_scene()

    def no_camera(*args, **kwargs):
        raise ValueError("camera unavailable")

    monkeypatch.setattr(gpu, "scene_camera", no_camera)
    monkeypatch.setattr(render_job, "render_frame_image", lambda *a, **kw: pytest.fail("no camera"))
    report = {"checks": []}
    _check_animation(report, recipe, {"rig": {"must_deform_components": ["driver", "target"]}},
                     {}, session, scene, 2.)
    check = report["checks"][-1]
    assert check["status"] == "passed", check
    assert check["details"]["rendered_sample_frames"] == 0
    assert len(check["details"]["samples"]) == 2
