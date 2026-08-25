"""High-level procedural geometry builders.

These are the vocabulary an LLM uses.  Instead of hand-placing B-spline
control points, a recipe says ``{"primitive": "sphere", "params":
{"radius": 0.6}}`` and one of the functions below produces the spline
control net(s).

Every builder returns a plain dict::

    {
        "patches": [(patch_name, control_net, degree_u, degree_v), ...],
        "splines": [(spline_name, points, degree, closed), ...],
    }

which :mod:`am3d.recipes.executor` turns into real Patches/Splines.
Control nets are ``(nu, nv, 3)`` arrays ready for
:func:`am3d.spline.kernel.build_patch_grid`.
"""

from __future__ import annotations

import numpy as np

from am3d.spline import kernel


def _clamp_degree(requested: int, count: int) -> int:
    """Largest usable degree <= *requested* given *count* control points."""
    return int(max(1, min(requested, count - 1)))


def _closed_lathe(profile, axis: str = "y", sections: int = 16) -> np.ndarray:
    """Lathe *profile* and duplicate the first ring so the revolution closes.

    ``kernel.build_lathe_net`` samples angles in ``[0, 2*pi)`` — the last
    section stops one step short of the first.  Appending a copy of row 0
    closes the loop with a zero-width segment (harmless when tessellated).
    """
    net = kernel.build_lathe_net(profile, axis=axis, sections=int(sections))
    return np.concatenate([net, net[:1]], axis=0)


def _face_grid(corner, du, dv, n: int = 4) -> np.ndarray:
    """An ``n x n`` coplanar control grid spanning corner -> corner+du+dv."""
    corner = np.asarray(corner, dtype=np.float64)
    du = np.asarray(du, dtype=np.float64)
    dv = np.asarray(dv, dtype=np.float64)
    u = np.linspace(0.0, 1.0, n)
    return (corner[None, None, :]
            + u[:, None, None] * du[None, None, :]
            + u[None, :, None] * dv[None, None, :])


# ---------------------------------------------------------------------------
# Revolution (lathe) family
# ---------------------------------------------------------------------------
def make_sphere(radius: float = 1.0, sections: int = 16, rings: int = 8):
    """UV-sphere: a lathed semicircular profile, poles pinched to the axis."""
    sections = max(int(sections), 4)
    rings = max(int(rings), 4)
    theta = np.linspace(0.0, np.pi, rings)
    profile = np.stack([radius * np.sin(theta), radius * np.cos(theta)], axis=1)
    net = _closed_lathe(profile, axis="y", sections=sections)
    return {"patches": [("sphere", net,
                         _clamp_degree(3, net.shape[0]),
                         _clamp_degree(3, net.shape[1]))],
            "splines": []}


def make_cylinder(radius: float = 0.5, height: float = 1.0,
                  sections: int = 16, capped: bool = True, rings: int = 4):
    """Cylinder along +Y; optional caps via pinched end rings."""
    sections = max(int(sections), 4)
    rings = max(int(rings), 4)
    ys = np.linspace(0.0, float(height), rings)
    profile = np.stack([np.full(rings, float(radius)), ys], axis=1)
    if capped:
        profile = np.concatenate([
            np.array([[0.0, 0.0]]), profile,
            np.array([[0.0, float(height)]]),
        ], axis=0)
    net = _closed_lathe(profile, axis="y", sections=sections)
    return {"patches": [("cylinder", net,
                         _clamp_degree(3, net.shape[0]),
                         _clamp_degree(3, net.shape[1]))],
            "splines": []}


def make_cone(radius: float = 0.5, height: float = 1.0, sections: int = 16,
              rings: int = 5):
    """Cone along +Y: linear taper from a full base ring to an apex."""
    sections = max(int(sections), 4)
    rings = max(int(rings), 4)
    f = np.linspace(0.0, 1.0, rings)
    profile = np.stack([float(radius) * (1.0 - f), float(height) * f], axis=1)
    net = _closed_lathe(profile, axis="y", sections=sections)
    return {"patches": [("cone", net,
                         _clamp_degree(3, net.shape[0]),
                         _clamp_degree(3, net.shape[1]))],
            "splines": []}


def make_torus(major_radius: float = 1.0, minor_radius: float = 0.3,
               major_sections: int = 24, minor_sections: int = 12):
    """Torus lying in the XZ plane (revolved minor-circle profile)."""
    major_sections = max(int(major_sections), 4)
    minor_sections = max(int(minor_sections), 4)
    t = np.linspace(0.0, 2.0 * np.pi, minor_sections, endpoint=False)
    prof_r = float(major_radius) + float(minor_radius) * np.cos(t)
    prof_y = float(minor_radius) * np.sin(t)
    profile = np.stack([prof_r, prof_y], axis=1)
    # Close the tube: duplicate the first profile point so the minor circle
    # has no seam when evaluated with clamped open knots.
    profile = np.concatenate([profile, profile[:1]], axis=0)
    net = _closed_lathe(profile, axis="y", sections=major_sections)
    return {"patches": [("torus", net,
                         _clamp_degree(3, net.shape[0]),
                         _clamp_degree(2, net.shape[1]))],
            "splines": []}


# ---------------------------------------------------------------------------
# Faceted / flat family
# ---------------------------------------------------------------------------
def make_box(width: float = 1.0, height: float = 1.0, depth: float = 1.0,
             n: int = 4):
    """Axis-aligned box built from six flat patch grids."""
    n = max(int(n), 3)
    hw, hh, hd = float(width) / 2, float(height) / 2, float(depth) / 2
    X = np.array([1.0, 0.0, 0.0])
    Y = np.array([0.0, 1.0, 0.0])
    Z = np.array([0.0, 0.0, 1.0])
    faces = [
        ("box_front", (-hw, -hh, hd), width * X, height * Y),
        ("box_back", (hw, -hh, -hd), -width * X, height * Y),
        ("box_right", (hw, -hh, hd), -depth * Z, height * Y),
        ("box_left", (-hw, -hh, -hd), depth * Z, height * Y),
        ("box_top", (-hw, hh, hd), width * X, -depth * Z),
        ("box_bottom", (-hw, -hh, -hd), width * X, depth * Z),
    ]
    patches = [(name, _face_grid(corner, du, dv, n), 2, 2)
               for name, corner, du, dv in faces]
    return {"patches": patches, "splines": []}


def make_plane(width: float = 1.0, height: float = 1.0, n: int = 4):
    """Flat card on the XY plane facing +Z — the base for sprites."""
    n = max(int(n), 3)
    grid = _face_grid((-float(width) / 2, -float(height) / 2, 0.0),
                      np.array([float(width), 0.0, 0.0]),
                      np.array([0.0, float(height), 0.0]), n)
    return {"patches": [("plane", grid, 2, 2)], "splines": []}


# ---------------------------------------------------------------------------
# Explicit-profile family
# ---------------------------------------------------------------------------
def make_lathe_profile(profile, axis: str = "y", sections: int = 24):
    """Revolve an explicit ``[[radius, axial], ...]`` profile."""
    profile = np.asarray(profile, dtype=np.float64)
    if profile.ndim != 2 or profile.shape[1] != 2 or len(profile) < 2:
        raise ValueError(
            "lathe profile must be an (m, 2) array of [radius, axial] rows")
    sections = max(int(sections), 4)
    net = _closed_lathe(profile, axis=axis, sections=sections)
    return {"patches": [("lathe", net,
                         _clamp_degree(3, net.shape[0]),
                         _clamp_degree(min(3, profile.shape[0]),
                                       net.shape[1]))],
            "splines": []}


def make_extrude_profile(profile, height: float = 1.0, twist_deg: float = 0.0,
                         rings: int = 4):
    """Extrude an explicit ``[[x, y, z], ...]`` profile along +Y."""
    profile = np.asarray(profile, dtype=np.float64)
    if profile.ndim != 2 or profile.shape[1] != 3 or len(profile) < 2:
        raise ValueError("extrude profile must be an (m, 3) array of points")
    rings = max(int(rings), 2)
    net = kernel.build_extrude_net(profile, float(height),
                                   float(twist_deg), rings)
    return {"patches": [("extrude", net,
                         _clamp_degree(min(3, rings), net.shape[0]),
                         _clamp_degree(min(3, profile.shape[0]),
                                       net.shape[1]))],
            "splines": []}


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------
BUILDERS = {
    "sphere": make_sphere,
    "cylinder": make_cylinder,
    "cone": make_cone,
    "torus": make_torus,
    "box": make_box,
    "plane": make_plane,
    "lathe": make_lathe_profile,
    "extrude": make_extrude_profile,
}


def build_primitive(name: str, params: dict | None = None) -> dict:
    """Build any registered primitive by name with a params dict."""
    key = str(name).lower()
    if key not in BUILDERS:
        raise ValueError(
            f"unknown primitive {name!r} (choose from {sorted(BUILDERS)})")
    try:
        return BUILDERS[key](**(params or {}))
    except (TypeError, ValueError) as exc:
        # Wrap so an LLM sees one consistent, actionable error shape.
        raise ValueError(
            f"primitive {name!r} got bad params {params!r}: {exc}") from exc