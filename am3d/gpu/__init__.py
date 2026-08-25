"""GPU multi-pass renderer for 3D MASTER:2005.

Provides a headless ModernGL-based pipeline: tessellated MeshData -> G-buffer ->
lighting pass -> tone-mapped RGBA output (numpy array).  Replaces the software
rasterizer for interactive viewport use and high-quality renders.

Public API:
    render_frame(project, camera, size, lights) -> np.ndarray  RGBA
    render_mesh(mesh, material, view_matrix, ...)
    GBuffer  (context manager wrapping FBO with position/normal/albedo targets)
    ShaderProgram  (compile + uniform helpers)
"""

from __future__ import annotations

import numpy as np

from .context import create_offscreen_context, ContextManager
from .gbuffer import GBuffer
from .shaders import ShaderProgram, _mesh_vs, _gbuf_fs, _lighting_fs, _quad_vs
from .lighting import light_pass
from .postprocess import tone_map, apply_fog

__all__ = [
    "create_offscreen_context", "ContextManager",
    "GBuffer", "ShaderProgram",
    "light_pass", "tone_map", "apply_fog",
    "render_frame", "render_mesh",
]


def render_frame(project_or_mesh, camera=None, size=(512, 512),
                 lights=None, gpu_context=None):
    """End-to-end GPU render of a project or MeshData.

    If *gpu_context* is None, a temporary offscreen context is created and
    destroyed (use :class:`ContextManager` for multiple frames).  If no GPU
    context can be created, falls back to the software toon rasterizer so the
    call always yields an image.
    """
    from am3d.renderer.tessellate import tessellate_project, MeshData
    from am3d.core.project import Project

    if isinstance(project_or_mesh, Project):
        mesh_dict = tessellate_project(project_or_mesh)
        meshes = list(mesh_dict.values())
    elif isinstance(project_or_mesh, dict):
        meshes = list(project_or_mesh.values())
    elif isinstance(project_or_mesh, MeshData):
        meshes = [project_or_mesh]
    else:
        meshes = list(project_or_mesh)

    W, H = size
    owned_ctx = False
    ctx = None
    if gpu_context is None:
        try:
            gpu_context = create_offscreen_context(W, H)
            owned_ctx = True
        except Exception:
            return _software_render(meshes, W, H)

    ctx = gpu_context.ctx if hasattr(gpu_context, "ctx") else gpu_context
    if ctx is None:
        if owned_ctx and gpu_context is not None:
            try:
                gpu_context.destroy()
            except Exception:
                pass
        return _software_render(meshes, W, H)

    gbuf = GBuffer(ctx, W, H)
    final = None
    released = False
    try:
        gbuf.bind()
        try:
            prog = ShaderProgram(ctx, _mesh_vs, _gbuf_fs)
        except Exception as exc:
            # Hardware pipeline unavailable — software fallback
            raise RuntimeError(f"GPU shader unavailable: {exc}")

        _vaos = []  # keep VAOs alive across render calls
        for mesh in meshes:
            _vaos.append(render_mesh(
                ctx, prog, mesh,
                camera if camera is not None else _default_cam(mesh)))

        # Lighting pass
        light_prog = ShaderProgram(ctx, _quad_vs, _lighting_fs)
        final = light_pass(ctx, light_prog, gbuf, lights)
        final = tone_map(final)
    except Exception:
        # Any hardware failure falls back to software rather than failing
        try:
            gbuf.unbind()
        except Exception:
            pass
        try:
            gbuf.release()
            released = True
        except Exception:
            pass
        final = _software_render(meshes, W, H)
    finally:
        if final is None:  # pragma: no cover - defensive
            final = _software_render(meshes, W, H)
        try:
            gbuf.unbind()
        except Exception:
            pass
        if not released:
            try:
                gbuf.release()
            except Exception:
                pass
        if owned_ctx and gpu_context is not None:
            try:
                gpu_context.destroy()
            except Exception:
                pass

    return final


def _software_render(meshes, W, H):
    """CPU fallback: first mesh via the toon rasterizer (toon shading).

    Always returns float32 RGBA in 0..1 (the render-boundary contract);
    conversion to uint8 happens only at export/QImage edges.
    """
    from am3d.renderer.toon import toon_render_view
    result = None
    if meshes:
        try:
            result = toon_render_view(meshes[0], size=max(W, H))
        except Exception:
            result = None
    if result is None:
        result = np.zeros((H, W, 4), dtype=np.float32)
    result = np.asarray(result, dtype=np.float32)
    if result.shape[0] != H or result.shape[1] != W:
        from am3d.renderer.materials import _resize
        result = _resize(result, H, W).astype(np.float32)
    return np.clip(result, 0.0, 1.0).astype(np.float32)


def render_mesh(ctx, program, mesh, view_matrix=None):
    """Upload and draw one MeshData into the currently bound FBO."""
    from .shaders import _build_vao
    return _build_vao(ctx, program, mesh, view_matrix)


def _default_cam(mesh):
    """Simple orbit camera looking at the mesh centroid."""
    if not hasattr(mesh, "vertices") or len(mesh.vertices) == 0:
        return np.eye(4)
    center = mesh.vertices.mean(axis=0)
    return _look_at(center + np.array([0.0, 0.0, 3.0]), center)


def _look_at(eye, target, up=(0, 1, 0)):
    """Build a view matrix (look-at)."""
    f = np.asarray(target, dtype=np.float64) - np.asarray(eye, dtype=np.float64)
    f = f / max(np.linalg.norm(f), 1e-12)
    s = np.cross(np.asarray(up, dtype=np.float64), f)
    s = s / max(np.linalg.norm(s), 1e-12)
    u = np.cross(f, s)
    m = np.eye(4)
    m[0, :3] = s
    m[1, :3] = u
    m[2, :3] = -f
    m[:3, 3] = -m[:3, :3] @ np.asarray(eye, dtype=np.float64)
    return m