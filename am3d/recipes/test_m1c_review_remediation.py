"""Focused regressions for the independent M1 exit-review blockers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from am3d.recipes.executor import RecipeExecutor
from am3d.recipes.resources import (
    LIMITS,
    estimate_recipe_resources,
    resource_limit_issues,
)
from am3d.recipes.schema import recipe_from_dict, validate_recipe


def _record_at(result, path):
    return next(record for record in result.error_records
                if record["path"] == path)


def test_animation_sheet_estimate_counts_padded_grids():
    recipe = recipe_from_dict({
        "objects": [{"name": "shape", "primitive": "plane"}],
        "exports": [{
            "format": "animation_sheet",
            "path": f"sheet_{index}",
            "params": {"frames": 1, "columns": 16, "size": 256},
        } for index in range(17)],
    })

    estimate = estimate_recipe_resources(recipe)

    assert estimate["sheet_cells"] == 16
    assert estimate["sheet_pixels"] == 17 * 16 * 256 * 256
    assert any(issue["path"] == "recipe.exports[].params"
               and issue["code"] == "resource_limit"
               for issue in resource_limit_issues(estimate))


@pytest.mark.parametrize(
    ("frames", "columns", "size", "rows", "cells", "width", "height"),
    [
        (1, 16, 256, 1, 16, 4096, 256),
        (16, 16, 16, 1, 16, 256, 16),
        (17, 16, 16, 2, 32, 256, 32),
        (5, 8, 32, 1, 8, 256, 32),
    ],
)
def test_sheet_layout_uses_padded_grid_formula(
        frames, columns, size, rows, cells, width, height):
    from am3d.core.sheet_layout import calculate_sheet_layout

    layout = calculate_sheet_layout(frames, columns, size)
    assert (layout.rows, layout.allocated_cells, layout.width, layout.height,
            layout.pixels) == (rows, cells, width, height, width * height)


@pytest.mark.parametrize("values", [(0, 1, 16), (1, 0, 16), (1, 1, 0)])
def test_sheet_layout_rejects_nonpositive_dimensions(values):
    from am3d.core.sheet_layout import calculate_sheet_layout

    with pytest.raises(ValueError):
        calculate_sheet_layout(*values)


@pytest.mark.parametrize(("actual", "is_limited"), [
    (16_000_000, False),
    (16_000_001, True),
])
def test_sheet_pixel_ceiling_accepts_exact_limit_and_rejects_over(
        monkeypatch, actual, is_limited):
    monkeypatch.setitem(LIMITS, "sheet_pixels", 16_000_000)
    issues = resource_limit_issues({"sheet_pixels": actual})
    assert any(issue["path"] == "recipe.exports[].params"
               for issue in issues) is is_limited


def test_explicit_png_sheets_derive_distinct_object_filenames(tmp_path):
    result = RecipeExecutor(output_root=str(tmp_path)).execute({
        "name": "named_sheets",
        "objects": [
            {"name": "ball", "primitive": "plane"},
            {"name": "cube", "primitive": "box"},
        ],
        "exports": [{"format": "spritesheet", "path": "sheet.png",
                     "params": {"views": 1, "size": 16}}],
    })

    paths = [path for fmt, path in result.exports if fmt == "spritesheet"]
    assert result.ok, result.error_records
    assert {Path(path).name for path in paths} == {
        "sheet_ball.png", "sheet_cube.png"}
    assert len(set(paths)) == 2
    assert all(Path(path).is_file() for path in paths)


def test_dotted_sheet_stem_and_sanitized_names_remain_distinct(tmp_path):
    result = RecipeExecutor(output_root=str(tmp_path)).execute({
        "name": "dotted_sheets",
        "objects": [
            {"name": "a/b", "primitive": "plane"},
            {"name": "a b", "primitive": "plane"},
        ],
        "exports": [{"format": "toon_sheet",
                     "path": "my.asset.sheet.png",
                     "params": {"views": 1, "size": 16}}],
    })

    paths = [path for fmt, path in result.exports if fmt == "toon_sheet"]
    assert result.ok, result.error_records
    assert len(paths) == 2 and len(set(paths)) == 2
    assert all(Path(path).name.startswith("my.asset.sheet_a_b_")
               for path in paths)
    assert all(path.endswith(".png") for path in paths)


def test_duplicate_export_destinations_fail_before_publication(tmp_path):
    destination = tmp_path / "same_ball.png"
    destination.write_bytes(b"keep existing file")
    result = RecipeExecutor(output_root=str(tmp_path)).execute({
        "name": "duplicate_sheet_targets",
        "objects": [{"name": "ball", "primitive": "plane"}],
        "exports": [
            {"format": "spritesheet", "path": "same.png",
             "params": {"views": 1, "size": 16}},
            {"format": "spritesheet", "path": "same",
             "params": {"views": 1, "size": 16}},
        ],
    })

    assert not result.ok
    assert any(record["code"] == "duplicate_export_destination"
               for record in result.error_records)
    assert result.exports == []
    assert destination.read_bytes() == b"keep existing file"


def test_same_sheet_basename_in_different_directories_is_valid(tmp_path):
    result = RecipeExecutor(output_root=str(tmp_path)).execute({
        "name": "separate_sheet_dirs",
        "objects": [{"name": "ball", "primitive": "plane"}],
        "exports": [
            {"format": "spritesheet", "path": "one/sheet.png",
             "params": {"views": 1, "size": 16}},
            {"format": "spritesheet", "path": "two/sheet.png",
             "params": {"views": 1, "size": 16}},
        ],
    })
    paths = [path for fmt, path in result.exports if fmt == "spritesheet"]
    assert result.ok, result.error_records
    assert len(paths) == 2 and len(set(paths)) == 2


def test_modifier_first_material_graph_fails_preflight():
    result = RecipeExecutor().execute({
        "materials": [{"name": "paint", "graph": [{"type": "tint"}]}],
    })
    issue = _record_at(result, "recipe.materials[0].graph[0].type")
    assert not result.ok
    assert issue["stage"] == "schema"
    assert issue["code"] != "execution_error"
    assert "upstream" in issue["message"]


def test_negative_noise_seed_fails_preflight_at_seed_path():
    result = RecipeExecutor().execute({
        "materials": [{"name": "grain", "pattern": "noise",
                       "params": {"seed": -1}}],
    })
    issue = _record_at(result, "recipe.materials[0].params.seed")
    assert not result.ok
    assert issue["stage"] == "schema"
    assert issue["code"] == "invalid_parameter"


def test_skeleton_reference_requires_bones_but_resolves_forward_reference():
    no_bones = recipe_from_dict({"objects": [
        {"name": "mesh", "primitive": "plane",
         "params": {"skeleton": "rig"}},
        {"name": "rig", "primitive": "box"},
    ]})
    result = RecipeExecutor().execute(no_bones)
    issue = _record_at(result, "recipe.objects[0].params.skeleton")
    assert not result.ok
    assert issue["stage"] == "schema"

    forward_reference = recipe_from_dict({"objects": [
        {"name": "mesh", "primitive": "plane",
         "params": {"skeleton": "rig"}},
        {"name": "rig", "bones": [
            {"name": "root", "head": [0, 0, 0], "tail": [0, 1, 0]}]},
    ]})
    assert validate_recipe(forward_reference) == []
    assert RecipeExecutor().execute(forward_reference).ok


def test_animation_sheet_rejects_unknown_explicit_action_before_build():
    result = RecipeExecutor().execute({
        "objects": [{"name": "shape", "primitive": "plane"}],
        "exports": [{"format": "animation_sheet", "path": "walk.png",
                     "params": {"action": "missing"}}],
    })
    issue = _record_at(result, "recipe.exports[0].params.action")
    assert not result.ok
    assert issue["stage"] == "schema"
    assert issue["code"] == "missing_reference"


def test_trusted_subdivisions_above_ai_ceiling_remain_supported(tmp_path):
    data = {"name": "trusted_high_subdivision", "objects": [
        {"name": "sphere", "primitive": "sphere",
         "params": {"sections": 129}},
    ]}

    trusted = RecipeExecutor().execute(data)
    ai = RecipeExecutor(ai_mode=True, output_root=str(tmp_path)).execute(data)

    assert trusted.ok, trusted.error_records
    assert not ai.ok
    issue = _record_at(ai, "recipe.objects[0].params.sections")
    assert issue["code"] == "invalid_parameter"
    assert "AI-mode" in issue["message"]


def test_ai_ceilings_are_profile_specific_across_other_capabilities():
    cases = [
        {"objects": [{"name": "plane", "primitive": "plane",
                      "params": {"n": 129}}]},
        {"materials": [{"name": "pattern", "pattern": "solid",
                         "params": {"size": 257}}]},
        {"objects": [{"name": "shape", "primitive": "plane"}],
         "exports": [{"format": "animation_sheet", "path": "sheet",
                      "params": {"frames": 17, "columns": 17}}]},
    ]
    for data in cases:
        recipe = recipe_from_dict(data)
        assert validate_recipe(recipe) == []
        assert validate_recipe(recipe, ai_mode=True)


def _moving_action_recipe(*, ineffective=False, add_unrelated=False):
    objects = [{"name": "hero", "primitive": "sphere", "bones": [
        {"name": "root", "head": [0, 0, 0], "tail": [0, 1, 0]}]}]
    if add_unrelated:
        objects.append({"name": "prop", "primitive": "plane"})
    keys = ([{"time": 0, "value": [0, 0, 0]},
             {"time": 1, "value": [0, 1, 0]}] if not ineffective else
            [{"time": 0, "value": [0, 0, 0]},
             {"time": 1, "value": [0, 0, 0]}])
    return {"objects": objects, "actions": [{
        "name": "move", "kind": "custom", "character": "hero",
        "channels": [{"bone": "root", "property": "translate",
                      "keys": keys}],
    }]}


def test_unassigned_reusable_action_is_allowed_in_ai_mode():
    result = RecipeExecutor(ai_mode=True).execute({
        "objects": [{"name": "rig", "bones": [
            {"name": "root", "head": [0, 0, 0], "tail": [0, 1, 0]}]}],
        "actions": [{"name": "library_idle", "kind": "custom",
                     "channels": []}],
    })
    assert result.ok, result.error_records
    assert not any(record["code"] == "no_action_effect"
                   for record in result.error_records)


def test_assigned_moving_action_with_unrelated_geometry_is_allowed():
    result = RecipeExecutor(ai_mode=True).execute(
        _moving_action_recipe(add_unrelated=True))
    assert result.ok, result.error_records
    assert not any(record["code"] == "no_action_effect"
                   for record in result.error_records)


def test_assigned_ineffective_action_is_rejected_in_ai_mode():
    result = RecipeExecutor(ai_mode=True).execute(
        _moving_action_recipe(ineffective=True))
    assert not result.ok
    assert any(record["code"] == "no_action_effect"
               for record in result.error_records)


def test_provider_schema_hides_texture_path_while_full_schema_keeps_it():
    import jsonschema
    from pathlib import Path

    root = Path(__file__).parents[2]
    full = json.loads((root / "docs/recipes/recipe-v1.schema.json").read_text())
    provider = json.loads(
        (root / "docs/recipes/recipe-v1.provider.schema.json").read_text())
    texture_recipe = {
        "version": 1,
        "name": "trusted_texture",
        "materials": [{"name": "paint", "texture": "/tmp/private.png"}],
    }

    jsonschema.validate(texture_recipe, full)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(texture_recipe, provider)
    assert "texture" not in provider["$defs"]["material"]["properties"]
    assert validate_recipe(recipe_from_dict(texture_recipe)) == []
    ai_issue = next(issue for issue in validate_recipe(
        recipe_from_dict(texture_recipe), ai_mode=True)
                    if issue.path == "recipe.materials[0].texture")
    assert ai_issue.code == "unsupported_capability"
