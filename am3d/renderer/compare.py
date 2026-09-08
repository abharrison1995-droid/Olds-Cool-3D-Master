"""Numeric and tolerant comparison helpers for rendered scene images.

Used to check that a scene's render is unaffected by a save/reload
round-trip (Phase 4, V3 plan Section 8): the same evaluated scene should
paint the same pixels before and after going through the project
serializer, under fixed camera/render settings.
"""

from __future__ import annotations

import io

import numpy as np

try:
    from PIL import Image
    _HAS_PIL = True
except Exception:  # pragma: no cover
    _HAS_PIL = False


def image_diff_stats(a: np.ndarray, b: np.ndarray) -> dict:
    """Max/mean absolute per-channel difference between two float RGBA images."""
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    if a.shape != b.shape:
        return {"max_abs_diff": float("inf"), "mean_abs_diff": float("inf"),
                "shape_mismatch": True}
    diff = np.abs(a - b)
    return {"max_abs_diff": float(diff.max()) if diff.size else 0.0,
            "mean_abs_diff": float(diff.mean()) if diff.size else 0.0,
            "shape_mismatch": False}


def png_roundtrip(img: np.ndarray) -> np.ndarray:
    """Quantize a float32 0..1 RGBA render through an actual PNG encode/decode.

    Mirrors what happens to a rendered frame once it is saved as a sprite
    sheet / animation frame on disk (float -> uint8 -> PNG bytes -> uint8),
    so a "tolerant image comparison" measures the same precision loss a
    human opening the exported PNG would see, not bit-exact floats.
    """
    u8 = (np.clip(img, 0.0, 1.0) * 255.0).astype(np.uint8)
    if not _HAS_PIL:
        return u8
    buf = io.BytesIO()
    Image.fromarray(u8, "RGBA").save(buf, format="PNG")
    buf.seek(0)
    return np.asarray(Image.open(buf).convert("RGBA"), dtype=np.uint8)


def assert_renders_match(a: np.ndarray, b: np.ndarray, *,
                         exact_atol: float = 1e-6,
                         png_mean_atol: float = 2.0) -> None:
    """Assert two renders of "the same" scene are equivalent two ways.

    1. Numeric: the raw float buffers must match almost exactly — the
       renderer is a deterministic function of scene geometry, so any
       divergence beyond floating-point noise means the reload changed
       something real (a dropped transform, a flipped visibility flag).
    2. Tolerant: after quantizing both through an actual PNG round-trip
       (what an exported/inspected image really looks like), the mean
       per-channel difference must stay small — catching regressions a
       purely numeric check could miss if it were loosened, while
       tolerating ordinary 8-bit quantization noise.
    """
    stats = image_diff_stats(a, b)
    assert not stats["shape_mismatch"], (
        f"render shape changed after reload: {a.shape} vs {b.shape}")
    assert stats["max_abs_diff"] <= exact_atol, (
        f"numeric render diverged after reload: {stats}")

    a8 = png_roundtrip(a)
    b8 = png_roundtrip(b)
    diff = np.abs(a8.astype(np.float64) - b8.astype(np.float64))
    mean_diff = float(diff.mean()) if diff.size else 0.0
    assert mean_diff <= png_mean_atol, (
        f"PNG-quantized renders diverged after reload: mean abs diff {mean_diff}")
