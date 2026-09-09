"""Toon / ink-line NPR shading (headless, numpy).

Implements the spec's non-photorealistic pipeline:
* **Cel shading** — quantized lighting bands for a flat cartoon look.
* **Ink lines** — depth + normal discontinuity edge detection.
* :func:`toon_render_view` — one orthographic toon frame of a mesh,
  reusing the sprite rasterizer's projection conventions.
"""

from __future__ import annotations

import numpy as np


def cel_shade(normals, light=(0.45, 0.75, 0.55), bands: int = 4,
              ambient: float = 0.35) -> np.ndarray:
    """Quantize Lambert lighting into *bands* discrete steps.

    ``normals`` : (N, 3) unit normals.  Returns (N,) factors in
    ``[ambient, 1]``.
    """
    normals = np.asarray(normals, dtype=np.float64).reshape(-1, 3)
    light = np.asarray(light[:3], dtype=np.float64)
    light = light / max(np.linalg.norm(light), 1e-9)
    lam = np.abs(normals @ light)
    bands = max(int(bands), 1)
    quant = np.floor(lam * bands).clip(0, bands - 1)
    shaded = (quant + 1.0) / bands
    return ambient + (1.0 - ambient) * shaded


def _sobel_mag(buf: np.ndarray) -> np.ndarray:
    """Sobel gradient magnitude of a single-channel buffer."""
    kx = np.array([[-1, 0, 1], [-2, 0, 2], [-1, 0, 1]], dtype=np.float64)
    ky = kx.T
    from numpy.lib.stride_tricks import sliding_window_view
    padded = np.pad(buf, 1, mode="edge")
    win = sliding_window_view(padded, (3, 3))
    gx = (win * kx).sum(axis=(-1, -2))
    gy = (win * ky).sum(axis=(-1, -2))
    return np.sqrt(gx * gx + gy * gy)


def detect_ink(depth, normals_img, depth_thresh: float = 0.05,
               normal_thresh: float = 0.6) -> np.ndarray:
    """Binary ink-line mask from depth + normal discontinuities."""
    depth_edges = _sobel_mag(np.asarray(depth, dtype=np.float64)) \
        > depth_thresh

    n = np.asarray(normals_img, dtype=np.float64)
    normal_edges = np.zeros(n.shape[:2], dtype=bool)
    dot_v = (n[1:, :] * n[:-1, :]).sum(axis=-1)
    normal_edges[1:, :] |= dot_v < 1.0 - normal_thresh
    dot_h = (n[:, 1:] * n[:, :-1]).sum(axis=-1)
    normal_edges[:, 1:] |= dot_h < 1.0 - normal_thresh

    return depth_edges | normal_edges


def dilate_mask(mask: np.ndarray, pixels: int = 2) -> np.ndarray:
    """Grow a bool mask by *pixels* (PIL MaxFilter, numpy fallback)."""
    if int(pixels) <= 0:
        return mask
    try:
        from PIL import Image, ImageFilter
    except ImportError:              # pragma: no cover
        out = mask.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                out |= np.roll(np.roll(mask, dy, axis=0), dx, axis=1)
        return out
    m = Image.fromarray((mask * 255).astype(np.uint8))
    for _ in range(int(pixels)):
        m = m.filter(ImageFilter.MaxFilter(3))
    return np.asarray(m) > 0


def composite_toon(base_rgb, alpha, cel_factors=None, ink_mask=None,
                   ink_color=(0.05, 0.04, 0.03),
                   ink_px_width: int = 2) -> np.ndarray:
    """Assemble the final toon RGBA frame from buffers."""
    h, w = base_rgb.shape[:2]
    out = np.asarray(base_rgb, dtype=np.float64).copy()

    if cel_factors is not None:
        out *= np.asarray(cel_factors, dtype=np.float64)[..., None]

    if ink_mask is not None and int(ink_px_width) > 0:
        dilated = dilate_mask(np.asarray(ink_mask, dtype=bool),
                              int(ink_px_width))
        ic = np.asarray(ink_color[:3], dtype=np.float64)
        out[dilated] = ic

    rgba = np.zeros((h, w, 4), dtype=np.float64)
    rgba[..., :3] = out
    a = np.asarray(alpha, dtype=np.float64)
    rgba[..., 3] = a if a.max() <= 1.0 + 1e-9 else a / 255.0
    return np.clip(rgba, 0.0, 1.0)


def toon_render_view(mesh, yaw_deg: float = 0.0, pitch_deg: float = 0.0,
                     size: int = 256, color=(0.85, 0.78, 0.55),
                     bands: int = 4, ink: bool = True,
                     ink_px_width: int = 2,
                     ink_color=(0.05, 0.04, 0.03),
                     supersample: int = 2) -> np.ndarray:
    """One orthographic **toon** frame of *mesh* as ``(size, size, 4)``.

    Renders via the sprite rasterizer with geometry buffers enabled, then
    applies cel-shade quantization and ink lines as a post-process.
    Returns float32 RGBA in 0..1 (the render-boundary contract).
    """
    from .sprite import _rasterize, _rotation_x, _rotation_y

    verts = np.asarray(mesh.vertices, dtype=np.float64)
    tris = np.asarray(mesh.indices, dtype=np.int64)
    if len(verts) == 0 or len(tris) == 0:
        return np.zeros((size, size, 4), dtype=np.float32)

    rot = _rotation_y(yaw_deg) @ _rotation_x(pitch_deg)
    view_verts = (rot @ verts.T).T
    view_normals = ((rot @ np.asarray(mesh.normals).T).T
                    if len(mesh.normals) == len(verts)
                    else np.zeros_like(view_verts))
    light = np.array([0.45, 0.75, 0.55])
    light /= np.linalg.norm(light)

    ss = max(int(supersample), 1)
    buffers = {"bands": int(bands)}
    img = _rasterize(view_verts, view_normals, tris, int(size), ss,
                     color, silhouette=False, light=light, buffers=buffers)

    alpha = img[..., 3]
    if not (alpha > 0).any():
        return np.zeros((size, size, 4), dtype=np.float32)

    # Normalize the raw depth buffer for edge detection.
    raw = buffers["_depth_raw"]
    valid = np.isfinite(raw)
    depth_norm = np.ones_like(raw)
    if valid.any():
        dmin = raw[valid].min()
        drange = float(np.ptp(raw[valid]))
        depth_norm[valid] = (raw[valid] - dmin) / max(drange, 1e-9)

    ink_mask = detect_ink(depth_norm, buffers["normals"]) if ink else None

    base_rgb = img[..., :3] / 255.0
    cel_px = np.where(valid, buffers["cel"], 1.0)
    frame = composite_toon(base_rgb, alpha / 255.0, cel_factors=cel_px,
                           ink_mask=ink_mask, ink_color=ink_color,
                           ink_px_width=int(ink_px_width) * ss)

    if ss > 1:
        try:
            from PIL import Image
            pil = Image.fromarray(
                np.clip(frame * 255, 0, 255).astype(np.uint8))
            return np.asarray(pil.resize((int(size), int(size)),
                                         Image.LANCZOS),
                              dtype=np.float32) / 255.0
        except ImportError:          # pragma: no cover
            step = ss
            return frame[::step, ::step][:size, :size].astype(np.float32)
    return frame.astype(np.float32)


def toon_render_camera(mesh, camera, width: int, height: int,
                       color=(0.85, 0.78, 0.55), bands: int = 4,
                       ink: bool = True, ink_px_width: int = 2,
                       ink_color=(0.05, 0.04, 0.03),
                       supersample: int = 2) -> np.ndarray:
    """One toon frame of *mesh* through *camera*'s own perspective projection.

    Unlike :func:`toon_render_view`, the screen mapping comes entirely from
    ``camera.world_to_screen`` -- the same call the viewport uses for picking
    rays, control-point handles and gizmos -- so what the user sees and what
    a click resolves to cannot drift apart (finding VIEW-01).

    *camera* must provide ``world_to_screen(points, width, height)`` and
    ``view_matrix()``. Returns float32 RGBA ``(height, width, 4)`` in 0..1.
    """
    from .sprite import _rasterize_screen

    W, H = max(int(width), 1), max(int(height), 1)
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    tris = np.asarray(mesh.indices, dtype=np.int64)
    if len(verts) == 0 or len(tris) == 0:
        return np.zeros((H, W, 4), dtype=np.float32)

    xs, ys, valid = camera.world_to_screen(verts, W, H)
    view = np.asarray(camera.view_matrix(), dtype=np.float64)
    rot = view[:3, :3]
    cam_verts = verts @ rot.T + view[:3, 3]
    # Camera space looks down -Z, so distance from the eye is -z; feed the
    # rasterizer "smaller == nearer" and mark points behind the eye as
    # non-finite so it drops those triangles.
    depths = -cam_verts[:, 2]
    depths = np.where(valid & (depths > 1e-9), depths, np.inf)

    normals = (np.asarray(mesh.normals, dtype=np.float64) @ rot.T
               if mesh.normals is not None and len(mesh.normals) == len(verts)
               else np.zeros_like(cam_verts))

    light = np.array([0.45, 0.75, 0.55])
    light /= np.linalg.norm(light)

    ss = max(int(supersample), 1)
    buffers = {"bands": int(bands)}
    img = _rasterize_screen(np.column_stack([xs, ys]), depths, normals, tris,
                            W, H, ss, color, silhouette=False, light=light,
                            buffers=buffers)

    alpha = img[..., 3]
    if not (alpha > 0).any():
        return np.zeros((H, W, 4), dtype=np.float32)

    raw = buffers["_depth_raw"]
    finite = np.isfinite(raw)
    depth_norm = np.ones_like(raw)
    if finite.any():
        dmin = raw[finite].min()
        drange = float(np.ptp(raw[finite]))
        depth_norm[finite] = (raw[finite] - dmin) / max(drange, 1e-9)

    ink_mask = detect_ink(depth_norm, buffers["normals"]) if ink else None
    frame = composite_toon(img[..., :3] / 255.0, alpha / 255.0,
                           cel_factors=np.where(finite, buffers["cel"], 1.0),
                           ink_mask=ink_mask, ink_color=ink_color,
                           ink_px_width=int(ink_px_width) * ss)

    if ss > 1:
        try:
            from PIL import Image
            pil = Image.fromarray(np.clip(frame * 255, 0, 255).astype(np.uint8))
            return np.asarray(pil.resize((W, H), Image.LANCZOS),
                              dtype=np.float32) / 255.0
        except ImportError:          # pragma: no cover
            return frame[::ss, ::ss][:H, :W].astype(np.float32)
    return frame.astype(np.float32)


def render_toon_sheet(mesh, views: int = 8, size: int = 256,
                      color=(0.85, 0.78, 0.55), bands: int = 4,
                      ink: bool = True, columns: int | None = None,
                      pitch_deg: float = 12.0):
    """Toon sprite sheet — same contract as the standard sprite sheet."""
    import math

    try:
        from PIL import Image
    except ImportError:
        Image = None

    views = max(int(views), 1)
    size = max(int(size), 16)
    frames = [
        toon_render_view(mesh, yaw_deg=360.0 * i / views,
                         pitch_deg=pitch_deg, size=size, color=color,
                         bands=bands, ink=ink)
        for i in range(views)
    ]
    cols = columns if columns and columns > 0 else views
    rows = int(math.ceil(views / cols))
    sheet = np.zeros((rows * size, cols * size, 4), dtype=np.uint8)
    for idx, frame in enumerate(frames):
        r, c = divmod(idx, cols)
        # frames are float RGBA 0..1; convert to uint8 at the export edge
        sheet[r * size:(r + 1) * size, c * size:(c + 1) * size] = \
            (np.clip(frame, 0.0, 1.0) * 255).astype(np.uint8)

    if Image is None:
        return sheet
    return Image.fromarray(sheet, "RGBA")


def save_toon_sheet(mesh, path: str, **kwargs):
    """Render a toon sheet and write it to *path* as PNG."""
    sheet = render_toon_sheet(mesh, **kwargs)
    if isinstance(sheet, np.ndarray):
        try:
            from PIL import Image
        except ImportError as exc:   # pragma: no cover
            raise RuntimeError("Pillow required to write PNG") from exc
        sheet = Image.fromarray(sheet, "RGBA")
    sheet.save(path, format="PNG")
    return path