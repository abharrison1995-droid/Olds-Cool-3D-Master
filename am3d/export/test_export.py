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

# -- multi-mesh OBJ index spaces ----------------------------------------


class _FakeMesh:
    """Minimal MeshData stand-in with independently controllable channels."""

    def __init__(self, n, with_uvs=True, with_normals=True):
        self.vertices = np.zeros((n, 3), dtype=np.float64)
        self.indices = np.array([[0, 1, 2]], dtype=np.int64)
        self.uvs = np.zeros((n, 2)) if with_uvs else None
        self.normals = np.zeros((n, 3)) if with_normals else None


def _index_spaces(text):
    """Return (counts, referenced) per channel for an OBJ document."""
    lines = text.splitlines()
    counts = {ch: sum(1 for ln in lines if ln.startswith(ch + " "))
              for ch in ("v", "vt", "vn")}
    referenced = {"v": set(), "vt": set(), "vn": set()}
    for ln in lines:
        if not ln.startswith("f "):
            continue
        for token in ln.split()[1:]:
            parts = token.split("/")
            for ch, part in zip(("v", "vt", "vn"), parts):
                if part:
                    referenced[ch].add(int(part))
    return counts, referenced


def _assert_indices_in_range(text):
    counts, referenced = _index_spaces(text)
    for ch in ("v", "vt", "vn"):
        if not referenced[ch]:
            continue
        assert min(referenced[ch]) >= 1, f"{ch} indices must be 1-based"
        assert max(referenced[ch]) <= counts[ch], (
            f"{ch} index {max(referenced[ch])} referenced but only "
            f"{counts[ch]} {ch} elements written")


def test_obj_mixed_uv_meshes_keep_index_spaces_separate(tmp_path):
    """A mesh without UVs must not shift the vt indices of later meshes."""
    out = tmp_path / "mixed.obj"
    write_obj(str(out), {"plain": _FakeMesh(4, with_uvs=False),
                         "textured": _FakeMesh(4, with_uvs=True)})
    text = out.read_text()
    counts, _ = _index_spaces(text)
    assert counts["v"] == 8
    assert counts["vt"] == 4        # only the textured mesh contributes
    _assert_indices_in_range(text)


def test_obj_mesh_without_normals_omits_vn_refs(tmp_path):
    out = tmp_path / "nonormals.obj"
    write_obj(str(out), {"a": _FakeMesh(3, with_uvs=True, with_normals=False),
                         "b": _FakeMesh(3, with_uvs=True, with_normals=True)})
    text = out.read_text()
    counts, referenced = _index_spaces(text)
    assert counts["vn"] == 3
    assert referenced["vn"] == {1, 2, 3}
    _assert_indices_in_range(text)


def test_obj_mismatched_normal_count_is_not_emitted(tmp_path):
    """Normals that do not pair 1:1 with vertices must not be referenced."""
    mesh = _FakeMesh(4, with_uvs=False)
    mesh.normals = np.zeros((2, 3))        # deliberately wrong length
    out = tmp_path / "bad_normals.obj"
    write_obj(str(out), {"m": mesh})
    text = out.read_text()
    counts, referenced = _index_spaces(text)
    assert counts["vn"] == 0
    assert not referenced["vn"]
    _assert_indices_in_range(text)


def test_obj_into_handle_also_keeps_index_spaces_separate(tmp_path):
    """write_obj_into shares the writer, so it gets the same guarantees."""
    import io
    from am3d.export.obj import write_obj_into

    buf = io.StringIO()
    write_obj_into(buf, "root", {"plain": _FakeMesh(4, with_uvs=False),
                                 "textured": _FakeMesh(4, with_uvs=True)})
    text = buf.getvalue()
    assert "o root_plain" in text and "o root_textured" in text
    _assert_indices_in_range(text)


def test_obj_all_channels_present_is_contiguous(tmp_path):
    """The common case still produces the compact v/vt/vn form."""
    out = tmp_path / "full.obj"
    write_obj(str(out), {"a": _FakeMesh(3), "b": _FakeMesh(3)})
    text = out.read_text()
    counts, referenced = _index_spaces(text)
    assert counts == {"v": 6, "vt": 6, "vn": 6}
    assert referenced["v"] == referenced["vt"] == referenced["vn"]
    _assert_indices_in_range(text)
