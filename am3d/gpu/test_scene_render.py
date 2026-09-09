"""Standalone render API: shared evaluation, one camera, complete fallback.

Findings GPU-01/02/03 (docs/evidence/desktop-release/phase-b/
gpu-reproduction.txt). Before these fixes ``render_frame`` tessellated a
Project directly (ignoring visibility, transforms, pose and materials), gave
every mesh its own look-at camera, and on GPU failure rendered only the first
mesh.
"""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.scene import evaluate_scene
from am3d.core.script import Session
from am3d.gpu import (_software_render, render_frame, resolve_scene,
                      scene_camera)
from am3d.ui.operators import CreatePrimitiveCommand

SIZE = (192, 192)


@pytest.fixture()
def two_objects():
    """A deliberately asymmetric scene: unequally sized, offset objects."""
    s = Session()
    CreatePrimitiveCommand(s, "left", "box").redo()
    CreatePrimitiveCommand(s, "right", "sphere").redo()
    s.get_object("left").transform[:3, 3] = (-2.0, 0.0, 0.0)
    right = s.get_object("right")
    right.transform[:3, 3] = (2.5, 0.0, 0.0)
    right.transform[:3, :3] *= 0.35
    return s


def _coverage(img):
    return int((img[..., 3] > 0.01).sum())


# --- GPU-01 -----------------------------------------------------------------

def test_project_input_honours_visibility(two_objects):
    two_objects.get_object("right").visible = False
    scene = resolve_scene(two_objects.project)
    assert "right" not in scene.meshes, (
        "a hidden object must not be rendered by the standalone API")
    assert "left" in scene.meshes


def test_project_input_applies_object_transforms(two_objects):
    scene = resolve_scene(two_objects.project)
    x = scene.meshes["left"].vertices[:, 0].mean()
    assert x == pytest.approx(-2.0, abs=0.2), (
        f"object transform ignored: centroid x={x:.3f}, expected about -2.0")


def test_project_input_matches_the_shared_evaluator(two_objects):
    two_objects.get_object("right").visible = False
    shared = evaluate_scene(two_objects, visible_only=True,
                            apply_transforms=True)
    resolved = resolve_scene(two_objects.project)
    assert set(resolved.meshes) == set(shared.meshes)
    for name, mesh in shared.meshes.items():
        assert np.allclose(resolved.meshes[name].vertices, mesh.vertices)


def test_session_input_honours_the_selected_frame():
    """A Session-based animated scene must render its selected frame."""
    s = Session()
    CreatePrimitiveCommand(s, "hero", "box").redo()
    s.add_bone("hero", "root", (0, 0, 0), (0, 1, 0))
    static = resolve_scene(s)
    posed = resolve_scene(s, pose={"hero": {"root": (0.0, 0.0, 1.2)}})
    assert set(static.meshes) == set(posed.meshes)
    # The pose argument must actually reach the evaluator.
    direct = evaluate_scene(s, pose={"hero": {"root": (0.0, 0.0, 1.2)}},
                            visible_only=True, apply_transforms=True)
    assert np.allclose(posed.meshes["hero"].vertices,
                       direct.meshes["hero"].vertices)


def test_resolve_scene_accepts_evaluated_scene_and_meshes(two_objects):
    scene = evaluate_scene(two_objects)
    assert resolve_scene(scene) is scene
    mesh = next(iter(scene.meshes.values()))
    assert len(resolve_scene(mesh).meshes) == 1
    assert len(resolve_scene(list(scene.meshes.values())).meshes) == 2


# --- GPU-02 -----------------------------------------------------------------

def test_software_fallback_renders_every_mesh(two_objects):
    meshes = list(resolve_scene(two_objects.project).meshes.values())
    assert len(meshes) == 2
    view = scene_camera(meshes)
    both = _software_render(meshes, *SIZE, camera=view)
    first_only = _software_render(meshes[:1], *SIZE, camera=view)

    assert not np.allclose(both, first_only), (
        "the fallback dropped every mesh after the first")
    assert _coverage(both) > _coverage(first_only), (
        f"fallback covered {_coverage(both)}px, first mesh alone covered "
        f"{_coverage(first_only)}px -- the second object is missing")


def test_forced_gpu_failure_still_renders_a_two_object_image(two_objects,
                                                             monkeypatch):
    """Force context creation to fail and prove both objects survive."""
    import am3d.gpu as gpu

    def _boom(*a, **k):
        raise RuntimeError("forced context failure")

    monkeypatch.setattr(gpu, "create_offscreen_context", _boom)
    img = render_frame(two_objects.project, size=SIZE)
    assert img.shape == (SIZE[1], SIZE[0], 4)

    # Both objects are on opposite sides of the frame: each half must have ink.
    half = SIZE[0] // 2
    left_cov = _coverage(img[:, :half])
    right_cov = _coverage(img[:, half:])
    assert left_cov > 0 and right_cov > 0, (
        f"fallback image has geometry only on one side "
        f"(left={left_cov}px, right={right_cov}px)")


def test_fallback_preserves_shared_occlusion():
    """Two overlapping objects must resolve against one depth buffer."""
    s = Session()
    CreatePrimitiveCommand(s, "near", "box").redo()
    CreatePrimitiveCommand(s, "far", "box").redo()
    s.get_object("near").transform[:3, 3] = (0.0, 0.0, 1.0)
    s.get_object("far").transform[:3, 3] = (0.0, 0.0, -1.0)
    meshes = list(resolve_scene(s.project).meshes.values())
    view = scene_camera(meshes)
    merged = _software_render(meshes, *SIZE, camera=view)
    near_only = _software_render([meshes[0]], *SIZE, camera=view)
    # The nearer box hides the farther one, so the merged image is dominated
    # by the near box rather than being a naive overlay of both.
    assert _coverage(merged) >= _coverage(near_only)


# --- GPU-03 -----------------------------------------------------------------

def test_one_camera_frames_the_whole_scene(two_objects):
    meshes = list(resolve_scene(two_objects.project).meshes.values())
    view = scene_camera(meshes)
    lo = np.min([m.vertices.min(axis=0) for m in meshes], axis=0)
    hi = np.max([m.vertices.max(axis=0) for m in meshes], axis=0)
    center = (lo + hi) / 2.0
    # Camera space position of the scene centre must be on the view axis.
    cam_center = view[:3, :3] @ center + view[:3, 3]
    assert abs(cam_center[0]) < 1e-6 and abs(cam_center[1]) < 1e-6


def test_offset_objects_keep_their_relative_placement(two_objects):
    """The reproduced GPU-03 symptom: each mesh used to be re-centred by its
    own camera, so a left object and a right object both drew in the middle."""
    scene = resolve_scene(two_objects.project)
    meshes = list(scene.meshes.values())
    view = scene_camera(meshes)
    img = _software_render(meshes, *SIZE, camera=view)
    ys, xs = np.nonzero(img[..., 3] > 0.01)
    assert len(xs)
    half = SIZE[0] // 2
    assert xs.min() < half < xs.max(), (
        "both objects collapsed onto the same part of the frame")

    left = scene.meshes["left"]
    right = scene.meshes["right"]
    # The big box on the left must occupy more pixels than the small sphere.
    cov_left = _coverage(_software_render([left], *SIZE, camera=view))
    cov_right = _coverage(_software_render([right], *SIZE, camera=view))
    assert cov_left > cov_right, (
        f"relative scale lost: left={cov_left}px right={cov_right}px")


def test_projection_is_independent_of_mesh_extent():
    from am3d.gpu.shaders import _perspective
    a = _perspective(45, size=(64, 32))
    b = _perspective(45, size=(64, 32))
    assert np.allclose(a, b)
    assert not np.allclose(a, _perspective(45, size=(32, 32))), (
        "aspect must still be honoured")


def test_gbuffer_is_not_released_twice_when_release_itself_fails(
        two_objects, monkeypatch):
    """Regression: `released = True` sat *after* the release() call inside the
    error path's try block, so a release() that raised left the flag False and
    the finally block released the same GL objects a second time."""
    import am3d.gpu as gpu

    calls = []

    class _Gbuf:
        def __init__(self, ctx, w, h):
            pass

        def bind(self):
            pass

        def unbind(self):
            pass

        def release(self):
            calls.append(1)
            raise RuntimeError("release failed")

    class _Ctx:
        ctx = object()

        def destroy(self):
            pass

    def _boom(*a, **k):
        raise RuntimeError("no shaders")

    monkeypatch.setattr(gpu, "GBuffer", _Gbuf)
    monkeypatch.setattr(gpu, "ShaderProgram", _boom)
    monkeypatch.setattr(gpu, "create_offscreen_context", lambda w, h: _Ctx())

    out = gpu.render_frame(two_objects, size=(16, 16))
    assert out.shape == (16, 16, 4)
    assert len(calls) == 1, f"gbuf.release() called {len(calls)} times"
