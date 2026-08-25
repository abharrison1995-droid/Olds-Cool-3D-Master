"""Shader program compilation and helpers for the GPU renderer."""

from __future__ import annotations

import numpy as np

# ---------------------------------------------------------------------------
# GLSL shader sources (inlined for zero-file-deployment)
# ---------------------------------------------------------------------------
_mesh_vs = """
#version 330
in vec3 in_position;
in vec3 in_normal;
in vec2 in_uv;

uniform mat4 u_model;
uniform mat4 u_view;
uniform mat4 u_proj;

out vec3 v_position;
out vec3 v_normal;
out vec2 v_uv;

void main() {
    vec4 world = u_model * vec4(in_position, 1.0);
    v_position = world.xyz;
    v_normal = normalize(mat3(u_model) * in_normal);
    v_uv = in_uv;
    gl_Position = u_proj * u_view * world;
}
"""

_gbuf_fs = """
#version 330
in vec3 v_position;
in vec3 v_normal;
in vec2 v_uv;

layout(location = 0) out vec4 g_position;
layout(location = 1) out vec3 g_normal;
layout(location = 2) out vec4 g_albedo;

uniform vec4 u_albedo = vec4(0.7, 0.7, 0.75, 1.0);
uniform float u_metalness = 0.0;
uniform float u_roughness = 0.5;

void main() {
    g_position = vec4(v_position, u_metalness);
    g_normal = normalize(v_normal);
    g_albedo = vec4(u_albedo.rgb, u_roughness);
}
"""

_lighting_fs = """
#version 330
in vec2 v_uv;

uniform sampler2D u_position;
uniform sampler2D u_normal;
uniform sampler2D u_albedo;

uniform vec3 u_light_dir = vec3(0.45, 0.75, 0.55);
uniform vec3 u_light_color = vec3(1.0, 0.98, 0.92);
uniform float u_ambient = 0.25;
uniform vec3 u_cam_pos = vec3(0.0, 0.0, 3.0);

layout(location = 0) out vec4 frag_color;

void main() {
    vec3 pos = texture(u_position, v_uv).rgb;
    float metalness = texture(u_position, v_uv).a;
    vec4 albedo_rough = texture(u_albedo, v_uv);
    vec3 albedo = albedo_rough.rgb;
    float roughness = max(albedo_rough.a, 0.02);
    vec3 normal = normalize(texture(u_normal, v_uv).rgb);

    vec3 view_dir = normalize(u_cam_pos - pos);
    vec3 light_dir = normalize(u_light_dir);
    vec3 half_vec = normalize(view_dir + light_dir);

    float NdotL = max(dot(normal, light_dir), 0.0);
    vec3 diffuse = albedo * NdotL;

    float NdotH = max(dot(normal, half_vec), 0.0);
    float spec = pow(NdotH, (1.0 - roughness) * 256.0 + 4.0);

    vec3 color = u_ambient * albedo + (1.0 - metalness) * diffuse
                 + (1.0 - roughness) * spec * u_light_color;

    if (metalness > 0.01) {
        float f0 = 0.04 + 0.96 * (1.0 - roughness);
        vec3 fresnel = mix(vec3(f0), albedo, metalness);
        color += fresnel * spec * u_light_color * 0.5;
    }

    frag_color = vec4(clamp(color, 0.0, 1.0), 1.0);
}
"""
_quad_vs = """
#version 330
in vec3 in_position;
in vec2 in_uv;
out vec2 v_uv;
void main() {
    v_uv = in_uv;
    gl_Position = vec4(in_position, 1.0);
}
"""


class ShaderProgram:
    """Compile and cache a ModernGL shader program."""

    def __init__(self, ctx, vs_source, fs_source):
        try:
            import moderngl as mgl  # noqa: F401
        except ImportError:
            raise RuntimeError("ModernGL required")
        self._ctx = ctx
        try:
            self.prog = ctx.program(vertex_shader=vs_source,
                                    fragment_shader=fs_source)
        except Exception as exc:
            raise RuntimeError(f"shader compilation error: {exc}")

    def uniform(self, name, value):
        """Set a uniform value, tolerating missing uniforms."""
        try:
            if isinstance(value, (float, int)):
                self.prog[name].value = value
            elif isinstance(value, np.ndarray):
                if value.shape == (4, 4):
                    self.prog[name].write(value.astype("f4").tobytes())
                elif value.shape == (3,):
                    self.prog[name].value = tuple(value)
                elif value.shape == (4,):
                    self.prog[name].value = tuple(value)
            elif isinstance(value, (tuple, list)):
                if len(value) == 16:
                    self.prog[name].write(np.array(value, dtype="f4").tobytes())
                elif len(value) == 3:
                    self.prog[name].value = tuple(value)
                elif len(value) == 4:
                    self.prog[name].value = tuple(value)
        except (KeyError, AttributeError):
            pass  # uniform not used in this variant

    def __getitem__(self, name):
        return self.prog[name]

    def __setitem__(self, name, value):
        self.uniform(name, value)


def _build_vao(ctx, program, mesh, view_matrix=None):
    """Upload mesh vertex data and build/return a VAO."""
    verts = np.asarray(mesh.vertices, dtype="f4")
    normals = np.asarray(mesh.normals, dtype="f4")
    mesh_uvs = getattr(mesh, "uvs", None)
    uvs = np.asarray(mesh_uvs if mesh_uvs is not None else
                     np.zeros((len(verts), 2), dtype="f4"), dtype="f4")
    indices = np.asarray(mesh.indices, dtype="u4")

    vbo_v = ctx.buffer(verts.tobytes())
    vbo_n = ctx.buffer(normals.tobytes())
    vbo_uv = ctx.buffer(uvs.tobytes())
    ibo = ctx.buffer(indices.tobytes())

    vao = ctx.vertex_array(
        program.prog,
        [(vbo_v, "3f", "in_position"),
         (vbo_n, "3f", "in_normal"),
         (vbo_uv, "2f", "in_uv")],
        ibo)

    proj = _perspective(45, mesh.vertices, size=_viewport_size(ctx)) \
        if len(verts) > 0 else np.eye(4)
    view = view_matrix if view_matrix is not None else np.eye(4)
    model = np.eye(4, dtype="f4")

    program.uniform("u_proj", proj)
    program.uniform("u_view", view)
    program.uniform("u_model", model)
    program.uniform("u_albedo", (0.7, 0.7, 0.75, 1.0))

    vao.render()
    return vao


def _viewport_size(ctx):
    """Best-effort ``(w, h)`` of the current GL viewport (square fallback)."""
    try:
        vp = ctx.viewport           # (x, y, w, h)
        if vp[2] > 0 and vp[3] > 0:
            return (vp[2], vp[3])
    except Exception:               # pragma: no cover - mock contexts
        pass
    return (1, 1)


def _perspective(fov_deg, verts, size=(1, 1), near=0.1, far=100.0):
    """Simple perspective projection fitting the mesh."""
    fov = float(fov_deg) * np.pi / 180.0
    if isinstance(size, (tuple, list)):
        w, h = float(size[0]), float(size[1])
    else:
        w = h = float(size)
    aspect = w / h if h > 0 else 1.0
    f = 1.0 / np.tan(fov / 2)
    m = np.zeros((4, 4), dtype="f4")
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = 2 * far * near / (near - far)
    m[3, 2] = -1.0
    return m