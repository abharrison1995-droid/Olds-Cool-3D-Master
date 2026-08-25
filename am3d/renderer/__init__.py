"""Rendering subsystem.

The renderer turns the pure-spline project into viewable geometry.  This
package presently provides the CPU-side tessellation bridge
(:mod:`am3d.renderer.tessellate`); the GPU multi-pass rasterizer, NPR toon
shader and volumetric atmosphere are built on top of it.
"""

from __future__ import annotations

from . import sprite, uv_mapping  # noqa: F401
from .sprite import (  # noqa: F401
    render_sprite_sheet,
    render_view,
    save_sprite_sheet,
)
from .tessellate import (  # noqa: F401
    MeshData,
    tessellate_object,
    tessellate_project,
    tessellate_splines,
)
from .uv_mapping import (  # noqa: F401
    atlas_grid_layout,
    grid_atlas_uvs,
    patch_uvs,
)

__all__ = [
    "MeshData", "tessellate_object", "tessellate_project", "tessellate_splines",
    "atlas_grid_layout", "grid_atlas_uvs", "patch_uvs", "uv_mapping",
    "render_sprite_sheet", "render_view", "save_sprite_sheet", "sprite",
]