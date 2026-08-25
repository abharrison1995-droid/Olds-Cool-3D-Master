"""Bone posing helpers for the Rig workspace (Qt-free).

Wraps :meth:`am3d.core.script.Session.apply_pose` output so the viewport
can draw bones (rest or posed) and drag a rotate gizmo on the selected
bone.  Pose rotations are stored on the session via
:meth:`~am3d.core.script.Session.pose_bone` and composed with each
bone's rest local transform before FK.
"""

from __future__ import annotations

import numpy as np

from am3d.core.mathutil import rot_matrix


def bone_world_transforms(session, object_name):
    """``{bone_name: 4x4 world}`` — posed when a pose exists, else rest.

    Object-space, including the object transform for display.
    """
    posed = session.apply_pose(object_name).get(object_name)
    if posed is None:
        return {}
    obj = session.project.objects.get(object_name)
    m = (np.asarray(obj.transform, dtype=np.float64).reshape(4, 4)
         if obj is not None else np.eye(4))
    return {name: m @ t for name, t in posed.items()}


def bone_endpoints(session, object_name):
    """``{bone_name: (head_world, tail_world)}`` for drawing."""
    bones = {b.name: b for b in session.get_bones(object_name)}
    out = {}
    for name, world in bone_world_transforms(session, object_name).items():
        length = float(np.linalg.norm(bones[name].tail - bones[name].head))
        head = world[:3, 3]
        tail = world[:3, :3] @ np.array([0.0, 0.0, length]) + head
        out[name] = (head, tail)
    return out


def compose_pose(session, object_name, bone_name, axis, angle):
    """Rotate bone *bone_name*'s pose by *angle* radians about world *axis*.

    Returns the new 3x3 pose rotation (also stored on the session).
    """
    current = session.poses.get(object_name, {}).get(bone_name)
    base = np.eye(3) if current is None else current
    rot = rot_matrix(axis, angle) @ base
    session.pose_bone(object_name, bone_name, rot)
    session.apply_pose(object_name)
    return rot
