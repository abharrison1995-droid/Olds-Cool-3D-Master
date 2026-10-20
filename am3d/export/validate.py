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
from pathlib import Path
import stat
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
    mtllibs = []
    resource_issues = []
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
                if len(parts) != 2:
                    resource_issues.append("unsupported mtllib declaration")
                else:
                    mtllib = parts[1]
                    mtllibs.append(parts[1])
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

    return {"v": v, "vt": vt, "vn": vn, "faces": faces, "mtllib": mtllib,
            "mtllibs": mtllibs, "resource_issues": resource_issues}


def read_mtl(path: str, *, include_resources: bool = False) -> dict:
    """Parse a .mtl sidecar with a from-scratch line-based reader."""
    materials: dict = {}
    resources = []
    resource_issues = []
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
            elif tag.casefold() in {"map_ka", "map_kd", "map_ks", "map_ke",
                                    "map_d", "map_bump", "bump", "norm",
                                    "disp", "decal", "refl"}:
                # The V1 strict reader accepts the writer's portable single
                # filename form. It rejects option-rich/quoted syntax instead
                # of guessing which token names a file.
                if len(parts) != 2 or parts[1].startswith("-"):
                    resource_issues.append("unsupported MTL texture reference")
                else:
                    resources.append(parts[1])
                    if include_resources and current is not None:
                        materials[current].setdefault("_resources", []).append(parts[1])
    if include_resources:
        return {"materials": materials, "resources": resources,
                "resource_issues": resource_issues}
    return materials


def _is_link_or_junction(path: Path) -> bool:
    try:
        info = path.lstat()
    except OSError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return stat.S_ISLNK(info.st_mode) or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _strict_output_budget_exceeded(paths, kind: str) -> dict | None:
    """Return explicit host measurements when strict inputs exceed policy."""
    from am3d.ai.policy import MAX_OUTPUT_BYTES

    total = 0
    seen = set()
    for path in paths:
        try:
            identity = os.path.normcase(os.path.realpath(path))
            if identity in seen:
                continue
            seen.add(identity)
            size = Path(path).stat().st_size
        except OSError:
            raise
        if size < 0:
            raise OSError("invalid file size")
        if size > MAX_OUTPUT_BYTES:
            return {"kind": kind, "actual": size,
                    "limit": MAX_OUTPUT_BYTES, "unit": "bytes"}
        total += size
        if total > MAX_OUTPUT_BYTES:
            return {"kind": kind, "actual": total,
                    "limit": MAX_OUTPUT_BYTES, "unit": "bytes"}
    return None


def _strict_resource_path(raw: str, base: Path, root: Path,
                          allowed_suffixes: set[str]) -> tuple[Path | None, str | None, dict | None]:
    from am3d.core.paths import (classify_portable_relative_path,
                                 extended_io_path, split_segments)

    if not isinstance(raw, str) or classify_portable_relative_path(raw) is not None:
        return None, "nonportable resource reference", None
    parts = split_segments(raw)
    if not parts or Path(parts[-1]).suffix.casefold() not in allowed_suffixes:
        return None, "unsupported resource type", None
    candidate = base.joinpath(*parts)
    try:
        candidate = Path(extended_io_path(candidate))
        root = Path(extended_io_path(root))
        root_real = Path(os.path.realpath(root))
        candidate_real = Path(os.path.realpath(candidate))
        if os.path.commonpath((str(root_real), str(candidate_real))) != str(root_real):
            return None, "resource escapes output root", None
    except (OSError, ValueError):
        return None, "resource escapes output root", None
    current = candidate
    while True:
        if current.exists() or current.is_symlink():
            if _is_link_or_junction(current):
                return None, "linked resource is not allowed", None
        if current == root or current == current.parent:
            break
        current = current.parent
    if not candidate.is_file():
        return None, "referenced resource is missing", None
    try:
        exceeded = _strict_output_budget_exceeded([candidate], "obj_dependency_bytes")
    except OSError:
        return None, "referenced resource is unavailable", None
    if exceeded is not None:
        return None, "referenced resource exceeds the policy byte limit", exceeded
    try:
        candidate.relative_to(root)
    except ValueError:
        return None, "resource escapes output root", None
    return candidate, None, None


def _validate_obj_strict(path: str, root: str) -> dict:
    """Validate OBJ dependencies without reading outside the supplied root.

    The returned resource names are root-relative and suitable for adding to a
    checked artifact manifest. Diagnostics intentionally contain no source
    paths or exception strings.
    """
    from am3d.core.paths import extended_io_path

    issues = []
    resources = []
    resource_details = None

    def _make_result(issue_list, *, resources_value=None, object_materials=None,
                     materials=None):
        return {
            "issues": issue_list,
            "resources": resources_value if resources_value is not None else [],
            "object_materials": object_materials if object_materials is not None else {},
            "materials": materials if materials is not None else {},
            "resource_limit": resource_details is not None,
            "resource_limit_details": resource_details,
        }

    try:
        root_path = Path(extended_io_path(root))
        obj_path = Path(extended_io_path(path))
        root_real = Path(os.path.realpath(root_path))
        obj_real = Path(os.path.realpath(obj_path))
        if (not root_path.is_dir() or _is_link_or_junction(root_path)
                or os.path.commonpath((str(root_real), str(obj_real))) != str(root_real)):
            return _make_result(["OBJ path is outside or below an unsafe output root"])
        current = obj_path
        while True:
            if current.exists() or current.is_symlink():
                if _is_link_or_junction(current):
                    return _make_result(["OBJ path contains a linked component"])
            if current == root_path or current == current.parent:
                break
            current = current.parent
        if not obj_path.is_file():
            return _make_result(["OBJ file is missing"])
        resource_details = _strict_output_budget_exceeded(
            [obj_path], "obj_input_bytes")
        if resource_details is not None:
            return _make_result(["OBJ exceeds the policy byte limit"])
        parsed = read_obj(str(obj_path))
    except Exception:
        return _make_result(["OBJ could not be parsed safely"])

    issues.extend(parsed.get("resource_issues", []))
    mtl_paths = []
    if len(parsed.get("mtllibs", [])) > 32:
        resource_details = {"kind": "obj_dependency_count",
                            "actual": len(parsed.get("mtllibs", [])),
                            "limit": 32, "unit": "count"}
        issues.append("OBJ has too many material sidecar references")
    if parsed.get("mtllibs"):
        # Preflight every sidecar before opening any of them.
        for reference in parsed["mtllibs"][:32]:
            sidecar, error, resource_failure = _strict_resource_path(
                reference, obj_path.parent, root_path, {".mtl"})
            if resource_failure is not None:
                resource_details = resource_failure
            if error:
                issues.append("OBJ material sidecar reference is unsafe or unavailable")
            else:
                mtl_paths.append(sidecar)
    if not issues:
        resource_details = _strict_output_budget_exceeded(
            [obj_path, *mtl_paths], "obj_dependency_bytes")
    if not issues and resource_details is not None:
        issues.append("OBJ material inputs exceed the policy byte limit")
    used_materials = {face["material"] for face in parsed["faces"]
                      if face.get("material")}
    if used_materials and not parsed.get("mtllibs"):
        issues.append("OBJ material assignment has no material sidecar")
    if issues:
        return _make_result(issues[:16], object_materials=_obj_object_materials(parsed))

    all_materials = {}
    texture_references = []
    for mtl_path in mtl_paths:
        try:
            mtl_result = read_mtl(str(mtl_path), include_resources=True)
        except Exception:
            issues.append("OBJ material sidecar could not be parsed")
            continue
        issues.extend(mtl_result["resource_issues"])
        all_materials.update(mtl_result["materials"])
        texture_references.extend((mtl_path.parent, name)
                                  for name in mtl_result["resources"])
        try:
            resources.append(mtl_path.relative_to(root_path).as_posix())
        except ValueError:
            issues.append("OBJ material sidecar escapes output root")

    textures = []
    # Again, validate the entire set before any referenced texture is opened.
    if len(texture_references) > 128:
        resource_details = {"kind": "obj_dependency_count",
                            "actual": len(texture_references),
                            "limit": 128, "unit": "count"}
        issues.append("MTL has too many texture references")
    if not issues:
        for base, reference in texture_references[:128]:
            texture, error, resource_failure = _strict_resource_path(
                reference, base, root_path, {".png"})
            if resource_failure is not None:
                resource_details = resource_failure
            if error:
                issues.append("OBJ texture reference is unsafe or unavailable")
            else:
                textures.append(texture)
    if not issues:
        resource_details = _strict_output_budget_exceeded(
            [obj_path, *mtl_paths, *textures], "obj_dependency_bytes")
    if not issues and resource_details is not None:
        issues.append("OBJ referenced files exceed the policy byte limit")
    if not issues:
        for texture in textures:
            try:
                resources.append(texture.relative_to(root_path).as_posix())
            except ValueError:
                issues.append("OBJ texture escapes output root")

    n_v, n_vt, n_vn = len(parsed["v"]), len(parsed["vt"]), len(parsed["vn"])
    for face in parsed["faces"]:
        for vi, vti, vni in face["refs"]:
            if not (1 <= vi <= n_v):
                issues.append("OBJ vertex index is out of range")
            if vti is not None and not (1 <= vti <= n_vt):
                issues.append("OBJ texture-coordinate index is out of range")
            if vni is not None and not (1 <= vni <= n_vn):
                issues.append("OBJ normal index is out of range")
        name = face.get("material")
        if name and name not in all_materials:
            issues.append("OBJ face references an undeclared material")
    return _make_result(issues[:32], resources_value=sorted(set(resources)),
                        object_materials=_obj_object_materials(parsed),
                        materials=all_materials)


def _obj_object_materials(parsed: dict) -> dict[str, list[str]]:
    assignments = {}
    for face in parsed.get("faces", []):
        object_name = face.get("object")
        material = face.get("material")
        if object_name and material:
            assignments.setdefault(object_name, set()).add(material)
    return {name: sorted(materials) for name, materials in assignments.items()}


def validate_obj(path: str, *, root: str | None = None,
                 return_details: bool = False) -> list[str] | dict:
    """Structural + referential validation of an OBJ (+ .mtl) file.

    Checks (independently of the writer): every ``f`` vertex/uv/normal
    index is a valid 1-based reference into its ``v``/``vt``/``vn`` table,
    a declared ``mtllib`` sidecar exists and parses, and every ``usemtl``
    name resolves to a ``newmtl`` entry in that sidecar.
    """
    if root is not None:
        result = _validate_obj_strict(path, root)
        return result if return_details else result["issues"]

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
