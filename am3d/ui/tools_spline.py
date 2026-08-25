"""Spline control-point editing helpers (Model workspace, Qt-free).

The viewport overlays the selected object's CPs and calls into these
functions for hit-testing and for the guarded insert/remove rules.  All
edits mutate :class:`am3d.core.project.Spline` control-point lists in
object space; undo wrappers live in :mod:`am3d.ui.operators`.
"""

from __future__ import annotations

import numpy as np

from am3d.core.project import ControlPoint

HIT_TOLERANCE_PX = 8.0


def spline_world_points(obj, spline):
    """World-space CP positions of one spline (object transform applied)."""
    m = np.asarray(obj.transform, dtype=np.float64).reshape(4, 4)
    pts = spline.point_array()
    return pts @ m[:3, :3].T + m[:3, 3]


def cp_screen_positions(obj, camera, width, height):
    """Project every CP: ``{(spline_name, index): (x, y, valid)}``."""
    out = {}
    if width < 2 or height < 2:
        return out
    for sname, spline in obj.splines.items():
        world = spline_world_points(obj, spline)
        if len(world) == 0:
            continue
        xs, ys, valid = camera.world_to_screen(world, width, height)
        for i in range(len(world)):
            out[(sname, i)] = (xs[i], ys[i], bool(valid[i]))
    return out


def hit_cp(obj, camera, width, height, px, py, tol=HIT_TOLERANCE_PX):
    """Nearest CP under pixel (px, py): ``(spline_name, index)`` or None."""
    best, best_d = None, float(tol)
    for key, (x, y, valid) in cp_screen_positions(
            obj, camera, width, height).items():
        if not valid:
            continue
        d = float(np.hypot(x - px, y - py))
        if d < best_d:
            best, best_d = key, d
    return best


def cp_ray_plane(camera, width, height, px, py, world_point):
    """Intersect the pixel ray with the view-parallel plane at a CP."""
    origin, direction = camera.view_ray(px, py, width, height)
    normal = camera.forward
    denom = float(np.dot(direction, normal))
    if abs(denom) < 1e-9:
        return np.asarray(world_point, dtype=np.float64)
    t = float(np.dot(np.asarray(world_point, dtype=np.float64) - origin,
                     normal) / denom)
    return origin + t * direction


def world_to_object(obj, point):
    """Inverse of the object transform for a world-space point."""
    m = np.asarray(obj.transform, dtype=np.float64).reshape(4, 4)
    inv = np.linalg.inv(m)
    p = np.append(np.asarray(point, dtype=np.float64).reshape(3), 1.0)
    return (inv @ p)[:3]


def can_remove_cp(spline, index):
    """True when removing *index* keeps at least ``degree + 1`` points."""
    return 0 <= index < len(spline.cps) and len(spline.cps) > \
        spline.degree + 1


def insert_cp_after(spline, index):
    """Insert a midpoint CP after *index*; returns the new CP's index.

    After the last point of an open spline the new CP extends the spline
    by one segment; a closed spline wraps around to the first point.
    """
    n = len(spline.cps)
    if n == 0:
        spline.cps.append(ControlPoint(np.zeros(3), 1.0))
        return 0
    index = max(0, min(int(index), n - 1))
    if index == n - 1 and not spline.closed:
        prev = spline.cps[index].position
        step = (prev - spline.cps[index - 1].position) if n > 1 \
            else np.array([1.0, 0.0, 0.0])
        cp = ControlPoint(prev + step, 1.0)
    else:
        nxt = spline.cps[(index + 1) % n].position
        cp = ControlPoint((spline.cps[index].position + nxt) * 0.5, 1.0)
    spline.cps.insert(index + 1, cp)
    return index + 1


def remove_cp(spline, index):
    """Remove CP *index*; raises ValueError when the degree guard fails."""
    if not can_remove_cp(spline, index):
        raise ValueError(
            f"spline {spline.name!r} needs at least "
            f"{spline.degree + 1} control points (degree {spline.degree})")
    return spline.cps.pop(index)
