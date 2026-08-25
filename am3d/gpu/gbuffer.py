"""G-buffer: multi-render-target FBO for deferred shading.

Binds position (RGB32F), normal (RGB16F), and albedo+RMA (RGBA8) render targets.
"""

from __future__ import annotations

import numpy as np


class GBuffer:
    """A multi-render-target framebuffer for deferred shading.

    Attachments:
        0 — world position  (R32F)
        1 — view normal     (RGB16F)
        2 — albedo + RMA    (RGBA8)  r=albedo_r g=albedo_g b=albedo_b a=roughness
    Also encodes metalness in position.a (via shader).

    The depth buffer is shared for early-z.
    """

    def __init__(self, ctx, width: int, height: int):
        self.ctx = ctx
        self.width = width
        self.height = height
        self.fbo = None
        self._attachments = []
        self._depth = None
        self._build()

    def _build(self):
        import moderngl
        ctx = self.ctx
        W, H = self.width, self.height

        # Position (RGB32F)
        pos_tex = ctx.texture((W, H), 4, dtype="f4")
        pos_tex.repeat_x = False
        pos_tex.repeat_y = False
        pos_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)

        # Normal (RGB16F)
        nrm_tex = ctx.texture((W, H), 4, dtype="f2")
        nrm_tex.repeat_x = False
        nrm_tex.repeat_y = False
        nrm_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)

        # Albedo (RGBA8)
        alb_tex = ctx.texture((W, H), 4, dtype="f1")
        alb_tex.repeat_x = False
        alb_tex.repeat_y = False
        alb_tex.filter = (moderngl.NEAREST, moderngl.NEAREST)

        # Depth
        depth = ctx.depth_texture((W, H))

        self._attachments = [pos_tex, nrm_tex, alb_tex]
        self._depth = depth

        self.fbo = ctx.framebuffer(
            color_attachments=self._attachments,
            depth_attachment=depth,
        )

    def bind(self):
        self.fbo.use()
        self.ctx.viewport = (0, 0, self.width, self.height)
        self.ctx.clear(0.0, 0.0, 0.0, 1.0)

    def unbind(self):
        # Restore the previous framebuffer (detect if we are chained)
        try:
            self.ctx.screen.use()
        except Exception:
            pass

    def position(self) -> np.ndarray:
        """Read back the world-position buffer as (H, W, 4) float32."""
        return np.frombuffer(
            self._attachments[0].read(), dtype=np.float32
        ).reshape(self.height, self.width, 4)

    def normal(self) -> np.ndarray:
        """Read back the normal buffer as (H, W, 4) float16 cast to float32."""
        raw = np.frombuffer(self._attachments[1].read(), dtype=np.float16)
        return raw.reshape(self.height, self.width, 4).astype(np.float32)

    def albedo_roughness(self) -> np.ndarray:
        """Read back the albedo+roughness buffer as (H, W, 4) uint8 -> float32."""
        raw = np.frombuffer(self._attachments[2].read(), dtype=np.uint8)
        return raw.reshape(self.height, self.width, 4).astype(np.float32) / 255.0

    def depth(self) -> np.ndarray:
        """Read back the depth buffer as (H, W) float32."""
        raw = np.frombuffer(self._depth.read(), dtype=np.float32)
        return raw.reshape(self.height, self.width)

    def read_back(self) -> dict:
        """Return all buffers as numpy arrays (for CPU compositing)."""
        return {
            "position": self.position(),
            "normal": self.normal(),
            "albedo": self.albedo_roughness(),
            "depth": self.depth(),
        }

    def release(self):
        for tex in self._attachments:
            tex.release()
        if self._depth:
            self._depth.release()
        self.fbo.release()