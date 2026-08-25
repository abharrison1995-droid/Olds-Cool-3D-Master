"""Transform-gizmo geometry and hit-testing (Qt-free, headless-testable).

The viewport draws the handles this module describes and feeds mouse
positions back in; everything here is pure numpy so tests can run without
a QApplication.

Handle ids:

* translate: ``"tx"``/``"ty"``/``"tz"``  (axis arrows)
* rotate:    ``"rx"``/``"ry"``/``"rz"``  (rings)
* scale:     ``"sx"``/``"sy"``/``"sz"``  (axis handles) + ``"sxyz"`` centre

Drag math conventions: mouse deltas are widget pixels (y down); results
are world-space values the caller applies to the object transform.
"""

from __future__ import annotations

import math

import numpy as np

AXES = {
    "x": np.array([1.0, 0.0, 0.0]),
    "y": np.array([0.0, 1.0, 0.0]),
    "z": np.array([0.0, 0.0, 1.0]),
}

MODES = ("translate", "rotate", "scale")

GIZMO_SIZE_PX = 70.0        # arrow / ring size on screen
HIT_TOLERANCE_PX = 8.0
_RING_SAMPLES = 48


def gizmo_size_world(camera, origin, height, size_px=GIZMO_SIZE_PX):
    """World-space handle length so the gizmo has constant screen size."""
    dist = max(float(np.linalg.norm(
        np.asarray(origin, dtype=np.float64) - camera.eye)), 1e-6)
    world_per_px = (2.0 * dist * math.tan(math.radians(camera.fov) / 2.0)
                    / max(float(height), 1.0))
    return world_per_px * size_px


def _project(camera, width, height, points):
    """Camera projection helper: returns (N,2) screen pts + valid mask."""
    xs, ys, valid = camera.world_to_screen(points, width, height)
    return np.stack([xs, ys], axis=1), valid


def handle_geometry(camera, width, height, origin, mode, size=None):
    """Screen-space geometry for one gizmo mode.

    Returns a list of ``(handle_id, kind, payload)`` where ``payload``
    is a list of polyline point arrays (2D pixel coordinates) — arrows
    are 2-point lines, rings a closed polyline, the centre handle a
    single point.  Returns [] when the widget is too small.
    """
    origin = np.asarray(origin, dtype=np.float64).reshape(3)
    if width < 2 or height < 2:
        return []
    if size is None:
        size = gizmo_size_world(camera, origin, height)
    out = []
    if mode == "translate" or mode == "scale":
        for key, axis in AXES.items():
            pts, valid = _project(camera, width, height,
                                  [origin, origin + axis * size])
            if not valid.all():
                continue
            out.append((f"{'t' if mode == 'translate' else 's'}{key}",
                        "axis", [pts]))
        if mode == "scale":
            c, valid = _project(camera, width, height, [origin])
            if valid[0]:
                out.append(("sxyz", "center", [c]))
    elif mode == "rotate":
        t = np.linspace(0.0, 2.0 * math.pi, _RING_SAMPLES + 1)
        for key, axis in AXES.items():
            u = np.cross(axis, np.array([0.0, 1.0, 0.0]))
            if np.linalg.norm(u) < 1e-6:
                u = np.cross(axis, np.array([1.0, 0.0, 0.0]))
            u = u / np.linalg.norm(u)
            v = np.cross(axis, u)
            ring = origin + size * (np.outer(np.cos(t), u)
                                    + np.outer(np.sin(t), v))
            pts, valid = _project(camera, width, height, ring)
            if valid.any():
                out.append((f"r{key}", "ring", [pts]))
    return out


def hit_test(camera, width, height, origin, mode, px, py,
             tol=HIT_TOLERANCE_PX, size=None):
    """Return the handle id under pixel (px, py), or None."""
    p = np.array([float(px), float(py)])
    best, best_d = None, float(tol)
    for handle_id, kind, polylines in handle_geometry(
            camera, width, height, origin, mode, size):
        for pts in polylines:
            if kind == "center":
                d = float(np.linalg.norm(pts[0] - p))
            elif kind == "ring":
                d = float(np.min(np.linalg.norm(pts - p, axis=1)))
            else:                                # axis: point-to-segment
                a, b = pts[0], pts[1]
                ab = b - a
                denom = float(np.dot(ab, ab))
                t = 0.0 if denom < 1e-12 else float(
                    np.clip(np.dot(p - a, ab) / denom, 0.0, 1.0))
                d = float(np.linalg.norm(p - (a + t * ab)))
            if d < best_d:
                best, best_d = handle_id, d
    return best


def axis_drag_delta(camera, width, height, origin, axis, dx, dy,
                    size=None):
    """World-space translation along *axis* for a pixel drag (dx, dy).

    The unit axis is projected to screen; the pixel delta is projected
    onto it and converted back to world units.
    """
    origin = np.asarray(origin, dtype=np.float64).reshape(3)
    axis = np.asarray(axis, dtype=np.float64).reshape(3)
    if size is None:
        size = gizmo_size_world(camera, origin, height)
    pts, valid = _project(camera, width, height, [origin, origin + axis])
    if not valid.all():
        return np.zeros(3)
    screen_axis = pts[1] - pts[0]
    denom = float(np.dot(screen_axis, screen_axis))
    if denom < 1e-12:
        return np.zeros(3)
    # pixels of motion along the projected axis -> fraction of unit axis
    t = float(np.dot(np.array([dx, dy]), screen_axis) / denom)
    return t * axis


def rotate_drag_angle(camera, width, height, origin, axis,
                      start_xy, cur_xy):
    """Signed rotation angle (radians) about *axis* for a ring drag.

    Measured as the angle swept around the gizmo's screen centre; the
    sign is corrected for whether the axis points toward or away from
    the viewer.
    """
    origin = np.asarray(origin, dtype=np.float64).reshape(3)
    axis = np.asarray(axis, dtype=np.float64).reshape(3)
    centre, valid = _project(camera, width, height, [origin])
    if not valid[0]:
        return 0.0
    a0 = np.asarray(start_xy, dtype=np.float64) - centre[0]
    a1 = np.asarray(cur_xy, dtype=np.float64) - centre[0]
    if np.linalg.norm(a0) < 1e-6 or np.linalg.norm(a1) < 1e-6:
        return 0.0
    angle = math.atan2(a1[1], a1[0]) - math.atan2(a0[1], a0[0])
    # Screen y is down, so positive sweep is clockwise on screen; a
    # clockwise drag should rotate positively about an axis facing away.
    facing = float(np.dot(axis, camera.forward))
    sign = 1.0 if facing > 0.0 else -1.0
    return -sign * angle


def scale_drag_factor(camera, width, height, origin, axis, dx, dy,
                      uniform=False, size=None):
    """Per-axis (or uniform) scale factor for a pixel drag."""
    origin = np.asarray(origin, dtype=np.float64).reshape(3)
    if uniform:
        return np.array([1.0, 1.0, 1.0]) * (1.0 + dx * 0.01)
    axis = np.asarray(axis, dtype=np.float64).reshape(3)
    delta = axis_drag_delta(camera, width, height, origin, axis,
                            dx, dy, size)
    factor = 1.0 + float(np.dot(delta, axis))
    out = np.ones(3)
    out[np.argmax(np.abs(axis))] = factor
    return out


def view_plane_delta(camera, height, origin, dx, dy):
    """World delta for a pixel drag in the view plane at *origin* depth."""
    dist = max(float(np.linalg.norm(
        np.asarray(origin, dtype=np.float64) - camera.eye)), 1e-6)
    scale = (2.0 * dist * math.tan(math.radians(camera.fov) / 2.0)
             / max(float(height), 1.0))
    m = camera.view_matrix()
    right, up = m[0, :3], m[1, :3]
    return right * (dx * scale) + up * (-dy * scale)
