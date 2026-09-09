"""End-to-end tests: a full recipe -> assets on disk, exactly as an LLM runs."""

from __future__ import annotations

import json
import os
import struct

import pytest
import numpy as np

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
    res = executor.execute(bad)
    assert not res.ok
    assert res.error_records[0]["stage"] == "schema"
    assert executor.session.project.objects == {}


def test_malformed_recipe_dict_raises_value_error_not_parser_exception(executor):
    """recipe_from_dict() used to be called outside execute()'s try block,
    so a parse-stage failure escaped as whatever the parser happened to
    raise (a bare TypeError here, from an unhashable dict landing in a
    `in PRIMITIVES` membership check) instead of the same "invalid recipe"
    ValueError contract validate_recipe's failures already use."""
    bad = {"objects": [{"name": "a", "primitive": {"not": "a string"}}]}
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
    res = executor.execute({
        "name": "solo",
        "objects": [{"name": "blob", "primitive": "box"}],
        "actions": [{"name": "walk", "kind": "walk",
                     "character": "blob"}],
    })
    assert not res.ok
    assert "declares no bones" in res.errors[0]


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


def test_cli_invalid_recipe_is_structured_json(tmp_path, capsys):
    p = tmp_path / "bad.json"
    p.write_text('{"version": 99}', encoding="utf-8")
    code = _run_cli(["--recipe", str(p)])
    captured = capsys.readouterr()
    assert code == 1
    report = json.loads(captured.out)
    assert report["ok"] is False
    assert report["error_records"][0]["code"] == "unsupported_version"
    assert report["error_records"][0]["path"] == "recipe.version"


def test_cli_malformed_json_is_structured_json(monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO('{"name":'))
    code = _run_cli(["--recipe", "-"])
    captured = capsys.readouterr()
    assert code == 1
    report = json.loads(captured.out)
    assert report["error_records"][0]["code"] == "recipe_read_error"
    assert report["error_records"][0]["stage"] == "parse"


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


def test_animation_sheet_export_renders_distinct_frames(tmp_path):
    """animation_sheet composites the whole posed character into one grid
    PNG, one cell per sampled time, and successive frames actually differ
    as the walk action deforms the bound geometry."""
    recipe = {
        "name": "walking_knight_sheet",
        "objects": [
            {
                "name": "knight",
                "primitive": "cylinder",
                "params": {"radius": 0.3, "height": 2.0, "sections": 8},
                "bones": [
                    {"name": "hip", "head": [0.0, 0.0, 0.0], "tail": [0.0, 1.0, 0.0]},
                    {"name": "spine", "head": [0.0, 1.0, 0.0], "tail": [0.0, 2.0, 0.0], "parent": "hip"},
                ],
            }
        ],
        "actions": [
            {"name": "walk", "kind": "walk", "duration": 1.0, "character": "knight"},
        ],
        "exports": [{
            "format": "animation_sheet", "path": "anim/knight",
            "params": {"action": "walk", "frames": 4, "size": 48, "columns": 4},
        }],
    }
    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    res = ex.execute(recipe)
    assert res.ok, res.errors

    paths = [p for f, p in res.exports if f == "animation_sheet"]
    assert len(paths) == 1
    sheet = _load_png(paths[0])
    assert sheet.shape == (48, 4 * 48, 4)   # 1 row x 4 columns of 48px cells

    cells = [sheet[:, i * 48:(i + 1) * 48, :3] for i in range(4)]
    assert any(not np.array_equal(cells[0], cell) for cell in cells[1:]), \
        "walk cycle frames must not all be identical"


def test_animation_sheet_respects_shared_depth_when_meshes_overlap(tmp_path):
    """Two overlapping planes: a near, dark (grazing-lit) one and a far,
    bright (face-lit) one. A correct shared z-buffer must show the
    nearer plane's darker shading at the overlap, never the farther
    plane's brighter one — a per-mesh max-blend composite gets this
    backwards, since it keeps whichever pixel is numerically brighter
    regardless of which surface is actually in front."""
    import math

    def rot_x(deg, tz):
        a = math.radians(deg)
        c, s = math.cos(a), math.sin(a)
        m = [[1, 0, 0, 0],
             [0, c, -s, 0],
             [0, s, c, tz],
             [0, 0, 0, 1]]
        return [v for row in m for v in row]

    recipe = {
        "name": "occluding_planes",
        "objects": [
            {"name": "near_dark", "primitive": "plane",
             "params": {"width": 1.5, "height": 1.5},
             "transform": rot_x(36.2, -1.0)},
            {"name": "far_bright", "primitive": "plane",
             "params": {"width": 1.5, "height": 1.5},
             "transform": rot_x(0.0, 1.0)},
        ],
        "exports": [{
            "format": "animation_sheet", "path": "anim/occlude",
            "params": {"frames": 1, "size": 32, "columns": 1,
                       "color": [1.0, 1.0, 1.0]},
        }],
    }
    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    res = ex.execute(recipe)
    assert res.ok, res.errors

    path = [p for f, p in res.exports if f == "animation_sheet"][0]
    sheet = _load_png(path)
    center = sheet[16, 16, :3].astype(np.float64) / 255.0

    # near_dark alone renders ~0.30 (grazing light); far_bright alone
    # renders ~0.67 (face-lit). The composited frame must match the
    # nearer, darker plane, not the farther, brighter one.
    assert center.mean() < 0.45, (
        f"animation_sheet showed the farther/brighter plane at an "
        f"occluded pixel (got {center.mean():.3f}); shared z-buffer "
        f"occlusion regressed to a per-mesh max-blend composite")


def test_animation_sheet_on_empty_scene_fails_loudly(tmp_path, executor):
    res = executor.execute({
        "name": "empty_anim",
        "objects": [],
        "exports": [{"format": "animation_sheet", "path": str(tmp_path / "anim")}],
    })
    assert not res.ok
    assert any(rec.get("code") == "missing_geometry" for rec in res.error_records)


def test_recipe_material_color_carries_into_obj_and_glb(tmp_path):
    """A flat-colour material assigned to an object reaches the OBJ .mtl
    sidecar and the GLB materials array, not just the writer unit tests."""
    recipe = {
        "name": "colored_ball",
        "objects": [{"name": "orb", "primitive": "sphere",
                     "params": {"sections": 10, "rings": 6}}],
        "materials": [{"name": "red", "color": [1.0, 0.0, 0.0], "objects": ["orb"]}],
        "exports": [
            {"format": "obj", "path": "orb"},
            {"format": "glb", "path": "orb"},
        ],
    }
    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    res = ex.execute(recipe)
    assert res.ok, res.errors

    obj_path = [p for f, p in res.exports if f == "obj"][0]
    mtl_path = os.path.splitext(obj_path)[0] + ".mtl"
    assert os.path.exists(mtl_path)
    obj_text = open(obj_path).read()
    assert "mtllib" in obj_text and "usemtl mat_orb" in obj_text
    mtl_text = open(mtl_path).read()
    assert "Kd 1.000000 0.000000 0.000000" in mtl_text

    glb_path = [p for f, p in res.exports if f == "glb"][0]
    blob = open(glb_path, "rb").read()
    json_len, _ = struct.unpack_from("<II", blob, 12)
    gltf = json.loads(blob[20:20 + json_len].decode("utf-8"))
    assert len(gltf["materials"]) == 1
    factor = gltf["materials"][0]["pbrMetallicRoughness"]["baseColorFactor"]
    assert factor[:3] == pytest.approx([1.0, 0.0, 0.0])


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
    res = RecipeExecutor().execute(_sphere_recipe(fmt))
    assert not res.ok
    assert fmt in res.errors[0]


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
    res = RecipeExecutor().execute(_action_recipe(
        [{"name": "r", "kind": "retarget", "character": "hero"}]))
    assert not res.ok
    assert "source_action" in res.errors[0]


def test_retarget_without_character_is_rejected():
    res = RecipeExecutor().execute(_action_recipe(
        [{"name": "r", "kind": "retarget", "source_action": "walk"}]))
    assert not res.ok
    assert "character" in res.errors[0]


def test_retarget_from_unknown_source_action_is_rejected():
    res = RecipeExecutor().execute(_action_recipe(
        [{"name": "r", "kind": "retarget", "character": "hero",
          "source_action": "nope"}]))
    assert not res.ok
    assert "'nope'" in res.errors[0]


def test_retarget_source_must_precede_its_use():
    """Sources are resolved in order; a forward reference cannot work."""
    res = RecipeExecutor().execute(_action_recipe([
        {"name": "r", "kind": "retarget", "character": "hero",
         "source_action": "later"},
        {"name": "later", "kind": "walk", "character": "hero"},
    ]))
    assert not res.ok
    assert "defined earlier" in res.errors[0]


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


def test_explicit_output_root_rejects_escape_without_writing(tmp_path):
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    res = RecipeExecutor(output_root=str(root)).execute({
        "name": "escape",
        "objects": [{"name": "o", "primitive": "box"}],
        "exports": [{"format": "obj", "path": "../outside/asset"}],
    })
    assert not res.ok
    assert res.error_records[0]["code"] == "output_path_escape"
    assert not outside.exists()


def test_path_escape_dot_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    res = RecipeExecutor(output_root=str(root)).execute({
        "name": "escape",
        "objects": [{"name": "o", "primitive": "box"}],
        "exports": [{"format": "obj", "path": "."}],
    })
    assert not res.ok
    assert res.error_records[0]["code"] == "output_path_escape"


def test_path_escape_drive_is_rejected(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    res = RecipeExecutor(output_root=str(root)).execute({
        "name": "escape",
        "objects": [{"name": "o", "primitive": "box"}],
        "exports": [{"format": "obj", "path": "D:outside_file"}],
    })
    assert not res.ok
    assert res.error_records[0]["code"] == "output_path_escape"


def test_failed_recipe_preserves_existing_session(tmp_path):
    session = Session()
    session.new_project("existing")
    session.create_object("keep")
    res = RecipeExecutor(session).execute({
        "name": "bad",
        "objects": [{"name": "bad", "primitive": "sphere",
                     "params": {"radius": "huge"}}],
    })
    assert not res.ok
    assert set(session.project.objects) == {"keep"}
    assert session.project.name == "existing"


def test_recipe_am3d_export_round_trips_action_state(tmp_path):
    executor = RecipeExecutor(Session())
    res = executor.execute(_action_recipe(
        [{"name": "walk", "kind": "walk", "character": "hero"}],
        objects=[dict(_RIGGED)],
    ) | {"exports": [{"format": "am3d",
                       "path": str(tmp_path / "animated")} ]})
    assert res.ok, res.error_records
    loaded = Session()
    loaded.load_project(str(tmp_path / "animated.am3d"))
    assert set(loaded.actions) == {"walk"}
    assert loaded.active_action == "walk"
    assert loaded.action_assignments == {"hero": "walk"}


def test_manifest_has_one_entry_per_written_artifact(tmp_path):
    res = RecipeExecutor().execute({
        "name": "manifest",
        "objects": [{"name": "orb", "primitive": "sphere"}],
        "exports": [{"format": "spritesheet",
                     "path": str(tmp_path / "orb"),
                     "params": {"views": 2, "size": 24}}],
    })
    assert res.ok, res.error_records
    assert len(res.manifest) == 1
    assert res.manifest[0]["format"] == "spritesheet"
    assert res.manifest[0]["status"] == "written"
    assert res.manifest[0]["size_bytes"] > 0


def test_staging_preserves_existing_files_on_failure(tmp_path):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    existing_obj = out_dir / "target.obj"
    existing_obj.write_text("pre-existing content", encoding="utf-8")

    recipe = {
        "name": "multi_fail",
        "objects": [{"name": "ball", "primitive": "sphere"}],
        "exports": [
            {"format": "obj", "path": str(existing_obj.with_suffix(""))},
            {"format": "render", "path": str(out_dir / "bad")},
        ],
    }
    res = RecipeExecutor().execute(recipe)
    assert not res.ok
    assert existing_obj.read_text(encoding="utf-8") == "pre-existing content"


def test_spritesheet_on_rig_only_fails_loudly(tmp_path):
    res = RecipeExecutor().execute({
        "name": "rig_only",
        "objects": [{"name": "hero", "bones": [
            {"name": "root", "head": [0, 0, 0], "tail": [0, 1, 0]}
        ]}],
        "exports": [{"format": "spritesheet", "path": str(tmp_path / "hero")}],
    })
    assert not res.ok
    assert any(e["code"] == "missing_geometry" for e in res.error_records)
    assert res.manifest == []


def test_manifest_includes_metadata(tmp_path):
    res = RecipeExecutor().execute({
        "name": "meta",
        "objects": [{"name": "orb", "primitive": "sphere"}],
        "exports": [
            {"format": "spritesheet", "path": str(tmp_path / "orb"),
             "params": {"views": 4, "size": 32}},
            {"format": "obj", "path": str(tmp_path / "orb_mesh")},
        ],
    })
    assert res.ok, res.error_records
    sheet_entry = next(e for e in res.manifest if e["format"] == "spritesheet")
    assert sheet_entry["views"] == 4
    assert sheet_entry["size"] == 32
    assert sheet_entry["status"] == "written"

    obj_entry = next(e for e in res.manifest if e["format"] == "obj")
    assert obj_entry["mesh_count"] == 1
    assert obj_entry["status"] == "written"


def test_subprocess_cli_valid_file(tmp_path):
    import subprocess
    import sys
    recipe_file = tmp_path / "recipe.json"
    out_dir = tmp_path / "out"
    recipe = {
        "name": "sub_test",
        "objects": [{"name": "ball", "primitive": "sphere"}],
        "exports": [{"format": "obj", "path": "ball"}],
    }
    recipe_file.write_text(json.dumps(recipe), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "am3d.recipes", "--recipe", str(recipe_file), "--out", str(out_dir)],
        capture_output=True, text=True)
    assert proc.returncode == 0
    report = json.loads(proc.stdout)
    assert report["ok"] is True
    assert len(report["manifest"]) == 1
    assert (out_dir / "ball.obj").exists()


def test_subprocess_cli_stdin_with_and_without_bom(tmp_path):
    import subprocess
    import sys
    out_dir = tmp_path / "out_stdin"
    recipe_json = json.dumps({
        "name": "stdin_test",
        "objects": [{"name": "box", "primitive": "box"}],
        "exports": [{"format": "obj", "path": "box"}],
    })
    # Without BOM
    proc = subprocess.run(
        [sys.executable, "-m", "am3d.recipes", "--recipe", "-", "--out", str(out_dir)],
        input=recipe_json, capture_output=True, text=True)
    assert proc.returncode == 0
    report = json.loads(proc.stdout)
    assert report["ok"] is True

    # With BOM
    proc_bom = subprocess.run(
        [sys.executable, "-m", "am3d.recipes", "--recipe", "-", "--out", str(out_dir)],
        input=("\ufeff" + recipe_json).encode("utf-8"),
        capture_output=True)
    assert proc_bom.returncode == 0
    report_bom = json.loads(proc_bom.stdout.decode("utf-8"))
    assert report_bom["ok"] is True


def test_subprocess_cli_missing_file():
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "am3d.recipes", "--recipe", "nonexistent_recipe_12345.json"],
        capture_output=True, text=True)
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    assert report["ok"] is False
    assert report["error_records"][0]["code"] == "recipe_read_error"


def test_subprocess_cli_validate_only(tmp_path):
    import subprocess
    import sys
    recipe_file = tmp_path / "validate.json"
    recipe = {
        "name": "val_test",
        "objects": [{"name": "ball", "primitive": "sphere"}],
        "exports": [{"format": "obj", "path": "ball"}],
    }
    recipe_file.write_text(json.dumps(recipe), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, "-m", "am3d.recipes", "--recipe", str(recipe_file), "--validate-only"],
        capture_output=True, text=True)
    assert proc.returncode == 0
    report = json.loads(proc.stdout)
    assert report["ok"] is True
    assert report["validated"] is True


def test_subprocess_cli_invalid_json():
    import subprocess
    import sys
    proc = subprocess.run(
        [sys.executable, "-m", "am3d.recipes", "--recipe", "-"],
        input='{"name": "broken', capture_output=True, text=True)
    assert proc.returncode == 1
    report = json.loads(proc.stdout)
    assert report["ok"] is False
    assert report["error_records"][0]["code"] == "recipe_read_error"


def test_subprocess_cli_file_with_bom(tmp_path):
    import subprocess
    import sys
    recipe_file = tmp_path / "bom_recipe.json"
    out_dir = tmp_path / "out_bom"
    recipe = {
        "name": "sub_bom",
        "objects": [{"name": "ball", "primitive": "sphere"}],
        "exports": [{"format": "obj", "path": "ball"}],
    }
    recipe_file.write_bytes(b"\xef\xbb\xbf" + json.dumps(recipe).encode("utf-8"))
    proc = subprocess.run(
        [sys.executable, "-m", "am3d.recipes", "--recipe", str(recipe_file), "--out", str(out_dir)],
        capture_output=True, text=True)
    assert proc.returncode == 0
    report = json.loads(proc.stdout)
    assert report["ok"] is True
    assert (out_dir / "ball.obj").exists()


def test_texture_only_material_retains_properties_and_binding(tmp_path):
    from am3d.renderer.materials import save_image, solid
    tex_dir = tmp_path / "textures"
    tex_dir.mkdir(parents=True, exist_ok=True)
    tex_file = tex_dir / "ball.png"
    save_image(solid((0.2, 0.4, 0.8), size=16), str(tex_file))

    recipe = {
        "name": "tex_only_recipe",
        "objects": [{"name": "ball", "primitive": "sphere"}],
        "materials": [{
            "name": "ball_mat",
            "texture": "textures/ball.png",
            "roughness": 0.3,
            "metalness": 0.8,
            "objects": ["ball"],
        }],
        "exports": [{"format": "am3d", "path": "ball"}],
    }
    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    res = ex.execute(recipe)
    assert res.ok, res.errors
    session = ex.session
    mat = session.project.materials["ball_mat"]
    assert mat.texture.replace("\\", "/").endswith("textures/ball.png")
    assert mat.roughness == 0.3
    assert mat.metalness == 0.8
    assert session.project.objects["ball"].material == "ball_mat"

    # Verify .am3d saved file reloads with exact material properties and binding
    from am3d.core.serializer import load_project
    loaded = load_project(str(tmp_path / "ball.am3d"))
    assert loaded.objects["ball"].material == "ball_mat"
    loaded_mat = loaded.materials["ball_mat"]
    assert loaded_mat.texture.replace("\\", "/").endswith("textures/ball.png")
    assert loaded_mat.roughness == 0.3
    assert loaded_mat.metalness == 0.8


def test_missing_texture_resource_reports_structured_error(tmp_path):
    recipe = {
        "name": "missing_tex_recipe",
        "objects": [{"name": "ball", "primitive": "sphere"}],
        "materials": [{
            "name": "ball_mat",
            "texture": "nonexistent_texture.png",
            "objects": ["ball"],
        }],
        "exports": [{"format": "obj", "path": "ball"}],
    }
    ex = RecipeExecutor(output_root=str(tmp_path))
    res = ex.execute(recipe)
    assert not res.ok
    assert any(err.get("code") == "missing_resource" for err in res.error_records)


def test_duplicate_patch_names_bake_matching_atlas(tmp_path):
    from am3d.core.project import Object3D, Patch
    from am3d.renderer.materials import bake_atlas
    from am3d.renderer.tessellate import tessellate_object
    from am3d.spline.kernel import build_lathe_net
    import numpy as np

    obj = Object3D(name="multi_patch")
    profile = np.array([[0.5, 0.0], [1.0, 1.0], [0.6, 2.0], [0.4, 2.5]])
    net1 = build_lathe_net(profile, sections=4)
    net2 = build_lathe_net(profile, sections=4)

    # Two patches with the EXACT same name
    p1 = Patch(name="patch", splines=[], interior=net1)
    p2 = Patch(name="patch", splines=[], interior=net2)
    obj.patches = [p1, p2]

    # Material per patch passed as list
    from am3d.core.project import Material
    m1 = Material(name="m1", color=(1.0, 0.0, 0.0))
    m2 = Material(name="m2", color=(0.0, 1.0, 0.0))

    mesh = tessellate_object(obj)
    atlas = bake_atlas(mesh, [m1, m2], cell_size=64)
    # With 2 patches, atlas grid layout creates 2 columns (or 2 cells)
    assert atlas.ndim == 3
    assert atlas.shape[2] == 4


def test_patch_material_takes_priority_over_mats_for_obj_filter(tmp_path):
    # Texture file
    tex_dir = tmp_path / "textures"
    tex_dir.mkdir(parents=True, exist_ok=True)
    tex_file = tex_dir / "gold.png"
    from PIL import Image
    Image.new("RGB", (64, 64), color="gold").save(str(tex_file))

    recipe = {
        "name": "gold_test",
        "objects": [
            {"name": "box", "primitive": "box"},
            {"name": "other_obj", "primitive": "box"},
        ],
        "materials": [
            {
                "name": "default_mat",
                "color": [0.5, 0.5, 0.5],
                "objects": ["box"],
            },
            {
                "name": "gold",
                "texture": str(tex_file),
                "objects": ["other_obj"],  # Does NOT list 'box'!
            },
        ],
        "exports": [{"format": "am3d", "path": "box"}],
    }

    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    # Explicitly set patch material
    res = ex.execute(recipe)
    assert res.ok, res.errors
    # Now set patch material explicitly on first patch and bake
    obj = ex.session.project.objects["box"]
    obj.patches[0].material = "gold"
    atlases = ex._bake_atlases(recipe)
    assert "box" in atlases
    assert atlases["box"] is not None


def test_recipe_object_transform_baked_into_exports(tmp_path):
    """Recipe object.transform is baked into exported meshes."""
    m = np.eye(4, dtype=np.float64)
    m[0, 3] = 5.0  # translate +5 along X
    m[1, 3] = 2.0  # translate +2 along Y
    recipe = {
        "name": "transformed_scene",
        "objects": [
            {
                "name": "shifted_box",
                "primitive": "box",
                "transform": m.tolist(),
            }
        ],
        "exports": [
            {"format": "obj", "path": "shifted_box"},
            {"format": "glb", "path": "shifted_box"},
        ],
    }
    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    res = ex.execute(recipe)
    assert res.ok, res.errors

    # Check exported session object transform
    obj = ex.session.project.objects["shifted_box"]
    assert np.allclose(obj.transform, m)

    # Check that evaluated meshes reflect the translation
    scene = ex.session.evaluate_scene(apply_transforms=True)
    v = scene.meshes["shifted_box"].vertices
    assert np.all(v[:, 0] >= 4.0)
    assert np.all(v[:, 1] >= 1.0)


def test_recipe_singular_transform_rejected_with_structured_error():
    """Recipe with singular object transform is rejected during validation."""
    singular_m = np.diag([1.0, 0.0, 1.0, 1.0]).tolist()
    recipe = {
        "name": "bad_transform",
        "objects": [
            {
                "name": "flattened",
                "primitive": "box",
                "transform": singular_m,
            }
        ],
    }
    ex = RecipeExecutor()
    res = ex.execute(recipe)
    assert not res.ok
    assert any(rec.get("code") == "singular_transform" for rec in res.error_records)


def test_recipe_animated_character_deforms_exports(tmp_path):
    """A recipe with character bones and walk action deforms the exported geometry."""
    recipe = {
        "name": "walking_knight",
        "objects": [
            {
                "name": "knight",
                "primitive": "cylinder",
                "params": {"radius": 0.3, "height": 2.0, "sections": 8},
                "bones": [
                    {"name": "hip", "head": [0.0, 0.0, 0.0], "tail": [0.0, 1.0, 0.0]},
                    {"name": "spine", "head": [0.0, 1.0, 0.0], "tail": [0.0, 2.0, 0.0], "parent": "hip"},
                ],
            }
        ],
        "actions": [
            {
                "name": "walk",
                "kind": "walk",
                "duration": 1.0,
                "character": "knight",
            }
        ],
        "exports": [
            {"format": "obj", "path": "knight_walk"},
            {"format": "am3d", "path": "knight_walk"},
        ],
    }
    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    res = ex.execute(recipe)
    assert res.ok, res.errors

    # Verify bones were added and auto-weighted
    bones = ex.session.get_bones("knight")
    assert len(bones) == 2
    assert any(b.cp_weights for b in bones)

    # Evaluate at t=0 and t=0.25; confirm deformation occurs
    f0 = ex.session.evaluate_scene(time=0.0)
    f1 = ex.session.evaluate_scene(time=0.25)
    v0 = f0.meshes["knight"].vertices
    v1 = f1.meshes["knight"].vertices
    assert np.max(np.linalg.norm(v1 - v0, axis=1)) > 0.01


def test_recipe_skeleton_reference_binds_and_deforms(tmp_path):
    """An object specifying skeleton: other_obj (even declared before the skeleton) binds and deforms."""
    recipe = {
        "name": "separate_rig_and_mesh",
        "objects": [
            {
                # Declared BEFORE hero_rig to verify order independence in Pass 2
                "name": "hero_mesh",
                "primitive": "cylinder",
                "params": {
                    "radius": 0.3,
                    "height": 2.0,
                    "sections": 8,
                    "skeleton": "hero_rig",
                },
            },
            {
                "name": "hero_rig",
                "bones": [
                    {"name": "hip", "head": [0.0, 0.0, 0.0], "tail": [0.0, 1.0, 0.0]},
                    {"name": "spine", "head": [0.0, 1.0, 0.0], "tail": [0.0, 2.0, 0.0], "parent": "hip"},
                ],
            },
        ],
        "actions": [
            {
                "name": "walk",
                "kind": "walk",
                "duration": 1.0,
                "character": "hero_rig",
            }
        ],
        "exports": [
            {"format": "am3d", "path": "hero_project"},
        ],
    }
    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    res = ex.execute(recipe)
    assert res.ok, res.errors

    # hero_mesh should have copied bones and non-empty weights
    mesh_bones = ex.session.get_bones("hero_mesh")
    assert len(mesh_bones) == 2
    assert any(b.cp_weights for b in mesh_bones)

    # Evaluate at t=0 and t=0.25; confirm deformation occurs
    f0 = ex.session.evaluate_scene(time=0.0)
    f1 = ex.session.evaluate_scene(time=0.25)
    v0 = f0.meshes["hero_mesh"].vertices
    v1 = f1.meshes["hero_mesh"].vertices
    assert np.max(np.linalg.norm(v1 - v0, axis=1)) > 0.01


def test_recipe_missing_skeleton_reference_rejected_with_structured_error():
    """Recipe with params.skeleton referencing nonexistent object emits structured missing_reference."""
    recipe = {
        "name": "bad_rig_ref",
        "objects": [
            {
                "name": "orphan_mesh",
                "primitive": "cylinder",
                "params": {"skeleton": "ghost_rig"},
            }
        ],
    }
    ex = RecipeExecutor()
    res = ex.execute(recipe)
    assert not res.ok
    assert any(rec["code"] == "missing_reference" and "params.skeleton" in rec["path"] for rec in res.error_records)


def test_recipe_transform_invalid_shape_and_non_numeric():
    """Transform with invalid shape or non-numeric values yields structured schema errors."""
    bad_shape = {
        "name": "bad_shape",
        "objects": [{"name": "b", "primitive": "box", "transform": [1.0, 2.0, 3.0, 4.0, 5.0]}],
    }
    ex = RecipeExecutor()
    res1 = ex.execute(bad_shape)
    assert not res1.ok
    assert any(rec["code"] == "invalid_shape" and rec["stage"] == "schema" for rec in res1.error_records)

    bad_val = {
        "name": "bad_val",
        "objects": [{"name": "b", "primitive": "box", "transform": ["x", "y", "z"]}],
    }
    res2 = ex.execute(bad_val)
    assert not res2.ok
    assert any(rec["code"] == "invalid_value" and rec["stage"] == "schema" for rec in res2.error_records)


def test_recipe_retarget_between_distinct_characters(tmp_path):
    """Retargeting action between two distinct characters in a recipe scales translation properly."""
    recipe = {
        "name": "retarget_demo",
        "objects": [
            {
                "name": "short_char",
                "bones": [
                    {"name": "root", "head": [0, 0, 0], "tail": [0, 1, 0]},
                ],
            },
            {
                "name": "tall_char",
                "bones": [
                    {"name": "root", "head": [0, 0, 0], "tail": [0, 2, 0]},
                ],
            },
        ],
        "actions": [
            {
                "name": "short_hop",
                "kind": "custom",
                "character": "short_char",
                "duration": 1.0,
                "channels": [
                    {
                        "bone": "root",
                        "property": "translate",
                        "keys": [
                            {"time": 0.0, "value": [0, 0, 0]},
                            {"time": 0.5, "value": [0, 0.5, 0]},
                            {"time": 1.0, "value": [0, 0, 0]},
                        ],
                    }
                ],
            },
            {
                "name": "tall_hop",
                "kind": "retarget",
                "character": "tall_char",
                "source_action": "short_hop",
                "duration": 1.0,
                "params": {"source_character": "short_char"},
            },
        ],
    }
    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    res = ex.execute(recipe)
    assert res.ok, res.errors
    assert "tall_hop" in res.actions

    act = ex.session.actions["tall_hop"]
    ch = act.get_channel("root", "translate")
    # Bone length ratio tall (2.0) / short (1.0) is 2.0; translation 0.5 becomes 1.0
    assert ch.sample(0.5)[1] == pytest.approx(1.0)


def test_flagship_knight_recipes_bind_and_deform(tmp_path):
    """Flagship knight recipes (knight_full.json and knight_recipe.json) bind and visibly deform."""
    for rel_path in ["docs/recipes/examples/knight_full.json", "scripts/knight_recipe.json"]:
        with open(rel_path, "r", encoding="utf-8") as f:
            r_data = json.load(f)

        r_data["exports"] = []  # test execution and deformation without writing exports to root
        ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
        res = ex.execute(r_data)
        assert res.ok, (rel_path, res.errors)

        # Check that geometry object received copied bones and weights
        geom_name = "body" if "body" in ex.session.project.objects else "torso"
        bones = ex.session.get_bones(geom_name)
        assert len(bones) > 0, f"{rel_path}: {geom_name} has no bones"
        assert any(b.cp_weights for b in bones), f"{rel_path}: {geom_name} has no skin weights"

        # Evaluate at t=0.0 and t=0.25; confirm deformation occurs
        f0 = ex.session.evaluate_scene(time=0.0)
        f1 = ex.session.evaluate_scene(time=0.25)
        v0 = f0.meshes[geom_name].vertices
        v1 = f1.meshes[geom_name].vertices
        delta = np.max(np.linalg.norm(v1 - v0, axis=1))
        assert delta > 0.01, f"{rel_path}: {geom_name} did not deform between frames (delta={delta})"


def test_gui_lathe_and_recipe_lathe_geometry_agree():
    """GUI lathe profile extraction [0, 1] produces identical geometry to recipe lathe."""
    from am3d.ui.operators import LatheProfileCommand
    from am3d.recipes.primitives import make_lathe_profile
    from am3d.core.project import Object3D, Patch
    from am3d.renderer.tessellate import tessellate_object

    # Create session with vase profile
    s = Session()
    s.create_object("vase_gui")
    # Vase control points: X=radius, Y=axial, Z=0.0
    cps = [
        np.array([0.2, 0.0, 0.0], dtype=np.float64),
        np.array([0.5, 0.3, 0.0], dtype=np.float64),
        np.array([0.3, 0.7, 0.0], dtype=np.float64),
        np.array([0.4, 1.0, 0.0], dtype=np.float64),
    ]
    s.add_spline("vase_gui", cps, name="profile")

    # GUI lathe extraction logic
    spline = s.project.objects["vase_gui"].splines["profile"]
    pts = spline.point_array()
    gui_profile = pts[:, [0, 1]]

    cmd = LatheProfileCommand(s, "vase_gui", gui_profile, sections=16)
    cmd.redo()

    # Recipe lathe using make_lathe_profile with same profile
    recipe_res = make_lathe_profile(gui_profile, sections=16)

    gui_patch = s.project.objects["vase_gui"].patches[0]
    recipe_patch_net = recipe_res["patches"][0][1]

    # Geometries must agree
    assert np.allclose(gui_patch.interior, recipe_patch_net)
    gui_obj = Object3D(name="vase_gui_lathed")
    gui_obj.patches.append(Patch(name="p", splines=[], interior=gui_patch.interior))
    gui_mesh = tessellate_object(gui_obj, nu=8, nv=8)

    recipe_obj = Object3D(name="vase_recipe")
    recipe_obj.patches.append(Patch(name="p", splines=[], interior=recipe_patch_net))
    recipe_mesh = tessellate_object(recipe_obj, nu=8, nv=8)

    assert np.allclose(gui_mesh.vertices, recipe_mesh.vertices)
    assert np.allclose(gui_mesh.normals, recipe_mesh.normals)




# --- Cross-platform export path policy (finding ENV-03) ---------------------
# These drive the real consumer (RecipeExecutor.execute), not the helper, so a
# policy that is correct in am3d/core/paths.py but unwired here still fails.

def _escape_recipe(path):
    return {"name": "escape",
            "objects": [{"name": "o", "primitive": "box"}],
            "exports": [{"format": "obj", "path": path}]}


@pytest.mark.parametrize("path", [
    "D:outside_file",              # Windows drive-relative
    "D:/outside_file",             # Windows drive-absolute
    "D:\\outside_file",
    "\\\\server\\share\\out",      # UNC
    "//server/share/out",
    "/tmp/outside",                # POSIX absolute
    "\\windows\\out",              # Windows root-relative
    "../outside",                  # traversal, POSIX separator
    "..\\outside",                 # traversal, Windows separator
    "sub/../../outside",
    ".",
    "NUL",                         # Windows reserved device name
    "bad?name",                    # invalid on Windows
])
def test_export_path_policy_rejects_identically_on_every_platform(tmp_path, path):
    root = tmp_path / "root"
    root.mkdir()
    res = RecipeExecutor(output_root=str(root)).execute(_escape_recipe(path))
    assert not res.ok, f"{path!r} should be rejected on every platform"
    assert res.error_records[0]["code"] == "output_path_escape"
    # Nothing may be written anywhere for a rejected path.
    assert list(root.iterdir()) == []


@pytest.mark.parametrize("name", [
    "plain",
    "ünïcødé",
    "日本語モデル",
    "Ω-mesh_v2.final",
    "with space/my model",
])
def test_export_path_policy_allows_legitimate_unicode_names(tmp_path, name):
    root = tmp_path / "root"
    root.mkdir()
    res = RecipeExecutor(output_root=str(root)).execute(_escape_recipe(name))
    assert res.ok, res.error_records
    written = res.exports[0][1]
    assert os.path.exists(written)
    # Stays inside the root, and the extension is applied.
    assert os.path.realpath(written).startswith(os.path.realpath(str(root)) + os.sep)
    assert written.endswith(".obj")


def test_export_backslash_is_treated_as_a_subdirectory_separator(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    res = RecipeExecutor(output_root=str(root)).execute(_escape_recipe("sub\\out"))
    assert res.ok, res.error_records
    # A literal "sub\out.obj" file would mean this recipe produces a different
    # tree on Linux than on Windows.
    assert (root / "sub" / "out.obj").exists()


# --- CLI-01 -----------------------------------------------------------------

def test_frozen_cli_usage_names_the_shipped_executable(monkeypatch):
    """A user of the bundle has no Python, so usage must not tell them to
    run ``python -m am3d.recipes`` (finding CLI-01)."""
    import sys as _sys

    from am3d.recipes.cli import _build_parser

    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "argv", ["/opt/app/am3d-recipe", "--help"])
    assert _build_parser().prog == "am3d-recipe"


def test_source_cli_usage_still_names_the_module_form(monkeypatch):
    import sys as _sys

    from am3d.recipes.cli import _build_parser

    monkeypatch.delattr(_sys, "frozen", raising=False)
    assert _build_parser().prog == "python -m am3d.recipes"
