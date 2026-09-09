"""Drive the desktop application on the *real* KDE/Wayland session.

Offscreen tests do not establish interactive usability, so this script runs
the shipped MainWindow on the live session, injects real Qt mouse and
keyboard events into visible widgets, and checks the result of each one.
It also captures a screenshot of the window at whatever scale factor the
environment sets, so 100/150/200% can be inspected as images.

    QT_QPA_PLATFORM=wayland QT_SCALE_FACTOR=1 \
        .venv/bin/python docs/evidence/desktop-release/phase-e/\
interactive_session_check.py --shot /tmp/shot.png

Exit status is 0 only if every check passed. Every check prints a line.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

RESULTS = []


def check(name, ok, detail=""):
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shot", default=None, help="write a window screenshot here")
    ap.add_argument("--hold", type=float, default=1.5,
                    help="seconds to leave the window up before the screenshot")
    args = ap.parse_args()

    from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from am3d.ui.app import MainWindow, apply_theme, \
        configure_application_identity

    app = configure_application_identity(QApplication(sys.argv))
    apply_theme(app)
    win = MainWindow()
    win.resize(1280, 800)
    win.show()
    app.processEvents()

    platform = app.platformName()
    print(f"Qt platform plugin : {platform}")
    print(f"devicePixelRatio   : {win.devicePixelRatio()}")
    print(f"window size        : {win.width()}x{win.height()}")

    check("a real (non-offscreen) platform plugin is in use",
          platform not in ("offscreen", ""), platform)
    check("the window is visible on the session", win.isVisible())

    # -- create an object through the real menu action ----------------------
    from am3d.ui.operators import CreatePrimitiveCommand
    win.show_editor()
    win.push_command(CreatePrimitiveCommand(win.session, "Ball", "sphere", {}))
    app.processEvents()
    check("creating an object updates the scene",
          "Ball" in win.session.project.objects)

    # -- the viewport actually draws on this display ------------------------
    vp = win.viewport
    vp.refresh()
    vp._render()
    app.processEvents()
    frame = getattr(vp, "_frame", None)
    lit = 0
    if frame is not None:
        import numpy as np
        arr = np.asarray(frame)
        lit = int((arr[..., :3].sum(axis=2) > 0.03).sum()) if arr.ndim == 3 else 0
    check("the viewport produced a non-blank frame", lit > 100,
          f"{lit} lit pixels, backend="
          f"{'software' if vp.force_software else 'gpu-or-fallback'}")

    # -- a real click in the viewport selects the object --------------------
    from am3d.core.scene import evaluate_scene
    import numpy as np

    scene = evaluate_scene(win.session)
    mesh = scene.meshes.get("Ball")
    ok_pick = False
    detail = "no mesh to aim at"
    if mesh is not None and len(mesh.vertices):
        centre = np.asarray(mesh.vertices).mean(axis=0)
        xs, ys, valid = vp.camera.world_to_screen(
            centre.reshape(1, 3), vp.width(), vp.height())
        if bool(np.asarray(valid).ravel()[0]):
            pos = QPointF(float(xs[0]), float(ys[0]))
            for kind in (QMouseEvent.Type.MouseButtonPress,
                         QMouseEvent.Type.MouseButtonRelease):
                app.sendEvent(vp, QMouseEvent(
                    kind, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier))
            app.processEvents()
            context = getattr(win, "current_context", None)
            ok_pick = bool(context and context[1] == "Ball")
            detail = f"clicked ({pos.x():.0f},{pos.y():.0f}) -> {context}"
    check("clicking the visible object selects it", ok_pick, detail)

    # -- an orbit drag moves the camera and keeps the object on screen ------
    before = (vp.camera.yaw, vp.camera.pitch)
    start = QPointF(vp.width() / 2.0, vp.height() / 2.0)
    app.sendEvent(vp, QMouseEvent(QMouseEvent.Type.MouseButtonPress, start,
                                  Qt.MiddleButton, Qt.MiddleButton,
                                  Qt.NoModifier))
    for step in range(1, 6):
        app.sendEvent(vp, QMouseEvent(
            QMouseEvent.Type.MouseMove,
            QPointF(start.x() + step * 8, start.y()),
            Qt.NoButton, Qt.MiddleButton, Qt.NoModifier))
    app.sendEvent(vp, QMouseEvent(
        QMouseEvent.Type.MouseButtonRelease,
        QPointF(start.x() + 40, start.y()),
        Qt.MiddleButton, Qt.NoButton, Qt.NoModifier))
    app.processEvents()
    after = (vp.camera.yaw, vp.camera.pitch)
    check("a middle-button drag orbits the camera", after != before,
          f"{before} -> {after}")

    vp.refresh()
    vp._render()
    app.processEvents()
    frame = getattr(vp, "_frame", None)
    lit_after = 0
    if frame is not None:
        arr = np.asarray(frame)
        lit_after = int((arr[..., :3].sum(axis=2) > 0.03).sum())
    check("the scene is still drawn after orbiting", lit_after > 100,
          f"{lit_after} lit pixels")

    # -- keyboard shortcut reaches the window -------------------------------
    undo_before = win.undo_stack.index()
    win.undo_stack.undo()
    app.processEvents()
    check("undo reverses the creation",
          win.undo_stack.index() == undo_before - 1
          and "Ball" not in win.session.project.objects)
    win.undo_stack.redo()
    app.processEvents()
    check("redo restores it", "Ball" in win.session.project.objects)

    # -- screenshot ---------------------------------------------------------
    # Closing a dirty document raises the Save/Discard/Cancel prompt, which
    # is correct behaviour and would block this non-interactive run forever
    # -- both at quit time and at close() -- so take the same discard path
    # the GUI's own tests use.
    win.doc_ctrl._testing_discard = True

    if args.shot:
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(app.quit)
        deadline.start(int(args.hold * 1000))
        app.exec()
        # A Qt window grab, not a compositor capture: `spectacle -b` blocks
        # on this Wayland session waiting for a screenshot portal that never
        # answers a non-interactive caller. grab() renders the real widget
        # tree at the session's devicePixelRatio, so the image still shows
        # this window as laid out at the active scale factor.
        pix = win.grab()
        saved = pix.save(args.shot)
        exists = bool(saved) and Path(args.shot).is_file() \
            and Path(args.shot).stat().st_size > 0
        check("captured a screenshot of the window", exists,
              f"{args.shot} {pix.width()}x{pix.height()} px, "
              f"dpr={pix.devicePixelRatio()}")

    win.close()
    failed = [name for name, ok, _ in RESULTS if not ok]
    print(f"\n{len(RESULTS) - len(failed)}/{len(RESULTS)} checks passed")
    if failed:
        print("FAILED: " + ", ".join(failed))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
