"""Final still and animation rendering (finding UI-02).

Before this existed the GUI could export OBJ/GLB but had no render command
at all, so the Render workspace's shading settings could not be applied to
anything and there was no way to produce a finished image.
"""

from __future__ import annotations

import os

import numpy as np
import pytest

from am3d.core.script import Session
from am3d.render_job import (SEQUENCE, STILL, RenderCancelled, RenderError,
                             frame_filename, frame_times, run_render,
                             validate_destination, validate_size)
from am3d.ui.camera import Camera
from am3d.ui.operators import CreatePrimitiveCommand


@pytest.fixture()
def scene():
    s = Session()
    CreatePrimitiveCommand(s, "box", "box").redo()
    return s


@pytest.fixture()
def camera():
    return Camera(yaw=30.0, pitch=20.0, distance=5.0)


# --- validation, before any time is spent rendering -------------------------

def test_frame_times_covers_both_ends():
    assert frame_times(2, 4, 24) == [(2, 2 / 24), (3, 3 / 24), (4, 4 / 24)]
    assert frame_times(5, 5, 30) == [(5, 5 / 30)]


@pytest.mark.parametrize("args, expect", [
    ((4, 2, 30), "before the first"),
    ((0, 4, 0), "greater than zero"),
])
def test_bad_frame_ranges_explain_what_to_do(args, expect):
    with pytest.raises(RenderError, match=expect):
        frame_times(*args)


@pytest.mark.parametrize("size, expect", [
    ((0, 100), "at least 1x1"),
    ((100, -3), "at least 1x1"),
    ((99999, 100), "exceeds"),
    (("wide", 100), "whole numbers"),
])
def test_bad_sizes_are_refused_with_an_actionable_message(size, expect):
    with pytest.raises(RenderError, match=expect):
        validate_size(*size)


def test_a_missing_destination_folder_is_reported_not_crashed(tmp_path):
    with pytest.raises(RenderError, match="does not exist"):
        validate_destination(str(tmp_path / "nope" / "out.png"))
    with pytest.raises(RenderError, match="Choose a destination"):
        validate_destination("   ")


def test_destination_lists_every_file_a_sequence_will_write(tmp_path):
    targets = validate_destination(str(tmp_path / "shot.png"),
                                   mode=SEQUENCE, frames=[7, 8])
    assert [os.path.basename(t) for t in targets] == ["shot_0007.png",
                                                      "shot_0008.png"]


def test_frame_filenames_sort_in_frame_order():
    names = [frame_filename("s.png", f) for f in (2, 10, 100)]
    assert names == sorted(names), "zero padding does not sort correctly"


# --- rendering --------------------------------------------------------------

def test_a_still_render_writes_one_image_of_the_requested_size(scene, camera,
                                                               tmp_path):
    from PIL import Image

    out = tmp_path / "still.png"
    written = run_render(scene, camera, path=str(out), width=64, height=48)
    assert written == [str(out)]
    with Image.open(out) as im:
        assert im.size == (64, 48)
        assert im.mode == "RGBA"
        pixels = np.asarray(im)
    assert pixels[..., 3].max() > 0, "the image is entirely empty"


def test_a_sequence_writes_one_numbered_file_per_frame(scene, camera,
                                                       tmp_path):
    progress = []
    written = run_render(scene, camera, path=str(tmp_path / "shot.png"),
                         width=32, height=32, mode=SEQUENCE,
                         start_frame=1, end_frame=3, fps=24,
                         on_progress=lambda d, t, p: progress.append((d, t)))
    assert [os.path.basename(w) for w in written] == [
        "shot_0001.png", "shot_0002.png", "shot_0003.png"]
    assert all(os.path.exists(w) for w in written)
    assert progress == [(1, 3), (2, 3), (3, 3)]


def test_cancelling_stops_early_and_keeps_the_frames_already_written(
        scene, camera, tmp_path):
    state = {"n": 0}

    def cancel_after_two():
        state["n"] += 1
        return state["n"] > 2

    with pytest.raises(RenderCancelled, match="2 of 5"):
        run_render(scene, camera, path=str(tmp_path / "shot.png"),
                   width=16, height=16, mode=SEQUENCE,
                   start_frame=0, end_frame=4, fps=30,
                   should_cancel=cancel_after_two)
    assert len(list(tmp_path.glob("*.png"))) == 2, \
        "cancelling should keep completed frames, not discard them"


def test_rendering_an_empty_scene_explains_the_problem(camera, tmp_path):
    empty = Session()
    with pytest.raises(RenderError, match="nothing to render"):
        run_render(empty, camera, path=str(tmp_path / "x.png"),
                   width=16, height=16)


def test_forced_software_rendering_produces_an_image_too(scene, camera,
                                                         tmp_path):
    """The reference machine must be testable with the GPU taken out."""
    out = tmp_path / "sw.png"
    run_render(scene, camera, path=str(out), width=48, height=32,
               force_software=True)
    from PIL import Image
    with Image.open(out) as im:
        assert im.size == (48, 32)
        assert np.asarray(im)[..., 3].max() > 0


def test_moving_the_camera_changes_the_image(scene, tmp_path):
    near = run_render(scene, Camera(distance=3.0), width=48, height=48,
                      path=str(tmp_path / "near.png"))
    far = run_render(scene, Camera(distance=12.0), width=48, height=48,
                     path=str(tmp_path / "far.png"))
    from PIL import Image

    def lit(path):
        """Pixels carrying colour. Alpha is unusable here: the GPU path
        returns an opaque background, the software path a transparent one."""
        with Image.open(path) as im:
            return int((np.asarray(im)[..., :3].sum(axis=2) > 8).sum())

    assert lit(near[0]) > lit(far[0]), \
        "the camera setting had no effect on the rendered image"


# --- the dialog shell -------------------------------------------------------

def _main_window():
    import sys
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PySide6 not available")
    from am3d.ui.app import MainWindow
    return MainWindow()


def test_the_dialog_renders_a_still_through_the_gui(tmp_path):
    from am3d.ui.render_dialog import RenderDialog

    win = _main_window()
    try:
        CreatePrimitiveCommand(win.session, "box", "box").redo()
        dialog = RenderDialog(win)
        dialog.path.setText(str(tmp_path / "gui.png"))
        dialog.width.setValue(40)
        dialog.height.setValue(40)
        written = dialog.start_render()
        assert written and os.path.exists(written[0])
        assert "Wrote 1 file" in dialog.status.text()
    finally:
        win.close()


def test_the_dialog_reports_a_bad_destination_instead_of_raising(tmp_path,
                                                                monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from am3d.ui.render_dialog import RenderDialog

    win = _main_window()
    try:
        CreatePrimitiveCommand(win.session, "box", "box").redo()
        monkeypatch.setattr(QMessageBox, "warning",
                            staticmethod(lambda *a, **k: None))
        dialog = RenderDialog(win)
        dialog.path.setText(str(tmp_path / "missing_folder" / "x.png"))
        assert dialog.start_render() == []
        assert "does not exist" in dialog.status.text()
        # The dialog must be usable again afterwards.
        assert dialog.render_button.isEnabled()
    finally:
        win.close()


def test_the_frame_range_controls_only_apply_to_a_sequence():
    from am3d.ui.render_dialog import RenderDialog

    win = _main_window()
    try:
        dialog = RenderDialog(win)
        dialog.mode.setCurrentIndex(dialog.mode.findData(STILL))
        assert not dialog.end_frame.isEnabled()
        dialog.mode.setCurrentIndex(dialog.mode.findData(SEQUENCE))
        assert dialog.end_frame.isEnabled() and dialog.fps.isEnabled()
    finally:
        win.close()


def test_the_scene_camera_option_frames_the_whole_scene(tmp_path):
    from am3d.ui.render_dialog import RenderDialog

    win = _main_window()
    try:
        CreatePrimitiveCommand(win.session, "box", "box").redo()
        dialog = RenderDialog(win)
        dialog.camera.setCurrentIndex(dialog.camera.findData("scene"))
        view = dialog._camera()
        assert np.asarray(view).shape == (4, 4)
    finally:
        win.close()
