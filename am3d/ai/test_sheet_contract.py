"""Focused regressions for the fixed checker's export contract."""

from __future__ import annotations

import json
import os
import uuid

import pytest
from PIL import Image

from am3d.ai import checks
from am3d.ai.checks import check_artifacts
from am3d.core.script import Session
from am3d.recipes.executor import RecipeExecutor, _artifact_object_name


def _recipe(exports, names=("body",)):
    export_specs = []
    for spec in exports:
        if spec.get("format") in {"spritesheet", "toon_sheet"}:
            export_specs.append({**spec,
                                 "params": {"views": 4, "size": 16,
                                            **spec.get("params", {})}})
        else:
            export_specs.append(spec)
    return {
        "name": "sheet contract fixture",
        "objects": [
            {"name": name, "primitive": "box",
             "params": {"width": 1.0, "height": 1.0, "depth": 0.8}}
            for name in names
        ],
        "materials": [],
        "actions": [],
        "exports": export_specs,
    }


def _execute(tmp_path, recipe):
    output = tmp_path / "candidate"
    output.mkdir(parents=True)
    session = Session()
    result = RecipeExecutor(session, output_root=str(output),
                            safe_artifact_names=True).execute(recipe)
    assert result.ok, result.errors
    session.save_project(str(output / "project.am3d"))
    return output, session


def _report(recipe, output, *, brief=None, requirements=None):
    accepted = brief or {"brief": "A bounded sheet fixture."}
    return check_artifacts(
        recipe, output, brief=accepted,
        generation={"run_id": str(uuid.uuid4()),
                    "accepted_brief": accepted},
        requirements=requirements,
    )


def _sheet_paths(scene, base):
    paths = []
    meshes = [(name, mesh) for name, mesh in scene.meshes.items()
              if len(mesh.vertices)]
    for index, (name, _mesh) in enumerate(meshes):
        opaque = _artifact_object_name(name, index, True)
        candidate = f"{base}_{opaque}"
        stem, suffix = os.path.splitext(candidate)
        paths.append(candidate if suffix.casefold() == ".png"
                     else stem + ".png")
    return paths


def _export_report(recipe, output, *, brief=None, requirements=None, scene=None):
    report = {"checks": [], "resource_limit": False}
    checks._verify_exports(
        output, recipe, report, requirements, scene=scene,
        accepted_brief=brief)
    return report


@pytest.mark.parametrize(
    ("fmt", "names"),
    [
        ("spritesheet", ("body café",)),
        ("toon_sheet", ("body café",)),
        ("spritesheet", ("body/骨", "arm .. / 翼")),
        ("toon_sheet", ("body/骨", "arm .. / 翼")),
    ],
)
def test_per_object_sheet_exports_match_fixed_worker_names_and_scene_order(
        tmp_path, fmt, names):
    recipe = _recipe([{"format": fmt, "path": "ignored-sheet"}], names)
    output, session = _execute(tmp_path, recipe)
    scene = session.evaluate_scene(visible_only=True, apply_transforms=True)
    expected = _sheet_paths(scene, "ignored-sheet")
    assert expected
    assert all((output / path).is_file() for path in expected)

    report = _export_report(recipe, output,
                            brief={"brief": "A bounded sheet fixture.",
                                   "exports": [fmt]},
                            requirements={"required_exports": [fmt]},
                            scene=scene)
    requested = next(item for item in report["checks"]
                     if item["id"] == "requested_exports")
    assert requested["status"] == "passed", requested["details"]
    assert set(expected).issubset(set(requested["details"]["files"]))
    assert report["resource_limit"] is False


def test_missing_object_sheet_cannot_be_filled_by_other_pngs(tmp_path):
    recipe = _recipe([{"format": "spritesheet", "path": "parts"}],
                     ("body/骨", "arm .. / 翼"))
    output, session = _execute(tmp_path, recipe)
    scene = session.evaluate_scene(visible_only=True, apply_transforms=True)
    expected = _sheet_paths(scene, "parts")
    assert len(expected) == 2
    (output / expected[0]).unlink()
    Image.new("RGBA", (16, 16), (20, 30, 40, 255)).save(output / "atlas.png")
    Image.new("RGBA", (16, 16), (20, 30, 40, 255)).save(output / "renamed.png")

    report = _export_report(recipe, output,
                            brief={"brief": "A bounded sheet fixture.",
                                   "exports": ["spritesheet"]},
                            scene=scene)
    requested = next(item for item in report["checks"]
                     if item["id"] == "requested_exports")
    assert requested["status"] == "failed"
    assert any("object sheet is missing" in issue
               for issue in requested["details"]["issues"])
    assert report["resource_limit"] is False


def test_malformed_expected_sheet_is_an_ordinary_export_failure(tmp_path):
    recipe = _recipe([{"format": "toon_sheet", "path": "toon"}])
    output, _session = _execute(tmp_path, recipe)
    expected = next(path for path in output.glob("toon_*.png"))
    expected.write_bytes(b"not a png")

    scene = Session()
    scene.load_project(str(output / "project.am3d"))
    report = _export_report(
        recipe, output,
        brief={"brief": "A bounded sheet fixture.",
               "exports": ["toon_sheet"]},
        scene=scene.evaluate_scene(visible_only=True, apply_transforms=True))
    requested = next(item for item in report["checks"]
                     if item["id"] == "requested_exports")
    assert requested["status"] == "failed"
    assert report["resource_limit"] is False


def test_oversized_sheet_header_sets_resource_flag_before_pixel_load(
        tmp_path, monkeypatch):
    recipe = _recipe([{"format": "spritesheet", "path": "sheet"}])
    output, session = _execute(tmp_path, recipe)
    scene = session.evaluate_scene(visible_only=True, apply_transforms=True)
    monkeypatch.setattr(checks, "_MAX_IMAGE_DIMENSION", 8)
    original_load = Image.Image.load
    oversized_loads = []

    def guarded_load(image, *args, **kwargs):
        if image.width > checks._MAX_IMAGE_DIMENSION or image.height > checks._MAX_IMAGE_DIMENSION:
            oversized_loads.append(image.size)
            raise AssertionError("oversized sheet must fail before pixel allocation")
        return original_load(image, *args, **kwargs)

    monkeypatch.setattr(Image.Image, "load", guarded_load)
    check_report = {"checks": []}
    checks._verify_exports(output, recipe, check_report, scene=scene)
    requested = check_report["checks"][0]
    assert requested["status"] == "failed"
    assert check_report["resource_limit"] is True
    assert check_report["resource_limit_details"][0]["kind"] in {
        "png_dimension", "png_pixels"}
    assert oversized_loads == []


def test_accepted_brief_exports_cannot_be_dropped_from_recipe(tmp_path):
    recipe = _recipe([])
    output, _session = _execute(tmp_path, recipe)
    accepted = {"brief": "A cube and its sprite sheet.",
                "exports": ["am3d", "spritesheet"]}
    report = _export_report(recipe, output, brief=accepted)
    requested = next(item for item in report["checks"]
                     if item["id"] == "requested_exports")
    assert requested["status"] == "failed"
    assert any("spritesheet" in issue
               for issue in requested["details"]["issues"])
    assert report["resource_limit"] is False


def test_accepted_and_independent_export_requirements_are_unioned(tmp_path):
    recipe = _recipe([{"format": "obj", "path": "mesh"}])
    output, _session = _execute(tmp_path, recipe)
    accepted = {"brief": "A cube with requested OBJ and GLB.",
                "exports": ["obj", "glb"]}
    report = _export_report(recipe, output, brief=accepted,
                            requirements={"required_exports": ["obj", "spritesheet"]})
    requested = next(item for item in report["checks"]
                     if item["id"] == "requested_exports")
    assert requested["status"] == "failed"
    assert "glb" in " ".join(requested["details"]["issues"])
    assert "spritesheet" in " ".join(requested["details"]["issues"])


def test_unrecognized_required_format_uses_fixed_diagnostic(tmp_path):
    recipe = _recipe([])
    output, _session = _execute(tmp_path, recipe)
    report = _export_report(recipe, output,
                            brief={"brief": "A bounded fixture."},
                            requirements={"required_exports": ["private-sentinel-format"]})
    requested = next(item for item in report["checks"]
                     if item["id"] == "requested_exports")
    assert requested["status"] == "failed"
    assert "unsupported or malformed" in " ".join(requested["details"]["issues"])
    assert "private-sentinel-format" not in json.dumps(report)


def test_native_obj_glb_and_per_object_sheet_remain_one_requested_export_set(
        tmp_path):
    exports = [
        {"format": "am3d", "path": "saved-project"},
        {"format": "obj", "path": "export_01"},
        {"format": "glb", "path": "export_02"},
        {"format": "spritesheet", "path": "export_03"},
    ]
    recipe = _recipe(exports)
    output, session = _execute(tmp_path, recipe)
    scene = session.evaluate_scene(visible_only=True, apply_transforms=True)
    expected_sheets = _sheet_paths(scene, "export_03")
    accepted = {"brief": "An editable cube with all requested exports.",
                "exports": ["am3d", "obj", "glb", "spritesheet"]}
    report = _report(recipe, output, brief=accepted,
                     requirements={"required_exports": ["am3d", "obj", "glb"]})
    requested = next(item for item in report["checks"]
                     if item["id"] == "requested_exports")
    assert requested["status"] == "passed", requested["details"]
    assert set(expected_sheets).issubset(set(requested["details"]["files"]))
    assert report["status"] == "passed", report["checks"]


def test_animation_sheet_keeps_single_unsuffixed_composited_output(tmp_path):
    recipe = {
        "name": "composited animation contract fixture",
        "objects": [
            {"name": "driver", "primitive": "box",
             "params": {"width": 1.0, "height": 1.0, "depth": 0.8},
             "bones": [{"name": "root", "head": [0, 0, 0],
                        "tail": [0, 0.5, 0]}]},
            {"name": "target", "primitive": "box",
             "params": {"width": 0.6, "height": 0.6, "depth": 0.6},
             "bones": [{"name": "root", "head": [0, 0, 0],
                        "tail": [0, 0.5, 0]}]},
        ],
        "materials": [],
        "actions": [{"name": "turn", "kind": "custom", "duration": 1.0,
                     "character": "driver",
                     "channels": [{"bone": "root", "property": "rotate",
                                   "keys": [{"time": 0, "value": [0, 0, 0]},
                                            {"time": 1, "value": [0, 0, 45]}]}]}],
        "exports": [
            {"format": "am3d", "path": "saved-project"},
            {"format": "animation_sheet", "path": "animation",
             "params": {"action": "turn", "frames": 2,
                        "columns": 2, "size": 24}},
        ],
    }
    output, _session = _execute(tmp_path, recipe)
    assert (output / "animation.png").is_file()
    assert not list(output.glob("animation_object_*.png"))
    accepted = {"brief": "Two animated meshes in one composite sheet.",
                "exports": ["am3d", "animation_sheet"]}
    report = _export_report(recipe, output, brief=accepted,
                            requirements={"required_exports": ["animation_sheet"]})
    requested = next(item for item in report["checks"]
                     if item["id"] == "requested_exports")
    assert requested["status"] == "passed", requested["details"]
    assert "animation.png" in requested["details"]["files"]
    assert report["resource_limit"] is False
