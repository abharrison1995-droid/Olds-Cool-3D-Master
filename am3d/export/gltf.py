"""Binary glTF 2.0 (.glb) export.

Emits one mesh per scene object with POSITION, NORMAL and TEXCOORD_0
attributes plus uint32 indices — directly loadable by three.js, Unity,
Unreal, Blender and glTF viewers.
"""

from __future__ import annotations

import json
import struct

import numpy as np

_GLTF_MAGIC = 0x46546C67          # 'glTF'
_CHUNK_JSON = 0x4E4F534A          # 'JSON'
_CHUNK_BIN = 0x004E4942           # 'BIN\0'
_COMPONENT_FLOAT = 5126
_COMPONENT_UINT = 5125


def _pad(data: bytearray, alignment: int = 4, fill: int = 0) -> None:
    while len(data) % alignment:
        data.append(fill)


def write_glb(path: str, meshes: dict, *,
              materials: dict | None = None,
              patch_materials: dict | None = None,
              textures: dict | None = None) -> str:
    """Write ``{name: MeshData}`` to *path* as a single binary glTF file.

    Parameters
    ----------
    materials:
        Optional ``{object_name: (r, g, b, a)}`` flat-colour map.  When
        provided each mesh primitive is assigned a glTF material entry with
        ``pbrMetallicRoughness.baseColorFactor``.  Alpha defaults to 1.0 if
        omitted from the colour tuple.
    textures:
        Optional ``{object_name: image array}`` of baked per-object atlases,
        embedded in the BIN chunk as PNG and bound as ``baseColorTexture``
        so the .glb stays one self-contained file and a patterned material
        keeps its appearance in an independent reader (finding MAT-01).
    patch_materials:
        Optional ``{object_name: {patch_name: (r, g, b, a)}}``. glTF binds a
        material per *primitive*, so an object whose patches carry different
        materials is written as several primitives sharing one set of vertex
        accessors -- one primitive per material group, each with its own
        index accessor (finding MAT-02). Patches with no entry fall into the
        object's own material primitive.
    """
    from .textures import PNG_MIME, encode_png

    bin_buf = bytearray()
    buffer_views: list = []
    gltf_images: list = []
    gltf_textures: list = []
    gltf_samplers: list = []
    tex_index_map: dict = {}   # object_name -> index into gltf_textures
    accessors: list = []
    meshes_json: list = []
    nodes: list = []
    gltf_materials: list = []
    mat_index_map: dict = {}   # object_name -> index into gltf_materials

    def add_view(data: bytes) -> int:
        _pad(bin_buf)
        offset = len(bin_buf)
        bin_buf.extend(data)
        buffer_views.append({
            "buffer": 0,
            "byteOffset": offset,
            "byteLength": len(data),
        })
        return len(buffer_views) - 1

    # Baked atlases are embedded in the BIN chunk so the .glb stays a single
    # self-contained file (finding MAT-01). The mesh's TEXCOORD_0, already
    # written below, is the atlas UV set.
    for obj_name, image in (textures or {}).items():
        if image is None:
            continue
        png_view = add_view(encode_png(image))
        gltf_images.append({"name": f"tex_{obj_name}",
                            "bufferView": png_view,
                            "mimeType": PNG_MIME})
        if not gltf_samplers:
            gltf_samplers.append({"wrapS": 10497, "wrapT": 10497})  # REPEAT
        tex_index_map[obj_name] = len(gltf_textures)
        gltf_textures.append({"sampler": 0, "source": len(gltf_images) - 1})

    def _pbr(rgba, obj_name):
        r, g, b = float(rgba[0]), float(rgba[1]), float(rgba[2])
        a = float(rgba[3]) if len(rgba) >= 4 else 1.0
        pbr = {"baseColorFactor": [r, g, b, a],
               "metallicFactor": 0.0,
               "roughnessFactor": 0.8}
        if obj_name in tex_index_map:
            pbr["baseColorTexture"] = {"index": tex_index_map[obj_name],
                                       "texCoord": 0}
        return pbr

    # Build material entries up-front so primitives can reference them
    if materials:
        for obj_name, rgba in materials.items():
            mat_index_map[obj_name] = len(gltf_materials)
            gltf_materials.append({
                "name": f"mat_{obj_name}",
                "pbrMetallicRoughness": _pbr(rgba, obj_name),
            })

    # A textured object needs a material even with no flat colour, or the
    # atlas is embedded but never bound to anything.
    for obj_name in tex_index_map:
        if obj_name in mat_index_map:
            continue
        mat_index_map[obj_name] = len(gltf_materials)
        gltf_materials.append({
            "name": f"mat_{obj_name}",
            "pbrMetallicRoughness": _pbr((1.0, 1.0, 1.0, 1.0), obj_name),
        })

    def _material_index(name, rgba, texture_owner=None):
        """Register (or reuse) a glTF material entry and return its index."""
        if name in mat_index_map:
            return mat_index_map[name]
        mat_index_map[name] = len(gltf_materials)
        gltf_materials.append({
            "name": f"mat_{name}",
            "pbrMetallicRoughness": _pbr(rgba, texture_owner),
        })
        return mat_index_map[name]

    for name, mesh in meshes.items():
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        tris = np.asarray(mesh.indices, dtype=np.int64).ravel()
        if len(verts) == 0 or len(tris) == 0:
            continue

        pos_view = add_view(verts.astype("<f4").tobytes())
        pos_acc = {
            "bufferView": pos_view,
            "componentType": _COMPONENT_FLOAT,
            "count": int(len(verts)),
            "type": "VEC3",
            "min": [float(v) for v in verts.min(axis=0)],
            "max": [float(v) for v in verts.max(axis=0)],
        }
        accessors.append(pos_acc)
        prim = {"attributes": {"POSITION": len(accessors) - 1}, "mode": 4}

        normals = np.asarray(mesh.normals, dtype=np.float64)
        if len(normals) == len(verts):
            nrm_view = add_view(normals.astype("<f4").tobytes())
            accessors.append({
                "bufferView": nrm_view,
                "componentType": _COMPONENT_FLOAT,
                "count": int(len(verts)),
                "type": "VEC3",
            })
            prim["attributes"]["NORMAL"] = len(accessors) - 1

        uvs = getattr(mesh, "uvs", None)
        if uvs is not None and len(uvs) == len(verts):
            uv_view = add_view(uvs.astype("<f4").tobytes())
            accessors.append({
                "bufferView": uv_view,
                "componentType": _COMPONENT_FLOAT,
                "count": int(len(verts)),
                "type": "VEC2",
            })
            prim["attributes"]["TEXCOORD_0"] = len(accessors) - 1

        def _index_accessor(triangle_indices):
            view = add_view(np.asarray(triangle_indices,
                                       dtype=np.int64).ravel()
                            .astype("<u4").tobytes())
            accessors.append({
                "bufferView": view,
                "componentType": _COMPONENT_UINT,
                "count": int(np.asarray(triangle_indices).size),
                "type": "SCALAR",
            })
            return len(accessors) - 1

        obj_patches = (patch_materials or {}).get(name)
        prims = []
        if obj_patches:
            tri_rows = np.asarray(mesh.indices, dtype=np.int64)
            for patch_name, idx in sorted(
                    mesh.group_triangles().items(),
                    key=lambda kv: int(kv[1][0]) if len(kv[1]) else -1):
                if not len(idx):
                    continue
                sub = dict(prim)
                sub["indices"] = _index_accessor(tri_rows[idx])
                rgba = obj_patches.get(patch_name)
                if rgba is not None:
                    sub["material"] = _material_index(
                        f"{name}__{patch_name}", rgba, texture_owner=name)
                elif name in mat_index_map:
                    sub["material"] = mat_index_map[name]
                prims.append(sub)
        if not prims:
            prim["indices"] = _index_accessor(tris)
            if name in mat_index_map:
                prim["material"] = mat_index_map[name]
            prims = [prim]

        meshes_json.append({"name": name, "primitives": prims})
        nodes.append({"mesh": len(meshes_json) - 1, "name": name})

    gltf = {
        "asset": {"version": "2.0", "generator": "3D MASTER:2005"},
        "scene": 0,
        "scenes": [{"nodes": list(range(len(nodes)))}],
        "nodes": nodes,
        "meshes": meshes_json,
        "accessors": accessors,
        "bufferViews": buffer_views,
        "buffers": [{"byteLength": len(bin_buf)}],
    }
    if gltf_materials:
        gltf["materials"] = gltf_materials
    if gltf_textures:
        gltf["images"] = gltf_images
        gltf["samplers"] = gltf_samplers
        gltf["textures"] = gltf_textures

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_pad = (4 - len(json_bytes) % 4) % 4
    json_bytes += b" " * json_pad
    bin_pad = (4 - len(bin_buf) % 4) % 4
    bin_bytes = bytes(bin_buf) + b"\x00" * bin_pad

    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    with open(path, "wb") as fh:
        fh.write(struct.pack("<III", _GLTF_MAGIC, 2, total))
        fh.write(struct.pack("<II", len(json_bytes), _CHUNK_JSON))
        fh.write(json_bytes)
        fh.write(struct.pack("<II", len(bin_bytes), _CHUNK_BIN))
        fh.write(bin_bytes)
    return path
