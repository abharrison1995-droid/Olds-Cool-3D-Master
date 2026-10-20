"""Material-aware shared-camera software preview used by Phase 4 checks."""

from __future__ import annotations

import numpy as np
import pytest

from am3d.ai.checks import _render_material_preview
from am3d.core.project import Material
from am3d.core.scene import EvaluatedScene
from am3d.gpu import scene_camera
from am3d.renderer.tessellate import MeshData


def _quad(name, x0, x1, z):
    vertices = np.array([[x0, -0.55, z], [x1, -0.55, z],
                         [x1, 0.55, z], [x0, 0.55, z]], dtype=np.float64)
    return MeshData(vertices, [[0, 1, 2], [0, 2, 3]], name=name)


def _scene():
    # One foreground object has distinct red and green patch assignments.
    # A coincident blue object is behind it and must lose the depth test.
    left = np.array([[-0.55, -0.55, 0.1], [0, -0.55, 0.1],
                     [0, 0.55, 0.1], [-0.55, 0.55, 0.1]])
    right = np.array([[0, -0.55, 0.1], [0.55, -0.55, 0.1],
                      [0.55, 0.55, 0.1], [0, 0.55, 0.1]])
    foreground = MeshData(
        np.vstack([left, right]),
        [[0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7]],
        name="foreground", tri_groups=[0, 0, 1, 1],
        group_names=["left", "right"],
    )
    foreground_material = _quad("blue_backdrop", -0.55, 0.55, 0.0)
    side_object = _quad("blue_side", 0.85, 1.25, 0.05)
    return EvaluatedScene(
        meshes={"foreground": foreground,
                "blue_backdrop": foreground_material,
                "blue_side": side_object},
        materials={"white": Material(name="white", color=(0.85, 0.85, 0.85)),
                   "blue": Material(name="blue", color=(0.02, 0.1, 0.95)),
                   "red": Material(name="red", color=(0.95, 0.03, 0.02)),
                   "green": Material(name="green", color=(0.02, 0.9, 0.04))},
        object_materials={"foreground": "white", "blue_backdrop": "blue",
                          "blue_side": "blue"},
        patch_materials={"foreground": {"left": "red", "right": "green"}},
    )


def _sample(frame, camera, point):
    from am3d.gpu import _MatrixCamera

    xs, ys, valid = _MatrixCamera(camera).world_to_screen(
        np.asarray([point], dtype=np.float64), frame.shape[1], frame.shape[0])
    assert valid[0]
    x, y = int(round(xs[0])), int(round(ys[0]))
    return frame[max(0, min(y, frame.shape[0] - 1)),
                 max(0, min(x, frame.shape[1] - 1)), :3]


@pytest.mark.parametrize("size", [(512, 512), (128, 96)])
def test_material_preview_keeps_patch_colors_and_shared_scene_occlusion(size):
    scene = _scene()
    camera = scene_camera(list(scene.meshes.values()))
    image, textured = _render_material_preview(scene, camera, *size)

    assert image.shape == (size[1], size[0], 4)
    assert textured == []
    red = _sample(image, camera, [-0.3, 0.0, 0.1])
    green = _sample(image, camera, [0.3, 0.0, 0.1])
    blue_side = _sample(image, camera, [1.05, 0.0, 0.05])
    assert red[0] > red[1] * 1.5 and red[0] > red[2] * 1.5
    assert green[1] > green[0] * 1.5 and green[1] > green[2] * 1.5
    assert blue_side[2] > blue_side[0] * 1.5 and blue_side[2] > blue_side[1] * 1.5
    # The rear blue backdrop is fully hidden behind the red/green foreground.
    assert np.allclose(_sample(image, camera, [-0.3, 0.0, 0.0]), red,
                       atol=3 / 255)
