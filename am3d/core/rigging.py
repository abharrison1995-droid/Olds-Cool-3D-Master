"""Skeletal rigging: FK, 2-bone IK, and SmartSkins deformation.

Implements the Segment-Mode mechanics:

* Forward kinematics through a bone hierarchy.
* An analytic 2-bone IK solver for limbs.
* **SmartSkins**: spline control-point skinning that *corrects* the collapse
  that plagues linear-blend skinning.  When a joint bends, control points
  near the bend are pushed back out along a per-point "bulge" direction so
  the underlying splines preserve volume instead of caving in.

Bones are expected to be :class:`~am3d.core.project.Bone` instances and
splines use :class:`~am3d.core.project.Spline` control points.
"""

from __future__ import annotations

import numpy as np

from .mathutil import normalize


def _rot_axis_angle(axis, angle):
    """Rotation matrix (Rodrigues) about a unit *axis* by *angle* radians."""
    x, y, z = axis
    c, s = np.cos(angle), np.sin(angle)
    C = 1.0 - c
    return np.array([
        [x * x * C + c, x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, y * y * C + c, y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, z * z * C + c],
    ])


def _bone_world(bone, world):
    if bone.parent and bone.parent in world:
        return world[bone.parent]
    return np.eye(4)


def _rest_local(bone):
    """A bone's rest local transform: translate to head, orient to tail."""
    d = bone.tail - bone.head
    length = float(np.linalg.norm(d)) or 1.0
    forward = d / length
    ref = np.array([0.0, 1.0, 0.0])
    if abs(np.dot(forward, ref)) > 0.99:
        ref = np.array([1.0, 0.0, 0.0])
    right = normalize(np.cross(ref, forward))
    up = np.cross(forward, right)
    m = np.eye(4)
    m[:3, 0] = right
    m[:3, 1] = up
    m[:3, 2] = forward
    m[:3, 3] = bone.head
    return m


def rest_local_transform(bone):
    """Public alias for a bone's rest local transform (see fk_pose)."""
    return _rest_local(bone)


def fk_pose(bones, local_transforms=None):
    """Compute world matrices for a bone list (parents before children).

    ``local_transforms`` : optional dict bone.name -> 4x4 local matrix used
    in place of the bone's rest transform.  Returns ``dict name -> 4x4``.
    """
    by_name = {b.name: b for b in bones}
    world = {}
    order = []
    visited = set()

    def visit(name):
        if name in visited:
            return
        visited.add(name)
        b = by_name[name]
        if b.parent and b.parent in by_name:
            visit(b.parent)
        order.append(name)

    for b in bones:
        visit(b.name)

    for name in order:
        b = by_name[name]
        if local_transforms and name in local_transforms:
            local = np.asarray(local_transforms[name], dtype=np.float64)
        else:
            local = _rest_local(b)
        parent_world = _bone_world(b, world)
        world[name] = parent_world @ local
    return world


def ik_two_bone(root_pos, mid_pos, tip_pos, target_pos, bend=None):
    """Analytic two-bone IK.  Returns ``(mid_pos_out, tip_pos_out)``.

    Solves in the plane defined by the origin → target, keeping the two bone
    lengths constant.  ``bend`` (+1/-1) selects the elbow side; when None it
    preserves the original bend direction.
    """
    root_pos = np.asarray(root_pos, dtype=np.float64)
    a = np.asarray(mid_pos, dtype=np.float64) - root_pos
    bvec = np.asarray(tip_pos, dtype=np.float64) - np.asarray(mid_pos, dtype=np.float64)
    l1 = float(np.linalg.norm(a))
    l2 = float(np.linalg.norm(bvec))
    if l1 < 1e-12 or l2 < 1e-12:
        return np.array(mid_pos, dtype=np.float64), np.array(tip_pos, dtype=np.float64)

    target = np.asarray(target_pos, dtype=np.float64) - root_pos
    d = float(np.linalg.norm(target))
    d = min(d, l1 + l2 - 1e-9)
    d = max(d, abs(l1 - l2) + 1e-9)

    cos_elbow = (l1 * l1 + l2 * l2 - d * d) / (2 * l1 * l2)
    cos_hinge = (l1 * l1 + d * d - l2 * l2) / (2 * l1 * d)
    elbow_angle = float(np.arccos(np.clip(cos_elbow, -1.0, 1.0)))
    hinge_angle = float(np.arccos(np.clip(cos_hinge, -1.0, 1.0)))

    forward = normalize(target)
    if bend is None:
        normal = np.cross(a, bvec)
        if np.linalg.norm(normal) < 1e-9:
            normal = np.array([0.0, 0.0, 1.0])
        normal = normalize(normal)
        sign = 1.0 if np.dot(normal, np.cross(a, forward)) >= 0 else -1.0
    else:
        sign = 1.0 if bend >= 0 else -1.0
        normal = np.cross(np.array([0.0, 1.0, 0.0]), forward)
        if np.linalg.norm(normal) < 1e-9:
            normal = np.array([0.0, 0.0, 1.0])
        normal = normalize(normal)

    cos_a, sin_a = np.cos(sign * hinge_angle), np.sin(sign * hinge_angle)
    rx, ry, rz = normal
    C = 1.0 - cos_a
    R = np.array([
        [rx * rx * C + cos_a, rx * ry * C - rz * sin_a, rx * rz * C + ry * sin_a],
        [ry * rx * C + rz * sin_a, ry * ry * C + cos_a, ry * rz * C - rx * sin_a],
        [rz * rx * C - ry * sin_a, rz * ry * C + rx * sin_a, rz * rz * C + cos_a],
    ])
    mid_dir = R @ forward
    mid = root_pos + l1 * mid_dir

    # The distal bone is the mirror of the proximal across the plane: it sits
    # at angle -sign*hinge while the proximal sits at +sign*hinge.  So rotate
    # the proximal by -2*sign*hinge about the plane normal to reach it.
    rot2 = _rot_axis_angle(normal, -2.0 * sign * hinge_angle)
    tdir = rot2 @ mid_dir
    tip = mid + l2 * tdir
    return np.asarray(mid, dtype=np.float64), np.asarray(tip, dtype=np.float64)


def smartskin_deform(cp_pos, weights, bone_transforms, rest_transforms,
                     bulge_strength=0.5):
    """Deform a control point via dual influence with SmartSkins correction.

    ``weights`` : dict bone_name -> weight (sum ~1).
    ``bone_transforms`` : dict name -> world 4x4 (animated pose).
    ``rest_transforms`` : dict name -> world 4x4 (rest pose).

    Returns a corrected world-space position.  Linear blending is applied
    first, then, for the two dominant bones, an outward "bulge" correction
    proportional to how far the joint bent is added to counter collapse.
    """
    pos = np.asarray(cp_pos, dtype=np.float64).reshape(3)
    if not weights:
        return pos.copy()

    items = sorted(weights.items(), key=lambda kv: -abs(kv[1]))[:2]
    w0 = items[0][1]
    w1 = items[1][1] if len(items) >= 2 else 0.0

    def apply(tm, p):
        return tm[:3, :3] @ p + tm[:3, 3]

    acc = np.zeros(3)
    total = 0.0
    for name, w in items:
        if name not in bone_transforms:
            continue
        # Linear-blend skinning applies the *delta* from rest to pose,
        # T_cur @ inv(T_rest), to the rest-space position.
        if name in rest_transforms:
            delta = bone_transforms[name] @ np.linalg.inv(rest_transforms[name])
        else:
            delta = bone_transforms[name]
        acc = acc + w * apply(delta, pos)
        total += abs(w)
    if total < 1e-9:
        return pos.copy()
    result = acc / total

    # SmartSkins correction for the top-two-bone joint.
    if len(items) >= 2 and abs(w1) > 1e-9:
        n1, n2 = items[0][0], items[1][0]
        if n1 in bone_transforms and n2 in bone_transforms and \
           n1 in rest_transforms and n2 in rest_transforms:
            b_rest = rest_transforms[n1][:3, 2]
            b_cur = bone_transforms[n1][:3, 2]
            nrm = (float(np.linalg.norm(b_rest)) * float(np.linalg.norm(b_cur)))
            cos_angle = float(np.dot(b_rest, b_cur)) / nrm if nrm > 1e-9 else 1.0
            bend = 1.0 - abs(float(np.clip(cos_angle, -1.0, 1.0)))
            joint_world = apply(rest_transforms[n1], np.zeros(3))
            outward = normalize(pos - joint_world)
            if np.linalg.norm(outward) > 1e-9:
                result = result + bulge_strength * bend * abs(w1) * outward * 0.35
    return np.asarray(result, dtype=np.float64)

# -- skin weights ------------------------------------------------------------
def object_cp_positions(obj):
    """Flatten an object's control points into one (N, 3) array.

    The canonical CP order — patch interiors first (C-order flattened),
    then spline CPs in spline-dict order — is what ``Bone.cp_weights``
    indexes into.  Returns ``(positions, writer)`` where ``writer(obj,
    positions)`` writes a deformed array back into a *copy* of ``obj``.
    """
    positions = []
    spans = []                       # (kind, ref, slice)
    for patch in obj.patches:
        if patch.interior is None:
            continue
        net = np.asarray(patch.interior, dtype=np.float64)
        n = int(net.size // 3)
        spans.append(("patch", patch, slice(len(positions),
                                            len(positions) + n)))
        positions.extend(net.reshape(-1, 3))
    for spline in obj.splines.values():
        spans.append(("spline", spline, slice(len(positions),
                                              len(positions) + len(spline))))
        positions.extend(spline.point_array())

    def writer(target, deformed):
        deformed = np.asarray(deformed, dtype=np.float64)
        for kind, ref, span in spans:
            block = deformed[span]
            if kind == "patch":
                ref.interior = block.reshape(ref.interior.shape)
            else:
                for cp, pos in zip(ref.cps, block):
                    cp.position = np.asarray(pos, dtype=np.float64)
        return target

    return (np.asarray(positions, dtype=np.float64).reshape(-1, 3), writer)


def deform_object(obj, bones, bone_transforms, rest_transforms,
                  bulge_strength=0.5):
    """Return a deformed *copy* of ``obj`` skinned by ``Bone.cp_weights``.

    ``bones`` : the object's skeleton (``.name`` / ``.cp_weights``).
    ``bone_transforms`` / ``rest_transforms`` : object-space 4x4 worlds,
    as produced by :func:`fk_pose`.  Control points with no weights are
    left untouched; when no bone carries any weight the object is
    returned unchanged (same object, no copy).
    """
    if not any(getattr(b, "cp_weights", None) for b in bones):
        return obj
    import copy as _copy
    out = _copy.copy(obj)
    out.patches = [_copy.copy(p) for p in obj.patches]
    out.splines = {name: _copy.copy(s) for name, s in obj.splines.items()}
    for s in out.splines.values():
        s.cps = [_copy.copy(cp) for cp in s.cps]

    # Build the position map on the copy so the writer cannot touch ``obj``.
    positions, writer = object_cp_positions(out)
    if len(positions) == 0:
        return out

    by_bone = {}
    for b in bones:
        for cp_index, w in getattr(b, "cp_weights", {}).items():
            idx = int(cp_index)
            if 0 <= idx < len(positions):
                by_bone.setdefault(idx, {})[b.name] = float(w)

    deformed = positions.copy()
    for idx, weights in by_bone.items():
        deformed[idx] = smartskin_deform(
            positions[idx], weights, bone_transforms, rest_transforms,
            bulge_strength=bulge_strength)
    return writer(out, deformed)
