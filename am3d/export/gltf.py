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


def write_glb(path: str, meshes: dict) -> str:
    """Write ``{name: MeshData}`` to *path* as a single binary glTF file."""
    bin_buf = bytearray()
    buffer_views: list = []
    accessors: list = []
    meshes_json: list = []
    nodes: list = []

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

        idx_view = add_view(tris.astype("<u4").tobytes())
        accessors.append({
            "bufferView": idx_view,
            "componentType": _COMPONENT_UINT,
            "count": int(len(tris)),
            "type": "SCALAR",
        })
        prim["indices"] = len(accessors) - 1

        meshes_json.append({"name": name, "primitives": [prim]})
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