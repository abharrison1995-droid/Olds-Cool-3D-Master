"""Baked appearance survives export (finding MAT-01).

Before the fix a checkerboard material baked into a real atlas (std 84.7 of
255) but both exporters wrote only its flat base colour: the MTL had no
map_Kd and the GLB had no images/textures at all, so an independent reader
showed plain white. Evidence:
docs/evidence/desktop-release/phase-b/mat-01-reproduction.txt
"""

from __future__ import annotations

import io
import json
import struct

import numpy as np
import pytest

from am3d.core.scene import bake_scene_atlases, evaluate_scene, \
    scene_material_colors
from am3d.core.script import Session
from am3d.export.gltf import write_glb
from am3d.export.obj import write_obj
from am3d.export.textures import encode_png, to_uint8_rgba
from am3d.ui.operators import CreatePrimitiveCommand


@pytest.fixture()
def checkered():
    """A box wearing a checkerboard -- appearance a flat colour cannot hold."""
    s = Session()
    CreatePrimitiveCommand(s, "box", "box").redo()
    mat = s.create_material("checked", color=(1.0, 1.0, 1.0, 1.0))
    mat.pattern = "checker"
    s.get_object("box").material = "checked"
    return s


def _scene_meshes(session):
    scene = evaluate_scene(session)
    return scene, {n: m for n, m in scene.meshes.items() if len(m.vertices)}


# --- the baking boundary ----------------------------------------------------

def test_a_patterned_material_bakes_an_atlas_a_flat_colour_cannot_express(
        checkered):
    atlases = bake_scene_atlases(checkered)
    assert "box" in atlases
    assert float(np.asarray(atlases["box"]).std()) > 0.01, \
        "the atlas is uniform -- nothing was actually baked"


def test_flat_only_scenes_bake_nothing_and_export_unchanged(tmp_path):
    """The existing flat-colour path must stay byte-identical."""
    s = Session()
    CreatePrimitiveCommand(s, "box", "box").redo()
    s.create_material("red", color=(1.0, 0.0, 0.0, 1.0))
    s.get_object("box").material = "red"
    assert bake_scene_atlases(s) == {}

    scene, meshes = _scene_meshes(s)
    colors = scene_material_colors(scene)
    # Same stem in two directories, so the mtllib reference is identical
    # and any difference is a real change to the flat-colour output.
    one = tmp_path / "one"
    two = tmp_path / "two"
    one.mkdir()
    two.mkdir()
    write_obj(str(one / "m.obj"), meshes, materials=colors)
    write_obj(str(two / "m.obj"), meshes, materials=colors, textures=None)
    assert (one / "m.obj").read_bytes() == (two / "m.obj").read_bytes()
    assert (one / "m.mtl").read_bytes() == (two / "m.mtl").read_bytes()
    assert "map_Kd" not in (one / "m.mtl").read_text(encoding="utf-8")
    assert not list(tmp_path.rglob("*.png"))


# --- OBJ / MTL, read back independently -------------------------------------

def test_obj_export_carries_the_atlas_through_an_mtl_map_kd(checkered,
                                                            tmp_path):
    from PIL import Image

    scene, meshes = _scene_meshes(checkered)
    out = tmp_path / "checked.obj"
    write_obj(str(out), meshes, materials=scene_material_colors(scene),
              textures=bake_scene_atlases(checkered))

    obj_text = out.read_text(encoding="utf-8")
    assert "mtllib checked.mtl" in obj_text
    assert "usemtl mat_box" in obj_text
    assert "\nvt " in obj_text, "no texture coordinates to address the atlas"

    mtl_text = (tmp_path / "checked.mtl").read_text(encoding="utf-8")
    maps = [l.split(None, 1)[1].strip() for l in mtl_text.splitlines()
            if l.startswith("map_Kd ")]
    assert maps, "MTL has no map_Kd, so a reader sees a flat colour"

    # Independent reader: Pillow, which knows nothing about this codebase.
    image_path = tmp_path / maps[0]
    assert image_path.exists(), f"MTL points at a missing image {maps[0]}"
    with Image.open(image_path) as im:
        assert im.mode == "RGBA"
        pixels = np.asarray(im)
    assert float(pixels.std()) > 5.0, \
        "the exported image is flat -- the pattern did not survive"
    assert len(np.unique(pixels.reshape(-1, 4), axis=0)) > 1


def test_map_kd_is_a_bare_basename_so_the_pair_stays_relocatable(checkered,
                                                                 tmp_path):
    import os
    import shutil

    scene, meshes = _scene_meshes(checkered)
    src = tmp_path / "src"
    src.mkdir()
    write_obj(str(src / "m.obj"), meshes,
              materials=scene_material_colors(scene),
              textures=bake_scene_atlases(checkered))
    mtl = (src / "m.mtl").read_text(encoding="utf-8")
    ref = [l.split(None, 1)[1].strip() for l in mtl.splitlines()
           if l.startswith("map_Kd ")][0]
    assert os.path.basename(ref) == ref, f"map_Kd is not relocatable: {ref}"

    moved = tmp_path / "moved"
    shutil.copytree(src, moved)
    assert (moved / ref).exists()


# --- GLB, read back independently -------------------------------------------

def _read_glb(path):
    """Minimal independent GLB reader -> (json document, BIN chunk bytes)."""
    with open(path, "rb") as fh:
        magic, version, total = struct.unpack("<4sII", fh.read(12))
        assert magic == b"glTF" and version == 2
        blob = fh.read()
    assert total == 12 + len(blob), "declared GLB length does not match"
    doc = bin_chunk = None
    offset = 0
    while offset < len(blob):
        length, kind = struct.unpack("<I4s", blob[offset:offset + 8])
        payload = blob[offset + 8:offset + 8 + length]
        if kind == b"JSON":
            doc = json.loads(payload.decode("utf-8"))
        elif kind.rstrip(b"\x00") == b"BIN":
            bin_chunk = payload
        offset += 8 + length
    return doc, bin_chunk


def test_glb_embeds_the_atlas_and_binds_it_as_base_color(checkered, tmp_path):
    from PIL import Image

    scene, meshes = _scene_meshes(checkered)
    out = tmp_path / "checked.glb"
    write_glb(str(out), meshes, materials=scene_material_colors(scene),
              textures=bake_scene_atlases(checkered))

    doc, bin_chunk = _read_glb(str(out))
    assert doc["images"] and doc["textures"] and doc["samplers"]

    material = doc["materials"][0]["pbrMetallicRoughness"]
    binding = material.get("baseColorTexture")
    assert binding is not None, "the image is embedded but never bound"
    texture = doc["textures"][binding["index"]]
    image = doc["images"][texture["source"]]
    assert image["mimeType"] == "image/png"

    # The primitive must actually supply the UV set the binding names.
    prim = doc["meshes"][0]["primitives"][0]
    assert f"TEXCOORD_{binding.get('texCoord', 0)}" in prim["attributes"]

    # Independent reader: slice the bufferView out of the BIN chunk and
    # decode it with Pillow.
    view = doc["bufferViews"][image["bufferView"]]
    start = view.get("byteOffset", 0)
    png_bytes = bin_chunk[start:start + view["byteLength"]]
    assert png_bytes[:8] == b"\x89PNG\r\n\x1a\n", "not a PNG at that offset"
    with Image.open(io.BytesIO(png_bytes)) as im:
        pixels = np.asarray(im)
    assert float(pixels.std()) > 5.0, \
        "the embedded image is flat -- the pattern did not survive"


def test_glb_without_textures_declares_no_image_blocks(tmp_path):
    s = Session()
    CreatePrimitiveCommand(s, "box", "box").redo()
    scene, meshes = _scene_meshes(s)
    out = tmp_path / "plain.glb"
    write_glb(str(out), meshes)
    doc, _ = _read_glb(str(out))
    assert "images" not in doc and "textures" not in doc


# --- the encoder itself -----------------------------------------------------

@pytest.mark.parametrize("shape", [(4, 4), (4, 4, 1), (4, 4, 3), (4, 4, 4)])
def test_atlas_channel_counts_all_normalise_to_rgba(shape):
    arr = np.full(shape, 0.5)
    out = to_uint8_rgba(arr)
    assert out.shape == (4, 4, 4) and out.dtype == np.uint8
    # An image with no alpha channel of its own becomes fully opaque; one
    # that has alpha keeps it.
    expected = 128 if len(shape) == 3 and shape[2] == 4 else 255
    assert (out[..., 3] == expected).all()


def test_png_is_flipped_so_uv_origin_matches_both_formats():
    """OBJ and glTF both put UV (0,0) at the image's bottom-left, while the
    baked atlas is stored top-row-first; without the flip patterns export
    upside down."""
    from PIL import Image

    atlas = np.zeros((4, 4, 4))
    atlas[..., 3] = 1.0
    atlas[0, :, 0] = 1.0            # red stripe on the atlas's FIRST row
    with Image.open(io.BytesIO(encode_png(atlas))) as im:
        pixels = np.asarray(im)
    assert pixels[-1, 0, 0] == 255, "top row did not become the image bottom"
    assert pixels[0, 0, 0] == 0


def test_an_uint8_atlas_is_passed_through_without_rescaling():
    arr = np.zeros((2, 2, 4), dtype=np.uint8)
    arr[..., 0] = 200
    arr[..., 3] = 255
    assert to_uint8_rgba(arr)[0, 0, 0] == 200


@pytest.mark.parametrize("bad", [np.zeros((4,)), np.zeros((2, 2, 2))])
def test_unusable_image_shapes_are_rejected_clearly(bad):
    with pytest.raises(ValueError):
        to_uint8_rgba(bad)
