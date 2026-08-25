"""Procedural texture generation and atlas baking (Material Mode engine).

Turns a :class:`~am3d.core.project.Material` into real pixel data:
albedo maps generated procedurally (checker, bricks, noise, gradients) or
loaded from disk, then baked into the UV-atlas cells the tessellator
reserves per patch — so an object renders with one shared texture.
"""

from __future__ import annotations

import numpy as np


# ---------------------------------------------------------------------------
# Pattern generators — each returns float RGBA in 0..1, shape (size, size, 4)
# ---------------------------------------------------------------------------
def _grid(size: int) -> tuple:
    y, x = np.mgrid[0:size, 0:size]
    return (x.astype(np.float64) / max(size - 1, 1),
            y.astype(np.float64) / max(size - 1, 1))


def _to_rgba(rgb: np.ndarray, alpha: float = 1.0) -> np.ndarray:
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[..., None], 3, axis=2)
    out = np.zeros((rgb.shape[0], rgb.shape[1], 4), dtype=np.float64)
    out[..., :3] = np.clip(rgb, 0.0, 1.0)
    out[..., 3] = alpha
    return out


def _resize(tex: np.ndarray, height: int, width: int) -> np.ndarray:
    """Resize a float RGBA texture (nearest via index ladders; PIL if present)."""
    try:
        from PIL import Image
    except ImportError:              # pragma: no cover
        ys = np.linspace(0, tex.shape[0] - 1, height).astype(np.int64)
        xs = np.linspace(0, tex.shape[1] - 1, width).astype(np.int64)
        return tex[np.ix_(ys, xs)]
    img = Image.fromarray(
        np.clip(tex * 255.0, 0, 255).astype(np.uint8), "RGBA")
    return np.asarray(img.resize((width, height), Image.LANCZOS),
                      dtype=np.float64) / 255.0


def solid(color=(0.8, 0.8, 0.8), size: int = 64) -> np.ndarray:
    """Flat colour fill."""
    return _to_rgba(np.tile(np.asarray(color[:3], dtype=np.float64),
                            (size, size, 1)))


def checkerboard(a=(0.9, 0.9, 0.9), b=(0.25, 0.25, 0.28), cells: int = 8,
                 size: int = 256) -> np.ndarray:
    u, v = _grid(size)
    block = (np.floor(u * cells).astype(np.int64)
             + np.floor(v * cells).astype(np.int64)) % 2
    ca, cb = np.asarray(a[:3]), np.asarray(b[:3])
    rgb = np.where(block[..., None] == 0, ca, cb)
    return _to_rgba(np.broadcast_to(rgb, (size, size, 3)))


def gradient(top=(1.0, 1.0, 1.0), bottom=(0.2, 0.2, 0.25),
             size: int = 256) -> np.ndarray:
    _, v = _grid(size)
    t = v[..., None]
    rgb = np.asarray(bottom[:3]) * (1 - t) + np.asarray(top[:3]) * t
    return _to_rgba(np.broadcast_to(rgb, (size, size, 3)))


def noise(seed: int = 7, size: int = 256, octaves: int = 4,
          base=(0.75, 0.72, 0.68), contrast: float = 0.25) -> np.ndarray:
    """Value-noise mottling — stone / plaster / skin base coats."""
    rng = np.random.default_rng(seed)
    acc = np.zeros((size, size))
    amp, total_amp = 1.0, 0.0
    for o in range(max(int(octaves), 1)):
        cell = max(2, size >> (o + 1))
        coarse = rng.random((cell, cell))
        ys = (np.arange(size) * cell / size).astype(np.int64)
        acc += amp * coarse[np.ix_(ys, ys)]
        total_amp += amp
        amp *= 0.5
    acc /= max(total_amp, 1e-9)
    acc = (acc - acc.mean()) / max(acc.std(), 1e-9)
    shade = 1.0 + contrast * np.tanh(acc)
    base_arr = np.asarray(base[:3], dtype=np.float64)
    rgb = np.clip(base_arr[None, None, :] * shade[..., None], 0.0, 1.0)
    return _to_rgba(np.broadcast_to(rgb, (size, size, 3)))


def bricks(brick=(0.62, 0.28, 0.18), mortar=(0.82, 0.80, 0.76),
           rows: int = 8, cols: int = 4, mortar_px: float = 4.0,
           size: int = 256) -> np.ndarray:
    """Running-bond brick pattern with offset courses."""
    u, v = _grid(size)
    row_h = 1.0 / rows
    row = np.floor(v / row_h).astype(np.int64)
    uu = (u + (row % 2) * 0.5) % 1.0
    col_w = 1.0 / cols
    col = np.floor(uu / col_w).astype(np.int64)

    in_mortar_v = ((v - row * row_h) < mortar_px / size) | \
                  (((row + 1) * row_h - v) < mortar_px / size)
    frac_u = (uu - col * col_w) * size
    in_mortar_u = (frac_u < mortar_px) | \
                  ((col_w * size - frac_u) < mortar_px)
    is_mortar = in_mortar_v | in_mortar_u

    # Per-brick tint variation via a stable hash of (row, col).
    h = (row * 73856093) ^ (col * 19349663)
    tint = (0.85 + 0.30 * ((h & 0xFF) / 255.0))[..., None]
    cb = np.clip(np.asarray(brick[:3])[None, None, :] * tint, 0.0, 1.0)
    cm = np.asarray(mortar[:3])[None, None, :]
    rgb = np.where(is_mortar[..., None], cm, cb[0])
    return _to_rgba(np.broadcast_to(rgb, (size, size, 3)))


PATTERNS = {
    "solid": solid,
    "checker": checkerboard,
    "gradient": gradient,
    "noise": noise,
    "bricks": bricks,
}


# ---------------------------------------------------------------------------
# Derived maps & image I/O
# ---------------------------------------------------------------------------
def height_to_normal(height: np.ndarray, strength: float = 2.0) -> np.ndarray:
    """Central differences on a height map -> tangent-space RGB normal map."""
    h = np.asarray(height, dtype=np.float64)
    dx = (np.roll(h, -1, axis=1) - np.roll(h, 1, axis=1)) * 0.5
    dy = (np.roll(h, -1, axis=0) - np.roll(h, 1, axis=0)) * 0.5
    nx = -dx * strength
    ny = -dy * strength
    nz = np.ones_like(h)
    length = np.sqrt(nx * nx + ny * ny + nz * nz)
    rgb = np.stack([(nx / length + 1) * 0.5,
                    (ny / length + 1) * 0.5,
                    (nz / length + 1) * 0.5], axis=-1)
    return np.clip(rgb, 0.0, 1.0)


def load_image(path: str, size: int | None = None) -> np.ndarray:
    """Load an image from disk as normalized RGBA floats."""
    try:
        from PIL import Image
    except ImportError as exc:      # pragma: no cover
        raise RuntimeError("Pillow required to load textures") from exc
    img = Image.open(path).convert("RGBA")
    if size is not None:
        img = img.resize((size, size), Image.LANCZOS)
    return np.asarray(img, dtype=np.float64) / 255.0


def save_image(texture: np.ndarray, path: str) -> str:
    """Write a normalized float texture to *path*."""
    try:
        from PIL import Image
    except ImportError as exc:      # pragma: no cover
        raise RuntimeError("Pillow required to save textures") from exc
    arr = np.clip(np.asarray(texture) * 255.0, 0, 255).astype(np.uint8)
    mode = "RGBA" if arr.ndim == 3 and arr.shape[-1] == 4 else "RGB"
    Image.fromarray(arr, mode).save(path)
    return path


def resolve_albedo(material, size: int = 256, seed: int = 7,
                   pattern: str | None = None,
                   params: dict | None = None) -> np.ndarray:
    """The material's albedo RGBA map.

    Resolution order: a node ``graph`` attribute, an explicit *pattern*
    argument or the material's own ``pattern``/``params``/``texture``
    attributes, then a flat ``material.color`` fill.
    """
    graph_specs = getattr(material, "graph", None)
    if graph_specs:
        from ..core.material_graph import MaterialGraph
        g = MaterialGraph.from_dicts(graph_specs)
        problems = g.validate()
        if problems:
            raise ValueError("invalid material graph: " + "; ".join(problems))
        return _resize(g.evaluate(size=size), size, size)

    pattern = pattern or getattr(material, "pattern", None)
    params = params or dict(getattr(material, "params", {}) or {})
    texture_path = getattr(material, "texture", None)

    if texture_path:
        return load_image(texture_path, size=size)
    if isinstance(pattern, str):
        key = pattern.lower()
        if key not in PATTERNS:
            raise ValueError(f"unknown pattern {pattern!r} "
                             f"(choose from {sorted(PATTERNS)})")
        params.setdefault("size", size)
        if key == "noise":
            params.setdefault("seed", seed)
        try:
            tex = PATTERNS[key](**params)
        except TypeError as exc:
            raise ValueError(
                f"pattern {key!r} got bad params {params!r}: {exc}") from exc
        if tex.shape[0] != size or tex.shape[1] != size:
            tex = _resize(tex, size, size)
        return tex
    color = getattr(material, "color", None)
    if color is None:
        color = params.get("color", (0.8, 0.8, 0.8))
    return solid(color, size=size)


def bake_atlas(mesh, materials_by_patch: dict, cell_size: int = 256,
               seed: int = 7, columns: int | None = None) -> np.ndarray:
    """Bake per-patch albedo maps into one atlas matching the mesh's UVs.

    Uses :func:`am3d.renderer.uv_mapping.atlas_grid_layout` with the same
    column count the tessellator used, so each patch's tile lands exactly on
    its UV cell.
    """
    from .uv_mapping import atlas_grid_layout

    names = list(materials_by_patch)
    if not names:
        return solid((0.8, 0.8, 0.8), size=cell_size)

    cols = columns if columns and columns > 0 else \
        max(int(np.ceil(np.sqrt(len(names)))), 1)
    rows = max(int(np.ceil(len(names) / cols)), 1)
    atlas = np.ones((rows * cell_size, cols * cell_size, 4),
                    dtype=np.float64)
    cells = atlas_grid_layout(len(names), columns=cols)

    for name, (ou, ov, su, sv) in zip(names, cells):
        mat = materials_by_patch[name]
        tile = resolve_albedo(mat, size=cell_size, seed=seed)
        r0 = int(round(ov * rows * cell_size))
        c0 = int(round(ou * cols * cell_size))
        rh = max(int(round(sv * rows * cell_size)), 1)
        ch = max(int(round(su * cols * cell_size)), 1)
        atlas[r0:r0 + rh, c0:c0 + ch] = \
            _resize(tile, rh, ch)[:rh, :ch]
    return np.clip(atlas, 0.0, 1.0)