"""Phase 2 MainWindow acceptance check, run against the checked-in sample copy."""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EVIDENCE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

import numpy as np
from PySide6.QtWidgets import QApplication

from am3d.ui.app import MainWindow, apply_theme
from am3d.ui.operators import SetObjectTransformCommand

SOURCE = ROOT / "docs/evidence/implementation-roadmap/phase-1/attempt-2/successful-output/clockwork_beetle_project.am3d"
PROJECT = EVIDENCE / "clockwork_beetle_refined.am3d"
shutil.copy2(SOURCE, PROJECT)

app = QApplication.instance() or QApplication([])
apply_theme(app)
window = MainWindow()
window.viewport.force_software = False
window.resize(1280, 820)
window.doc_ctrl.do_open(str(PROJECT))
window._reset_document_ui_state()
window._refresh_all()
window.show_editor()
window.show()
app.processEvents()
# Frame the complete generated beetle for the acceptance captures. The
# default editor view is intentionally a close work view for direct edits.
window.viewport.camera.distance = 4.0
window.viewport.camera.target[1] = 0.65
window.viewport._schedule_render()
app.processEvents()

session = window.session
assert len(session.project.objects) == 18
assert "clockwork_walk" in session.actions
assert session.action_assignments.get("beetle_rig") == "clockwork_walk"
assert "patterned_copper" in session.project.materials
assert sum(bool(b.cp_weights) for b in session.get_bones("front_left_upper")) > 0

# Make a visible object-space edit to the generated head through the UI's
# undo command stack, then verify undo and redo restore the exact transforms.
head = session.get_object("head")
before = np.array(head.transform, copy=True)
after = before.copy()
after[2, 3] += 0.16
window.push_command(SetObjectTransformCommand(session, "head", before, after))
window._refresh_all()
assert np.allclose(session.get_object("head").transform, after)
assert window.doc_ctrl.dirty
window.undo_stack.undo()
assert np.allclose(session.get_object("head").transform, before)
window._refresh_all()
window.undo_stack.redo()
assert np.allclose(session.get_object("head").transform, after)
window._refresh_all()
assert window.doc_ctrl.dirty
window.doc_ctrl.do_save()
assert not window.doc_ctrl.dirty

# Reopen through the same DocumentController + MainWindow refresh path used
# by File -> Open, so this checks serialization and editor handoff together.
window.doc_ctrl.do_open(str(PROJECT))
window._reset_document_ui_state()
window._refresh_all()
window.show_editor()
app.processEvents()
loaded = window.session
assert np.allclose(loaded.get_object("head").transform, after)
assert "clockwork_walk" in loaded.actions
assert loaded.action_assignments.get("beetle_rig") == "clockwork_walk"
assert "patterned_copper" in loaded.project.materials

# Wait for the actual MainWindow viewport renderer to produce its preview.
deadline = time.monotonic() + 15
while window.viewport._frame is None and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(0.05)
if window.viewport._frame is None:
    raise RuntimeError("MainWindow viewport did not produce a rendered preview")
frame = np.asarray(window.viewport._frame)
if not np.isfinite(frame).all() or float(frame.std()) < 0.01:
    raise RuntimeError("MainWindow viewport frame is blank or invalid")

# Show generated asset properties for Layout; show a rig bone, properties,
# and action timeline for Animate. Capture both target sizes.
head_item = window.object_dock._find("object", "head", "")
window.object_dock.tree.setCurrentItem(head_item)
window.set_workspace("Layout")
app.processEvents()
for width, height in ((1280, 820), (1440, 900)):
    window.resize(width, height)
    app.processEvents()
    time.sleep(0.35)
    image = window.grab()
    out = EVIDENCE / f"layout-{width}.png"
    if not image.save(str(out), "PNG"):
        raise RuntimeError(f"failed to save {out}")

bone_item = window.object_dock._find("bone", "beetle_rig", "front_left_leg")
window.object_dock.tree.setCurrentItem(bone_item)
window.set_workspace("Animate")
# Keep the outliner bone selection and properties context, while removing the
# stale object transform gizmo from the viewport screenshot.
window.viewport.set_selected(None)
app.processEvents()
for width, height in ((1280, 820), (1440, 900)):
    window.resize(width, height)
    app.processEvents()
    time.sleep(0.35)
    image = window.grab()
    out = EVIDENCE / f"animate-{width}.png"
    if not image.save(str(out), "PNG"):
        raise RuntimeError(f"failed to save {out}")

report = {
    "source_project": str(SOURCE),
    "saved_project": str(PROJECT),
    "objects": len(loaded.project.objects),
    "materials": sorted(loaded.project.materials),
    "actions": sorted(loaded.actions),
    "action_assignments": loaded.action_assignments,
    "head_transform_before": before.tolist(),
    "head_transform_after": after.tolist(),
    "undo_restored_before": True,
    "redo_restored_after": True,
    "saved_and_reopened_after_transform": True,
    "viewport_frame_shape": list(frame.shape),
    "viewport_frame_stddev": float(frame.std()),
    "screenshots": [
        "layout-1280.png", "animate-1280.png",
        "layout-1440.png", "animate-1440.png",
    ],
    "renderer_setting": "Auto (GPU preferred; software toon fallback)",
    "renderer_used": window.viewport.renderer_name,
}
(EVIDENCE / "acceptance.json").write_text(json.dumps(report, indent=2) + "\n")
window.close()
app.processEvents()
print(json.dumps(report, indent=2))
