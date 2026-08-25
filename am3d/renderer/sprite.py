"""Headless sprite-sheet rendering (software rasterizer, no GPU needed).

Turns tessellated spline geometry into PNG sprite sheets: the mesh is
rendered from N evenly-spaced orbit views using a small numpy rasterizer
(z-buffered, Lambert-shaded, supersampled), then tiled into one atlas.

This is what makes "generate sprites" work from a plain recipe::

    {"format": "spritesheet", "path": "out/knight",
     "params": {"views": 8, "size": 256, "color": [0.7, 0.75, 0.9]}}
"""

from __future__ import annotations

import math

import numpy as np

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False


def _rotation_y(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def _rotation_x(deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return np.array([[1, 0, 0], [0, c, -s], [0, s, c]])


def _rasterize(view_verts, view_normals, tri_indices, size, ss, color,
               silhouette, light, buffers=None):
    """Render one orthographic view into an ``(W, W, 4)`` float buffer.

    When *buffers* is a dict, it is filled with per-pixel geometry data for
    post-processing (toon shading):

    * ``buffers["depth"]``  <- (W, W) normalized view depth
    * ``buffers["normals"]``<- (W, W, 3) view-space normals
    * ``buffers["cel"]``    <- (W, W) cel-shade factor per pixel
    """
    W = size * ss
    img = np.zeros((W, W, 4), dtype=np.float32)
    zbuf = np.full((W, W), np.inf, dtype=np.float32)
    if buffers is not None:
        nbuf = buffers.setdefault("normals", np.zeros((W, W, 3)))
        cbuf = buffers.setdefault("cel", np.ones((W, W)))
        depth_vals = buffers.setdefault("_depth_raw",
                                        np.full((W, W), np.inf))

    xs, ys, zs = view_verts[:, 0], view_verts[:, 1], view_verts[:, 2]
    span_x = float(xs.max() - xs.min())
    span_y = float(ys.max() - ys.min())
    span = max(span_x, span_y, 1e-6)
    margin = W * 0.08
    scale = (W - 2 * margin) / span
    cx, cy = (xs.max() + xs.min()) / 2, (ys.max() + ys.min()) / 2
    px = (xs - cx) * scale + W / 2
    py = W / 2 - (ys - cy) * scale          # flip so +Y is up on screen

    base = np.asarray(color[:3], dtype=np.float32) * 255.0

    # Per-triangle cel-shade factors (only computed when buffers are wanted).
    cel_factors = None
    if buffers is not None:
        from .toon import cel_shade
        cel_factors = cel_shade(view_normals, light=light, bands=buffers.get(
            "bands", 4))

    for tri in tri_indices:
        i0, i1, i2 = int(tri[0]), int(tri[1]), int(tri[2])
        ax, ay, az = px[i0], py[i0], zs[i0]
        bx, by, bz = px[i1], py[i1], zs[i1]
        cx2, cy2, cz = px[i2], py[i2], zs[i2]

        minx = max(int(math.floor(min(ax, bx, cx2))), 0)
        maxx = min(int(math.ceil(max(ax, bx, cx2))), W - 1)
        miny = max(int(math.floor(min(ay, by, cy2))), 0)
        maxy = min(int(math.ceil(max(ay, by, cy2))), W - 1)
        if minx > maxx or miny > maxy:
            continue

        area = (bx - ax) * (cy2 - ay) - (by - ay) * (cx2 - ax)
        if abs(area) < 1e-9:
            continue

        gx, gy = np.meshgrid(np.arange(minx, maxx + 1) + 0.5,
                             np.arange(miny, maxy + 1) + 0.5)
        w0 = ((bx - ax) * (gy - ay) - (by - ay) * (gx - ax)) / area
        w1 = ((cx2 - bx) * (gy - by) - (cy2 - by) * (gx - bx)) / area
        w2 = 1.0 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue

        depth = w1 * az + w2 * bz + w0 * cz
        sub_z = zbuf[miny:maxy + 1, minx:maxx + 1]
        nearer = inside & (depth < sub_z)
        if not nearer.any():
            continue

        if silhouette:
            shade = base
        else:
            n = view_normals[tri].mean(axis=0)
            nn = float(np.linalg.norm(n))
            n = n / nn if nn > 1e-9 else np.array([0.0, 0.0, 1.0])
            lam = abs(float(np.dot(n, light)))
            shade = base * (0.30 + 0.70 * lam)

        sub_img = img[miny:maxy + 1, minx:maxx + 1]
        for c in range(3):
            ch = sub_img[..., c]
            ch[nearer] = shade[c]
            sub_img[..., c] = ch
        sub_img[..., 3][nearer] = 255.0
        sub_z[nearer] = depth[nearer]

        if buffers is not None:
            nmean = view_normals[tri].mean(axis=0)
            nn = float(np.linalg.norm(nmean))
            if nn > 1e-9:
                nmean = nmean / nn
            nbuf_tile = nbuf[miny:maxy + 1, minx:maxx + 1]
            nbuf_tile[nearer] = nmean
            cbuf_tile = cbuf[miny:maxy + 1, minx:maxx + 1]
            cbuf_tile[nearer] = float(cel_factors[tri].mean())
            dvals = depth_vals[miny:maxy + 1, minx:maxx + 1]
            dvals[nearer] = depth[nearer]

    return img


def render_view(mesh, yaw_deg: float = 0.0, pitch_deg: float = 0.0,
                size: int = 256, color=(0.72, 0.74, 0.82),
                silhouette: bool = False, supersample: int = 2) -> np.ndarray:
    """Render one orthographic view of *mesh* as ``(size, size, 4)`` floats.

    Returns float32 RGBA in 0..1 (the render-boundary contract);
    conversion to uint8 happens only at the sprite-sheet export edge.
    """
    verts = np.asarray(mesh.vertices, dtype=np.float64)
    tris = np.asarray(mesh.indices, dtype=np.int64)
    if len(verts) == 0 or len(tris) == 0:
        return np.zeros((size, size, 4), dtype=np.float32)

    rot = _rotation_y(yaw_deg) @ _rotation_x(pitch_deg)
    view_verts = (rot @ verts.T).T

    normals = np.asarray(mesh.normals, dtype=np.float64)
    view_normals = ((rot @ normals.T).T
                    if len(normals) == len(verts) else view_verts * 0.0)

    light = np.array([0.45, 0.75, 0.55])
    light = light / np.linalg.norm(light)

    ss = max(int(supersample), 1)
    img = _rasterize(view_verts, view_normals, tris, int(size), ss,
                     color, bool(silhouette), light)

    if ss > 1:
        if _HAS_PIL:
            pil = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8))
            return np.asarray(pil.resize((size, size), Image.LANCZOS),
                              dtype=np.float32) / 255.0
        # Block-mean downsample when PIL is unavailable.
        img = img.reshape(size, ss, size, ss, 4).mean(axis=(1, 3))
    return (img[:size, :size] / 255.0).astype(np.float32)


def render_sprite_sheet(mesh, views: int = 8, size: int = 256,
                        color=(0.72, 0.74, 0.82), silhouette: bool = False,
                        columns: int | None = None, pitch_deg: float = 12.0):
    """Render *mesh* from *views* orbit angles into one RGBA sprite sheet."""
    views = max(int(views), 1)
    size = max(int(size), 16)
    frames = [
        render_view(mesh, yaw_deg=360.0 * i / views, pitch_deg=pitch_deg,
                    size=size, color=color, silhouette=silhouette)
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

    if not _HAS_PIL:
        return sheet
    return Image.fromarray(sheet, "RGBA")


def save_sprite_sheet(mesh, path: str, **kwargs):
    """Render a sprite sheet for *mesh* and write it to *path* as PNG."""
    sheet = render_sprite_sheet(mesh, **kwargs)
    if isinstance(sheet, np.ndarray):
        if not _HAS_PIL:
            raise RuntimeError("Pillow is required to write PNG files")
        sheet = Image.fromarray(sheet, "RGBA")
    sheet.save(path, format="PNG")
    return path