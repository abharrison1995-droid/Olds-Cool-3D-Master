"""Adversarial and boundary tests for the AI-only recipe policy."""

from __future__ import annotations

import pytest

from am3d.ai.policy import (
    MAX_AUTHORED_POINTS,
    MAX_BONES_PER_RIG,
    MAX_EVALUATED_TRIANGLES,
    MAX_GRAPH_NODES,
    MAX_OBJECTS,
    MAX_RECIPE_BYTES,
    MAX_SHEET_CELL_SIZE,
    PolicyError,
    prepare_recipe,
)
from am3d.recipes.schema import RecipeValidationError


def _recipe(**changes):
    recipe = {"name": "test asset", "objects": [{"name": "body", "primitive": "box"}]}
    recipe.update(changes)
    return recipe


def test_prepare_recipe_always_adds_host_native_export_and_replaces_model_paths():
    out = prepare_recipe(_recipe(exports=[
        {"format": "obj", "path": "models/body.obj"},
        {"format": "glb", "path": "also-body.glb"},
    ]))
    assert out["exports"] == [
        {"format": "am3d", "path": "project.am3d", "params": {}},
        {"format": "obj", "path": "export_01", "params": {}},
        {"format": "glb", "path": "export_02", "params": {}},
    ]


@pytest.mark.parametrize("bad_path", [
    "C:\\outside\\project.am3d", "C:relative.obj", "\\\\server\\share\\x.obj",
    "../escape.obj", "exports/../../outside.obj", "/tmp/out.obj", "NUL.obj",
    "bad\nname.obj",
])
def test_unsafe_original_export_path_is_terminal_policy_error(bad_path):
    with pytest.raises(PolicyError) as exc:
        prepare_recipe(_recipe(exports=[{"format": "obj", "path": bad_path}]))
    assert exc.value.code == "output_path_denied"
    assert str(exc.value).find(bad_path) < 0


def test_safe_malformed_numeric_parameter_is_repairable_schema_validation():
    with pytest.raises(RecipeValidationError) as exc:
        prepare_recipe(_recipe(objects=[{"name": "body", "primitive": "sphere",
                                        "params": {"radius": "large"}}]))
    assert exc.value.code == "invalid_type"
    assert exc.value.path == "recipe.objects[0].params.radius"


@pytest.mark.parametrize("raw,code", [
    (_recipe(objects=[{"name": "sphere", "primitive": "sphere",
                       "params": {"radius": float("nan")}}]), "invalid_value"),
    (_recipe(objects=[{"name": "lathe", "primitive": "lathe",
                       "params": {"profile": [[0, 0], [1, 1]], "sections": 129}}]), "resource_limit"),
    (_recipe(objects=[{"name": "plane", "primitive": "plane",
                       "params": {"n": MAX_SHEET_CELL_SIZE + 1}}]), "resource_limit"),
    (_recipe(objects=[{"name": "sphere", "primitive": "sphere",
                       "params": {"path": "outside.png"}}]), "resource_access_denied"),
    (_recipe(objects=[{"name": "sphere", "primitive": "shell"}]), "unsupported_verb"),
])
def test_numeric_count_and_unsupported_operation_preflight(raw, code):
    with pytest.raises((PolicyError, RecipeValidationError)) as exc:
        prepare_recipe(raw)
    assert exc.value.code == code


def test_object_count_is_rejected_before_geometry_preflight():
    objects = [{"name": f"part-{i}", "primitive": "plane"}
               for i in range(MAX_OBJECTS + 1)]
    with pytest.raises(PolicyError, match="objects") as exc:
        prepare_recipe(_recipe(objects=objects))
    assert exc.value.code == "resource_limit"


def test_default_tessellation_triangle_budget_rejects_many_box_patches():
    objects = [{"name": f"box-{i}", "primitive": "box"}
               for i in range(MAX_OBJECTS)]
    with pytest.raises(PolicyError) as exc:
        prepare_recipe(_recipe(objects=objects))
    assert exc.value.code == "resource_limit"
    assert "triangles" in str(exc.value)
    assert MAX_EVALUATED_TRIANGLES == 250_000


def test_bone_graph_and_copied_rig_bounds_are_enforced():
    bones = [{"name": f"b{i}", "head": [0, i, 0], "tail": [0, i + 1, 0]}
             for i in range(MAX_BONES_PER_RIG + 1)]
    with pytest.raises(PolicyError) as exc:
        prepare_recipe(_recipe(objects=[{"name": "rig", "bones": bones}]))
    assert exc.value.code == "resource_limit"

    source_bones = [{"name": f"b{i}", "head": [0, i, 0], "tail": [0, i + 1, 0]}
                    for i in range(44)]
    shared = [
        {"name": "rig", "bones": source_bones},
        {"name": "one", "params": {"skeleton": "rig"}},
        {"name": "two", "params": {"skeleton": "rig"}},
        {"name": "three", "params": {"skeleton": "rig"}},
        {"name": "four", "params": {"skeleton": "rig"}},
        {"name": "five", "params": {"skeleton": "rig"}},
    ]
    with pytest.raises(PolicyError) as exc:
        prepare_recipe(_recipe(objects=shared))
    assert exc.value.code == "resource_limit"
    assert "256" in str(exc.value)


def test_authored_profile_point_and_graph_node_limits():
    profile = [[i / 4096, i / 4096] for i in range(MAX_AUTHORED_POINTS + 1)]
    with pytest.raises(PolicyError) as exc:
        prepare_recipe(_recipe(objects=[{"name": "lathe", "primitive": "lathe",
                                        "params": {"profile": profile}}]))
    assert exc.value.code == "resource_limit"

    graph = [{"type": "solid"} for _ in range(MAX_GRAPH_NODES + 1)]
    with pytest.raises(PolicyError) as exc:
        prepare_recipe(_recipe(materials=[{"name": "paint", "graph": graph}]))
    assert exc.value.code == "resource_limit"


def test_nested_resource_path_and_code_fields_are_terminal():
    with pytest.raises(PolicyError) as resource:
        prepare_recipe(_recipe(materials=[{
            "name": "paint", "graph": [{"type": "noise", "params": {"image_path": "C:/secret.png"}}],
        }]))
    assert resource.value.code == "resource_access_denied"

    with pytest.raises(PolicyError) as code:
        prepare_recipe({**_recipe(), "script": "print('no')"})
    assert code.value.code == "unsupported_code"


@pytest.mark.parametrize("change,field_path", [
    ({"objects": [{"name": "body", "primitive": "box", "bones": 0}]},
     "recipe.objects[0].bones"),
    ({"materials": [{"name": "paint", "graph": 0}]},
     "recipe.materials[0].graph"),
    ({"exports": [{"format": "obj", "path": None}]},
     "recipe.exports[0].path"),
])
def test_falsy_wrongly_typed_optional_fields_are_repairable(change, field_path):
    with pytest.raises(RecipeValidationError) as exc:
        prepare_recipe(_recipe(**change))
    assert exc.value.path == field_path


def test_procedural_action_budget_includes_bones_copied_from_shared_rig():
    bones = [{"name": f"b{i}", "head": [0, i, 0], "tail": [0, i + 1, 0]}
             for i in range(MAX_BONES_PER_RIG)]
    objects = [
        {"name": "rig", "bones": bones},
        {"name": "body", "primitive": "box", "params": {"skeleton": "rig"}},
    ]
    actions = [{"name": f"walk-{index}", "kind": "walk", "character": "body"}
               for index in range(5)]
    with pytest.raises(PolicyError) as exc:
        prepare_recipe(_recipe(objects=objects, actions=actions))
    assert exc.value.code == "resource_limit"
    assert "action" in str(exc.value)


def test_export_collisions_are_host_resolved_and_unicode_scene_names_survive():
    original = _recipe(
        objects=[{"name": "箱 — body / front", "primitive": "box"}],
        exports=[
            {"format": "obj", "path": "same"},
            {"format": "glb", "path": "same"},
        ],
    )
    safe = prepare_recipe(original)
    assert safe["objects"][0]["name"] == original["objects"][0]["name"]
    assert safe["exports"][1]["path"] != safe["exports"][2]["path"]
    assert safe["exports"][1]["path"] == "export_01"
    assert safe["exports"][2]["path"] == "export_02"


def test_oversized_recipe_wire_representation_is_rejected():
    raw = _recipe(name="x" * MAX_RECIPE_BYTES)
    with pytest.raises(PolicyError) as exc:
        prepare_recipe(raw)
    assert exc.value.code == "response_too_large"
