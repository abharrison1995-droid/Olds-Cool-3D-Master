"""Visual evidence for original-vs-reopened render comparison (Phase 4).

The automated checks in ``am3d/core/test_render_roundtrip.py`` assert the
numeric and PNG-tolerant equivalence of a scene's render before and after
a save/reload round-trip. That's the part a human doesn't need to look
at. What still benefits from eyes is the actual picture: this script
renders the same six scenarios (empty, occluding two-object, invisible,
translated, rotated, non-uniformly scaled), saves and reloads each one,
and writes original / reopened / diff PNGs so someone can visually
confirm nothing looks wrong, not just that the two buffers matched.

Run:
    QT_QPA_PLATFORM=offscreen python scripts/render_roundtrip_evidence.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from am3d.core.project import Patch
from am3d.core.script import Session
from am3d.recipes.primitives import build_primitive
from am3d.renderer.compare import image_diff_stats, png_roundtrip
from am3d.renderer.sprite import render_scene

RENDER_KW = dict(yaw_deg=25.0, pitch_deg=15.0, size=256,
                 color=(0.7, 0.75, 0.9), supersample=2)

OUT_DIR = os.path.join(os.path.dirname(__file__), "..",
                       "docs", "evidence", "v3", "phase-4", "render_roundtrip")


def _add_primitive(session, name, primitive="sphere", params=None,
                   transform=None, visible=True):
    session.create_object(name)
    obj = session.project.objects[name]
    built = build_primitive(primitive, params or {})
    for pname, net, du, dv in built["patches"]:
        obj.patches.append(Patch(name=pname, splines=[], interior=net))
    if transform is not None:
        obj.transform = np.asarray(transform, dtype=np.float64)
    obj.visible = visible
    return obj


def _render_current(session):
    scene = session.evaluate_scene(apply_transforms=True, visible_only=True)
    meshes = {n: m for n, m in scene.meshes.items() if len(m.vertices)}
    return render_scene(meshes, **RENDER_KW)


def _translation(x=0.0, y=0.0, z=0.0):
    m = np.eye(4, dtype=np.float64)
    m[:3, 3] = [x, y, z]
    return m


def _rotation_y(deg):
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    m = np.eye(4, dtype=np.float64)
    m[[0, 0, 2, 2], [0, 2, 0, 2]] = [c, s, -s, c]
    return m


def _scale(sx=1.0, sy=1.0, sz=1.0):
    m = np.eye(4, dtype=np.float64)
    m[0, 0], m[1, 1], m[2, 2] = sx, sy, sz
    return m


def _build_empty():
    s = Session()
    s.new_project("empty")
    return s


def _build_occluding_two_objects():
    s = Session()
    s.new_project("occlusion")
    _add_primitive(s, "near", "sphere", {"radius": 0.6, "sections": 16, "rings": 10},
                   transform=_translation(z=0.4))
    _add_primitive(s, "far", "sphere", {"radius": 0.6, "sections": 16, "rings": 10},
                   transform=_translation(z=-0.4))
    return s


def _build_invisible():
    s = Session()
    s.new_project("invisible")
    _add_primitive(s, "shown", "box", {"width": 1.0, "height": 1.0, "depth": 1.0})
    _add_primitive(s, "hidden", "sphere", {"radius": 5.0, "sections": 16, "rings": 10},
                   visible=False)
    return s


def _build_translated():
    s = Session()
    s.new_project("translated")
    _add_primitive(s, "orb", "sphere", {"radius": 0.5, "sections": 16, "rings": 10},
                   transform=_translation(x=1.3, y=-0.6, z=0.2))
    return s


def _build_rotated():
    s = Session()
    s.new_project("rotated")
    _add_primitive(s, "box", "box", {"width": 1.4, "height": 0.6, "depth": 0.9},
                   transform=_rotation_y(37.0))
    return s


def _build_non_uniformly_scaled():
    s = Session()
    s.new_project("scaled")
    _add_primitive(s, "orb", "sphere", {"radius": 0.5, "sections": 16, "rings": 10},
                   transform=_scale(sx=2.0, sy=0.5, sz=1.3))
    return s


SCENARIOS = {
    "empty": _build_empty,
    "occluding_two_objects": _build_occluding_two_objects,
    "invisible_object": _build_invisible,
    "translated": _build_translated,
    "rotated": _build_rotated,
    "non_uniformly_scaled": _build_non_uniformly_scaled,
}


def _save_png(path, img_float_rgba):
    from PIL import Image
    u8 = (np.clip(img_float_rgba, 0.0, 1.0) * 255.0).astype(np.uint8)
    Image.fromarray(u8, "RGBA").save(path, format="PNG")


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"writing evidence to {os.path.abspath(OUT_DIR)}")

    rows = []
    for name, build in SCENARIOS.items():
        s1 = build()
        img1 = _render_current(s1)

        save_path = os.path.join(OUT_DIR, f"_{name}.am3d")
        s1.save_project(save_path)
        s2 = Session()
        s2.load_project(save_path)
        img2 = _render_current(s2)
        os.remove(save_path)

        stats = image_diff_stats(img1, img2)
        a8 = png_roundtrip(img1).astype(np.float64)
        b8 = png_roundtrip(img2).astype(np.float64)
        png_mean = float(np.abs(a8 - b8).mean())

        _save_png(os.path.join(OUT_DIR, f"{name}_original.png"), img1)
        _save_png(os.path.join(OUT_DIR, f"{name}_reopened.png"), img2)
        diff_img = np.clip(np.abs(img1 - img2) * 8.0, 0.0, 1.0)  # amplified for visibility
        diff_img[..., 3] = 1.0
        _save_png(os.path.join(OUT_DIR, f"{name}_diff_x8.png"), diff_img)

        status = "OK" if stats["max_abs_diff"] <= 1e-6 and png_mean <= 2.0 else "MISMATCH"
        rows.append((name, status, stats["max_abs_diff"], png_mean))
        print(f"[{status}] {name}: max_abs_diff={stats['max_abs_diff']:.3g} "
              f"png_mean_diff={png_mean:.3g}")

    summary_path = os.path.join(OUT_DIR, "summary.txt")
    with open(summary_path, "w") as f:
        f.write("scenario, status, max_abs_diff, png_mean_diff\n")
        for name, status, max_diff, png_mean in rows:
            f.write(f"{name}, {status}, {max_diff:.6g}, {png_mean:.6g}\n")
    print(f"wrote {summary_path}")

    return 0 if all(r[1] == "OK" for r in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
