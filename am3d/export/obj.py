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


def _patch_material_name(obj_name: str, patch_name: str) -> str:
    """MTL material name for one patch of one object (finding MAT-02)."""
    return f"mat_{obj_name}__{patch_name}"


def _write_meshes(fh, meshes: dict, name_prefix: str = "",
                  materials: dict | None = None, mtl_filename: str | None = None,
                  patch_materials: dict | None = None) -> None:
    """Write ``{name: MeshData}`` as OBJ groups into an open text handle.

    ``v``, ``vt`` and ``vn`` occupy *independent* 1-based index spaces in the
    OBJ format, so each is counted separately. A shared counter is only
    correct while every mesh carries all three channels; the moment one mesh
    lacks UVs (or its normals do not match its vertex count) the channels
    drift apart and the emitted faces reference elements that were never
    written.

    Parameters
    ----------
    materials:
        Optional ``{object_name: (r, g, b, a)}`` flat-colour overrides. When
        supplied the OBJ file references a MTL sidecar and emits ``usemtl``
        directives.
    mtl_filename:
        Base filename (no directory) of the MTL sidecar to reference in the
        ``mtllib`` directive.  Required when *materials* is not empty.
    patch_materials:
        Optional ``{object_name: {patch_name: (r, g, b, a)}}``. A patch may
        carry its own material, so one object is not necessarily one material
        group; when present, this object's faces are emitted as several
        ``usemtl`` groups instead of one (finding MAT-02). Patches without an
        entry fall back to the object's own material.
    """
    # Per-patch materials alone are enough to need the sidecar: without this
    # the file emitted usemtl directives naming materials no reader could
    # resolve, so an independent reader saw untextured default geometry.
    if (materials or patch_materials) and mtl_filename:
        fh.write(f"mtllib {mtl_filename}\n")

    v_base = vt_base = vn_base = 1
    for name, mesh in meshes.items():
        verts = np.asarray(mesh.vertices, dtype=np.float64)
        if len(verts) == 0:
            continue
        fh.write(f"o {name_prefix}{name}\n")

        # Emit usemtl directive if we have a material for this object
        mat_name = None
        if materials and name in materials:
            mat_name = f"mat_{name}"
            fh.write(f"usemtl {mat_name}\n")

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

        def _write_face(tri):
            refs = []
            for corner in (int(tri[0]), int(tri[1]), int(tri[2])):
                refs.append(_face_token(
                    corner + v_base,
                    corner + vt_base if has_vt else None,
                    corner + vn_base if has_vn else None))
            fh.write("f " + " ".join(refs) + "\n")

        tris = np.asarray(mesh.indices, dtype=np.int64)
        obj_patches = (patch_materials or {}).get(name)
        if obj_patches:
            # Faces are grouped by source patch so two differently coloured
            # patches on one object stay distinct in the OBJ (finding MAT-02).
            # Groups are emitted in first-triangle order, keeping face order
            # stable and readable in an external viewer.
            groups = mesh.group_triangles()
            for patch_name, idx in sorted(
                    groups.items(),
                    key=lambda kv: int(kv[1][0]) if len(kv[1]) else -1):
                if not len(idx):
                    continue
                if patch_name in obj_patches:
                    fh.write(f"usemtl {_patch_material_name(name, patch_name)}\n")
                elif mat_name:
                    fh.write(f"usemtl {mat_name}\n")
                for tri in tris[idx]:
                    _write_face(tri)
        else:
            for tri in tris:
                _write_face(tri)

        v_base += len(verts)
        if has_vt:
            vt_base += len(verts)
        if has_vn:
            vn_base += len(verts)


def _write_mtl(path: str, materials: dict,
               patch_materials: dict | None = None) -> None:
    """Write a .mtl sidecar for object and per-patch ``(r,g,b,a)`` colours."""

    def _emit(fh, mtl_name, rgba):
        r, g, b = float(rgba[0]), float(rgba[1]), float(rgba[2])
        fh.write(f"\nnewmtl {mtl_name}\n")
        fh.write(f"Kd {r:.6f} {g:.6f} {b:.6f}\n")
        fh.write("Ka 0.000000 0.000000 0.000000\n")
        fh.write("Ks 0.000000 0.000000 0.000000\n")
        if len(rgba) >= 4:
            fh.write(f"d {float(rgba[3]):.6f}\n")

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# MTL exported by 3D MASTER:2005\n")
        for name, rgba in (materials or {}).items():
            _emit(fh, f"mat_{name}", rgba)
        for obj_name, patches in (patch_materials or {}).items():
            for patch_name, rgba in patches.items():
                _emit(fh, _patch_material_name(obj_name, patch_name), rgba)


def write_obj(path: str, meshes: dict, *,
              materials: dict | None = None,
              patch_materials: dict | None = None) -> str:
    """Write ``{name: MeshData}`` to *path* as a single OBJ file.

    Parameters
    ----------
    materials:
        Optional ``{object_name: (r, g, b, a)}`` flat-colour map. When
        provided, a ``.mtl`` sidecar is written alongside the OBJ and
        referenced via ``mtllib``.
    patch_materials:
        Optional ``{object_name: {patch_name: (r, g, b, a)}}`` per-patch
        colours; see :func:`_write_meshes` (finding MAT-02).
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    mtl_filename = None
    if materials or patch_materials:
        stem = os.path.splitext(os.path.basename(path))[0]
        mtl_filename = stem + ".mtl"
        mtl_path = os.path.join(os.path.dirname(os.path.abspath(path)), mtl_filename)
        _write_mtl(mtl_path, materials, patch_materials)

    with open(path, "w", encoding="utf-8") as fh:
        fh.write("# Exported by 3D MASTER:2005\n")
        _write_meshes(fh, meshes, materials=materials,
                      mtl_filename=mtl_filename,
                      patch_materials=patch_materials)
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
