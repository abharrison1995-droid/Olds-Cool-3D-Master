"""Headless tests for the viewport camera math and CPU ray picking.

These import no Qt modules, so they run anywhere numpy does.
"""

from __future__ import annotations

import numpy as np

from am3d.ui.camera import Camera, PRESETS
from am3d.ui.picking import pick_object, ray_triangles
from am3d.renderer.tessellate import MeshData


def _cube(name="cube", offset=(0, 0, 0)):
    """Unit cube mesh centered at *offset*, faces outward."""
    off = np.asarray(offset, dtype=np.float64)
    c = np.array([[x, y, z] for x in (-.5, .5) for y in (-.5, .5)
                  for z in (-.5, .5)], dtype=np.float64) + off
    tris = np.array([
        [0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6],   # -x? (double-sided)
        [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
        [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5],
    ], dtype=np.int64)
    return MeshData(c, tris, name=name)


# -- camera presets ---------------------------------------------------------

def test_preset_front_looks_down_minus_z():
    cam = Camera()
    cam.set_view("front")
    eye = cam.eye
    assert np.allclose(eye[:2], 0, atol=1e-9)
    assert eye[2] > 0                       # on +Z, looking back at origin
    assert np.allclose(cam.forward, [0, 0, -1], atol=1e-9)


def test_preset_side_looks_down_minus_x():
    cam = Camera()
    cam.set_view("side")
    assert np.allclose(cam.forward, [-1, 0, 0], atol=1e-9)


def test_preset_top_looks_down():
    cam = Camera()
    cam.set_view("top")
    assert np.allclose(cam.forward, [0, -1, 0], atol=1e-6)


def test_all_presets_reachable():
    for name in PRESETS:
        cam = Camera()
        cam.set_view(name)
        m = cam.view_matrix()
        assert np.all(np.isfinite(m))


def test_unknown_preset_raises():
    cam = Camera()
    try:
        cam.set_view("isometric")
    except ValueError:
        return
    raise AssertionError("expected ValueError")


# -- pan / orbit / zoom --------------------------------------------------------

def test_pan_translates_target_not_orientation():
    cam = Camera(yaw=30.0, pitch=10.0)
    m0 = cam.view_matrix()
    t0 = cam.target.copy()
    cam.pan(50, -20, viewport_height=480)
    m1 = cam.view_matrix()
    assert not np.allclose(cam.target, t0)          # target moved
    assert np.allclose(m0[:3, :3], m1[:3, :3])      # orientation unchanged
    assert not np.allclose(m0[:3, 3], m1[:3, 3])    # translation changed


def test_orbit_clamps_pitch():
    cam = Camera()
    cam.orbit(0, 500)
    assert cam.pitch <= 89.9
    cam.orbit(0, -1000)
    assert cam.pitch >= -89.9


def test_zoom_clamps_distance():
    cam = Camera(distance=3.5)
    cam.zoom(1e-6)
    assert cam.distance >= 0.1
    cam.zoom(1e9)
    assert cam.distance <= 200.0


# -- projection --------------------------------------------------------------

def test_projection_respects_aspect():
    cam = Camera()
    wide = cam.projection_matrix(aspect=2.0)
    square = cam.projection_matrix(aspect=1.0)
    # horizontal fov term scales as 1/aspect, vertical term unchanged
    assert np.isclose(wide[0, 0], square[0, 0] / 2.0)
    assert np.isclose(wide[1, 1], square[1, 1])


def test_world_to_screen_center_is_target():
    cam = Camera(yaw=25.0, pitch=30.0, target=[1.0, 2.0, 3.0])
    xs, ys, valid = cam.world_to_screen([cam.target], 800, 600)
    assert valid[0]
    assert np.isclose(xs[0], 400, atol=1e-6)
    assert np.isclose(ys[0], 300, atol=1e-6)


def test_view_ray_center_points_at_target():
    cam = Camera(yaw=15.0, pitch=25.0)
    origin, direction = cam.view_ray(320, 240, 640, 480)
    assert np.allclose(origin, cam.eye)
    assert np.allclose(direction, cam.forward, atol=1e-9)


# -- picking --------------------------------------------------------------------

def test_ray_triangles_hit_and_miss():
    mesh = _cube()
    # Ray from +Z toward origin hits the front face of the cube.
    t = ray_triangles([0, 0, 5], [0, 0, -1], mesh.vertices, mesh.indices)
    assert np.isfinite(t).any()
    assert np.isclose(t.min(), 4.5, atol=1e-9)
    # Ray pointing away misses everything.
    t = ray_triangles([0, 0, 5], [0, 0, 1], mesh.vertices, mesh.indices)
    assert not np.isfinite(t).any()


def test_pick_object_nearest_wins():
    near = _cube("near", offset=(0, 0, 0))
    far = _cube("far", offset=(0, 0, -5))
    meshes = {"far": far, "near": near}
    assert pick_object(meshes, [0, 0, 10], [0, 0, -1]) == "near"
    assert pick_object(meshes, [0, 0, 10], [0, 0, 1]) is None


def test_center_click_selects_corner_click_misses():
    """A camera looking at a cube: center pixel hits, far corner misses."""
    cam = Camera(yaw=0.0, pitch=0.0, distance=4.0, target=[0, 0, 0])
    mesh = _cube("hero")
    meshes = {"hero": mesh}
    W, H = 640, 480
    o, d = cam.view_ray(W / 2, H / 2, W, H)
    assert pick_object(meshes, o, d) == "hero"
    o, d = cam.view_ray(2, 2, W, H)
    assert pick_object(meshes, o, d) is None
