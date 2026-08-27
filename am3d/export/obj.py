"""Wavefront OBJ export."""

from __future__ import annotations

import os

import numpy as np


def _face_token(v: int, vt: int | None, vn: int | None) -> str:
    """One ``f`` vertex reference in the narrowest legal OBJ form."""
    if vt is not None and vn is not None:
        return f"{v}/{vt}/{vn}"
    if vt is not None:
        return f"{v}/{vt}"
    if vn is not None:
        return f"{v}//{vn}"
    return f"{v}"


def _write_meshes(fh, meshes: dict, name_prefix: str = "") -> None:
    """Write ``{name: MeshData}`` as OBJ groups into an open text handle.

    ``v``, ``vt`` and ``vn`` occupy *independent* 1-based index spaces in the
    OBJ format, so each is counted separately. A shared counter is only
    correct while every mesh carries all three channels; the moment one mesh
    lacks UVs (or its normals do not match its vertex count) the channels
    drift apart and the emitted faces reference elements that were never
    written.
    """
    v_base = vt_base = vn_base = 1
    for name, mesh in meshes.items():
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        if len(verts) == 0:
            continue
        fh.write(f"o {name_prefix}{name}\n")
        for x, y, z in verts:
            fh.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")

        uvs = getattr(mesh, "uvs", None)
        has_vt = uvs is not None and len(uvs) == len(verts)
        if has_vt:
            for u, v in np.asarray(uvs, dtype=np.float64):
                fh.write(f"vt {u:.6f} {v:.6f}\n")

        normals = getattr(mesh, "normals", None)
        has_vn = normals is not None and len(normals) == len(verts)
        if has_vn:
            for nx, ny, nz in np.asarray(normals, dtype=np.float64):
                fh.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")

        for tri in np.asarray(mesh.indices, dtype=np.int64):
            refs = []
            for corner in (int(tri[0]), int(tri[1]), int(tri[2])):
                refs.append(_face_token(
                    corner + v_base,
                    corner + vt_base if has_vt else None,
                    corner + vn_base if has_vn else None))
            fh.write("f " + " ".join(refs) + "\n")

        v_base += len(verts)
        if has_vt:
            vt_base += len(verts)
        if has_vn:
            vn_base += len(verts)


def write_obj(path: str, meshes: dict) -> str:
    """Write ``{name: MeshData}`` to *path* as a single OBJ file."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Exported by 3D MASTER:2005\n")
        _write_meshes(fh, meshes)
    return path


def write_obj_zip(path: str, meshes_by_project: dict) -> str:
    """Write several OBJ files (one per entry) into a zip archive."""
    import zipfile

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, meshes in meshes_by_project.items():
            import io
            buf = io.StringIO()
            buf.write("# Exported by 3D MASTER:2005\n")
            write_obj_into(buf, name, meshes)
            zf.writestr(f"{name}.obj", buf.getvalue())
    return path


def write_obj_into(fh, root_name: str, meshes: dict) -> None:
    """Write ``{name: MeshData}`` into an open text handle."""
    _write_meshes(fh, meshes, name_prefix=f"{root_name}_")


def ensure_parent_dir(path: str) -> str:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path
