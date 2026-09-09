"""Render the application icon with the application's own renderer.

The desktop entry in docs/QUICK_START.md needs an icon file, and the window
itself had none. Rather than ship unrelated artwork, the icon is a render of
a scene built by this engine, reproducible from source:

    QT_QPA_PLATFORM=offscreen .venv/bin/python scripts/make_icon.py

writes assets/icon.png (256x256 RGBA, transparent background).
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from am3d.core.script import Session                       # noqa: E402
from am3d.gpu import _software_render, resolve_scene       # noqa: E402
from am3d.ui.operators import CreatePrimitiveCommand       # noqa: E402

SIZE = 256


def main() -> int:
    session = Session()
    CreatePrimitiveCommand(session, "sphere", "sphere", {}).redo()
    CreatePrimitiveCommand(session, "torus", "torus", {}).redo()
    torus = session.project.objects["torus"]
    transform = torus.transform.copy()
    transform[:3, 3] = (0.0, -0.15, 0.0)
    torus.transform = transform

    meshes = [m for m in resolve_scene(session).meshes.values()
              if len(getattr(m, "indices", ()))]
    image = _software_render(meshes, SIZE, SIZE)

    rgba = (np.clip(np.asarray(image), 0.0, 1.0) * 255.0).round().astype("uint8")
    # The renderer leaves untouched pixels black with zero alpha; make that
    # explicit so the icon has a transparent background in a panel.
    rgba[..., 3] = np.where(rgba[..., :3].sum(axis=2) > 8, 255, 0)
    out = Path(__file__).resolve().parents[1] / "assets" / "icon.png"
    Image.fromarray(rgba, mode="RGBA").save(out)
    print(f"wrote {out} ({SIZE}x{SIZE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
