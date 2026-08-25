"""Headless tests for the Qt-free gizmo math (am3d.ui.gizmos)."""

from __future__ import annotations

import numpy as np

from am3d.ui import gizmos
from am3d.ui.camera import Camera

W, H = 640, 480


def _cam():
    return Camera(yaw=0.0, pitch=0.0, distance=4.0)


def test_handle_geometry_translate():
    handles = gizmos.handle_geometry(_cam(), W, H, (0, 0, 0), "translate")
    ids = {h for h, _, _ in handles}
    assert ids == {"tx", "ty", "tz"}
    # Front view: screen right is -X world (camera x-row), so the X
    # arrow points screen-left from the origin and +Y points up.
    geom = dict((h, polys) for h, _, polys in handles)
    cx, cy = W / 2, H / 2
    x_line = geom["tx"][0]
    assert np.allclose(x_line[0], (cx, cy), atol=2)
    assert x_line[1][0] < cx - 30
    y_line = geom["ty"][0]
    assert y_line[1][1] < cy - 30          # +Y is up on screen


def test_handle_geometry_scale_has_center():
    handles = gizmos.handle_geometry(_cam(), W, H, (0, 0, 0), "scale")
    ids = {h for h, _, _ in handles}
    assert {"sx", "sy", "sz", "sxyz"} <= ids


def test_handle_geometry_rotate_rings():
    handles = gizmos.handle_geometry(_cam(), W, H, (0, 0, 0), "rotate")
    ids = {h for h, _, _ in handles}
    assert ids == {"rx", "ry", "rz"}
    geom = dict((h, polys) for h, _, polys in handles)
    assert len(geom["ry"][0]) > 20         # sampled closed ring


def test_hit_test_axes():
    cam = _cam()
    # X arrow tip is right of centre; hitting it returns "tx".
    size = gizmos.gizmo_size_world(cam, (0, 0, 0), H)
    tip = gizmos.handle_geometry(cam, W, H, (0, 0,0), "translate",
                                 size=size)
    x_line = dict((h, p) for h, _, p in tip)["tx"][0]
    mx, my = (x_line[0] + x_line[1]) / 2   # middle of the X arrow
    assert gizmos.hit_test(cam, W, H, (0, 0, 0), "translate",
                           mx, my) == "tx"
    assert gizmos.hit_test(cam, W, H, (0, 0, 0), "translate",
                           5, 5) is None


def test_axis_drag_delta_moves_along_axis():
    cam = _cam()
    # Screen right is -X world at the front view, so dragging right
    # along the X arrow yields -X world motion, purely on that axis.
    delta = gizmos.axis_drag_delta(cam, W, H, (0, 0, 0),
                                   gizmos.AXES["x"], 40, 0)
    assert delta[0] < 0
    assert abs(delta[1]) < 1e-9 and abs(delta[2]) < 1e-9


def test_rotate_drag_angle_sweep():
    cam = _cam()
    # Quarter sweep around the screen centre about the Z (view) axis.
    angle = gizmos.rotate_drag_angle(cam, W, H, (0, 0, 0),
                                     gizmos.AXES["z"],
                                     (W / 2 + 100, H / 2),
                                     (W / 2, H / 2 - 100))
    assert abs(abs(angle) - np.pi / 2) < 1e-6


def test_scale_drag_factor():
    cam = _cam()
    f = gizmos.scale_drag_factor(cam, W, H, (0, 0, 0),
                                 gizmos.AXES["x"], 50, 0)
    assert f[0] < 1.0                      # screen right = -X: shrink
    assert f[1] == 1.0 and f[2] == 1.0
    fu = gizmos.scale_drag_factor(cam, W, H, (0, 0, 0),
                                  gizmos.AXES["x"], 50, 0, uniform=True)
    assert np.allclose(fu, fu[0])


def test_view_plane_delta():
    cam = _cam()
    d = gizmos.view_plane_delta(cam, H, (0, 0, 0), 50, 0)
    # Front view: screen right is -X world (camera x-row).
    assert d[0] < 0
    d = gizmos.view_plane_delta(cam, H, (0, 0, 0), 0, 50)
    assert d[1] < 0                        # dragging down moves -Y
