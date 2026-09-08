"""Independent readers/validators for exported OBJ and GLB files.

These do not call anything in :mod:`am3d.export.obj` or
:mod:`am3d.export.gltf` and do not share their internal data structures —
they re-derive geometry and structure straight from the bytes on disk, the
same way an external tool would. A bug in the writer that a round-trip
through the writer's own helpers would not catch (wrong index arithmetic,
a sidecar that never reaches the file it references, a declared bound that
does not match the actual data) is exactly what this is for.

Each ``validate_*`` function returns a list of human-readable issue
strings; an empty list means the file is structurally sound. Nothing here
raises on a malformed file except when the file cannot be parsed at all.
"""

from __future__ import annotations

import json
import os
import struct

import numpy as np

_GLTF_MAGIC = 0x46546C67
_CHUNK_JSON = 0x4E4F534A
_CHUNK_BIN = 0x004E4942

_COMPONENT_DTYPES = {
    5120: "<i1", 5121: "<u1", 5122: "<i2", 5123: "<u2",
    5125: "<u4", 5126: "<f4",
}
_TYPE_COMPONENTS = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4,
                    "MAT2": 4, "MAT3": 9, "MAT4": 16}


# ---------------------------------------------------------------------------
# glTF binary (.glb)
# ---------------------------------------------------------------------------
def read_glb(path: str) -> tuple[dict, bytes, int]:
    """Parse a .glb container from raw bytes: ``(json_dict, bin_chunk, bin_chunk_file_offset)``.

    Walks the 12-byte header and each chunk by its declared length, exactly
    as an external glTF loader would — no use of anything from
    :mod:`am3d.export.gltf`.
    """
    with open(path, "rb") as fh:
        blob = fh.read()
    if len(blob) < 12:
        raise ValueError("file too small to be a glTF binary")
    magic, version, total_len = struct.unpack_from("<III", blob, 0)
    if magic != _GLTF_MAGIC:
        raise ValueError(f"bad magic {magic:#x}, expected glTF")
    if total_len != len(blob):
        raise ValueError(f"header declares {total_len} bytes, file is {len(blob)}")

    offset = 12
    gltf_json = None
    bin_chunk = b""
    bin_offset = -1
    while offset + 8 <= total_len:
        chunk_len, chunk_type = struct.unpack_from("<II", blob, offset)
        offset += 8
        data = blob[offset:offset + chunk_len]
        if chunk_type == _CHUNK_JSON:
            gltf_json = json.loads(data.decode("utf-8"))
        elif chunk_type == _CHUNK_BIN:
            bin_chunk = data
            bin_offset = offset
        offset += chunk_len

    if gltf_json is None:
        raise ValueError("no JSON chunk found")
    return gltf_json, bin_chunk, bin_offset


def accessor_byte_range(gltf: dict, accessor_index: int) -> tuple[int, int]:
    """Byte offset/length of *accessor_index*'s data within the bin chunk."""
    acc = gltf["accessors"][accessor_index]
    bv = gltf["bufferViews"][acc["bufferView"]]
    dtype = np.dtype(_COMPONENT_DTYPES[acc["componentType"]])
    ncomp = _TYPE_COMPONENTS[acc["type"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    length = acc["count"] * ncomp * dtype.itemsize
    return start, length


def read_accessor(gltf: dict, bin_chunk: bytes, accessor_index: int) -> np.ndarray:
    """Decode one accessor's data straight out of the binary chunk."""
    acc = gltf["accessors"][accessor_index]
    dtype = np.dtype(_COMPONENT_DTYPES[acc["componentType"]])
    ncomp = _TYPE_COMPONENTS[acc["type"]]
    start, length = accessor_byte_range(gltf, accessor_index)
    raw = bin_chunk[start:start + length]
    if len(raw) != length:
        raise ValueError(
            f"accessor {accessor_index}: expected {length} bytes at "
            f"offset {start}, bin chunk only has {len(bin_chunk) - start}")
    flat = np.frombuffer(raw, dtype=dtype)
    return flat.reshape(acc["count"], ncomp) if ncomp > 1 else flat.copy()


def validate_glb(path: str) -> list[str]:
    """Structural + referential validation of a .glb file.

    Checks (independently of the writer): every accessor's declared
    min/max matches the data actually in the buffer, every triangle index
    is within the referenced position accessor's vertex count, every
    NORMAL accessor is unit-length, and every primitive/material index
    reference resolves to something that exists.
    """
    issues: list[str] = []
    try:
        gltf, bin_chunk, _ = read_glb(path)
    except Exception as exc:
        return [f"could not parse GLB: {exc}"]

    n_accessors = len(gltf.get("accessors", []))
    n_materials = len(gltf.get("materials", []))

    for mi, mesh in enumerate(gltf.get("meshes", [])):
        for pi, prim in enumerate(mesh.get("primitives", [])):
            where = f"mesh[{mi}] {mesh.get('name', '?')!r} primitive[{pi}]"
            attrs = prim.get("attributes", {})

            pos_idx = attrs.get("POSITION")
            if pos_idx is None:
                issues.append(f"{where}: missing POSITION attribute")
                continue
            if not (0 <= pos_idx < n_accessors):
                issues.append(f"{where}: POSITION accessor {pos_idx} out of range")
                continue
            positions = read_accessor(gltf, bin_chunk, pos_idx)
            n_verts = len(positions)

            acc = gltf["accessors"][pos_idx]
            actual_min = positions.min(axis=0)
            actual_max = positions.max(axis=0)
            declared_min = np.asarray(acc.get("min", actual_min), dtype=np.float32)
            declared_max = np.asarray(acc.get("max", actual_max), dtype=np.float32)
            if not np.allclose(declared_min, actual_min, atol=1e-4):
                issues.append(f"{where}: accessor min {list(declared_min)} "
                              f"!= actual data min {list(actual_min)}")
            if not np.allclose(declared_max, actual_max, atol=1e-4):
                issues.append(f"{where}: accessor max {list(declared_max)} "
                              f"!= actual data max {list(actual_max)}")

            norm_idx = attrs.get("NORMAL")
            if norm_idx is not None:
                if not (0 <= norm_idx < n_accessors):
                    issues.append(f"{where}: NORMAL accessor {norm_idx} out of range")
                else:
                    normals = read_accessor(gltf, bin_chunk, norm_idx)
                    if len(normals) != n_verts:
                        issues.append(f"{where}: {len(normals)} normals for {n_verts} vertices")
                    lengths = np.linalg.norm(normals, axis=1)
                    bad = np.abs(lengths - 1.0) > 1e-3
                    if bad.any():
                        issues.append(
                            f"{where}: {int(bad.sum())} normal(s) not unit length "
                            f"(e.g. index {int(np.argmax(bad))} has length {lengths[bad][0]:.6f})")

            uv_idx = attrs.get("TEXCOORD_0")
            if uv_idx is not None:
                if not (0 <= uv_idx < n_accessors):
                    issues.append(f"{where}: TEXCOORD_0 accessor {uv_idx} out of range")
                elif gltf["accessors"][uv_idx]["count"] != n_verts:
                    issues.append(f"{where}: TEXCOORD_0 count != vertex count")

            idx_idx = prim.get("indices")
            if idx_idx is not None:
                if not (0 <= idx_idx < n_accessors):
                    issues.append(f"{where}: indices accessor {idx_idx} out of range")
                else:
                    indices = read_accessor(gltf, bin_chunk, idx_idx)
                    if len(indices) % 3 != 0:
                        issues.append(f"{where}: index count {len(indices)} not a multiple of 3")
                    if len(indices):
                        lo, hi = int(indices.min()), int(indices.max())
                        if lo < 0 or hi >= n_verts:
                            issues.append(
                                f"{where}: index range [{lo}, {hi}] out of "
                                f"bounds for {n_verts} vertices")

            mat_idx = prim.get("material")
            if mat_idx is not None and not (0 <= mat_idx < n_materials):
                issues.append(f"{where}: material index {mat_idx} out of range "
                              f"({n_materials} material(s) declared)")

    return issues


def outward_normal_fraction(positions: np.ndarray, normals: np.ndarray) -> float:
    """Fraction of vertices whose normal points away from the mesh centroid.

    A heuristic, not a hard invariant (concave shapes legitimately have
    inward-facing normals at concavities) — meant for star-shaped/convex
    fixtures such as the primitive builders, to catch a wholesale inverted-
    normal regression.
    """
    centroid = positions.mean(axis=0)
    outward = positions - centroid
    outward_norm = np.linalg.norm(outward, axis=1, keepdims=True)
    outward_unit = outward / np.maximum(outward_norm, 1e-12)
    dots = np.einsum("ij,ij->i", outward_unit, normals)
    return float((dots > 0).mean())


# ---------------------------------------------------------------------------
# Wavefront OBJ (+ MTL sidecar)
# ---------------------------------------------------------------------------
def read_obj(path: str) -> dict:
    """Parse an OBJ file with a from-scratch line-based reader."""
    v, vt, vn = [], [], []
    faces = []
    mtllib = None
    current_object = None
    current_mat = None

    with open(path, "r", encoding="utf-8") as fh:
        for lineno, raw_line in enumerate(fh, start=1):
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            tag = parts[0]
            if tag == "mtllib":
                mtllib = parts[1]
            elif tag == "o":
                current_object = parts[1] if len(parts) > 1 else None
            elif tag == "usemtl":
                current_mat = parts[1] if len(parts) > 1 else None
            elif tag == "v":
                v.append(tuple(float(x) for x in parts[1:4]))
            elif tag == "vt":
                vt.append(tuple(float(x) for x in parts[1:3]))
            elif tag == "vn":
                vn.append(tuple(float(x) for x in parts[1:4]))
            elif tag == "f":
                refs = []
                for token in parts[1:]:
                    bits = token.split("/")
                    vi = int(bits[0])
                    vti = int(bits[1]) if len(bits) > 1 and bits[1] else None
                    vni = int(bits[2]) if len(bits) > 2 and bits[2] else None
                    refs.append((vi, vti, vni))
                faces.append({"line": lineno, "object": current_object,
                              "material": current_mat, "refs": refs})

    return {"v": v, "vt": vt, "vn": vn, "faces": faces, "mtllib": mtllib}


def read_mtl(path: str) -> dict:
    """Parse a .mtl sidecar with a from-scratch line-based reader."""
    materials: dict = {}
    current = None
    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            tag = parts[0]
            if tag == "newmtl":
                current = parts[1] if len(parts) > 1 else None
                materials[current] = {}
            elif current is not None and tag in ("Kd", "Ka", "Ks"):
                materials[current][tag] = tuple(float(x) for x in parts[1:4])
            elif current is not None and tag == "d":
                materials[current]["d"] = float(parts[1])
    return materials


def validate_obj(path: str) -> list[str]:
    """Structural + referential validation of an OBJ (+ .mtl) file.

    Checks (independently of the writer): every ``f`` vertex/uv/normal
    index is a valid 1-based reference into its ``v``/``vt``/``vn`` table,
    a declared ``mtllib`` sidecar exists and parses, and every ``usemtl``
    name resolves to a ``newmtl`` entry in that sidecar.
    """
    issues: list[str] = []
    try:
        parsed = read_obj(path)
    except Exception as exc:
        return [f"could not parse OBJ: {exc}"]

    n_v, n_vt, n_vn = len(parsed["v"]), len(parsed["vt"]), len(parsed["vn"])

    for face in parsed["faces"]:
        for vi, vti, vni in face["refs"]:
            if not (1 <= vi <= n_v):
                issues.append(f"line {face['line']}: v index {vi} out of range (1..{n_v})")
            if vti is not None and not (1 <= vti <= n_vt):
                issues.append(f"line {face['line']}: vt index {vti} out of range (1..{n_vt})")
            if vni is not None and not (1 <= vni <= n_vn):
                issues.append(f"line {face['line']}: vn index {vni} out of range (1..{n_vn})")

    used_materials = {f["material"] for f in parsed["faces"] if f["material"]}
    if used_materials and not parsed["mtllib"]:
        issues.append(f"usemtl references {sorted(used_materials)} but no mtllib directive")
    elif parsed["mtllib"]:
        mtl_path = os.path.join(os.path.dirname(os.path.abspath(path)), parsed["mtllib"])
        if not os.path.exists(mtl_path):
            issues.append(f"mtllib {parsed['mtllib']!r} does not exist next to {path!r}")
        else:
            try:
                mtl_materials = read_mtl(mtl_path)
            except Exception as exc:
                issues.append(f"could not parse mtllib {mtl_path!r}: {exc}")
                mtl_materials = {}
            for mat_name in used_materials:
                if mat_name not in mtl_materials:
                    issues.append(f"usemtl {mat_name!r} has no matching newmtl in {parsed['mtllib']!r}")

    return issues
