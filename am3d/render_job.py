"""Final still and animation rendering (finding UI-02).

The GUI could export OBJ/GLB but had no way to produce a finished image or
frame sequence at all -- the render workspace exposed shading settings with
nothing to apply them to. This module is the headless core of that feature:
frame enumeration, naming, rendering and writing, with progress and
cancellation. The Qt dialog in :mod:`am3d.ui.render_dialog` is a thin shell
around it, so the whole render path is testable without a display.

Every error raised here is a :class:`RenderError` carrying a message that
says what to do about it, because "render failed" in a dialog is useless.
"""

from __future__ import annotations

import os

import numpy as np

STILL = "still"
SEQUENCE = "sequence"


class RenderError(Exception):
    """A render that cannot proceed, with an actionable message."""


class RenderCancelled(Exception):
    """The caller's cancel callback asked to stop."""


def frame_times(start_frame, end_frame, fps):
    """``[(frame_number, time_seconds), ...]`` inclusive of both ends."""
    fps = float(fps)
    if fps <= 0:
        raise RenderError("Frames per second must be greater than zero.")
    start, end = int(start_frame), int(end_frame)
    if end < start:
        raise RenderError(
            f"The last frame ({end}) is before the first ({start}). "
            f"Swap them, or render a single frame by setting both the same.")
    return [(f, f / fps) for f in range(start, end + 1)]


def frame_filename(base_path, frame, digits=4):
    """``shot.png`` -> ``shot_0007.png`` for one frame of a sequence."""
    stem, ext = os.path.splitext(base_path)
    return f"{stem}_{int(frame):0{int(digits)}d}{ext or '.png'}"


def validate_destination(path, *, mode=STILL, frames=()):
    """Check *path* is writable before spending time rendering.

    *frames* is the sequence of frame numbers that will be written (ignored
    for a still). Returns the list of files that will be written, so a
    caller can warn about overwrites before anything is rendered.
    """
    if not str(path).strip():
        raise RenderError("Choose a destination file for the render.")
    path = os.path.abspath(str(path))
    directory = os.path.dirname(path) or "."
    if not os.path.isdir(directory):
        raise RenderError(
            f"The folder {directory!r} does not exist. Pick an existing "
            f"folder, or create it first.")
    if not os.access(directory, os.W_OK):
        raise RenderError(
            f"No permission to write into {directory!r}. Choose a different "
            f"folder.")
    if mode == SEQUENCE:
        return [frame_filename(path, f) for f in frames]
    return [path]


def validate_size(width, height, *, limit=8192):
    """Reject sizes that would fail deep inside the rasterizer instead."""
    try:
        w, h = int(width), int(height)
    except (TypeError, ValueError):
        raise RenderError("Width and height must be whole numbers of pixels.")
    if w < 1 or h < 1:
        raise RenderError(
            f"Image size must be at least 1x1 pixels, got {w}x{h}.")
    if w > limit or h > limit:
        raise RenderError(
            f"Image size {w}x{h} exceeds the {limit}x{limit} limit. "
            f"Render smaller, or in tiles.")
    return w, h


def render_frame_image(session, camera, width, height, *, time=None,
                       action_name=None, force_software=False):
    """One rendered frame as float RGBA 0..1, shaped ``(height, width, 4)``.

    Routed through ``am3d.gpu.render_frame``, which resolves the session
    through the shared scene evaluator and falls back to the software
    rasterizer when no GPU context is available -- so a machine with no
    working GL still renders, just more slowly.
    """
    from am3d.gpu import _software_render, render_frame, resolve_scene

    view = camera.view_matrix() if hasattr(camera, "view_matrix") else camera
    if force_software:
        scene = resolve_scene(session, time=time, action_name=action_name)
        meshes = [m for m in scene.meshes.values()
                  if getattr(m, "vertices", None) is not None
                  and len(m.vertices) and len(m.indices)]
        return _software_render(meshes, width, height, camera=view)
    return render_frame(session, camera=view, size=(width, height),
                        time=time, action_name=action_name)


def save_image(image, path):
    """Write float RGBA 0..1 (the render-boundary contract) as an 8-bit PNG."""
    from PIL import Image

    arr = np.asarray(image, dtype=np.float64)
    if arr.ndim != 3 or arr.shape[2] != 4:
        raise RenderError(
            f"Internal error: expected an RGBA image, got shape {arr.shape}.")
    rgba = (np.clip(arr, 0.0, 1.0) * 255.0).round().astype(np.uint8)
    directory = os.path.dirname(os.path.abspath(path))
    if directory:
        os.makedirs(directory, exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(path)
    return path


def run_render(session, camera, *, path, width, height, mode=STILL,
               start_frame=0, end_frame=0, fps=30.0, action_name=None,
               force_software=False, on_progress=None, should_cancel=None):
    """Render a still or a frame sequence and return the paths written.

    *on_progress* is called as ``(done, total, path)`` after each frame, and
    *should_cancel* is polled before each frame. Cancelling mid-sequence
    leaves the frames already written in place and reports them, rather than
    deleting work the user may want.
    """
    width, height = validate_size(width, height)
    if mode == SEQUENCE:
        times = frame_times(start_frame, end_frame, fps)
    else:
        times = [(int(start_frame), float(start_frame) / float(fps or 30.0))]

    from am3d.gpu import resolve_scene

    targets = validate_destination(path, mode=mode,
                                   frames=[f for f, _ in times])
    if not any(len(getattr(m, "indices", ()))
               for m in resolve_scene(session).meshes.values()):
        raise RenderError(
            "There is nothing to render: the scene has no visible geometry. "
            "Create or unhide an object first.")

    written = []
    total = len(times)
    for index, (frame, time_s) in enumerate(times):
        if should_cancel is not None and should_cancel():
            raise RenderCancelled(
                f"Cancelled after {len(written)} of {total} frames.")
        image = render_frame_image(session, camera, width, height,
                                   time=time_s if mode == SEQUENCE else None,
                                   action_name=action_name,
                                   force_software=force_software)
        target = (frame_filename(path, frame) if mode == SEQUENCE
                  else targets[0])
        save_image(image, target)
        written.append(target)
        if on_progress is not None:
            on_progress(index + 1, total, target)
    return written
