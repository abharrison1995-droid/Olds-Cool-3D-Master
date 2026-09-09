"""Baked texture images for export (finding MAT-01).

A patterned or image-backed material bakes into a per-object atlas whose
layout matches the UVs the tessellator already writes into every OBJ and GLB.
Until this module existed the exporters wrote those UVs but no image, so a
checkerboard material arrived in an independent reader as flat white -- the
appearance was silently lost rather than refused.

Everything here works on the export boundary's float RGBA 0..1 convention and
converts to 8-bit only at the PNG edge.
"""

from __future__ import annotations

import io

import numpy as np

PNG_MIME = "image/png"


def to_uint8_rgba(image):
    """Normalise a baked atlas to an ``(H, W, 4)`` uint8 array.

    Accepts float 0..1 (the renderer's convention) or an existing uint8
    array, and greyscale/RGB/RGBA channel counts.
    """
    arr = np.asarray(image)
    if arr.ndim == 2:
        arr = arr[:, :, None]
    if arr.ndim != 3:
        raise ValueError(
            f"texture must be a 2-D or 3-D image array, got shape {arr.shape}")
    if arr.dtype != np.uint8:
        arr = np.clip(np.asarray(arr, dtype=np.float64), 0.0, 1.0) * 255.0
        arr = arr.round().astype(np.uint8)
    channels = arr.shape[2]
    if channels == 1:
        arr = np.repeat(arr, 3, axis=2)
        channels = 3
    if channels == 3:
        alpha = np.full(arr.shape[:2] + (1,), 255, dtype=np.uint8)
        arr = np.concatenate([arr, alpha], axis=2)
    elif channels != 4:
        raise ValueError(f"texture must have 1, 3 or 4 channels, got {channels}")
    return np.ascontiguousarray(arr)


def encode_png(image) -> bytes:
    """Encode a baked atlas as PNG bytes.

    The image is flipped vertically because both OBJ and glTF put UV origin
    at the bottom-left of the image while the baked atlas is stored top-row
    first; without the flip the pattern exports upside down.
    """
    from PIL import Image

    arr = to_uint8_rgba(image)[::-1]
    buf = io.BytesIO()
    Image.fromarray(arr, mode="RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def texture_filename(stem: str, object_name: str) -> str:
    """Sidecar image filename for one object's atlas, next to the export.

    Object names are sanitised for the filesystem, which is lossy: "a b" and
    "a/b" both reduce to "a_b". A short digest of the *original* name is
    appended whenever sanitising changed anything, so two objects can never
    silently overwrite each other's atlas. The digest is a pure function of
    the name, so repeated exports of the same scene produce the same
    filenames.
    """
    import hashlib

    name = str(object_name)
    safe = "".join(c if (c.isalnum() or c in "-_") else "_" for c in name)
    if safe != name or not safe:
        digest = hashlib.blake2s(name.encode("utf-8"),
                                 digest_size=4).hexdigest()
        safe = f"{safe or 'object'}_{digest}"
    return f"{stem}_{safe}.png"
