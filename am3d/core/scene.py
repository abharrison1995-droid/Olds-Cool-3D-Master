"""Single authoritative scene evaluation boundary.

Accepts Session, pose/action/frame, visibility, and tessellation settings,
and produces evaluated world-space geometry and material assignments without
mutating bind geometry or caching mutable state on project entities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from am3d.core.mathutil import transform_mesh_geometry
from am3d.core.project import Material
from am3d.core.rigging import deform_object, fk_pose
from am3d.renderer.tessellate import MeshData, tessellate_object


@dataclass
class EvaluatedScene:
    """Evaluated scene representation for viewport, rendering, and export."""

    meshes: dict[str, MeshData] = field(default_factory=dict)
    materials: dict[str, Material] = field(default_factory=dict)
    object_materials: dict[str, Optional[str]] = field(default_factory=dict)
    # {object_name: {patch_name: material_name}} for patches that override
    # the object's material (finding MAT-02). Only populated for patches
    # that actually carry an assignment, so an unassigned patch inherits the
    # object material exactly as before.
    patch_materials: dict[str, dict[str, str]] = field(default_factory=dict)
    bounds: tuple[np.ndarray, np.ndarray] = field(
        default_factory=lambda: (np.zeros(3), np.zeros(3)))


def evaluate_scene(
    session,
    *,
    action_name: str | None = None,
    time: float | None = None,
    pose: dict | None = None,
    visible_only: bool = True,
    nu: int = 16,
    nv: int = 16,
    apply_transforms: bool = True,
) -> EvaluatedScene:
    """Evaluate scene geometry, rigging deformation, and transforms.

    Parameters
    ----------
    session : Session
        The active scripting/document session.
    action_name : str or None
        Specific action to sample. If None and time is not None, uses session.active_action.
    time : float or None
        Timeline time in seconds to evaluate. If None, uses static/current session pose.
    pose : dict or None
        Optional explicit pose dictionary `{object_name: {bone_name: 3x3 or euler}}`.
    visible_only : bool
        Whether to filter out objects marked as visible=False (default True).
    nu, nv : int
        Tessellation grid resolution per patch (default 16).
    apply_transforms : bool
        Whether to bake object.transform into world-space vertices and normals (default True).

    Returns
    -------
    EvaluatedScene
        Evaluated meshes with world-space transforms, inverse transpose normals,
        reflection-corrected triangle winding, and material assignments.
    """
    proj = session.project
    meshes: dict[str, MeshData] = {}
    obj_materials: dict[str, Optional[str]] = {}
    patch_materials: dict[str, dict[str, str]] = {}

    obj_bone_worlds: dict[str, dict[str, np.ndarray]] = {}

    assignments = getattr(session, "action_assignments", {})
    actions_dict = getattr(session, "actions", {})

    if time is not None:
        for c_name in getattr(proj, "skeletons", {}):
            if action_name is not None:
                assigned = (assignments.get(c_name) == action_name
                            or (action_name not in assignments.values()
                                and len(proj.skeletons) == 1))
                char_act_name = action_name if assigned else None
            else:
                char_act_name = assignments.get(c_name) or getattr(session, "active_action", None)

            if char_act_name and char_act_name in actions_dict:
                act = actions_dict[char_act_name]
                sampled = act.sample(float(time))
                rig = proj.skeletons[c_name]
                bones = list(rig.values())
                local_transforms = {}
                from am3d.core.rigging import _rest_local
                from am3d.core.mathutil import compose_trs

                def _rot_to_matrix(r):
                    r_arr = np.asarray(r, dtype=np.float64).reshape(-1)
                    if r_arr.size == 3:
                        return compose_trs((0, 0, 0), np.rad2deg(r_arr), (1, 1, 1))[:3, :3]
                    elif r_arr.size == 9:
                        return r_arr.reshape(3, 3)
                    return np.eye(3)

                for b in bones:
                    if b.name in sampled:
                        props = sampled[b.name]
                        rest_m = _rest_local(b).copy()
                        rot = props.get("rotate")
                        if rot is not None:
                            rest_m[:3, :3] = rest_m[:3, :3] @ _rot_to_matrix(rot)
                        trans = props.get("translate")
                        if trans is not None:
                            rest_m[:3, 3] = rest_m[:3, 3] + np.asarray(trans, dtype=np.float64).reshape(3)
                        local_transforms[b.name] = rest_m
                obj_bone_worlds[c_name] = fk_pose(bones, local_transforms)

    for name, obj in proj.objects.items():
        if visible_only and not getattr(obj, "visible", True):
            continue

        obj_materials[name] = getattr(obj, "material", None)
        per_patch = {p.name: p.material for p in getattr(obj, "patches", [])
                     if getattr(p, "material", None)}
        if per_patch:
            patch_materials[name] = per_patch
        source = obj

        rig = getattr(proj, "skeletons", {}).get(name)
        if rig and any(getattr(b, "cp_weights", None) for b in rig.values()):
            bones = list(rig.values())
            rest = fk_pose(bones)
            if name in obj_bone_worlds:
                cur_bone_world = obj_bone_worlds[name]
            elif len(obj_bone_worlds) == 1:
                cur_bone_world = next(iter(obj_bone_worlds.values()))
            elif pose and name in pose:
                from am3d.core.rigging import _rest_local
                from am3d.core.mathutil import compose_trs
                locals_ = {}
                for b in bones:
                    if b.name in pose[name]:
                        p_val = np.asarray(pose[name][b.name], dtype=np.float64).reshape(-1)
                        if p_val.size == 3:
                            # Standard Euler XYZ degrees matching Session.pose_bone
                            r_mat = compose_trs((0, 0, 0), p_val, (1, 1, 1))[:3, :3]
                        else:
                            r_mat = p_val.reshape(3, 3)
                        rest_m = _rest_local(b).copy()
                        rest_m[:3, :3] = rest_m[:3, :3] @ r_mat
                        locals_[b.name] = rest_m
                cur_bone_world = fk_pose(bones, locals_)
            elif hasattr(session, "posed_transforms") and name in session.posed_transforms:
                cur_bone_world = session.posed_transforms[name]
            else:
                cur_bone_world = rest

            source = deform_object(obj, bones, cur_bone_world, rest)

        mesh = tessellate_object(source, nu=nu, nv=nv)

        if apply_transforms and len(mesh.vertices):
            m = np.asarray(getattr(obj, "transform", np.eye(4)), dtype=np.float64).reshape(4, 4)
            if not np.allclose(m, np.eye(4)):
                v, n, idx = transform_mesh_geometry(mesh.vertices, mesh.normals, mesh.indices, m)
                mesh.vertices = v
                if n is not None:
                    mesh.normals = n
                if idx is not None:
                    mesh.indices = idx

        mesh.name = name
        meshes[name] = mesh

    all_verts = [m.vertices for m in meshes.values() if len(m.vertices)]
    if all_verts:
        concat = np.concatenate(all_verts, axis=0)
        bounds = (concat.min(axis=0), concat.max(axis=0))
    else:
        bounds = (np.zeros(3), np.zeros(3))

    return EvaluatedScene(
        meshes=meshes,
        materials=dict(proj.materials),
        object_materials=obj_materials,
        patch_materials=patch_materials,
        bounds=bounds,
    )


def scene_material_colors(scene: EvaluatedScene) -> dict[str, tuple]:
    """``{object_name: (r, g, b, a)}`` for every object bound to a material.

    Single source of truth for the flat colour an OBJ/GLB export writes
    into its material record — derived from the same evaluated scene the
    viewport and recipe exporter already share, so every caller agrees on
    which objects are coloured and with what.
    """
    colors: dict[str, tuple] = {}
    for obj_name, mat_name in scene.object_materials.items():
        if not mat_name:
            continue
        mat = scene.materials.get(mat_name)
        if mat is None or mat.color is None or len(mat.color) < 3:
            continue
        r, g, b = float(mat.color[0]), float(mat.color[1]), float(mat.color[2])
        a = float(mat.color[3]) if len(mat.color) >= 4 else 1.0
        colors[obj_name] = (r, g, b, a)
    return colors


def _material_rgba(scene, mat_name):
    """``(r, g, b, a)`` for *mat_name*, or None when it has no usable colour."""
    mat = scene.materials.get(mat_name) if mat_name else None
    if mat is None or mat.color is None or len(mat.color) < 3:
        return None
    return (float(mat.color[0]), float(mat.color[1]), float(mat.color[2]),
            float(mat.color[3]) if len(mat.color) >= 4 else 1.0)


def scene_patch_material_colors(scene: EvaluatedScene) -> dict:
    """``{object_name: {patch_name: (r, g, b, a)}}`` for per-patch materials.

    Companion to :func:`scene_material_colors` for finding MAT-02: two
    differently coloured patches on one object must stay distinct through
    rendering and export instead of collapsing to the object's own colour.
    Patches with no assignment are absent here and inherit the object colour.
    """
    out: dict[str, dict[str, tuple]] = {}
    for obj_name, patches in (scene.patch_materials or {}).items():
        resolved = {}
        for patch_name, mat_name in patches.items():
            rgba = _material_rgba(scene, mat_name)
            if rgba is not None:
                resolved[patch_name] = rgba
        if resolved:
            out[obj_name] = resolved
    return out


def scene_triangle_colors(scene: EvaluatedScene, obj_name: str):
    """Per-triangle ``(N, 4)`` colours for *obj_name*, or None if uniform.

    Resolves each triangle through its patch material, falling back to the
    object material. Returns None when every triangle would get the same
    colour, so callers can keep their existing single-colour fast path.
    """
    mesh = scene.meshes.get(obj_name)
    if mesh is None or not len(mesh.indices):
        return None
    per_patch = scene_patch_material_colors(scene).get(obj_name)
    if not per_patch:
        return None
    base = _material_rgba(scene, scene.object_materials.get(obj_name)) \
        or (0.7, 0.7, 0.75, 1.0)
    colors = np.tile(np.asarray(base, dtype=np.float64), (len(mesh.indices), 1))
    for patch_name, tri_idx in mesh.group_triangles().items():
        rgba = per_patch.get(patch_name)
        if rgba is not None and len(tri_idx):
            colors[tri_idx] = rgba
    if np.allclose(colors, colors[0]):
        return None
    return colors
