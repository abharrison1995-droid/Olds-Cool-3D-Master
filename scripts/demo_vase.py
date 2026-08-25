"""End-to-end headless demo of the 3D MASTER:2005 spline pipeline.

This script is exactly what an external agentic pipeline can run to drive
the software: build a model from splines, rig it, animate a reusable Action,
tessellate to renderable triangles, and persist assets — all without a GUI.

Run:
    python scripts/demo_vase.py
"""

from __future__ import annotations

import os
import sys

# Make the in-tree `am3d` package importable when running the demo directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from am3d.core import script
from am3d.renderer import tessellate_project


def main() -> int:
    s = script.Session()
    s.new_project("Vase demo")

    # --- Object Mode: a vase from a profile spline, lathed into a surface ---
    s.create_object("vase")
    s.add_spline("vase",
                 [(0.4, 0.0, 0.0), (1.0, 0.6, 0.0), (0.7, 1.4, 0.0),
                  (0.9, 2.0, 0.0), (0.3, 2.6, 0.0)],
                 name="profile")
    s.lathe_spline("vase", "profile", axis="y", sections=24)
    print(f"[object] vase created with {len(s.get_object('vase').patches)} patch(es)")

    # --- Segment Mode: skeleton for a character -----------------------------
    s.create_object("hero")
    s.add_bone("hero", "hip", (0, 0, 0), (0, 0.5, 0))
    s.add_bone("hero", "upper", (0, 0.5, 0), (0, 1.0, 0), parent="hip")
    print("[segment] hero skeleton: hip -> upper")

    # --- Choreography Mode: reusable walk Action -----------------------------
    walk = s.create_action("walk", duration=1.0)
    ch = walk.add_channel("hip", "translate")
    ch.add_key(0.0, [0, 0, 0])
    ch.add_key(0.5, [0.25, 0, 0])
    ch.add_key(1.0, [0.5, 0, 0])
    walk.signature = ("hip->root", "upper->hip")
    s.apply_action_to_character("walk", "hero")
    print("[choreography] walk action applied to hero")

    # --- Render: tessellate all objects to renderable triangles -------------
    meshes = tessellate_project(s.project)
    for name, mesh in meshes.items():
        print(f"[render] {name}: {mesh.vertices.shape[0]} verts, "
              f"{mesh.indices.shape[0]} triangles, normals ok={mesh.normals.shape[0] > 0}")

    # --- Persist as reusable assets ------------------------------------------
    out = os.path.join(os.path.dirname(__file__), "..", "assets")
    os.makedirs(out, exist_ok=True)
    act_path = os.path.join(out, "walk.am3a")
    proj_path = os.path.join(out, "vase_demo.am3d")
    s.save_action_file("walk", act_path)
    from am3d.core.serializer import save_project
    save_project(s.project, proj_path)
    print(f"[assets] wrote {act_path}")
    print(f"[assets] wrote {proj_path}")
    print("demo complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())