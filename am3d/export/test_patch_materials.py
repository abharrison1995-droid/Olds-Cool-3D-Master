"""Per-patch material identity through render and export (finding MAT-02).

Reproduction before the fix (docs/evidence/desktop-release/phase-b/
mat-02-reproduction.txt): a box whose two faces were assigned different
materials evaluated to a scene carrying no patch identity at all, and
scene_material_colors() returned {} -- both patches exported with the object
colour. The acceptance requirement from the plan is that two differently
coloured patches on one object remain distinct.
"""

from __future__ import annotations

import json
import struct

import numpy as np
import pytest

from am3d.core.scene import (evaluate_scene, scene_patch_material_colors,
                             scene_triangle_colors)
from am3d.core.script import Session
from am3d.export.gltf import write_glb
from am3d.export.obj import write_obj
from am3d.ui.operators import CreatePrimitiveCommand

RED = (1.0, 0.0, 0.0, 1.0)
BLUE = (0.0, 0.0, 1.0, 1.0)


@pytest.fixture()
def two_tone_box():
    s = Session()
    CreatePrimitiveCommand(s, "box", "box").redo()
    s.create_material("red", color=RED)
    s.create_material("blue", color=BLUE)
    obj = s.get_object("box")
    obj.patches[0].material = "red"
    obj.patches[1].material = "blue"
    return s, obj.patches[0].name, obj.patches[1].name


# --- evaluation -------------------------------------------------------------

def test_tessellation_records_which_patch_each_triangle_came_from(two_tone_box):
    session, first, second = two_tone_box
    mesh = evaluate_scene(session).meshes["box"]
    groups = mesh.group_triangles()
    assert first in groups and second in groups
    assert len(groups[first]) > 0 and len(groups[second]) > 0
    assert sum(len(v) for v in groups.values()) == len(mesh.indices)


def test_evaluated_scene_carries_per_patch_assignments(two_tone_box):
    session, first, second = two_tone_box
    colors = scene_patch_material_colors(evaluate_scene(session))
    assert colors["box"][first] == RED
    assert colors["box"][second] == BLUE


def test_triangle_colors_distinguish_the_two_patches(two_tone_box):
    session, first, second = two_tone_box
    scene = evaluate_scene(session)
    tri_colors = scene_triangle_colors(scene, "box")
    assert tri_colors is not None, "per-triangle colour resolution collapsed"
    groups = scene.meshes["box"].group_triangles()
    assert np.allclose(tri_colors[groups[first]], RED)
    assert np.allclose(tri_colors[groups[second]], BLUE)
    assert len(np.unique(tri_colors, axis=0)) >= 2


def test_unassigned_patches_inherit_the_object_material():
    s = Session()
    CreatePrimitiveCommand(s, "box", "box").redo()
    s.create_material("green", color=(0.0, 1.0, 0.0, 1.0))
    s.get_object("box").material = "green"
    scene = evaluate_scene(s)
    assert scene_patch_material_colors(scene) == {}
    # Uniform colour: the single-colour fast path stays available.
    assert scene_triangle_colors(scene, "box") is None


# --- OBJ / MTL --------------------------------------------------------------

def _parse_obj_groups(obj_text):
    """Independent minimal OBJ reader: {material_name: face_count}."""
    counts, current = {}, None
    for line in obj_text.splitlines():
        if line.startswith("usemtl "):
            current = line.split(None, 1)[1].strip()
            counts.setdefault(current, 0)
        elif line.startswith("f "):
            if current is not None:
                counts[current] += 1
    return counts


def _parse_mtl(mtl_text):
    """Independent minimal MTL reader: {material_name: (r, g, b)}."""
    out, name = {}, None
    for line in mtl_text.splitlines():
        parts = line.split()
        if not parts:
            continue
        if parts[0] == "newmtl":
            name = parts[1]
        elif parts[0] == "Kd" and name:
            out[name] = tuple(round(float(v), 6) for v in parts[1:4])
    return out


def test_obj_export_keeps_the_two_patches_in_separate_material_groups(
        two_tone_box, tmp_path):
    session, first, second = two_tone_box
    scene = evaluate_scene(session)
    meshes = {n: m for n, m in scene.meshes.items() if len(m.vertices)}
    out = tmp_path / "two_tone.obj"
    write_obj(str(out), meshes,
              patch_materials=scene_patch_material_colors(scene))

    text = out.read_text(encoding="utf-8")
    # Regression: per-patch materials alone did not emit mtllib, so every
    # usemtl below named a material no independent reader could resolve.
    mtllib = [l.split(None, 1)[1].strip() for l in text.splitlines()
              if l.startswith("mtllib ")]
    assert mtllib == ["two_tone.mtl"], f"mtllib directive missing: {mtllib}"
    assert (tmp_path / mtllib[0]).exists()

    groups = _parse_obj_groups(text)
    assert f"mat_box__{first}" in groups
    assert f"mat_box__{second}" in groups
    assert groups[f"mat_box__{first}"] > 0
    assert groups[f"mat_box__{second}"] > 0
    # Every face is still written exactly once.
    assert sum(groups.values()) == len(scene.meshes["box"].indices)

    mtl = _parse_mtl((tmp_path / "two_tone.mtl").read_text(encoding="utf-8"))
    assert mtl[f"mat_box__{first}"] == (1.0, 0.0, 0.0)
    assert mtl[f"mat_box__{second}"] == (0.0, 0.0, 1.0)
    assert mtl[f"mat_box__{first}"] != mtl[f"mat_box__{second}"], \
        "the two patches must not share one colour"


# --- GLB --------------------------------------------------------------------

def _read_glb_json(path):
    """Independent minimal GLB reader: returns the JSON chunk."""
    with open(path, "rb") as fh:
        magic, version, _total = struct.unpack("<4sII", fh.read(12))
        assert magic == b"glTF" and version == 2
        length, kind = struct.unpack("<I4s", fh.read(8))
        assert kind == b"JSON"
        return json.loads(fh.read(length).decode("utf-8"))


def test_glb_export_writes_one_primitive_per_patch_material(two_tone_box,
                                                            tmp_path):
    session, first, second = two_tone_box
    scene = evaluate_scene(session)
    meshes = {n: m for n, m in scene.meshes.items() if len(m.vertices)}
    out = tmp_path / "two_tone.glb"
    write_glb(str(out), meshes,
              patch_materials=scene_patch_material_colors(scene))

    doc = _read_glb_json(str(out))
    prims = doc["meshes"][0]["primitives"]
    assert len(prims) >= 2, "patches collapsed into a single primitive"

    names = [m["name"] for m in doc["materials"]]
    assert f"mat_box__{first}" in names
    assert f"mat_box__{second}" in names
    factors = {m["name"]: m["pbrMetallicRoughness"]["baseColorFactor"]
               for m in doc["materials"]}
    assert factors[f"mat_box__{first}"][:3] == [1.0, 0.0, 0.0]
    assert factors[f"mat_box__{second}"][:3] == [0.0, 0.0, 1.0]

    # Each primitive must reference valid accessors and cover all triangles.
    total = 0
    for prim in prims:
        acc = doc["accessors"][prim["indices"]]
        assert acc["count"] % 3 == 0
        total += acc["count"]
    assert total == len(scene.meshes["box"].indices) * 3


def test_glb_stays_single_primitive_without_patch_materials(tmp_path):
    """The multi-primitive path must not fire for ordinary single-material
    objects -- that would change every existing export."""
    s = Session()
    CreatePrimitiveCommand(s, "box", "box").redo()
    scene = evaluate_scene(s)
    out = tmp_path / "plain.glb"
    write_glb(str(out), {n: m for n, m in scene.meshes.items()})
    doc = _read_glb_json(str(out))
    assert len(doc["meshes"][0]["primitives"]) == 1
