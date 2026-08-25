"""Shared numeric helpers (pure numpy, dependency-light).

Kept separate from the B-spline kernel so geometry evaluators can run
under :mod:`numba` without pulling in the whole project.
"""

from __future__ import annotations

from typing import Iterable, Sequence

import numpy as np


def as_vec(p, dtype=np.float64):
    """Coerce *p* to a 1-D numpy array of a known float dtype."""
    v = np.asarray(p, dtype=dtype)
    if v.ndim == 0:
        v = v.reshape(1)
    return np.atleast_1d(v)


def cross(a, b) -> np.ndarray:
    """3-D cross product of two vectors (sequence or arrays)."""
    return np.cross(np.asarray(a, dtype=np.float64),
                    np.asarray(b, dtype=np.float64))


def normalize(v, eps: float = 1e-12) -> np.ndarray:
    """Normalize a vector, returning zeros if it is degenerate."""
    a = np.asarray(v, dtype=np.float64)
    n = np.linalg.norm(a)
    if n < eps:
        return np.zeros_like(a)
    return a / n


def rot_matrix(axis, angle) -> np.ndarray:
    """Rotation matrix about *axis* by *angle* radians (Rodrigues)."""
    axis = normalize(axis)
    x, y, z = axis
    c, s = np.cos(angle), np.sin(angle)
    C = 1.0 - c
    return np.array([
        [x * x * C + c,     x * y * C - z * s, x * z * C + y * s],
        [y * x * C + z * s, y * y * C + c,     y * z * C - x * s],
        [z * x * C - y * s, z * y * C + x * s, z * z * C + c],
    ])


def sample_range(start=0.0, end=1.0, n: int = 100) -> np.ndarray:
    """Return *n* sample parameters in [start, end] (inclusive)."""
    if n <= 0:
        return np.array([], dtype=np.float64)
    return np.linspace(start, end, max(n, 2))


def compose_trs(location, rotation_deg, scale) -> np.ndarray:
    """Build a 4x4 transform from location, Euler XYZ degrees and scale."""
    loc = np.asarray(location, dtype=np.float64).reshape(3)
    rx, ry, rz = np.deg2rad(np.asarray(rotation_deg, dtype=np.float64))
    s = np.asarray(scale, dtype=np.float64).reshape(3)
    m = (rot_matrix((0, 0, 1), rz) @ rot_matrix((0, 1, 0), ry)
         @ rot_matrix((1, 0, 0), rx))
    out = np.eye(4, dtype=np.float64)
    out[:3, :3] = m * s[None, :]
    out[:3, 3] = loc
    return out


def decompose_trs(transform):
    """Split a 4x4 transform into (location, Euler XYZ degrees, scale)."""
    m = np.asarray(transform, dtype=np.float64).reshape(4, 4)
    loc = m[:3, 3].copy()
    r = m[:3, :3]
    scale = np.linalg.norm(r, axis=0)
    scale = np.where(scale < 1e-12, 1e-12, scale)
    rn = r / scale[None, :]
    ry = np.arcsin(np.clip(-rn[2, 0], -1.0, 1.0))
    rx = np.arctan2(rn[2, 1], rn[2, 2])
    rz = np.arctan2(rn[1, 0], rn[0, 0])
    return loc, np.rad2deg([rx, ry, rz]), scale