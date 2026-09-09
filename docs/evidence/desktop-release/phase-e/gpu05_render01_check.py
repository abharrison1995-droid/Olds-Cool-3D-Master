"""Re-runnable probe for the two phase-E rendering findings.

GPU-05   forced-software renders framed the scene differently from the GPU
         path, because `_software_render(camera=None)` fell back to the toon
         renderer's own per-image fit instead of `scene_camera()`.
RENDER-01 `detect_ink` marked most of a smooth curved surface as outline, so
         a sphere rendered as a black disc in software.

Each check is measured twice: once through the shipped code and once with the
pre-fix behaviour restored by monkeypatching, so the numbers are comparable
without checking out the old revision.

    cd <repo> && QT_QPA_PLATFORM=offscreen .venv/bin/python \
        docs/evidence/desktop-release/phase-e/gpu05_render01_check.py
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from am3d.core.script import Session
from am3d.render_job import STILL, run_render
from am3d.ui.operators import CreatePrimitiveCommand


def two_object_scene():
    """Unequally placed objects -- a fixture where framing errors show."""
    s = Session()
    CreatePrimitiveCommand(s, "Ball", "sphere", {}).redo()
    CreatePrimitiveCommand(s, "Box", "box", {}).redo()
    box = s.project.objects["Box"]
    t = box.transform.copy()
    t[0, 3] = 2.0
    box.transform = t
    return s


def silhouette(path):
    arr = np.asarray(Image.open(path).convert("RGB")).astype(int)
    return np.abs(arr - arr[0, 0]).sum(axis=2) > 12, arr


def gpu_vs_software_iou(tmp):
    s = two_object_scene()
    masks = {}
    for tag, soft in (("sw", True), ("gpu", False)):
        written = run_render(s, None, mode=STILL, path=str(tmp / f"{tag}.png"),
                             width=160, height=120, force_software=soft)
        masks[tag], _ = silhouette(written[0])
    inter = int((masks["sw"] & masks["gpu"]).sum())
    union = int((masks["sw"] | masks["gpu"]).sum())
    return inter / max(union, 1)


def sphere_brightness(tmp, name="sphere.png"):
    s = Session()
    CreatePrimitiveCommand(s, "O", "sphere", {}).redo()
    written = run_render(s, None, mode=STILL, path=str(tmp / name),
                         width=160, height=120, force_software=True)
    mask, arr = silhouette(written[0])
    return float(arr[mask].mean()) if mask.any() else 0.0


def main():
    tmp = Path(tempfile.mkdtemp(prefix="am3d_phase_e_"))
    import am3d.gpu as gpu
    import am3d.renderer.toon as toon

    print("GPU-05  GPU vs forced-software silhouette IoU (two objects)")
    print(f"  shipped code                 : {gpu_vs_software_iou(tmp):.3f}")

    original = gpu._software_render.__wrapped__ \
        if hasattr(gpu._software_render, "__wrapped__") else gpu._software_render

    def prefix_software_render(meshes, W, H, camera=None):
        """The pre-fix body: no camera means the toon renderer's own fit."""
        from am3d.renderer.sprite import merge_meshes
        from am3d.renderer.toon import toon_render_view
        meshes = [m for m in (meshes or [])
                  if getattr(m, "vertices", None) is not None
                  and len(m.vertices) and len(m.indices)]
        if not meshes:
            return np.zeros((H, W, 4), dtype=np.float32)
        merged = meshes[0] if len(meshes) == 1 else merge_meshes(meshes)
        if camera is not None:
            result = gpu._toon_through_camera(merged, camera, W, H)
        else:
            result = toon_render_view(merged, size=max(W, H))
        result = np.asarray(result, dtype=np.float32)
        if result.shape[0] != H or result.shape[1] != W:
            from am3d.renderer.materials import _resize
            result = _resize(result, H, W).astype(np.float32)
        return np.clip(result, 0.0, 1.0).astype(np.float32)

    gpu._software_render = prefix_software_render
    try:
        print(f"  with the pre-fix fallback    : {gpu_vs_software_iou(tmp):.3f}")
    finally:
        gpu._software_render = original

    print()
    print("RENDER-01  mean brightness of a software-rendered sphere (0..255)")
    print(f"  shipped code                 : {sphere_brightness(tmp):6.1f}")

    real_detect = toon.detect_ink

    def prefix_detect_ink(depth, normals_img, depth_thresh=0.05,
                          normal_thresh=0.6):
        from am3d.renderer.toon import _sobel_mag
        depth_edges = _sobel_mag(np.asarray(depth, dtype=np.float64)) > depth_thresh
        n = np.asarray(normals_img, dtype=np.float64)
        normal_edges = np.zeros(n.shape[:2], dtype=bool)
        dot_v = (n[1:, :] * n[:-1, :]).sum(axis=-1)
        normal_edges[1:, :] |= dot_v < 1.0 - normal_thresh
        dot_h = (n[:, 1:] * n[:, :-1]).sum(axis=-1)
        normal_edges[:, 1:] |= dot_h < 1.0 - normal_thresh
        return depth_edges | normal_edges

    toon.detect_ink = prefix_detect_ink
    try:
        print("  with the pre-fix detect_ink  : "
              f"{sphere_brightness(tmp, 'sphere_prefix.png'):6.1f}")
    finally:
        toon.detect_ink = real_detect

    print(f"\nimages written to {tmp}")


if __name__ == "__main__":
    main()
