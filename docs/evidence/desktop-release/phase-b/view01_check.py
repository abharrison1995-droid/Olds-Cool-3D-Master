"""VIEW-01 check: the software render must agree with the picking model.

Two independent assertions, across orbit / pan / zoom:
  1. The silhouette of the rendered image lines up with where
     camera.world_to_screen() places the same geometry (what the CP handles
     and gizmos are drawn from).
  2. A click at the centre of the *rendered* object actually picks it, and a
     click on empty canvas does not.
Run with: QT_QPA_PLATFORM=offscreen PYTHONPATH=. python <this file>
"""
import sys

import numpy as np
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication(sys.argv)
from am3d.ui.app import MainWindow                       # noqa: E402
from am3d.ui.operators import CreatePrimitiveCommand     # noqa: E402

BBOX_TOL = 4        # px; ink dilation + supersampling widen the silhouette

win = MainWindow(); win.resize(800, 600); win.show_editor()
s = win.doc_ctrl.session
s.project.objects.clear()
win.push_command(CreatePrimitiveCommand(s, "box", "box"))
vp = win.viewport
vp.resize(800, 600)
vp.force_software = True

failures = []
for label, setup in [
        ("default", lambda: None),
        ("orbit",   lambda: vp.camera.orbit(35.0, -20.0)),
        ("pan",     lambda: vp.camera.pan(60.0, -40.0)),
        ("zoom in", lambda: vp.camera.zoom(0.55)),
        ("zoom out", lambda: vp.camera.zoom(2.2)),
]:
    setup()
    vp.refresh(); vp._render()
    frame = vp._frame
    if frame is None:
        failures.append(f"{label}: software render produced no frame")
        continue
    H, W = frame.shape[:2]
    ys, xs = np.nonzero(frame[..., 3] > 0.01)
    px, py, valid = vp.camera.world_to_screen(vp._merged.vertices, W, H)
    px, py = px[valid], py[valid]
    # The rendered silhouette is clipped to the canvas, so compare against
    # the projection clipped the same way (a zoomed-in object runs off-screen).
    px = np.clip(px, 0, W - 1)
    py = np.clip(py, 0, H - 1)

    d = [abs(px.min() - xs.min()), abs(px.max() - xs.max()),
         abs(py.min() - ys.min()), abs(py.max() - ys.max())]
    agree = max(d) <= BBOX_TOL
    print(f"[{label:9s}] render bbox x {xs.min():3d}..{xs.max():3d} "
          f"y {ys.min():3d}..{ys.max():3d} | "
          f"pick bbox x {px.min():3.0f}..{px.max():3.0f} "
          f"y {py.min():3.0f}..{py.max():3.0f} | max edge delta {max(d):.1f}px")
    if not agree:
        failures.append(f"{label}: silhouette/projection disagree by {max(d):.1f}px")

    # A click in the middle of what the user can actually see must select it.
    cx, cy = int(round(xs.mean())), int(round(ys.mean()))
    vp.set_selected(None)
    vp._pick(cx, cy)
    hit = vp._selected
    # ... and a click on empty canvas must not.
    vp.set_selected(None)
    vp._pick(4, 4)
    miss = vp._selected
    print(f"            click ({cx},{cy}) -> {hit!r}   click (4,4) -> {miss!r}")
    if not (hit and (hit[0] if isinstance(hit, tuple) else hit) == "box"):
        failures.append(f"{label}: click on the visible object picked {hit!r}")
    if miss is not None:
        failures.append(f"{label}: click on empty canvas picked {miss!r}")

print()
if failures:
    print("VERDICT: MISMATCH -- VIEW-01 present")
    for f in failures:
        print("  -", f)
    sys.exit(1)
print("VERDICT: AGREE -- render, picking and overlays share one projection")
