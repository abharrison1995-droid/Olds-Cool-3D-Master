"""Independent verification of OBJ/GLB written by the frozen artifacts.

Deliberately imports nothing from am3d: it re-implements just enough of
the Wavefront OBJ and glTF 2.0 binary container to check the files with
readers that cannot share a bug with the exporters that wrote them.

    python3 verify_exports.py <scene.obj> <scene.glb>
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


def read_obj(path):
    verts, faces, groups, mtllib, usemtl = [], [], {}, [], []
    current = None
    for line in Path(path).read_text().splitlines():
        parts = line.split()
        if not parts:
            continue
        tag, rest = parts[0], parts[1:]
        if tag == "v":
            verts.append(tuple(float(x) for x in rest[:3]))
        elif tag == "f":
            idx = [int(p.split("/")[0]) for p in rest]
            faces.append(idx)
            groups.setdefault(current, []).append(len(faces) - 1)
        elif tag in ("g", "o"):
            current = rest[0] if rest else None
        elif tag == "mtllib":
            mtllib += rest
        elif tag == "usemtl":
            usemtl += rest
    return dict(verts=verts, faces=faces, groups=groups,
                mtllib=mtllib, usemtl=usemtl)


def read_glb(path):
    data = Path(path).read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF", f"not a GLB: {magic!r}"
    assert version == 2, f"unexpected glTF version {version}"
    assert length == len(data), f"header length {length} != file size {len(data)}"
    offset, chunks = 12, []
    while offset < length:
        clen, ctype = struct.unpack_from("<I4s", data, offset)
        body = data[offset + 8: offset + 8 + clen]
        assert clen % 4 == 0, f"chunk {ctype!r} length {clen} is not 4-byte aligned"
        chunks.append((ctype, body))
        offset += 8 + clen
    kinds = [c[0] for c in chunks]
    assert kinds[0] == b"JSON", f"first chunk is {kinds[0]!r}, not JSON"
    doc = json.loads(chunks[0][1].decode("utf-8"))
    binary = chunks[1][1] if len(chunks) > 1 else b""
    return doc, binary


def main(obj_path, glb_path):
    problems = []
    obj = read_obj(obj_path)
    print(f"OBJ  {obj_path}")
    print(f"  vertices        : {len(obj['verts'])}")
    print(f"  faces           : {len(obj['faces'])}")
    print(f"  groups          : {sorted(k for k in obj['groups'] if k)}")
    print(f"  mtllib          : {obj['mtllib']}")
    print(f"  usemtl          : {sorted(set(obj['usemtl']))}")
    if not obj["verts"] or not obj["faces"]:
        problems.append("OBJ has no geometry")
    nmax = len(obj["verts"])
    for face in obj["faces"]:
        for i in face:
            if not (1 <= i <= nmax):
                problems.append(f"OBJ face index {i} out of range 1..{nmax}")
                break
    if obj["usemtl"] and not obj["mtllib"]:
        problems.append("OBJ uses materials but declares no mtllib")

    doc, binary = read_glb(glb_path)
    meshes = doc.get("meshes", [])
    prims = [p for m in meshes for p in m.get("primitives", [])]
    print(f"GLB  {glb_path}")
    print(f"  asset.version   : {doc.get('asset', {}).get('version')}")
    print(f"  nodes/meshes    : {len(doc.get('nodes', []))}/{len(meshes)}")
    print(f"  primitives      : {len(prims)}")
    print(f"  materials       : {[m.get('name') for m in doc.get('materials', [])]}")
    print(f"  BIN chunk bytes : {len(binary)}")
    if doc.get("asset", {}).get("version") != "2.0":
        problems.append("GLB asset.version is not 2.0")
    if not prims:
        problems.append("GLB contains no primitives")
    for i, acc in enumerate(doc.get("accessors", [])):
        view = doc["bufferViews"][acc["bufferView"]]
        end = view.get("byteOffset", 0) + view["byteLength"]
        if end > len(binary):
            problems.append(f"GLB accessor {i} reads past the BIN chunk")
    for i, view in enumerate(doc.get("bufferViews", [])):
        if view.get("byteOffset", 0) % 4:
            problems.append(f"GLB bufferView {i} is not 4-byte aligned")
    for p in prims:
        if "POSITION" not in p.get("attributes", {}):
            problems.append("GLB primitive has no POSITION attribute")

    # Cross-check: the two formats must describe the same amount of geometry.
    total_positions = sum(
        doc["accessors"][p["attributes"]["POSITION"]]["count"] for p in prims)
    print(f"  total positions : {total_positions}")
    if abs(total_positions - len(obj["verts"])) > len(obj["verts"]) * 0.5:
        problems.append(
            f"OBJ ({len(obj['verts'])} verts) and GLB ({total_positions} "
            "positions) disagree about how much geometry the scene has")

    print()
    if problems:
        for p in problems:
            print("PROBLEM:", p)
        return 1
    print("All independent checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
