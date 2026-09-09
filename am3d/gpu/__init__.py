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
    "resolve_scene", "scene_camera",
    "GBuffer", "ShaderProgram",
    "light_pass", "tone_map", "apply_fog",
    "render_frame", "render_mesh",
]


class _ProjectSessionAdapter:
    """Minimal Session-shaped view of a bare Project.

    ``evaluate_scene`` only reads ``session.project`` and, optionally,
    ``session.posed_transforms``; a Project on its own carries no pose state,
    so a static evaluation is exactly what it should get (finding GPU-01).
    """

    def __init__(self, project):
        self.project = project


def resolve_scene(source, *, action_name=None, time=None, pose=None):
    """Normalise *source* into an :class:`EvaluatedScene`.

    Finding GPU-01: ``render_frame`` used to call ``tessellate_project``
    directly on a Project, which bypasses the shared evaluator and therefore
    ignored object visibility, object transforms, skeletal deformation and
    material assignment -- so the standalone render API disagreed with the
    viewport, the exporters and the recipe pipeline about what the scene
    even is. Everything now funnels through ``am3d.core.scene.evaluate_scene``.

    Accepts a Session (action/time/pose honoured), a Project (evaluated
    statically), an EvaluatedScene, a ``{name: MeshData}`` dict, a single
    MeshData, or any iterable of MeshData.
    """
    from am3d.core.project import Project
    from am3d.core.scene import EvaluatedScene, evaluate_scene
    from am3d.renderer.tessellate import MeshData

    if isinstance(source, EvaluatedScene):
        return source
    if isinstance(source, Project):
        source = _ProjectSessionAdapter(source)
    if hasattr(source, "project"):
        return evaluate_scene(source, action_name=action_name, time=time,
                              pose=pose, visible_only=True,
                              apply_transforms=True)
    if isinstance(source, MeshData):
        meshes = {"mesh": source}
    elif isinstance(source, dict):
        meshes = dict(source)
    else:
        meshes = {f"mesh{i}": m for i, m in enumerate(source)}
    scene = EvaluatedScene(meshes=meshes)
    scene.bounds = _scene_bounds(list(meshes.values()))
    return scene


def _scene_bounds(meshes):
    """Combined world-space ``(min, max)`` of every mesh with geometry."""
    pts = [np.asarray(m.vertices, dtype=np.float64) for m in meshes
           if getattr(m, "vertices", None) is not None and len(m.vertices)]
    if not pts:
        return (np.zeros(3), np.zeros(3))
    allv = np.vstack(pts)
    return (allv.min(axis=0), allv.max(axis=0))


def scene_camera(meshes):
    """One view matrix framing *all* meshes together.

    Finding GPU-03: the per-mesh ``_default_cam`` gave every object its own
    look-at, so two unequally sized, offset objects were each re-centred and
    lost their relative placement and depth ordering. The camera must be a
    property of the scene, not of whichever mesh is being drawn.
    """
    lo, hi = _scene_bounds(meshes)
    center = (lo + hi) / 2.0
    radius = float(np.linalg.norm(hi - lo)) / 2.0
    # 45 deg vertical FOV (matching shaders._perspective) with headroom.
    distance = max(radius / np.tan(np.radians(45.0) / 2.0) * 1.3, 3.0)
    return _look_at(center + np.array([0.0, 0.0, distance]), center)


def render_frame(project_or_mesh, camera=None, size=(512, 512),
                 lights=None, gpu_context=None, *,
                 action_name=None, time=None, pose=None):
    """End-to-end GPU render of a scene, session, project or mesh.

    The input is resolved through :func:`resolve_scene`, so visibility,
    transforms, pose and materials always come from the one shared evaluator
    (finding GPU-01). When *camera* is None a single camera framing the whole
    scene is used (finding GPU-03). If no GPU context can be created, or the
    hardware pipeline fails part-way, the software fallback renders **every**
    visible mesh through the same camera with shared occlusion (finding
    GPU-02) rather than only the first one.

    If *gpu_context* is None, a temporary offscreen context is created and
    destroyed (use :class:`ContextManager` for multiple frames).
    """
    scene = resolve_scene(project_or_mesh, action_name=action_name,
                          time=time, pose=pose)
    drawable = {name: m for name, m in scene.meshes.items()
                if getattr(m, "vertices", None) is not None
                and len(m.vertices) and len(m.indices)}
    meshes = list(drawable.values())

    W, H = size
    view = camera if camera is not None else scene_camera(meshes)

    owned_ctx = False
    ctx = None
    if gpu_context is None:
        try:
            gpu_context = create_offscreen_context(W, H)
            owned_ctx = True
        except Exception:
            return _software_render(meshes, W, H, camera=view)

    ctx = gpu_context.ctx if hasattr(gpu_context, "ctx") else gpu_context
    if ctx is None:
        if owned_ctx and gpu_context is not None:
            try:
                gpu_context.destroy()
            except Exception:
                pass
        return _software_render(meshes, W, H, camera=view)

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
        for name, mesh in drawable.items():
            _vaos.append(render_mesh(
                ctx, prog, mesh, view,
                albedo=_mesh_albedo(scene, name)))

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
        # Mark released *before* the call: a release() that raises has still
        # consumed its one attempt, and calling it a second time from the
        # finally block would double-free the GL objects.
        released = True
        try:
            gbuf.release()
        except Exception:
            pass
        final = _software_render(meshes, W, H, camera=view)
    finally:
        if final is None:  # pragma: no cover - defensive
            final = _software_render(meshes, W, H, camera=view)
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


def _mesh_albedo(scene, name, default=(0.7, 0.7, 0.75, 1.0)):
    """Base colour for *name* from the evaluated scene's material assignment."""
    mat_name = (scene.object_materials or {}).get(name)
    material = (scene.materials or {}).get(mat_name) if mat_name else None
    color = getattr(material, "color", None)
    if color is None or len(color) < 3:
        return default
    return (float(color[0]), float(color[1]), float(color[2]),
            float(color[3]) if len(color) > 3 else 1.0)


def _software_render(meshes, W, H, camera=None):
    """CPU fallback: **every** mesh, merged, through the scene camera.

    Finding GPU-02: this used to render ``meshes[0]`` alone, so losing the
    GPU silently dropped every object after the first and produced an image
    with no shared occlusion between them. The meshes are merged first --
    the same merge the viewport uses -- so one depth buffer resolves them
    against each other.

    Always returns float32 RGBA in 0..1 (the render-boundary contract);
    conversion to uint8 happens only at export/QImage edges.
    """
    from am3d.renderer.sprite import merge_meshes

    result = None
    meshes = [m for m in (meshes or [])
              if getattr(m, "vertices", None) is not None
              and len(m.vertices) and len(m.indices)]
    if meshes:
        try:
            merged = meshes[0] if len(meshes) == 1 else merge_meshes(meshes)
            # Finding GPU-05: with no explicit camera this used to fall back
            # to toon_render_view's own per-image fit, while the GPU path
            # framed the same scene with scene_camera(). The two renders of
            # one scene then disagreed about framing (measured silhouette
            # IoU 0.18 on a two-object fixture). Derive the same scene
            # camera the GPU path uses, so "the software fallback" means a
            # slower renderer, not a different picture.
            view = camera if camera is not None else scene_camera(meshes)
            result = _toon_through_camera(merged, view, W, H)
        except Exception:
            result = None
    if result is None:
        result = np.zeros((H, W, 4), dtype=np.float32)
    result = np.asarray(result, dtype=np.float32)
    if result.shape[0] != H or result.shape[1] != W:
        from am3d.renderer.materials import _resize
        result = _resize(result, H, W).astype(np.float32)
    return np.clip(result, 0.0, 1.0).astype(np.float32)


class _MatrixCamera:
    """Adapt a bare 4x4 view matrix to the camera protocol the software
    renderer needs, so GPU and fallback frame the scene identically."""

    def __init__(self, view, fov_deg=45.0):
        self._view = np.asarray(view, dtype=np.float64)
        self.fov = float(fov_deg)

    def view_matrix(self):
        return self._view

    def world_to_screen(self, points, width, height):
        pts = np.asarray(points, dtype=np.float64).reshape(-1, 3)
        aspect = max(float(width), 1.0) / max(float(height), 1.0)
        cam = pts @ self._view[:3, :3].T + self._view[:3, 3]
        t = np.tan(np.radians(self.fov) / 2.0)
        depth = -cam[:, 2]
        valid = depth > 1e-9
        safe = np.where(valid, depth, 1.0)
        ndc_x = cam[:, 0] / (safe * t * aspect)
        ndc_y = cam[:, 1] / (safe * t)
        xs = (ndc_x * 0.5 + 0.5) * float(width)
        ys = (1.0 - (ndc_y * 0.5 + 0.5)) * float(height)
        return xs, ys, valid


def _toon_through_camera(mesh, view, W, H):
    from am3d.renderer.toon import toon_render_camera
    return toon_render_camera(mesh, _MatrixCamera(view), W, H)


def render_mesh(ctx, program, mesh, view_matrix=None, albedo=None):
    """Upload and draw one MeshData into the currently bound FBO."""
    from .shaders import _build_vao
    return _build_vao(ctx, program, mesh, view_matrix, albedo=albedo)


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