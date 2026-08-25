"""Numba-accelerated B-spline evaluation and surface construction.

Pure-spline geometry kernel of 3D MASTER:2005.  All surfaces are modelled
as *control-point grids* where every row and column is a B-spline.  The
control nets are tiny; tessellation to triangles only happens at render
time, so geometry stays mathematically smooth at any density without
growing the file.

Reference implementation: The NURBS Book (Piegl & Tiller), ch. 2 & 3.
"""

from __future__ import annotations

import numpy as np

try:
    from numba import njit
    _HAS_NUMBA = True
except Exception:  # pragma: no cover - fallback so the module runs w/o numba
    _HAS_NUMBA = False

    def njit(_f=None, *a, **k):
        if _f is None:
            return lambda f: f
        return _f


_EPS = 1e-12


# ---------------------------------------------------------------------------
# Knot-vector construction
# ---------------------------------------------------------------------------
def make_clamped_knots(degree: int, ncp: int) -> np.ndarray:
    """Clamped (open-uniform) knot vector for a degree-*degree* spline.

    The end knots are repeated ``degree + 1`` times so the curve interpolates
    its first and last control points.
    """
    if degree < 0:
        raise ValueError("degree must be >= 0")
    if ncp <= degree:
        raise ValueError("need at least degree + 1 control points")
    n = ncp + degree + 1
    knots = np.zeros(n, dtype=np.float64)
    inner = n - 2 * (degree + 1)
    if inner > 0:
        knots[degree + 1 : ncp] = np.linspace(0.0, 1.0, inner + 2)[1:-1]
    knots[ncp:] = 1.0
    return knots


# ---------------------------------------------------------------------------
# Basis functions and point evaluation (Algorithms A2.1-A2.3)
# ---------------------------------------------------------------------------
@njit(cache=True, fastmath=True)
def find_span(t, degree, knots):
    """Return index *k* with ``knots[k] <= t < knots[k+1]`` (A2.1)."""
    n = knots.shape[0] - degree - 1
    if t >= knots[n]:
        return n - 1
    if t <= knots[degree]:
        return degree
    lo, hi = degree, n
    mid = (lo + hi) // 2
    while t < knots[mid] or t >= knots[mid + 1]:
        if t < knots[mid]:
            hi = mid
        else:
            lo = mid + 1
        mid = (lo + hi) // 2
    return mid


def basis(i: int, p: int, u: float, knots) -> float:
    """Value of ``N_{i,p}`` at ``u`` (find_span + A2.2 table)."""
    knots = np.asarray(knots, dtype=np.float64)
    i, p, u = int(i), int(p), float(u)
    s = find_span(u, p, knots)
    if not (s - p <= i <= s):
        return 0.0
    N = np.zeros(p + 1)
    left = np.zeros(p + 1)
    right = np.zeros(p + 1)
    N[0] = 1.0
    for j in range(1, p + 1):
        left[j] = u - knots[s + 1 - j]
        right[j] = knots[s + j] - u
        saved = 0.0
        for r in range(j):
            den = right[r + 1] + left[j - r]
            temp = N[r] / den if abs(den) > _EPS else 0.0
            N[r] = saved + right[r + 1] * temp
            saved = left[j - r] * temp
        N[j] = saved
    return N[i - s + p]


def deboor(t, degree, knots, cps, weights=None):
    """Evaluate a (possibly rational) B-spline point at ``t`` (A2.3)."""
    cps = np.asarray(cps, dtype=np.float64)
    knots = np.asarray(knots, dtype=np.float64)
    p = int(degree)
    n = cps.shape[0]

    span0 = knots[-1] - knots[0]
    u = knots[0] + (0.0 if abs(span0) < _EPS else float(t) * span0)
    u = min(max(u, knots[p]), knots[n])
    span = find_span(u, p, knots)

    if weights is None:
        d = np.zeros((p + 1, 3), dtype=np.float64)
        for j in range(p + 1):
            d[j] = cps[span - p + j]
        for r in range(1, p + 1):
            for j in range(p, r - 1, -1):
                k = span - p + j
                den = knots[k + p - r + 1] - knots[k]
                alpha = (u - knots[k]) / den if abs(den) > _EPS else 0.0
                d[j] = (1.0 - alpha) * d[j - 1] + alpha * d[j]
        return d[p].copy()

    w = np.asarray(weights, dtype=np.float64).reshape(n)
    hom = np.zeros((p + 1, 4), dtype=np.float64)
    for j in range(p + 1):
        idx = span - p + j
        hom[j, :3] = w[idx] * cps[idx]
        hom[j, 3] = w[idx]
    for r in range(1, p + 1):
        for j in range(p, r - 1, -1):
            k = span - p + j
            num = u - knots[k]
            den = knots[k + p - r + 1] - knots[k]
            alpha = num / den if abs(den) > _EPS else 0.0
            hom[j] = (1.0 - alpha) * hom[j - 1] + alpha * hom[j]
    pt = hom[p]
    if abs(pt[3]) > _EPS:
        return (pt[:3] / pt[3]).copy()
    return pt[:3].copy()


def eval_curve(t, degree, knots, cps, weights=None):
    """Evaluate a spline at one or many normalised parameters in [0, 1]."""
    cps = np.asarray(cps, dtype=np.float64)
    knots = np.asarray(knots, dtype=np.float64)
    if isinstance(t, (int, np.integer)) and int(t) > 1:
        # Backward-compatible overload: an int > 1 means "number of samples".
        t_arr = np.linspace(0.0, 1.0, int(t))
    elif np.isscalar(t):
        t_arr = np.array([t], dtype=np.float64)
    else:
        t_arr = np.asarray(t, dtype=np.float64).ravel()
    out = np.empty((t_arr.shape[0], 3), dtype=np.float64)
    for i, ti in enumerate(t_arr):
        out[i] = deboor(ti, degree, knots, cps, weights)
    return out


# ---------------------------------------------------------------------------
# Surface construction (4-sided control-point nets)
# ---------------------------------------------------------------------------
def build_patch_grid(control_grid, degree_u=3, degree_v=3, nu=16, nv=16,
                     weights_u=None, weights_v=None):
    """Tessellate a 4-sided B-spline patch into a triangle mesh.

    ``control_grid`` : ndarray (mu, mv, 3).  Evaluates the tensor-product
    surface: first the degree-*degree_u* splines along **u** (fixed v-column)
    to build an intermediate ``(nu, mv, 3)`` buffer, then the degree-
    *degree_v* splines along **v** of that buffer.

    Returns ``(vertices, indices)``: an ``(nu*nv, 3)`` vertex array and an
    integer triangle index array.
    """
    grid = np.asarray(control_grid, dtype=np.float64)
    if grid.ndim != 3 or grid.shape[2] != 3:
        raise ValueError("control_grid must have shape (mu, mv, 3)")
    mu, mv = grid.shape[:2]

    knots_u = make_clamped_knots(degree_u, mu)
    knots_v = make_clamped_knots(degree_v, mv)
    u_samples = np.linspace(0.0, 1.0, nu)
    v_samples = np.linspace(0.0, 1.0, nv)

    wu = None if weights_u is None else np.asarray(weights_u, dtype=np.float64)
    V = np.empty((nu, mv, 3), dtype=np.float64)
    for iu in range(nu):
        for iv in range(mv):
            V[iu, iv] = deboor(u_samples[iu], degree_u, knots_u,
                               grid[:, iv, :], wu)

    wv = None if weights_v is None else np.asarray(weights_v, dtype=np.float64)
    vertices = np.empty((nu, nv, 3), dtype=np.float64)
    for iu in range(nu):
        for iv in range(nv):
            vertices[iu, iv] = deboor(v_samples[iv], degree_v, knots_v,
                                      V[iu, :, :], wv)

    verts = vertices.reshape(-1, 3)
    tris = np.empty(((nu - 1) * (nv - 1) * 2, 3), dtype=np.int64)
    t = 0
    for i in range(nu - 1):
        for j in range(nv - 1):
            a = i * nv + j
            b = a + 1
            c = (i + 1) * nv + j
            d = c + 1
            tris[t] = (a, b, c); t += 1
            tris[t] = (b, d, c); t += 1
    return verts, tris


def eval_surface(control_grid, degree_u=3, degree_v=3, nu=32, nv=32,
                 weights_u=None, weights_v=None):
    """Evaluate a 4-sided B-spline surface as an ``(nu, nv, 3)`` grid."""
    verts, _ = build_patch_grid(control_grid, degree_u, degree_v,
                                nu, nv, weights_u, weights_v)
    return verts.reshape(nu, nv, 3)


# ---------------------------------------------------------------------------
# Procedural net builders (extrusion + lathe)
# ---------------------------------------------------------------------------
def build_extrude_net(profile, height, twist_deg=0.0, n_rings=2):
    """Build a profile-extruded cylindrical control net.

    *profile* : ndarray (m, 3) of control points in the XZ plane.
    *height* : extrusion distance along +Y.
    *twist_deg* : optional total angular twist (degrees) of the top ring.

    Returns an ``(n_rings, m, 3)`` control net.
    """
    profile = np.asarray(profile, dtype=np.float64)
    if int(n_rings) < 2:
        raise ValueError("n_rings must be >= 2")
    m = profile.shape[0]
    net = np.empty((n_rings, m, 3), dtype=np.float64)
    for r in range(n_rings):
        t = r / (n_rings - 1)
        y = t * height
        angle = np.radians(twist_deg) * t
        c, s = np.cos(angle), np.sin(angle)
        for j in range(m):
            x, _y, z = profile[j, 0], profile[j, 1], profile[j, 2]
            net[r, j] = (x * c - z * s, y, x * s + z * c)
    return net


def build_lathe_net(profile, axis="y", sections=24):
    """Revolve a 2-D profile around an axis (lathing a control net).

    *profile* : ndarray (m, 2); ``(radius, axial)`` per row.
    *axis* : "x", "y", or "z" — axis of revolution.
    Returns an ``(sections, m, 3)`` control net.
    """
    profile = np.asarray(profile, dtype=np.float64)
    m = profile.shape[0]
    net = np.empty((sections, m, 3), dtype=np.float64)
    for i in range(sections):
        a = 2.0 * np.pi * i / sections
        c, s = np.cos(a), np.sin(a)
        for j in range(m):
            r, axial = profile[j, 0], profile[j, 1]
            if axis == "y":
                net[i, j] = (r * c, axial, r * s)
            elif axis == "z":
                net[i, j] = (r * c, r * s, axial)
            else:  # axis == "x"
                net[i, j] = (axial, r * s, r * c)
    return net