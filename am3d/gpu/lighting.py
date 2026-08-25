"""Deferred lighting pass — reads G-buffer, writes final RGBA."""

from __future__ import annotations

import numpy as np


def light_pass(ctx, program, gbuffer, lights=None):
    """Full-screen quad lighting pass reading GBuffer textures.

    *lights* is a list of dicts with keys ``dir`` (3-vec), ``color`` (3-vec),
    ``ambient`` (float).  When omitted/empty a single warm key light is used.

    The lighting shader is single-directional, so each light is accumulated
    into a CPU buffer (ambient applied only once, on the first pass).
    Returns (H, W, 4) float32 RGBA.
    """
    W, H = gbuffer.width, gbuffer.height

    if lights is None:
        lights = []
    if not lights:
        lights = [{"dir": (0.45, 0.75, 0.55),
                   "color": (1.0, 0.98, 0.92), "ambient": 0.25}]

    # Build a full-screen quad VAO (two triangles covering clip space).
    quad_v = np.array([
        [-1, -1, 0], [1, -1, 0], [1, 1, 0],
        [-1, -1, 0], [1, 1, 0], [-1, 1, 0],
    ], dtype="f4")
    quad_uv = np.array([
        [0, 0], [1, 0], [1, 1],
        [0, 0], [1, 1], [0, 1],
    ], dtype="f4")

    vbo_v = ctx.buffer(quad_v.tobytes())
    vbo_uv = ctx.buffer(quad_uv.tobytes())
    vao = ctx.vertex_array(program.prog, [
        (vbo_v, "3f", "in_position"),
        (vbo_uv, "2f", "in_uv"),
    ])

    # Bind G-buffer textures once
    gbuf_attachments = gbuffer._attachments
    program["u_position"] = 0
    program["u_normal"] = 1
    program["u_albedo"] = 2
    gbuf_attachments[0].use(0)
    gbuf_attachments[1].use(1)
    gbuf_attachments[2].use(2)

    # Create output FBO
    out_tex = ctx.texture((W, H), 4, dtype="f1")
    out_fbo = ctx.framebuffer(color_attachments=[out_tex])
    out_fbo.use()
    ctx.viewport = (0, 0, W, H)

    accumulated = None
    for i, light in enumerate(lights):
        ldir = light.get("dir", (0.45, 0.75, 0.55))
        lcol = light.get("color", (1.0, 0.98, 0.92))
        amb = float(light.get("ambient", 0.25) if i == 0 else 0.0)

        program["u_light_dir"] = ldir
        program["u_light_color"] = lcol
        program["u_ambient"] = amb
        ctx.clear(0.0, 0.0, 0.0, 1.0)
        vao.render()

        raw = np.frombuffer(out_tex.read(), dtype=np.uint8)
        rgba = raw.reshape(H, W, 4).astype(np.float32) / 255.0
        accumulated = rgba if accumulated is None else accumulated + rgba

    out_fbo.release()
    out_tex.release()
    vao.release()
    vbo_v.release()
    vbo_uv.release()
    return np.clip(accumulated, 0.0, 1.0)