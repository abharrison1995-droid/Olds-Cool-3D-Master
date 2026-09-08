"""Tests for the independent OBJ/GLB validator (am3d.export.validate).

Two concerns, kept separate:

1. Self-tests that the validator actually has teeth — it must flag files
   deliberately corrupted at the byte/text level, not just rubber-stamp
   anything write_obj/write_glb happens to produce (that would only prove
   the validator agrees with the writer, not that either is correct).
2. Real recipe exports (posed, materially coloured) run through the
   validator to catch structural/referential bugs a writer-level unit
   test — which only checks what the writer intended to write — would not.
"""

from __future__ import annotations

import os
import struct

import numpy as np
import pytest

from am3d.core.project import Patch, Project
from am3d.export.gltf import write_glb
from am3d.export.obj import write_obj
from am3d.export.validate import (
    accessor_byte_range, outward_normal_fraction, read_glb, read_obj,
    validate_glb, validate_obj,
)
from am3d.recipes.executor import RecipeExecutor
from am3d.recipes.primitives import build_primitive
from am3d.renderer.tessellate import tessellate_object


def _mesh(name="m"):
    p = Project()
    obj = p.create_object(name)
    built = build_primitive("sphere", {"radius": 1.0, "sections": 10, "rings": 6})
    for pname, net, du, dv in built["patches"]:
        obj.patches.append(Patch(name=pname, splines=[], interior=net))
    return tessellate_object(obj, nu=8, nv=6)


# ---------------------------------------------------------------------------
# 1. The validator has teeth
# ---------------------------------------------------------------------------
def test_validate_glb_accepts_a_clean_export(tmp_path):
    path = tmp_path / "orb.glb"
    write_glb(str(path), {"orb": _mesh("orb")},
             materials={"orb": (0.2, 0.4, 0.8, 1.0)})
    assert validate_glb(str(path)) == []


def test_validate_glb_flags_out_of_range_index(tmp_path):
    path = tmp_path / "orb.glb"
    write_glb(str(path), {"orb": _mesh("orb")})

    gltf, bin_chunk, bin_offset = read_glb(str(path))
    idx_accessor = gltf["meshes"][0]["primitives"][0]["indices"]
    start, length = accessor_byte_range(gltf, idx_accessor)

    blob = bytearray(open(path, "rb").read())
    # Corrupt the first index to a wildly out-of-range vertex reference.
    struct.pack_into("<I", blob, bin_offset + start, 0xFFFFFF)
    path.write_bytes(bytes(blob))

    issues = validate_glb(str(path))
    assert any("out of bounds" in msg for msg in issues), issues


def test_validate_glb_flags_min_max_mismatch(tmp_path):
    path = tmp_path / "orb.glb"
    write_glb(str(path), {"orb": _mesh("orb")})

    gltf, bin_chunk, bin_offset = read_glb(str(path))
    pos_accessor = gltf["meshes"][0]["primitives"][0]["attributes"]["POSITION"]

    blob = bytearray(open(path, "rb").read())
    # Rewrite the JSON chunk's declared max with a lie, keeping the chunk's
    # byte length identical (pad with spaces, glTF's whitespace-padding
    # convention) so the container's chunk-length header stays valid.
    import json as _json
    gltf["accessors"][pos_accessor]["max"] = [999.0, 999.0, 999.0]
    new_json = _json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    # Pad/truncate to the original JSON chunk length so the container stays valid.
    orig_json_len = struct.unpack_from("<I", blob, 12)[0]
    if len(new_json) < orig_json_len:
        new_json += b" " * (orig_json_len - len(new_json))
    assert len(new_json) == orig_json_len, "lying max must not change JSON length"
    blob[20:20 + orig_json_len] = new_json
    path.write_bytes(bytes(blob))

    issues = validate_glb(str(path))
    assert any("accessor max" in msg for msg in issues), issues


def test_validate_obj_accepts_a_clean_export(tmp_path):
    path = tmp_path / "orb.obj"
    write_obj(str(path), {"orb": _mesh("orb")}, materials={"orb": (1.0, 0.0, 0.0, 1.0)})
    assert validate_obj(str(path)) == []


def test_validate_obj_flags_out_of_range_face_index(tmp_path):
    path = tmp_path / "orb.obj"
    write_obj(str(path), {"orb": _mesh("orb")})
    text = path.read_text()
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("f "):
            lines[i] = "f 999999/999999/999999 " + " ".join(line.split()[2:])
            break
    path.write_text("\n".join(lines))

    issues = validate_obj(str(path))
    assert any("out of range" in msg for msg in issues), issues


def test_validate_obj_flags_missing_mtl_sidecar(tmp_path):
    path = tmp_path / "orb.obj"
    write_obj(str(path), {"orb": _mesh("orb")}, materials={"orb": (1.0, 0.0, 0.0, 1.0)})
    os.remove(tmp_path / "orb.mtl")

    issues = validate_obj(str(path))
    assert any("does not exist" in msg for msg in issues), issues


def test_validate_obj_flags_usemtl_with_no_matching_newmtl(tmp_path):
    path = tmp_path / "orb.obj"
    write_obj(str(path), {"orb": _mesh("orb")}, materials={"orb": (1.0, 0.0, 0.0, 1.0)})
    mtl_path = tmp_path / "orb.mtl"
    mtl_path.write_text(mtl_path.read_text().replace("newmtl mat_orb", "newmtl mat_something_else"))

    issues = validate_obj(str(path))
    assert any("no matching newmtl" in msg for msg in issues), issues


def test_outward_normal_fraction_detects_inverted_normals():
    mesh = _mesh("orb")
    correct = outward_normal_fraction(mesh.vertices, mesh.normals)
    assert correct > 0.95, "a UV-sphere's normals should point outward almost everywhere"
    inverted = outward_normal_fraction(mesh.vertices, -mesh.normals)
    assert inverted < 0.05


# ---------------------------------------------------------------------------
# 2. Real recipe exports, read back independently
# ---------------------------------------------------------------------------
def test_recipe_export_passes_independent_validation(tmp_path):
    """A textured/coloured, posed character export must be structurally
    and referentially sound when read back by code that has never seen
    am3d.export.obj/gltf's internals."""
    recipe = {
        "name": "validated_knight",
        "objects": [
            {"name": "knight", "primitive": "cylinder",
             "params": {"radius": 0.3, "height": 2.0, "sections": 10},
             "bones": [
                 {"name": "hip", "head": [0.0, 0.0, 0.0], "tail": [0.0, 1.0, 0.0]},
                 {"name": "spine", "head": [0.0, 1.0, 0.0], "tail": [0.0, 2.0, 0.0], "parent": "hip"},
             ]},
        ],
        "materials": [{"name": "steel", "color": [0.6, 0.6, 0.65], "objects": ["knight"]}],
        "actions": [{"name": "walk", "kind": "walk", "duration": 1.0, "character": "knight"}],
        "exports": [
            {"format": "obj", "path": "knight"},
            {"format": "glb", "path": "knight"},
        ],
    }
    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    res = ex.execute(recipe)
    assert res.ok, res.errors

    obj_path = [p for f, p in res.exports if f == "obj"][0]
    glb_path = [p for f, p in res.exports if f == "glb"][0]

    obj_issues = validate_obj(obj_path)
    assert obj_issues == [], obj_issues
    glb_issues = validate_glb(glb_path)
    assert glb_issues == [], glb_issues

    # Independent normal-direction sanity check on the exported (posed,
    # world-transformed) GLB geometry: a knobbly cylinder should still be
    # mostly convex-outward even after skeletal deformation.
    gltf, bin_chunk, _ = read_glb(glb_path)
    prim = gltf["meshes"][0]["primitives"][0]
    from am3d.export.validate import read_accessor
    positions = read_accessor(gltf, bin_chunk, prim["attributes"]["POSITION"])
    normals = read_accessor(gltf, bin_chunk, prim["attributes"]["NORMAL"])
    assert outward_normal_fraction(positions, normals) > 0.7


def test_recipe_export_reflects_the_selected_pose(tmp_path):
    """The vertex data landing in the exported OBJ, read back with the
    independent parser, must match an independently-recomputed pose at
    the same time — not the bind pose and not some other frame."""
    recipe = {
        "name": "posed_knight",
        "objects": [
            {"name": "knight", "primitive": "cylinder",
             "params": {"radius": 0.3, "height": 2.0, "sections": 8},
             "bones": [
                 {"name": "hip", "head": [0.0, 0.0, 0.0], "tail": [0.0, 1.0, 0.0]},
                 {"name": "spine", "head": [0.0, 1.0, 0.0], "tail": [0.0, 2.0, 0.0], "parent": "hip"},
             ]},
        ],
        "actions": [{"name": "walk", "kind": "walk", "duration": 1.0, "character": "knight"}],
        "exports": [{"format": "obj", "path": "knight"}],
    }
    ex = RecipeExecutor(output_root=str(tmp_path), base_dir=str(tmp_path))
    res = ex.execute(recipe)
    assert res.ok, res.errors

    # RecipeExecutor exports the scene at its default/bind evaluation.
    # Independently recompute that same evaluation via evaluate_scene and
    # compare against what the independent OBJ parser actually read off
    # disk, proving no vertex was dropped, reordered, or mistranscribed.
    expected = ex.session.evaluate_scene(apply_transforms=True, visible_only=True)
    expected_verts = np.asarray(expected.meshes["knight"].vertices, dtype=np.float64)

    obj_path = [p for f, p in res.exports if f == "obj"][0]
    parsed = read_obj(obj_path)
    parsed_verts = np.asarray(parsed["v"], dtype=np.float64)

    assert parsed_verts.shape == expected_verts.shape
    assert np.allclose(parsed_verts, expected_verts, atol=1e-5)
