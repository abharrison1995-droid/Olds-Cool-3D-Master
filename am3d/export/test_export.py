"""Tests for OBJ and binary glTF exporters."""

from __future__ import annotations

import struct

import numpy as np
import pytest

from am3d.core.project import Patch, Project
from am3d.export.gltf import write_glb
from am3d.export.obj import write_obj
from am3d.recipes.primitives import build_primitive
from am3d.renderer.tessellate import tessellate_object


def _mesh(name="m"):
    p = Project()
    obj = p.create_object(name)
    built = build_primitive("sphere", {"radius": 1.0, "sections": 10,
                                       "rings": 6})
    for pname, net, du, dv in built["patches"]:
        obj.patches.append(Patch(name=pname, splines=[], interior=net))
    return tessellate_object(obj, nu=8, nv=6)


def test_obj_roundtrip_basic_structure(tmp_path):
    mesh = _mesh("orb")
    out = tmp_path / "orb.obj"
    write_obj(str(out), {"orb": mesh})
    text = out.read_text().splitlines()
    v_lines = [ln for ln in text if ln.startswith("v ")]
    f_lines = [ln for ln in text if ln.startswith("f ")]
    assert len(v_lines) == len(mesh.vertices)
    assert len(f_lines) == len(mesh.indices)
    # faces must be 1-based and within range
    max_idx = max(int(part.split("/")[0])
                  for ln in f_lines for part in ln.split()[1:])
    assert max_idx == len(mesh.vertices)
    assert any(ln.startswith("vt ") for ln in text), "UVs should be exported"
    assert not hasattr(mesh, "_obj_base"), "export must not monkey-patch meshes"


def test_glb_header_and_chunks(tmp_path):
    pytest.importorskip("numpy")
    mesh = _mesh("orb")
    out = tmp_path / "orb.glb"
    write_glb(str(out), {"orb": mesh})
    blob = out.read_bytes()

    magic, version, total = struct.unpack_from("<III", blob, 0)
    assert magic == 0x46546C67            # 'glTF'
    assert version == 2
    assert total == len(blob)

    json_len, json_type = struct.unpack_from("<II", blob, 12)
    assert json_type == 0x4E4F534A        # 'JSON'
    gltf = __import__("json").loads(blob[20:20 + json_len].decode("utf-8"))
    assert gltf["asset"]["version"] == "2.0"
    assert len(gltf["meshes"]) == 1
    prim = gltf["meshes"][0]["primitives"][0]
    assert set(prim["attributes"]) >= {"POSITION"}
    assert "TEXCOORD_0" in prim["attributes"]

    bin_off = 20 + json_len
    bin_len, bin_type = struct.unpack_from("<II", blob, bin_off)
    assert bin_type == 0x004E4942         # 'BIN\0'
    assert bin_off + 8 + bin_len == len(blob)


def test_glb_positions_accessor_bounds_match_mesh(tmp_path):
    import json as _json
    mesh = _mesh("orb")
    out = tmp_path / "o.glb"
    write_glb(str(out), {"orb": mesh})
    blob = out.read_bytes()
    json_len, _ = struct.unpack_from("<II", blob, 12)
    gltf = _json.loads(blob[20:20 + json_len].decode("utf-8"))
    pos_acc = next(a for a in gltf["accessors"] if a.get("type") == "VEC3"
                   and "min" in a)
    assert np.allclose(pos_acc["min"], mesh.vertices.min(axis=0), atol=1e-5)
    assert np.allclose(pos_acc["max"], mesh.vertices.max(axis=0), atol=1e-5)