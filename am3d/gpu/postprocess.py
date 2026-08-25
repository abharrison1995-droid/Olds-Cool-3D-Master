"""Post-processing: tone-mapping, fog, god rays (volumetrics)."""

from __future__ import annotations

import numpy as np


def tone_map(rgba: np.ndarray, exposure: float = 1.0,
             gamma: float = 2.2) -> np.ndarray:
    """Simple Reinhard tone-map + gamma correction.

    *rgba* is (H, W, 3 or 4) float32 in [0, inf). Returns (H, W, 3 or 4) in [0, 1].
    """
    out = np.asarray(rgba, dtype=np.float64)
    out = out * exposure / (1.0 + out * exposure)
    out = np.power(np.maximum(out, 0.0), 1.0 / gamma)
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def apply_fog(rgba: np.ndarray, depth: np.ndarray,
              fog_color=(0.6, 0.65, 0.72), density: float = 0.15,
              height_falloff: float = 0.0, camera_height: float = 0.0
              ) -> np.ndarray:
    """Exponential height fog blending.

    *rgba* (H, W, 3) — pre-tonemap linear color.
    *depth* (H, W) — per-pixel view depth (any distance unit).

    Returns (H, W, 3) fog-blended linear color.
    """
    rgba = np.asarray(rgba, dtype=np.float64)
    depth = np.asarray(depth, dtype=np.float64)
    fc = np.asarray(fog_color[:3], dtype=np.float64)

    fog_factor = np.exp(-density * depth)

    if float(height_falloff) > 0.0:
        h_factor = np.exp(-height_falloff * np.abs(depth) * 0.1)
        fog_factor = np.minimum(fog_factor, h_factor)

    fog_factor = np.clip(fog_factor, 0.0, 1.0)

    out = rgba * fog_factor[..., None] + fc * (1.0 - fog_factor[..., None])
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def god_rays(light_screen_pos: tuple,
             shadow: np.ndarray, intensity: float = 0.3,
             decay: float = 0.95, samples: int = 32) -> np.ndarray:
    """Screen-space god rays (radial blur from light position).

    *shadow* — (H, W, 3) pre-tonemap RGB; light_screen_pos — (x, y) in pixels.
    Returns (H, W, 3) layered god-ray contribution (add to scene).
    """
    shadow = np.asarray(shadow, dtype=np.float64)
    H, Ws = shadow.shape[:2]
    lx, ly = float(light_screen_pos[0]), float(light_screen_pos[1])
    rays = np.zeros_like(shadow)
    illum = 1.0

    for i in range(max(samples, 1)):
        illum *= decay
        offset = (i + 1) * (1.0 / max(samples, 1))

        # Compute sample coordinate shift per pixel
        dx = (np.arange(Ws, dtype=np.float64) - lx) * offset
        dy = (np.arange(H, dtype=np.float64) - ly) * offset

        # Build shift grids
        sx = np.clip(lx + dx, 0, Ws - 1).astype(np.int64)
        sy = np.clip(ly + dy, 0, H - 1).astype(np.int64)

        # Sample at shifted coords
        for c in range(min(shadow.shape[2], 3)):
            rays[..., c] += illum * shadow[sy[:, None], sx, c]

        # Crude radial sample: downsampled contribution every 4th iteration
        if i % 4 == 0 and i > 0:
            ds = max(1, i // 4)
            if ds < min(H, Ws) // 2:
                small = shadow[::ds, ::ds]
                small_ray = illum * small.repeat(ds, axis=0).repeat(ds, axis=1)[:H, :Ws]
                for c in range(min(shadow.shape[2], 3)):
                    rays[..., c] += small_ray[..., c]

    rays *= float(intensity)
    # Clip negative (can happen from repeated ds samples near boundaries)
    rays = np.clip(rays, 0.0, None)
    return rays.astype(np.float32)