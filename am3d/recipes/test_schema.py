"""Tests for the recipe schema (the LLM contract)."""

from __future__ import annotations

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


def test_unknown_primitive_rejected():
    with pytest.raises(ValueError, match="unknown primitive"):
        recipe_from_dict({"objects": [{"name": "x", "primitive": "dragon"}]})


def test_unknown_action_kind_rejected():
    with pytest.raises(ValueError, match="unknown kind"):
        recipe_from_dict({"actions": [{"name": "a", "kind": "fly"}]})


def test_unknown_export_format_rejected():
    with pytest.raises(ValueError, match="unknown export format"):
        recipe_from_dict({"exports": [{"format": "fbx"}]})


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


def test_extra_keys_are_ignored_not_fatal():
    # LLMs add stray keys; the coercer must tolerate them.
    r = recipe_from_dict({
        "objects": [{"name": "b", "primitive": "box", "colour": "red",
                     "notes": "make it shiny"}],
    })
    assert r.objects[0].params == {}
    assert validate_recipe(r) == []


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