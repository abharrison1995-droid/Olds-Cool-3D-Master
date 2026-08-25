"""Orbit camera for the viewport (pure numpy, no Qt — headless-testable).

The camera orbits a *target* point: ``yaw``/``pitch`` (degrees) plus
``distance`` place the eye on a sphere around the target.  Panning
translates eye **and** target together so it never introduces rotation.

Conventions: +Y is world up, yaw=0/pitch=0 puts the eye on +Z looking
toward the target ("front"), yaw=90 looks from +X ("side"), pitch=90
straight down from +Y ("top").
"""

from __future__ import annotations

import math

import numpy as np

PITCH_LIMIT = 89.9
DISTANCE_RANGE = (0.1, 200.0)

# Numpad-style view presets: name -> (yaw_deg, pitch_deg)
PRESETS = {
    "front": (0.0, 0.0),
    "side": (90.0, 0.0),
    "top": (0.0, 90.0),
    "perspective": (45.0, 20.0),
}


class Camera:
    """Blender-style orbit camera with view/perspective matrices."""

    def __init__(self, yaw: float = 45.0, pitch: float = 20.0,
                 distance: float = 3.5, target=None, fov: float = 45.0):
        self.yaw = float(yaw)
        self.pitch = float(pitch)
        self.distance = float(distance)
        self.target = (np.zeros(3) if target is None
                       else np.asarray(target, dtype=np.float64).reshape(3))
        self.fov = float(fov)

    # -- pose -------------------------------------------------------------
    @property
    def eye(self) -> np.ndarray:
        """Eye position on the orbit sphere around the target."""
        yaw = math.radians(self.yaw)
        pitch = math.radians(self.pitch)
        return self.target + self.distance * np.array([
            math.cos(pitch) * math.sin(yaw),
            math.sin(pitch),
            math.cos(pitch) * math.cos(yaw),
        ])

    @property
    def forward(self) -> np.ndarray:
        """Unit view direction (eye -> target)."""
        f = self.target - self.eye
        return f / max(np.linalg.norm(f), 1e-12)

    def view_matrix(self) -> np.ndarray:
        """World -> camera look-at matrix (camera looks down -Z)."""
        eye = self.eye
        f = self.forward
        up = np.array([0.0, 1.0, 0.0])
        if abs(np.dot(f, up)) > 0.999:      # looking straight up/down
            up = np.array([1.0, 0.0, 0.0])
        s = np.cross(up, f)
        s = s / max(np.linalg.norm(s), 1e-12)
        u = np.cross(f, s)
        m = np.eye(4)
        m[0, :3] = s
        m[1, :3] = u
        m[2, :3] = -f
        m[:3, 3] = -m[:3, :3] @ eye
        return m

    def projection_matrix(self, aspect: float, near: float = 0.01,
                          far: float = 1000.0) -> np.ndarray:
        """OpenGL-style perspective matrix with correct aspect ratio."""
        aspect = max(float(aspect), 1e-6)
        f = 1.0 / math.tan(math.radians(self.fov) / 2.0)
        m = np.zeros((4, 4))
        m[0, 0] = f / aspect
        m[1, 1] = f
        m[2, 2] = (far + near) / (near - far)
        m[2, 3] = 2.0 * far * near / (near - far)
        m[3, 2] = -1.0
        return m

    # -- interaction --------------------------------------------------------
    def orbit(self, dyaw: float, dpitch: float):
        """Orbit the eye around the target (pitch clamped near the poles)."""
        self.yaw += float(dyaw)
        self.pitch = max(-PITCH_LIMIT, min(PITCH_LIMIT,
                                           self.pitch + float(dpitch)))

    def pan(self, dx_pixels: float, dy_pixels: float,
            viewport_height: float = 480.0):
        """Translate eye **and** target along camera right/up.

        ``dx_pixels``/``dy_pixels`` are screen-space pixel deltas; the step
        is scaled so the point under the cursor roughly follows it.
        """
        scale = (2.0 * self.distance
                 * math.tan(math.radians(self.fov) / 2.0)
                 / max(float(viewport_height), 1.0))
        m = self.view_matrix()
        right = m[0, :3]
        up = m[1, :3]
        self.target = self.target + right * (dx_pixels * scale) \
            + up * (-dy_pixels * scale)

    def zoom(self, factor: float):
        """Dolly toward/away from the target (clamped)."""
        lo, hi = DISTANCE_RANGE
        self.distance = max(lo, min(hi, self.distance * float(factor)))

    def set_view(self, preset: str):
        """Snap yaw/pitch to a named preset (front/side/top/perspective)."""
        if preset not in PRESETS:
            raise ValueError(f"unknown view preset {preset!r}")
        self.yaw, self.pitch = PRESETS[preset]

    # -- projection helpers ---------------------------------------------------
    def world_to_screen(self, points, width: float, height: float):
        """Project world points to widget pixels.

        Returns ``(xs, ys, valid)``; ``valid`` is False for points behind
        the camera (their coordinates are meaningless).
        """
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        aspect = max(float(width), 1.0) / max(float(height), 1.0)
        vp = self.projection_matrix(aspect) @ self.view_matrix()
        hom = np.concatenate([pts, np.ones((len(pts), 1))], axis=1)
        clip = hom @ vp.T
        w = clip[:, 3]
        valid = w > 1e-9
        safe_w = np.where(valid, w, 1.0)
        ndc = clip[:, :3] / safe_w[:, None]
        xs = (ndc[:, 0] * 0.5 + 0.5) * float(width)
        ys = (1.0 - (ndc[:, 1] * 0.5 + 0.5)) * float(height)
        return xs, ys, valid

    def view_ray(self, px: float, py: float, width: float, height: float):
        """World-space picking ray ``(origin, unit_dir)`` through a pixel."""
        aspect = max(float(width), 1.0) / max(float(height), 1.0)
        ndc_x = 2.0 * float(px) / max(float(width), 1.0) - 1.0
        ndc_y = 1.0 - 2.0 * float(py) / max(float(height), 1.0)
        t = math.tan(math.radians(self.fov) / 2.0)
        dir_cam = np.array([ndc_x * t * aspect, ndc_y * t, -1.0])
        rot = self.view_matrix()[:3, :3]     # world -> camera
        dir_world = rot.T @ dir_cam          # camera -> world
        dir_world = dir_world / max(np.linalg.norm(dir_world), 1e-12)
        return self.eye, dir_world
