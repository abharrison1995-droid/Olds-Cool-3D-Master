"""End-to-end tests: a full recipe -> assets on disk, exactly as an LLM runs."""

from __future__ import annotations

import json
import os
import struct

import pytest

from am3d.core.script import Session
from am3d.recipes.executor import ExecutionResult, RecipeExecutor
from am3d.recipes.schema import recipe_from_dict


def _knight_recipe(out_base):
    return {
        "name": "knight",
        "objects": [
            {"name": "torso", "primitive": "sphere",
             "params": {"radius": 0.5, "sections": 12, "rings": 6}},
            {"name": "hero", "bones": [
                {"name": "hip", "head": [0, 0.9, 0], "tail": [0, 1.0, 0]},
                {"name": "spine", "head": [0, 1.0, 0], "tail": [0, 1.4, 0],
                 "parent": "hip"},
                {"name": "leg_l", "head": [-0.12, 0.9, 0],
                 "tail": [-0.12, 0.45, 0], "parent": "hip"},
                {"name": "leg_r", "head": [0.12, 0.9, 0],
                 "tail": [0.12, 0.45, 0], "parent": "hip"},
            ]},
        ],
        "materials": [{"name": "steel", "color": [0.6, 0.65, 0.75]}],
        "actions": [
            {"name": "walk", "kind": "walk", "duration": 1.1,
             "character": "hero"},
        ],
        "exports": [
            {"format": "obj", "path": f"{out_base}/knight"},
            {"format": "glb", "path": f"{out_base}/knight"},
            {"format": "spritesheet", "path": f"{out_base}/knight",
             "params": {"views": 4, "size": 48}},
            {"format": "am3d", "path": f"{out_base}/knight"},
        ],
    }


@pytest.fixture()
def executor():
    return RecipeExecutor(Session())


def test_full_recipe_builds_everything(tmp_path, executor):
    base = str(tmp_path / "out" / "knight")
    res = executor.execute(_knight_recipe(base))
    assert res.ok, res.errors
    assert set(res.objects) == {"torso", "hero"}
    assert res.materials == ["steel"]
    assert res.actions == ["walk"]


def test_recipe_exports_all_files(tmp_path, executor):
    base = str(tmp_path / "out" / "knight")
    res = executor.execute(_knight_recipe(base))
    formats = {fmt for fmt, _ in res.exports}
    assert formats == {"obj", "glb", "spritesheet", "am3d"}

    written = {p for _, p in res.exports}
    for suffix in (".obj", ".glb", ".am3d"):
        assert any(p.endswith(suffix) for p in written), suffix
    # Only geometry-bearing objects get sheets (hero is a rig-only object).
    assert any(p.endswith("_torso.png") for p in written)
    assert not any(p.endswith("_hero.png") for p in written)
    for p in written:
        for single in p.split(", "):
            from pathlib import Path
            assert Path(single).stat().st_size > 0


def test_invalid_recipe_raises_before_touching_disk(tmp_path, executor):
    bad = {
        "objects": [{"name": "a", "primitive": "sphere"}],
        "actions": [{"name": "w", "kind": "walk", "character": "ghost"}],
    }
    with pytest.raises(ValueError, match="invalid recipe"):
        executor.execute(bad)


def test_runtime_error_is_captured_not_raised(tmp_path, executor):
    # A primitive param that survives schema validation but fails at build.
    recipe = {
        "name": "x",
        "objects": [{"name": "bad", "primitive": "sphere",
                     "params": {"radius": "huge"}}],
    }
    res = executor.execute(recipe)
    assert not res.ok
    assert res.errors and "radius" in res.errors[0]


def test_procedural_action_requires_bones(tmp_path, executor):
    """A character with no bones cannot carry an action -- fail, don't skip.

    This previously returned ok=True with the action silently absent, which
    let a recipe report success while producing none of the animation it
    asked for.
    """
    with pytest.raises(ValueError) as excinfo:
        executor.execute({
            "name": "solo",
            "objects": [{"name": "blob", "primitive": "box"}],
            "actions": [{"name": "walk", "kind": "walk",
                         "character": "blob"}],
        })
    assert "declares no bones" in str(excinfo.value)


def test_custom_keyframed_action_roundtrip(tmp_path, executor):
    res = executor.execute({
        "name": "custom",
        "objects": [
            {"name": "hero", "bones": [
                {"name": "hip", "head": [0, 0.9, 0], "tail": [0, 1.0, 0]},
            ]},
        ],
        "actions": [{
            "name": "wave", "kind": "custom", "duration": 2.0,
            "character": "hero",
            "channels": [{
                "bone": "hip", "property": "translate",
                "keys": [
                    {"time": 0.0, "value": [0, 0, 0], "interp": "linear"},
                    {"time": 2.0, "value": [1, 0, 0], "interp": "linear"},
                ],
            }],
        }],
        "exports": [{"format": "am3d",
                     "path": str(tmp_path / "custom")}],
    })
    assert res.ok, res.errors
    act = executor.session.get_action("wave")
    mid = act.get_channel("hip").sample(1.0)
    assert mid[0] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# CLI (python -m am3d.recipes)
# ---------------------------------------------------------------------------
def _run_cli(argv):
    from am3d.recipes.cli import main
    return main(argv)


def test_cli_builds_assets_from_json_file(tmp_path):
    import json as _json
    recipe = {
        "name": "cli_box",
        "objects": [{"name": "crate", "primitive": "box"}],
        "exports": [{"format": "obj", "path": str(tmp_path / "crate")}],
    }
    recipe_path = tmp_path / "r.json"
    recipe_path.write_text(_json.dumps(recipe), encoding="utf-8")

    code = _run_cli(["--recipe", str(recipe_path)])
    assert code == 0
    assert (tmp_path / "crate.obj").stat().st_size > 0


def test_cli_tolerates_utf8_bom(tmp_path):
    import json as _json
    recipe = {
        "name": "bom",
        "objects": [{"name": "s", "primitive": "sphere"}],
    }
    recipe_path = tmp_path / "bom.json"
    recipe_path.write_bytes(
        b"\xef\xbb\xbf" + _json.dumps(recipe).encode("utf-8"))
    assert _run_cli(["--recipe", str(recipe_path),
                     "--validate-only"]) == 0


def test_cli_rejects_invalid_recipe_with_exit_1(tmp_path, capsys):
    import json as _json
    p = tmp_path / "bad.json"
    p.write_text(_json.dumps(
        {"objects": [{"name": "x", "primitive": "dragon"}]}), encoding="utf-8")
    code = _run_cli(["--recipe", str(p)])
    assert code == 1
    err = capsys.readouterr().err
    assert "unknown primitive" in err


def test_cli_validate_only_makes_no_files(tmp_path, capsys):
    import json as _json
    recipe = {
        "name": "v",
        "objects": [{"name": "s", "primitive": "sphere"}],
        "exports": [{"format": "obj", "path": str(tmp_path / "never")}],
    }
    p = tmp_path / "v.json"
    p.write_text(_json.dumps(recipe), encoding="utf-8")
    code = _run_cli(["--recipe", str(p), "--validate-only"])
    assert code == 0
    report = _json.loads(capsys.readouterr().out)
    assert report["validated"] is True
    assert not list(tmp_path.glob("never*"))


# ---------------------------------------------------------------------------
# Phase 3D integration: procedural materials -> baked atlases + toon sheets
# ---------------------------------------------------------------------------
def test_textured_recipe_bakes_atlas(tmp_path, executor):
    res = executor.execute({
        "name": "textured",
        "objects": [
            {"name": "wall", "primitive": "box"},
            {"name": "hero", "bones": [
                {"name": "hip", "head": [0, 0.9, 0], "tail": [0, 1.0, 0]},
            ]},
        ],
        "materials": [{
            "name": "bricks",
            "color": [0.6, 0.3, 0.2],
            "pattern": "bricks",
            "params": {"rows": 4, "cols": 2},
            "objects": ["wall"],
        }],
        "exports": [{"format": "obj", "path": str(tmp_path / "out/wall")}],
    })
    assert res.ok, res.errors
    atlas_exports = [(f, p) for f, p in res.exports if f == "atlas"]
    assert len(atlas_exports) == 1
    path = atlas_exports[0][1]
    assert path.endswith("wall_atlas.png")

    from PIL import Image
    img = np.asarray(Image.open(path))
    assert img.shape[2] == 4
    # brick colour present somewhere in the baked atlas
    rgb = img[..., :3].astype(float) / 255.0
    assert (np.abs(rgb - np.array([0.6, 0.3, 0.2])).sum(axis=-1) < 0.3).any()


def test_toon_sheet_export_writes_png(tmp_path, executor):
    res = executor.execute({
        "name": "toon_demo",
        "objects": [{"name": "orb", "primitive": "sphere",
                     "params": {"sections": 10, "rings": 6}}],
        "exports": [{
            "format": "toon_sheet", "path": str(tmp_path / "toon/orb"),
            "params": {"views": 4, "size": 48, "bands": 3},
        }],
    })
    assert res.ok, res.errors
    sheets = [p for _, p in res.exports]
    from pathlib import Path
    for single in sheets[0].split(", "):
        assert Path(single).stat().st_size > 0
        img = np.asarray(Image.open(single)) \
            if False else _load_png(single)
        # ink lines present: some near-black opaque pixels
        dark = ((img[..., :3] < 40).all(axis=-1) & (img[..., 3] > 200))
        assert dark.any(), "toon sheet should contain ink lines"


def test_unpatterned_material_does_not_bake(tmp_path, executor):
    res = executor.execute({
        "name": "plain",
        "objects": [{"name": "b", "primitive": "box"}],
        "materials": [{"name": "flat", "color": [1, 0, 0]}],   # no pattern
        "exports": [{"format": "obj", "path": str(tmp_path / "b")}],
    })
    assert res.ok
    assert not any(f == "atlas" for f, _ in res.exports)


# ---------------------------------------------------------------------------
# Regression: scene correctness in exports (Group D)
# ---------------------------------------------------------------------------
def _executor_with_plane(translation):
    """A session holding one plane object placed at *translation*."""
    from am3d.core.project import Patch
    from am3d.recipes.primitives import build_primitive

    s = Session()
    s.new_project("placed")
    obj = s.create_object("card")
    for pname, net, du, dv in build_primitive("plane")["patches"]:
        obj.patches.append(Patch(name=pname, splines=[], interior=net))
    obj.transform = np.eye(4)
    obj.transform[:3, 3] = translation
    return RecipeExecutor(s)


def test_obj_export_bakes_object_transform(tmp_path):
    executor = _executor_with_plane([10.0, 0.0, 0.0])
    res = ExecutionResult()
    executor._run_exports(recipe_from_dict({
        "name": "placed",
        "exports": [{"format": "obj", "path": str(tmp_path / "card")}],
    }), res)
    assert res.exports and not res.errors
    path = [p for f, p in res.exports if f == "obj"][0]
    xs = [float(ln.split()[1])
          for ln in open(path, encoding="utf-8")
          if ln.startswith("v ")]
    # plane local x is in [-0.5, 0.5]; translated copy must sit near x=10
    assert min(xs) > 9.0 and max(xs) < 11.0


def test_glb_export_bakes_object_transform(tmp_path):
    executor = _executor_with_plane([0.0, 5.0, 0.0])
    res = ExecutionResult()
    executor._run_exports(recipe_from_dict({
        "name": "placed",
        "exports": [{"format": "glb", "path": str(tmp_path / "card")}],
    }), res)
    path = [p for f, p in res.exports if f == "glb"][0]
    blob = open(path, "rb").read()
    json_len, _ = struct.unpack_from("<II", blob, 12)
    gltf = json.loads(blob[20:20 + json_len].decode("utf-8"))
    pos_acc = next(a for a in gltf["accessors"]
                   if a.get("type") == "VEC3" and "min" in a)
    # the translation must be baked into the vertex data itself
    assert pos_acc["min"][1] > 4.0 and pos_acc["max"][1] < 6.0


def test_apply_object_transform_rotates_normals():
    from am3d.recipes.executor import _apply_object_transform
    from am3d.renderer.tessellate import MeshData

    mesh = MeshData([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]],
                    normals=[[0, 0, 1], [0, 0, 1], [0, 0, 1]])
    rot_z_90 = np.array([[0, -1, 0, 0],
                         [1, 0, 0, 0],
                         [0, 0, 1, 0],
                         [0, 0, 0, 1]], dtype=np.float64)
    out = _apply_object_transform(mesh, rot_z_90)
    assert np.allclose(out.vertices[1], [0, 1, 0], atol=1e-9)
    assert np.allclose(out.normals[0], [0, 0, 1], atol=1e-9)
    # identity transform leaves the mesh untouched
    fresh = MeshData([[0, 0, 0], [1, 0, 0], [0, 1, 0]], [[0, 1, 2]])
    same = _apply_object_transform(fresh, np.eye(4))
    assert np.allclose(same.vertices, fresh.vertices)


def test_atlas_outdir_considers_all_export_specs():
    from am3d.recipes.executor import _atlas_outdir
    from am3d.recipes.schema import ExportRecipe

    specs = [ExportRecipe("am3d", "bare"),
             ExportRecipe("obj", os.path.join("sub", "dir", "out"))]
    assert _atlas_outdir(specs) == os.path.join("sub", "dir")
    assert _atlas_outdir([ExportRecipe("obj", "bare")]) == "."
    assert _atlas_outdir([]) == ""


def test_per_patch_material_assignment(tmp_path, executor):
    """Each patch must bake with *its* material, not the first one."""
    res = executor.execute({
        "name": "patches",
        "objects": [{"name": "wall", "primitive": "box"}],
        "materials": [
            {"name": "box_front", "pattern": "solid",
             "params": {"color": [1.0, 0.0, 0.0]}},
            {"name": "box_back", "pattern": "solid",
             "params": {"color": [0.0, 0.0, 1.0]}},
        ],
        "exports": [{"format": "obj", "path": str(tmp_path / "out/wall")}],
    })
    assert res.ok, res.errors
    path = [p for f, p in res.exports if f == "atlas"][0]
    img = _load_png(path).astype(float) / 255.0

    from am3d.renderer.uv_mapping import atlas_grid_layout
    cells = atlas_grid_layout(6)            # box has six patches
    h, w = img.shape[:2]
    # patch 0 = wall_box_front -> red, patch 1 = wall_box_back -> blue
    for idx, expect in ((0, [1, 0, 0]), (1, [0, 0, 1])):
        ou, ov, su, sv = cells[idx]
        r, c = int((ov + sv / 2) * h), int((ou + su / 2) * w)
        assert np.allclose(img[r, c, :3], expect, atol=0.1), idx


def test_graph_material_bakes_through_recipe(tmp_path, executor):
    res = executor.execute({
        "name": "graph_demo",
        "objects": [{"name": "wall", "primitive": "box"}],
        "materials": [{
            "name": "aged_brick",
            "graph": [
                {"type": "bricks", "params": {"rows": 4}},
                {"type": "noise_overlay", "params": {"amount": 0.2,
                                                     "seed": 11}},
            ],
            "objects": ["wall"],
        }],
        "exports": [{"format": "toon_sheet",
                     "path": str(tmp_path / "art/wall"),
                     "params": {"views": 2, "size": 32, "bands": 3}}],
    })
    assert res.ok, res.errors
    atlases = [p for f, p in res.exports if f == "atlas"]
    assert len(atlases) == 1


def _load_png(path):
    pytest.importorskip("PIL")
    from PIL import Image
    return np.asarray(Image.open(path))


import numpy as np  # noqa: E402  (used by the Phase-3D tests above)

# -- export format / dispatch agreement ---------------------------------


def _sphere_recipe(fmt, path=os.devnull):
    return {"name": "t",
            "objects": [{"name": "o", "primitive": "sphere"}],
            "exports": [{"format": fmt, "path": path}]}


@pytest.mark.parametrize("fmt", ["render", "atlas", "bogus"])
def test_unwritable_export_format_is_rejected_by_validation(fmt):
    """A format with no writer must fail loudly, not warn and report ok."""
    with pytest.raises(ValueError) as excinfo:
        RecipeExecutor().execute(_sphere_recipe(fmt))
    assert fmt in str(excinfo.value)


@pytest.mark.parametrize("fmt", ["render", "atlas", "bogus"])
def test_unwritable_export_format_rejected_when_built_directly(fmt):
    """validate_recipe must catch it too, not just recipe_from_dict."""
    from am3d.recipes.schema import (ExportRecipe, ObjectRecipe, Recipe,
                                     validate_recipe)
    recipe = Recipe(name="t",
                    objects=[ObjectRecipe(name="o", primitive="sphere")],
                    exports=[ExportRecipe(format=fmt,
                                          path=os.devnull)])
    problems = validate_recipe(recipe)
    assert any(fmt in p for p in problems), problems


@pytest.mark.parametrize("path_key", ["dict", "direct"])
def test_gltf_alias_is_accepted_on_every_path(path_key, tmp_path):
    """'gltf' is an accepted spelling of 'glb' and must write a real file."""
    from am3d.recipes.schema import (ExportRecipe, ObjectRecipe, Recipe,
                                     validate_recipe)
    out = str(tmp_path / "aliased")
    if path_key == "dict":
        res = RecipeExecutor().execute(_sphere_recipe("gltf", out))
    else:
        recipe = Recipe(name="t",
                        objects=[ObjectRecipe(name="o", primitive="sphere")],
                        exports=[ExportRecipe(format="gltf", path=out)])
        assert validate_recipe(recipe) == []
        res = RecipeExecutor().execute(recipe)
    assert res.ok, res.errors
    assert os.path.exists(out + ".glb")


def test_every_advertised_export_format_actually_writes(tmp_path):
    """EXPORT_FORMATS and the executor dispatch must not drift apart."""
    from am3d.recipes.schema import EXPORT_FORMATS
    for fmt in sorted(EXPORT_FORMATS):
        out = tmp_path / f"as_{fmt}"
        res = RecipeExecutor().execute(_sphere_recipe(fmt, str(out)))
        assert res.ok, (fmt, res.errors)
        assert res.exports, f"{fmt} reported ok but produced no export entry"
        for _, written in res.exports:
            for one in str(written).split(", "):
                assert os.path.exists(one), f"{fmt}: {one} not written"


def test_executor_backstop_fails_when_dispatch_is_missing(tmp_path):
    """If validation is bypassed, the executor still must not report ok."""
    from am3d.recipes.schema import ExportRecipe, ObjectRecipe, Recipe
    recipe = Recipe(name="t",
                    objects=[ObjectRecipe(name="o", primitive="sphere")],
                    exports=[ExportRecipe(format="render",
                                          path=str(tmp_path / "x"))])
    ex = RecipeExecutor()
    ex.session.new_project("t")
    res = ExecutionResult()
    ex._build_objects(recipe, res)
    ex._run_exports(recipe, res)          # bypasses validate_recipe
    assert res.ok is False
    assert any("no writer" in e for e in res.errors), res.errors


# -- action preconditions are checked, not silently skipped -------------


_RIGGED = {"name": "hero", "bones": [
    {"name": "hip", "head": [0, 0.9, 0], "tail": [0, 1.0, 0]},
    {"name": "leg", "head": [0, 0.9, 0], "tail": [0, 0.4, 0],
     "parent": "hip"},
]}


def _action_recipe(actions, objects=None):
    return {"name": "t", "objects": objects or [dict(_RIGGED)],
            "actions": actions}


def test_retarget_without_source_action_is_rejected():
    with pytest.raises(ValueError) as excinfo:
        RecipeExecutor().execute(_action_recipe(
            [{"name": "r", "kind": "retarget", "character": "hero"}]))
    assert "source_action" in str(excinfo.value)


def test_retarget_without_character_is_rejected():
    with pytest.raises(ValueError) as excinfo:
        RecipeExecutor().execute(_action_recipe(
            [{"name": "r", "kind": "retarget", "source_action": "walk"}]))
    assert "character" in str(excinfo.value)


def test_retarget_from_unknown_source_action_is_rejected():
    with pytest.raises(ValueError) as excinfo:
        RecipeExecutor().execute(_action_recipe(
            [{"name": "r", "kind": "retarget", "character": "hero",
              "source_action": "nope"}]))
    assert "'nope'" in str(excinfo.value)


def test_retarget_source_must_precede_its_use():
    """Sources are resolved in order; a forward reference cannot work."""
    with pytest.raises(ValueError) as excinfo:
        RecipeExecutor().execute(_action_recipe([
            {"name": "r", "kind": "retarget", "character": "hero",
             "source_action": "later"},
            {"name": "later", "kind": "walk", "character": "hero"},
        ]))
    assert "defined earlier" in str(excinfo.value)


def test_retarget_from_earlier_recipe_action_is_accepted():
    """The legitimate ordering must still run and produce both actions."""
    res = RecipeExecutor().execute(_action_recipe([
        {"name": "base", "kind": "walk", "character": "hero"},
        {"name": "copy", "kind": "retarget", "character": "hero",
         "source_action": "base"},
    ]))
    assert res.ok, res.errors
    assert set(res.actions) == {"base", "copy"}


def test_action_backstop_fails_when_validation_is_bypassed():
    """Direct _build_actions must not report ok after skipping an action."""
    from am3d.recipes.schema import ActionRecipe, ObjectRecipe, Recipe
    recipe = Recipe(name="t",
                    objects=[ObjectRecipe(name="blob", primitive="box")],
                    actions=[ActionRecipe(name="walk", kind="walk",
                                          character="blob")])
    ex = RecipeExecutor()
    ex.session.new_project("t")
    res = ExecutionResult()
    ex._build_objects(recipe, res)
    ex._build_actions(recipe, res)          # bypasses validate_recipe
    assert res.ok is False
    assert res.actions == []
    assert any("not created" in e for e in res.errors), res.errors


def test_successful_recipe_reports_no_errors_and_real_actions():
    """Guard against over-correcting: the good path must stay clean."""
    res = RecipeExecutor().execute(_action_recipe(
        [{"name": "w", "kind": "walk", "character": "hero"}]))
    assert res.ok and res.errors == []
    assert res.actions == ["w"]
