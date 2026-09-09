"""Re-runnable patch generators (finding EDIT-01).

A lathe or extrude bakes a control net into ``Patch.interior``. Without a
record of where that net came from, editing the profile spline afterwards
moved only the construction curve and left the surface frozen -- and because
the viewport draws the moved curve, the edit *looked* like it had taken
effect while the rendered and exported surface was unchanged.

A generated patch therefore records its generator:

    {"op": "lathe" | "extrude", "spline": <spline name>, "params": {...}}

and :func:`regenerate_object_patches` re-runs it from the spline's current
control points. Regeneration is a pure function of the spline, so undo needs
no snapshot: undoing the control-point move and regenerating again restores
the previous surface exactly.
"""

from __future__ import annotations

import numpy as np


def _lathe_net(profile_points, params):
    from am3d.recipes.primitives import make_lathe_profile
    # Profile spline varies in X/Y; X is radius, Y is the axial coordinate.
    profile = np.asarray(profile_points, dtype=np.float64)[:, [0, 1]]
    return make_lathe_profile(profile,
                              axis=params.get("axis", "y"),
                              sections=int(params.get("sections", 24)))


def _extrude_net(profile_points, params):
    from am3d.recipes.primitives import make_extrude_profile
    return make_extrude_profile(np.asarray(profile_points, dtype=np.float64),
                                height=float(params.get("height", 1.0)),
                                twist_deg=float(params.get("twist_deg", 0.0)),
                                rings=int(params.get("rings", 4)))


_OPS = {"lathe": _lathe_net, "extrude": _extrude_net}


def generator_ops():
    """Names of the generators that can be re-run."""
    return frozenset(_OPS)


def rebuild_patch(obj, patch):
    """Rebuild one generated *patch* from its source spline, in place.

    Returns True if the patch was rebuilt. Returns False -- leaving the patch
    exactly as it was -- when it has no generator, names an unknown operation,
    or its source spline is gone or too short to generate from. A stale
    surface is a far better outcome than a destroyed one, and the patch keeps
    its generator so the edit takes effect again once the spline is valid.
    """
    gen = getattr(patch, "generator", None)
    if not gen:
        return False
    op = _OPS.get(gen.get("op"))
    spline = obj.splines.get(gen.get("spline"))
    if op is None or spline is None or len(spline.cps) < 2:
        return False
    try:
        result = op(spline.point_array(), gen.get("params") or {})
    except (ValueError, IndexError):
        return False
    patches = result.get("patches") or []
    if not patches:
        return False
    _name, net, du, dv = patches[0]
    patch.interior = np.asarray(net, dtype=np.float64)
    patch.degree_u = int(du)
    patch.degree_v = int(dv)
    return True


def regenerate_object_patches(obj, spline_name=None):
    """Rebuild every generated patch of *obj* fed by *spline_name*.

    With *spline_name* None, every generated patch is rebuilt. Returns the
    number of patches actually rebuilt.
    """
    count = 0
    for patch in getattr(obj, "patches", []):
        gen = getattr(patch, "generator", None)
        if not gen:
            continue
        if spline_name is not None and gen.get("spline") != spline_name:
            continue
        if rebuild_patch(obj, patch):
            count += 1
    return count
