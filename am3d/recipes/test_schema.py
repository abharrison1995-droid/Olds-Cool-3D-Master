"""Tests for the recipe schema (the LLM contract)."""

from __future__ import annotations

import copy
import json

import pytest

from am3d.recipes import (
    Recipe,
    recipe_from_dict,
    validate_recipe,
)


def test_minimal_recipe_roundtrip():
    data = {
        "name": "knight",
        "objects": [
            {"name": "body", "primitive": "sphere",
             "params": {"radius": 0.6}},
        ],
    }
    r = recipe_from_dict(data)
    assert r.name == "knight"
    assert validate_recipe(r) == []
    # JSON round-trip must stay valid
    again = recipe_from_dict(json.loads(r.to_json()))
    assert again.objects[0].primitive == "sphere"


def test_unknown_primitive_reported_by_validator():
    problems = validate_recipe(recipe_from_dict(
        {"objects": [{"name": "x", "primitive": "dragon"}]}))
    assert any(p.code == "unsupported_primitive" and
               p.path == "recipe.objects[0].primitive" for p in problems)


def test_unknown_action_kind_reported_by_validator():
    problems = validate_recipe(recipe_from_dict(
        {"actions": [{"name": "a", "kind": "fly"}]}))
    assert any(p.code == "unsupported_action_kind" and
               p.path == "recipe.actions[0].kind" for p in problems)


def test_unknown_export_format_reported_by_validator():
    problems = validate_recipe(recipe_from_dict(
        {"exports": [{"format": "fbx"}]}))
    assert any(p.code == "unsupported_export_format" and
               p.path == "recipe.exports[0].format" for p in problems)


def test_gltf_normalises_to_glb():
    r = recipe_from_dict({"exports": [{"format": "gltf", "path": "o"}]})
    assert r.exports[0].format == "glb"


def test_validation_catches_bad_parent_and_character():
    data = {
        "objects": [
            {"name": "hero", "bones": [
                {"name": "hip", "head": [0, 0, 0], "tail": [0, 1, 0]},
                {"name": "up", "head": [0, 1, 0], "tail": [0, 2, 0],
                 "parent": "nonexistent"},
            ]},
        ],
        "actions": [{"name": "walk", "kind": "walk", "character": "ghost"}],
    }
    problems = validate_recipe(recipe_from_dict(data))
    assert any("unknown parent" in p for p in problems)
    assert any("unknown character" in p for p in problems)


def test_unknown_fields_are_rejected_with_a_path():
    with pytest.raises(ValueError, match="unknown field 'colour'") as excinfo:
        recipe_from_dict({
            "objects": [{"name": "b", "primitive": "box",
                         "colour": "red"}],
        })
    assert excinfo.value.path == "recipe.objects[0].colour"


def test_unsupported_version_is_rejected():
    with pytest.raises(ValueError, match="unsupported recipe version"):
        recipe_from_dict({"version": 99})


def test_object_without_geometry_flagged():
    r = recipe_from_dict({"objects": [{"name": "empty"}]})
    assert any("no primitive, splines or bones" in p
               for p in validate_recipe(r))


def test_rig_only_object_is_valid():
    r = recipe_from_dict({"objects": [{"name": "hero", "bones": [
        {"name": "hip", "head": [0, 0, 0], "tail": [0, 1, 0]}]}]})
    assert validate_recipe(r) == []


def test_root_must_be_dict():
    with pytest.raises(ValueError, match="JSON object"):
        recipe_from_dict([1, 2, 3])


def test_bone_hierarchy_cycle_is_rejected():
    r = recipe_from_dict({
        "objects": [{
            "name": "cyclical",
            "bones": [
                {"name": "a", "head": [0, 0, 0], "tail": [0, 1, 0], "parent": "b"},
                {"name": "b", "head": [0, 1, 0], "tail": [0, 2, 0], "parent": "a"},
            ]
        }]
    })
    problems = validate_recipe(r)
    assert any("cyclic bone hierarchy" in p for p in problems)
    issue = next(p for p in problems if "cyclic bone hierarchy" in p)
    assert issue.code == "cyclic_bone_hierarchy"


def test_numeric_ranges_and_finite_checks():
    # Roughness out of range
    with pytest.raises(ValueError, match="roughness"):
        recipe_from_dict({
            "materials": [{"name": "m", "roughness": 1.5}]
        })

    # Duration <= 0
    with pytest.raises(ValueError, match="duration"):
        recipe_from_dict({
            "actions": [{"name": "a", "kind": "walk", "duration": 0}]
        })


def test_custom_action_unknown_bone_is_rejected():
    r = recipe_from_dict({
        "objects": [{"name": "hero", "bones": [
            {"name": "hip", "head": [0, 0, 0], "tail": [0, 1, 0]}
        ]}],
        "actions": [{
            "name": "wave",
            "kind": "custom",
            "character": "hero",
            "channels": [{"bone": "nonexistent_bone", "keys": [{"time": 0, "value": [0, 0, 0]}]}],
        }],
    })
    problems = validate_recipe(r)
    assert any("references unknown bone" in p for p in problems)
    issue = next(p for p in problems if "references unknown bone" in p)
    assert issue.code == "unknown_bone"


def test_container_type_validation():
    with pytest.raises(ValueError, match="must be a list"):
        recipe_from_dict({"objects": 123})

    with pytest.raises(ValueError, match="must be a list"):
        recipe_from_dict({"materials": "none"})


def test_schema_json_conformance():
    import jsonschema
    from pathlib import Path
    from am3d.recipes.schema import PRIMITIVES, ACTION_KINDS

    schema_path = Path(__file__).parent.parent.parent / "docs" / "recipes" / "recipe-v1.schema.json"
    assert schema_path.exists()
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    # Assert enum parity
    schema_prims = set(schema["$defs"]["object"]["properties"]["primitive"]["enum"]) - {None}
    assert schema_prims == PRIMITIVES

    schema_actions = set(schema["$defs"]["action"]["properties"]["kind"]["enum"])
    assert schema_actions == ACTION_KINDS
    from am3d.recipes.capabilities import CAPABILITIES
    assert set(schema["$defs"]["material"]["properties"]["pattern"]["enum"]) - {None} == {
        name for category, name in CAPABILITIES if category == "pattern"}
    assert set(schema["$defs"]["graphNode"]["properties"]["type"]["enum"]) == {
        name for category, name in CAPABILITIES if category == "graph_node"}
    assert set(schema["$defs"]["channel"]["properties"]["property"]["enum"]) == {
        name for category, name in CAPABILITIES if category == "channel_property"}
    assert set(schema["$defs"]["key"]["properties"]["interp"]["enum"]) == {
        name for category, name in CAPABILITIES if category == "interpolation"}

    # Validate minimal and full recipes against json schema
    valid_sample = {
        "version": 1,
        "name": "valid_knight",
        "objects": [
            {
                "name": "body",
                "primitive": "sphere",
                "params": {"radius": 0.5},
                "transform": [1.0, 2.0, 3.0],
            },
            {
                "name": "hero",
                "transform": [
                    [1, 0, 0, 0],
                    [0, 1, 0, 0],
                    [0, 0, 1, 0],
                    [0, 0, 0, 1],
                ],
                "bones": [
                    {
                        "name": "hip",
                        "head": [0, 0, 0],
                        "tail": [0, 1, 0],
                        "weights": {"0": 0.5, "1": 0.5},
                        "cp_weights": {"0": 0.5, "1": 0.5},
                    }
                ],
            },
        ],
        "materials": [{"name": "iron", "roughness": 0.4, "metalness": 0.8}],
        "actions": [{"name": "walk", "kind": "walk", "duration": 1.0, "character": "hero"}],
        "exports": [{"format": "obj", "path": "out/knight"}],
    }
    jsonschema.validate(instance=valid_sample, schema=schema)

    trs_sample = copy.deepcopy(valid_sample)
    trs_sample["objects"][0]["transform"] = {
        "translate": [1, 2, 3], "rotate_deg": [10, 20, 30],
        "scale": [1, 1, 1],
    }
    jsonschema.validate(instance=trs_sample, schema=schema)

    # Negative weights must fail schema validation
    invalid_weights_sample = copy.deepcopy(valid_sample)
    invalid_weights_sample["objects"][1]["bones"][0]["weights"] = {"0": -0.5}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=invalid_weights_sample, schema=schema)

    # Validate actual repo examples against schema
    with open("docs/recipes/examples/knight_full.json", "r", encoding="utf-8") as f:
        kf = json.load(f)
    jsonschema.validate(instance=kf, schema=schema)

    with open("scripts/knight_recipe.json", "r", encoding="utf-8") as f:
        kr = json.load(f)
    jsonschema.validate(instance=kr, schema=schema)


def test_provider_schema_omits_legacy_graph_nodes_and_matches_generator():
    from pathlib import Path
    from am3d.recipes.capabilities import CAPABILITIES
    from am3d.recipes.schema import recipe_from_dict, validate_recipe

    root = Path(__file__).parents[2]
    full = json.loads((root / "docs/recipes/recipe-v1.schema.json").read_text())
    provider_path = root / "docs/recipes/recipe-v1.provider.schema.json"
    provider = json.loads(provider_path.read_text())
    full_nodes = set(full["$defs"]["graphNode"]["properties"]["type"]["enum"])
    provider_nodes = set(provider["$defs"]["graphNode"]["properties"]["type"]["enum"])
    visible_nodes = {cap.name for (kind, _), cap in CAPABILITIES.items()
                     if kind == "graph_node" and cap.model_visible}

    assert full_nodes == {cap.name for (kind, _), cap in CAPABILITIES.items()
                          if kind == "graph_node"}
    assert provider_nodes == visible_nodes
    assert provider_nodes < full_nodes
    assert provider["$id"] != full["$id"]
    assert len(provider_path.read_bytes()) < len(
        (root / "docs/recipes/recipe-v1.schema.json").read_bytes())
    from scripts.build_recipe_provider_schema import render
    assert provider_path.read_text(encoding="utf-8") == render()

    with (root / "am3d/recipes/fixtures/m1/legacy_mix.json").open(
            encoding="utf-8") as fixture:
        legacy = recipe_from_dict(json.load(fixture))
    assert not validate_recipe(legacy)
    assert any(issue.code == "unsupported_capability"
               for issue in validate_recipe(legacy, ai_mode=True))
