"""Wavefront OBJ export."""

from __future__ import annotations

import os

import numpy as np


def write_obj(path: str, meshes: dict) -> str:
    """Write ``{name: MeshData}`` to *path* as a single OBJ file."""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Exported by 3D MASTER:2005\n")
        base = 1
        for name, mesh in meshes.items():
            if len(mesh.vertices) == 0:
                continue
            fh.write(f"o {name}\n")
            verts = np.asarray(mesh.vertices, dtype=np.float64)
            for x, y, z in verts:
                fh.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
            uvs = getattr(mesh, "uvs", None)
            has_vt = uvs is not None and len(uvs) == len(verts)
            if has_vt:
                for u, v in np.asarray(uvs, dtype=np.float64):
                    fh.write(f"vt {u:.6f} {v:.6f}\n")
            for nx, ny, nz in np.asarray(mesh.normals, dtype=np.float64):
                fh.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")
            for tri in np.asarray(mesh.indices, dtype=np.int64):
                a = int(tri[0]) + base
                b = int(tri[1]) + base
                c = int(tri[2]) + base
                if has_vt:
                    fh.write(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")
                else:
                    fh.write(f"f {a}//{a} {b}//{b} {c}//{c}\n")
            base += len(verts)
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
    base = 1
    for name, mesh in meshes.items():
        if len(mesh.vertices) == 0:
            continue
        fh.write(f"o {root_name}_{name}\n")
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        for x, y, z in verts:
            fh.write(f"v {x:.6f} {y:.6f} {z:.6f}\n")
        uvs = getattr(mesh, "uvs", None)
        has_vt = uvs is not None and len(uvs) == len(verts)
        if has_vt:
            for u, v in np.asarray(uvs, dtype=np.float64):
                fh.write(f"vt {u:.6f} {v:.6f}\n")
        for nx, ny, nz in np.asarray(mesh.normals, dtype=np.float64):
            fh.write(f"vn {nx:.6f} {ny:.6f} {nz:.6f}\n")
        for tri in np.asarray(mesh.indices, dtype=np.int64):
            a = int(tri[0]) + base
            b = int(tri[1]) + base
            c = int(tri[2]) + base
            if has_vt:
                fh.write(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")
            else:
                fh.write(f"f {a}//{a} {b}//{b} {c}//{c}\n")
        base += len(verts)


def ensure_parent_dir(path: str) -> str:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
    return path