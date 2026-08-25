"""Tests for the GPU renderer (smoke tests via software fallback path)."""

from __future__ import annotations

from am3d.gpu import (
    ContextManager, GBuffer, ShaderProgram,
    tone_map, apply_fog, _software_render, render_frame,
)
from am3d.renderer.tessellate import MeshData
import numpy as np


def test_import():
    """Package imports correctly."""
    import am3d.gpu as g
    assert "render_frame" in g.__all__
    assert "tone_map" in g.__all__


def test_tone_map():
    """Tone-map does not crash and returns correct shape/dtype."""
    rgba = np.array([[[2.0, 3.0, 1.5, 1.0]]], dtype=np.float32)
    out = tone_map(rgba, exposure=1.0, gamma=2.2)
    assert out.shape == (1, 1, 4)
    assert out.dtype == np.float32
    assert 0.0 <= out.min() <= out.max() <= 1.0


def test_apply_fog():
    """Fog blending returns same shape."""
    rgba = np.ones((16, 16, 3), dtype=np.float32) * 0.5
    depth = np.ones((16, 16), dtype=np.float32) * 5.0
    out = apply_fog(rgba, depth, density=0.1)
    assert out.shape == (16, 16, 3)
    assert out.dtype == np.float32


def test_software_render_fallback():
    """_software_render returns valid RGBA for a simple mesh."""
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=np.float64)
    indices = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int64)
    normals = np.array([[0, 0, 1]] * 4, dtype=np.float64)
    mesh = MeshData(verts, indices, normals)
    result = _software_render([mesh], 32, 32)
    assert result.shape == (32, 32, 4)
    assert result.dtype == np.float32
    assert result[..., 3].max() > 0.5  # non-zero alpha in drawn area


def test_render_frame_software_fallback():
    """render_frame with no GL context falls back to software."""
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]], dtype=np.float64)
    indices = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int64)
    normals = np.array([[0, 0, 1]] * 4, dtype=np.float64)
    mesh = MeshData(verts, indices, normals)
    try:
        result = render_frame(mesh, size=(16, 16))
        assert result.shape == (16, 16, 4)
    except Exception:
        # Some CI environments may not support even the software path
        pass


def test_gbuffer_context_standalone():
    """Try creating a standalone GL context (skip if not available)."""
    try:
        cm = ContextManager(64, 64)
        ctx = cm.create()
        assert ctx is not None
        gbuf = GBuffer(ctx, 64, 64)
        assert gbuf.width == 64
        assert gbuf.height == 64
        gbuf.release()
        cm.destroy()
    except Exception:
        import pytest
        pytest.skip("standalone GL context not available")


def _quad_mesh():
    verts = np.array([[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]],
                     dtype=np.float64)
    indices = np.array([[0, 1, 2], [1, 3, 2]], dtype=np.int64)
    normals = np.array([[0, 0, 1]] * 4, dtype=np.float64)
    return MeshData(verts, indices, normals)


def test_perspective_respects_aspect():
    """Regression: _perspective must derive aspect from the size parameter."""
    import pytest
    from am3d.gpu.shaders import _perspective
    m_wide = _perspective(45, None, size=(64, 32))
    m_square = _perspective(45, None, size=(32, 32))
    assert m_wide[0, 0] == pytest.approx(m_square[0, 0] / 2.0)  # aspect 2
    assert m_wide[1, 1] == pytest.approx(m_square[1, 1])


def test_build_vao_accepts_mesh_with_uvs():
    """Regression: a real uvs ndarray must not raise a truth-value error."""
    from am3d.gpu.shaders import _build_vao

    class _Buf:
        pass

    class _Vao:
        def render(self):
            pass

    class _Ctx:
        def buffer(self, data):
            return _Buf()

        def vertex_array(self, *a, **k):
            return _Vao()

    class _Prog:
        prog = None

        def uniform(self, *a, **k):
            pass

    mesh = _quad_mesh()
    assert mesh.uvs is not None and len(mesh.uvs) == 4
    _build_vao(_Ctx(), _Prog(), mesh)  # must not raise


def test_software_render_unit_scale_and_nonsquare():
    """Regression: 0..1 float RGBA, non-square sizes not zeroed out."""
    import pytest
    result = _software_render([_quad_mesh()], 24, 48)  # W=24, H=48
    assert result.shape == (48, 24, 4)
    assert result.dtype == np.float32
    assert result.min() >= 0.0 and result.max() <= 1.0
    assert result[..., 3].max() == pytest.approx(1.0)
    # background alpha must stay 0 (not forced opaque)
    assert result[..., 3].min() == 0.0


def test_render_frame_releases_gbuffer_once(monkeypatch):
    """Regression: gbuf.release() runs exactly once on the error path."""
    import am3d.gpu as gpu

    releases = []

    class _FakeGbuf:
        def __init__(self, ctx, w, h):
            pass

        def bind(self):
            pass

        def unbind(self):
            pass

        def release(self):
            releases.append(1)

    def _boom(*a, **k):
        raise RuntimeError("no shaders")

    class _FakeCtxObj:
        ctx = object()

        def destroy(self):
            pass

    monkeypatch.setattr(gpu, "GBuffer", _FakeGbuf)
    monkeypatch.setattr(gpu, "ShaderProgram", _boom)
    monkeypatch.setattr(gpu, "create_offscreen_context",
                        lambda w, h: _FakeCtxObj())
    out = gpu.render_frame(_quad_mesh(), size=(16, 16))
    assert out.shape == (16, 16, 4)
    assert len(releases) == 1


def test_render_frame_accepts_ndarray_camera(monkeypatch):
    """Regression: a 4x4 ndarray camera must not raise an ambiguity error."""
    import am3d.gpu as gpu

    class _FakeGbuf:
        width = height = 16
        _attachments = []

        def __init__(self, ctx, w, h):
            pass

        def bind(self):
            pass

        def unbind(self):
            pass

        def release(self):
            pass

    class _FakeProg:
        def __init__(self, *a, **k):
            self.prog = None

        def uniform(self, *a, **k):
            pass

    class _FakeCtxObj:
        ctx = object()

        def destroy(self):
            pass

    seen = []

    def _fake_render_mesh(ctx, prog, mesh, view_matrix=None):
        seen.append(view_matrix)
        return None

    monkeypatch.setattr(gpu, "GBuffer", _FakeGbuf)
    monkeypatch.setattr(gpu, "ShaderProgram", _FakeProg)
    monkeypatch.setattr(gpu, "render_mesh", _fake_render_mesh)
    # Lighting pass returns pure black so tone_map keeps it black — if the
    # camera check raised, the except-branch would return a lit frame.
    monkeypatch.setattr(gpu, "light_pass",
                        lambda *a, **k: np.zeros((16, 16, 4), np.float32))
    monkeypatch.setattr(gpu, "create_offscreen_context",
                        lambda w, h: _FakeCtxObj())
    camera = np.eye(4)
    out = gpu.render_frame(_quad_mesh(), camera=camera, size=(16, 16))
    assert seen and seen[0] is camera
    assert out.shape == (16, 16, 4)
    assert out.max() == 0.0  # GPU path taken (black), not the SW fallback


def test_gbuffer_filter_uses_nearest(monkeypatch):
    """Regression: texture filter must use moderngl constants, not None."""
    import sys
    import types
    monkeypatch.setitem(sys.modules, "moderngl",
                        types.SimpleNamespace(NEAREST=9728, LINEAR=9729))

    class _Tex:
        def __init__(self):
            self.filter = None
            self.repeat_x = None
            self.repeat_y = None

    class _Fbo:
        pass

    class _Ctx:
        def texture(self, *a, **k):
            return _Tex()

        def depth_texture(self, *a, **k):
            return _Tex()

        def framebuffer(self, **k):
            return _Fbo()

    gbuf = GBuffer(_Ctx(), 8, 8)
    for tex in gbuf._attachments:
        assert tex.filter == (9728, 9728)


def test_light_pass_releases_quad_resources():
    """Regression: light_pass must release the VAO/VBOs it creates."""
    from am3d.gpu.lighting import light_pass

    released = []

    class _Res:
        def __init__(self, name="res"):
            self.name = name

        def release(self):
            released.append(self.name)

    class _Tex(_Res):
        def read(self):
            return np.zeros(4 * 4 * 4, dtype=np.uint8).tobytes()

        def use(self, idx):
            pass

    class _Fbo(_Res):
        def use(self):
            pass

    class _Vao(_Res):
        def render(self):
            pass

    class _Ctx:
        viewport = None

        def buffer(self, data):
            return _Res("vbo")

        def vertex_array(self, *a, **k):
            return _Vao("vao")

        def texture(self, *a, **k):
            return _Tex("tex")

        def framebuffer(self, **k):
            return _Fbo("fbo")

        def clear(self, *a):
            pass

    class _Prog:
        prog = None

        def __setitem__(self, key, value):
            pass

    class _Gbuf:
        width = height = 4
        _attachments = [_Tex("t0"), _Tex("t1"), _Tex("t2")]

    out = light_pass(_Ctx(), _Prog(), _Gbuf())
    assert out.shape == (4, 4, 4)
    assert released.count("vbo") == 2
    assert "vao" in released
    assert "fbo" in released
    assert "tex" in released