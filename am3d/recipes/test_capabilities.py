"""Contract tests for the recipe capability registry."""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path

import numpy as np

from am3d.recipes.capabilities import CAPABILITIES
from am3d.recipes.primitives import BUILDERS
from am3d.recipes.schema import recipe_from_dict, validate_recipe


def test_registry_names_match_runtime_builders():
    from am3d.renderer.materials import PATTERNS
    from am3d.recipes import animation

    assert {name for category, name in CAPABILITIES
            if category == "primitive"} == set(BUILDERS)
    assert {name for category, name in CAPABILITIES
            if category == "pattern"} == set(PATTERNS)
    assert {name for category, name in CAPABILITIES
            if category == "action_kind"} == {
                *animation._GENERATORS, "custom", "retarget"}

    for category, functions, excluded in (
            ("primitive", BUILDERS, set()),
            ("pattern", PATTERNS, set()),
            ("action_kind", animation._GENERATORS,
             {"bones", "name", "duration"})):
        for name, function in functions.items():
            params = CAPABILITIES[(category, name)].params
            sig = inspect.signature(function).parameters
            expected = set(sig) - excluded
            assert set(params) == expected, (category, name)
            for param_name in expected:
                actual = sig[param_name].default
                spec = params[param_name]
                if actual is inspect.Parameter.empty:
                    assert spec.required
                else:
                    assert spec.has_default
                    assert spec.default == actual


def test_every_registry_entry_has_description_cost_and_typed_parameters():
    supported_types = {"number", "integer", "boolean", "string",
                       "nullable_string", "color", "profile2", "profile3",
                       "mapping", "object"}
    for cap in CAPABILITIES.values():
        assert cap.description
        assert cap.cost_hint
        for param in cap.params.values():
            assert param.type in supported_types
            assert param.has_default or param.required or param.type


def test_registry_validation_collects_full_path_errors_in_one_pass():
    recipe = recipe_from_dict({
        "objects": [{"name": "body", "primitive": "sphere",
                     "params": {"radius": "wide", "sektions": 8}}],
        "materials": [{"name": "paint", "pattern": "scales",
                       "params": {"colur": [1, 0, 0]}}],
        "actions": [{"name": "clip", "kind": "custom", "character": "body",
                     "channels": [{"bone": "root", "property": "move",
                                   "keys": [{"time": 0, "value": [0, 0, 0],
                                             "interp": "cubic"}]}]}],
        "exports": [{"format": "spritesheet", "path": "sheet",
                     "params": {"views": 64, "quality": 2}}],
    })
    records = [problem.to_record() for problem in validate_recipe(recipe)]
    paths = {record["path"] for record in records}
    assert {
        "recipe.objects[0].params.radius",
        "recipe.objects[0].params.sektions",
        "recipe.materials[0].pattern",
        "recipe.actions[0].channels[0].property",
        "recipe.actions[0].channels[0].keys[0].interp",
        "recipe.exports[0].params.views",
        "recipe.exports[0].params.quality",
    } <= paths
    assert all(record["message"] for record in records)


def test_trs_shorthand_compiles_with_the_gui_transform_convention():
    from am3d.core.mathutil import compose_trs

    recipe = recipe_from_dict({"objects": [{
        "name": "prop", "primitive": "box",
        "transform": {"translate": [1, 2, 3],
                      "rotate_deg": [15, -20, 30],
                      "scale": [2, 3, 4]},
    }]})
    expected = compose_trs([1, 2, 3], [15, -20, 30], [2, 3, 4])
    assert np.allclose(recipe.objects[0].transform, expected)
    assert validate_recipe(recipe) == []


def test_ai_mode_applies_the_portable_object_name_contract():
    ok = recipe_from_dict({"objects": [{"name": "Knight body-1",
                                        "primitive": "box"}]})
    bad = recipe_from_dict({"objects": [{"name": "../Knight",
                                         "primitive": "box"}]})
    assert validate_recipe(ok, ai_mode=True) == []
    issue = next(p for p in validate_recipe(bad, ai_mode=True)
                 if p.code == "invalid_name")
    assert issue.path == "recipe.objects[0].name"


def test_shared_filename_sanitizer_is_collision_resistant_and_portable():
    from am3d.core.paths import sanitize_filename_component

    assert sanitize_filename_component("hero") == "hero"
    assert sanitize_filename_component("a/b") != sanitize_filename_component("a b")
    assert sanitize_filename_component("CON") != "CON"
    assert "/" not in sanitize_filename_component("a/b")


def test_shared_filename_sanitizer_is_collision_resistant_and_portable():
    from am3d.core.paths import sanitize_filename_component

    assert sanitize_filename_component("hero") == "hero"
    assert sanitize_filename_component("a/b") != sanitize_filename_component("a b")
    assert sanitize_filename_component("CON") != "CON"
    assert "/" not in sanitize_filename_component("a/b")


def test_external_agent_guide_registry_table_is_current():
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/generate_recipe_capabilities.py", "--check"],
        cwd=root, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr or result.stdout
