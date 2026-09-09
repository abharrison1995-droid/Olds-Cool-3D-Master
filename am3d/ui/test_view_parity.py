"""Software-render / picking parity (finding VIEW-01).

The software toon path used to feed the orthographic, auto-fitting sprite
rasterizer, whose screen mapping is a function of the mesh's bounding box.
Picking rays, CP handles and gizmos use the perspective camera. In software
mode a box therefore drew about 4x smaller than where a click on it resolved,
so clicking the visible object selected nothing. These tests hold the render
and the interaction model to one projection.
"""

from __future__ import annotations

import sys

import numpy as np
import pytest

BBOX_TOL = 4.0      # px: ink dilation and supersampling widen the silhouette


def _qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture()
def software_viewport():
    _qapp()
    from am3d.ui.app import MainWindow
    from am3d.ui.operators import CreatePrimitiveCommand
    win = MainWindow()
    win.resize(800, 600)
    win.show_editor()
    win.doc_ctrl.session.project.objects.clear()
    win.push_command(CreatePrimitiveCommand(win.doc_ctrl.session, "box", "box"))
    vp = win.viewport
    vp.resize(800, 600)
    vp.force_software = True       # exercise the software path specifically
    try:
        yield win, vp
    finally:
        vp._timer.stop()
        win.close()


def _silhouette_and_projection(vp):
    vp.refresh()
    vp._render()
    frame = vp._frame
    assert frame is not None, "software render produced no frame"
    H, W = frame.shape[:2]
    ys, xs = np.nonzero(frame[..., 3] > 0.01)
    assert len(xs), "software render drew nothing"
    px, py, valid = vp.camera.world_to_screen(vp._merged.vertices, W, H)
    # Clip like the canvas does, so an object running off-screen is not
    # mistaken for a projection disagreement.
    px = np.clip(px[valid], 0, W - 1)
    py = np.clip(py[valid], 0, H - 1)
    return (xs, ys), (px, py)


CAMERA_MOVES = [
    ("default", lambda cam: None),
    ("orbit", lambda cam: cam.orbit(35.0, -20.0)),
    ("pan", lambda cam: cam.pan(60.0, -40.0)),
    ("zoom_in", lambda cam: cam.zoom(0.55)),
    ("zoom_out", lambda cam: cam.zoom(2.2)),
]


@pytest.mark.parametrize("label,move", CAMERA_MOVES,
                         ids=[m[0] for m in CAMERA_MOVES])
def test_software_silhouette_matches_the_picking_projection(
        software_viewport, label, move):
    _win, vp = software_viewport
    move(vp.camera)
    (xs, ys), (px, py) = _silhouette_and_projection(vp)
    deltas = {
        "left": abs(px.min() - xs.min()), "right": abs(px.max() - xs.max()),
        "top": abs(py.min() - ys.min()), "bottom": abs(py.max() - ys.max()),
    }
    worst = max(deltas.values())
    assert worst <= BBOX_TOL, (
        f"{label}: rendered silhouette and camera projection disagree by "
        f"{worst:.1f}px ({deltas}) -- overlays and picking would be drawn "
        f"away from the visible surface")


@pytest.mark.parametrize("label,move", CAMERA_MOVES,
                         ids=[m[0] for m in CAMERA_MOVES])
def test_clicking_the_visible_object_selects_it_in_software_mode(
        software_viewport, label, move):
    _win, vp = software_viewport
    move(vp.camera)
    (xs, ys), _ = _silhouette_and_projection(vp)
    cx, cy = int(round(xs.mean())), int(round(ys.mean()))

    vp.set_selected(None)
    vp._pick(cx, cy)
    picked = vp._selected
    name = picked[0] if isinstance(picked, tuple) else picked
    assert name == "box", (
        f"{label}: clicking ({cx},{cy}), the centre of the object the user "
        f"can actually see, picked {picked!r}")


def test_clicking_empty_canvas_selects_nothing(software_viewport):
    _win, vp = software_viewport
    _silhouette_and_projection(vp)
    vp.set_selected("box")
    vp._pick(4, 4)
    assert vp._selected is None


def test_toon_render_camera_uses_the_supplied_camera_projection():
    """Unit-level: the frame size and placement follow the camera, not the
    mesh bounding box."""
    from am3d.renderer.tessellate import MeshData
    from am3d.renderer.toon import toon_render_camera
    from am3d.ui.camera import Camera

    verts = np.array([[-1.0, -1, 0], [1, -1, 0], [0, 1, 0]])
    mesh = MeshData(verts, np.array([[0, 1, 2]]),
                    normals=np.tile([0.0, 0, 1], (3, 1)))
    cam = Camera()
    frame = toon_render_camera(mesh, cam, 320, 200, supersample=1)
    assert frame.shape == (200, 320, 4), "output must be widget-sized, not square"

    ys, xs = np.nonzero(frame[..., 3] > 0.01)
    px, py, valid = cam.world_to_screen(verts, 320, 200)
    assert abs(xs.min() - px[valid].min()) <= BBOX_TOL
    assert abs(ys.min() - py[valid].min()) <= BBOX_TOL


def test_toon_render_camera_handles_empty_geometry():
    from am3d.renderer.tessellate import MeshData
    from am3d.renderer.toon import toon_render_camera
    from am3d.ui.camera import Camera
    empty = MeshData(np.zeros((0, 3)), np.zeros((0, 3), dtype=int),
                     normals=np.zeros((0, 3)))
    frame = toon_render_camera(empty, Camera(), 64, 48)
    assert frame.shape == (48, 64, 4)
    assert not frame[..., 3].any()
