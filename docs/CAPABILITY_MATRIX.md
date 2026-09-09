# Capability matrix

What this release can do, and *from where*. Three surfaces reach the same
engine, but they do not expose the same set of verbs:

- **Engine / Python API** — `import am3d` in a Python environment. Source
  installs only; the frozen bundles do not expose an interpreter.
- **Recipe CLI** — the standalone `am3d-recipe` executable shipped in both
  bundles. Declarative JSON in, assets out, no Python required.
- **Desktop GUI** — the `3D MASTER 2005` application shipped in both bundles.

"Yes" means the capability is reachable and covered by tests on that surface.
"No" means it is not reachable there — not that it is planned.

## Modelling

| Capability | Engine / API | Recipe CLI | Desktop GUI |
| --- | --- | --- | --- |
| Primitive patch objects (box, sphere, cylinder, cone, torus, plane) | Yes | Yes | Yes (Create menu) |
| Profile / construction splines | Yes | Yes | Yes (Create ▸ Profile/Spline) |
| Lathe and extrude a profile into a surface | Yes | Yes | Yes (Create menu) |
| Edit a generated surface by moving its profile points | Yes | n/a (declarative) | Yes — the surface regenerates live and undo/redo is exact (EDIT-01) |
| Direct control-point editing of a patch net | Yes | No | Yes (viewport handles) |
| Object transforms, duplication, visibility | Yes | Yes | Yes |
| Boolean/CSG, subdivision, sculpting | No | No | No |

## Materials and appearance

| Capability | Engine / API | Recipe CLI | Desktop GUI |
| --- | --- | --- | --- |
| Flat albedo colour per material | Yes | Yes | Yes (Material tab) |
| Per-*patch* material assignment preserved through render and export | Yes | Yes | Yes (MAT-02) |
| Procedural pattern baking to a texture atlas (e.g. `checker`) | Yes | Yes | **No** — recipe-only; the GUI edits colours and map filenames, it cannot bake an atlas |
| Baked atlas carried into OBJ/MTL (`map_Kd` + PNG) and GLB (embedded `baseColorTexture`) | Yes | Yes | Yes, when the project already carries baked atlases (MAT-01) |
| Node-based material graph | Partial (`am3d.core.material_graph`) | No | No |

## Rigging and animation

| Capability | Engine / API | Recipe CLI | Desktop GUI |
| --- | --- | --- | --- |
| Create / parent / delete bones | Yes | Yes | Yes (Rig menu, UI-01) |
| Bind geometry to a skeleton with automatic proximity weights | Yes | Yes | Yes (Rig ▸ Bind Geometry) |
| Hand-painted vertex weights | No | No | No |
| Pose bones; forward-kinematic deformation | Yes | Yes | Yes |
| Actions, keyframes, interpolation, playback and scrubbing | Yes | Yes | Yes (timeline / dope sheet) |
| Import an action file (`.am3a`) | Yes | No — a recipe generates actions (`walk`, `retarget`, …) rather than importing them | Yes (File ▸ Import Action) |
| Inverse kinematics, constraints, motion blending | No | No | No |

## Rendering

| Capability | Engine / API | Recipe CLI | Desktop GUI |
| --- | --- | --- | --- |
| Software toon rasterizer (no GPU required) | Yes | Yes | Yes |
| GPU deferred renderer via ModernGL/OpenGL | Yes | Yes | Yes |
| Automatic fallback to software when no GL context exists | Yes | Yes | Yes |

| Forced software rendering on demand | Yes | Via the environment (`LIBGL_ALWAYS_SOFTWARE=1`); sheet rendering is a CPU rasterizer already | Yes (render dialog checkbox; `--software` launcher flag) |
| Final still image to PNG | Yes (`am3d.render_job`) | Only as a sprite/toon/animation **sheet** (`spritesheet`, `toon_sheet`, `animation_sheet`) | Yes (File ▸ Render Image / Sequence…, F12) |
| Frame sequence (numbered PNGs) with progress and cancel | Yes | No — a recipe writes one sheet, not numbered frames | Yes |
| Video/container encoding (mp4, gif) | No | No | No |
| Ray tracing, global illumination, shadow maps | No | No | No |

## Exchange and persistence

| Capability | Engine / API | Recipe CLI | Desktop GUI |
| --- | --- | --- | --- |
| Native project save/load (`.am3d`) | Yes | Yes (writes projects) | Yes |
| OBJ + MTL export (tessellated, per-patch material groups) | Yes | Yes | Yes |
| GLB export (glTF 2.0, one primitive per patch material) | Yes | Yes | Yes |
| Sprite sheets / toon sheets / animation sheets | Yes | Yes | No |
| Autosave and crash recovery with document identity | Yes | n/a | Yes (DATA-01/02) |
| Import of OBJ, FBX, glTF or any third-party format | No | No | No |

### What OBJ and GLB exports are, precisely

Both are **static, tessellated snapshots of one pose** — the pose selected at
export time. Spline patches remain the authoritative model; the exported
triangles are an output representation of it.

Neither export carries skeletons, skinning weights, actions or keyframes.
**This release is not a skeletal-animation interchange.** To move animation
out of the application, render a frame sequence.

Open construction splines produce no triangles by design (see
`docs/MODELLING_SCOPE.md`); an object made only of open splines exports an
empty surface, and the application says so rather than writing a silent
empty file.

## Platform availability

| | Linux x86-64 | Windows x86-64 |
| --- | --- | --- |
| Desktop GUI bundle | Built and acceptance-tested on the reference machine | **Not produced in this environment** — no Windows host available |
| Recipe CLI bundle | Built and tested | Same |
| Source install (Python 3.11+) | Yes | Expected; not executed here |

See `docs/SUPPORTED_PLATFORMS.md` for the verified configurations and
`docs/evidence/desktop-release/` for what was actually executed.
