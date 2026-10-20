# External recipe agent guide — schema version 1

Emit one JSON object matching [`recipe-v1.schema.json`](recipe-v1.schema.json).
The `version` field is optional for backwards compatibility and defaults to
`1`; any other version is rejected. Unknown fields are rejected with a stable
error record instead of being silently ignored.

This guide documents the external-agent and recipe-CLI contract. The current
development source also has a first-class **Create with AI...** workflow, but
the accepted Mint preview bundle is an older artifact and does not qualify
that workflow or V1. The CLI remains a separate, provider-free way to run
structured recipe JSON. See [the active V1 plan](../V1_MASTER_IMPLEMENTATION_PLAN.md)
and [`SUPPORTED_PLATFORMS.md`](../SUPPORTED_PLATFORMS.md).

## 1. Invocation & Machine Interface

Invoke the shipped source entry point with:

```text
python -m am3d.recipes --recipe recipe.json --out output-directory
```

Stdin execution is also supported:

```text
cat recipe.json | python -m am3d.recipes --recipe - --out output-directory
```

Machine mode prints exactly one JSON result to `stdout`. Diagnostics are also
written to `stderr`. A successful execution result has `ok: true`, an artifact
`manifest`, and one manifest entry per physical file. A successful
`--validate-only` result has `ok: true` and `validated: true` and intentionally
has no manifest because it writes no artifacts. A recipe failure has
`ok: false` and
`error_records` containing `code`, `stage`, `path`, `message`, and an optional
`hint`. Exit code `0` means success; exit code `1` means parse, validation,
runtime, resource, or write failure.

Argument/usage errors are handled by the command-line parser: they print usage
to `stderr` and exit with code `2`; they do not produce the recipe JSON report.
`--verbose` writes human-readable progress before the JSON result, so its
`stdout` is mixed and is not suitable for a machine parser. Omit it for an
agent-driven invocation.

Use `--validate-only` to check a recipe without creating a Session or any
output. With `--out`, every export path must be relative and must resolve
inside that directory; absolute paths, drive letters, and traversal escapes are rejected.
Without `--out`, relative exports resolve next to the recipe file.

Recipes are declarative data interpreted by fixed application code; they do
not carry executable Python. The standalone CLI is not an operating-system
sandbox. Keep untrusted recipe execution in a controlled environment and use
an explicit output root.

### Packaged entry points (no Python required)

The accepted Linux Mint 22.3 preview candidate includes `./am3d-recipe`
alongside the GUI. That historical artifact is identified by archive SHA-256
`4d41c0cf7cbf069edf907483cbf16ff4b0f8dcc54130aa791a16a049568d6433` and
build-input digest
`6e62c8cdf6ecfb578885f852391b5d8b50d118a6405b9f4817cb36aa0fd60283`; it was
checked with Qt offscreen/software paths and is not V1 qualification. It is a
different artifact from the older MX archive built from `b96c922`, SHA-256
`ad36d7ef798d3fd3bd7dc68bd15a8540a8c535655b2e8ec1e7fe6e86eefc4cdf`.
Invoke the Mint preview executable with the same options shown above. It is a
standalone build of this entry point for an external process that cannot rely
on Python being installed.

The Windows build definition is intended to produce `am3d-recipe.exe`
alongside the GUI executable. Windows 11 x86-64 is a selected V1 target, but
no Windows V1 qualification is recorded. A Windows candidate may be produced
for testing; do not describe it as a supported release until the actual
acceptance gates pass. When available, invoke it as follows:

```text
am3d-recipe.exe --recipe recipe.json --out output-directory
```

```text
type recipe.json | am3d-recipe.exe --recipe - --out output-directory
```

It is built from the identical `am3d.recipes.cli:main` source as
`python -m am3d.recipes`, so JSON report shape, exit codes (`0`/`1`),
stdin (`--recipe -`) support, and `--validate-only` semantics are exactly
the same -- only the invocation differs.

## 2. Coordinate, Angle, and Time Conventions

- **Coordinate System**: Right-handed, $Y$-up, $X$-right, $Z$-forward.
- **Units**: 1.0 unit $\approx$ 1.0 meter.
- **Rotations**: Expressed as Euler angles in radians or quaternion `[x, y, z, w]`.
- **Time**: All durations and keyframe times are floating-point seconds ($> 0$).
- **Colors**: `[r, g, b]` or `[r, g, b, a]` normalized in the range $[0.0, 1.0]$.
- **PBR Roughness / Metalness**: Normalized in the range $[0.0, 1.0]$.

## 3. Supported Primitives & Parameters

Supported primitives under `objects[].primitive`:
- `sphere`: `radius` (float), `sections` (int, longitude divisions), `rings` (int, latitude divisions).
- `box`: `width` (float), `height` (float), `depth` (float), `n` (int, optional, default 4, grid density per face).
- `cylinder`: `radius` (float), `height` (float), `sections` (int), `capped` (bool, optional, default true), `rings` (int, optional, default 4, axial tessellation density).
- `cone`: `radius` (float), `height` (float), `sections` (int), `rings` (int, optional, default 5, axial tessellation density).
- `torus`: `major_radius` (float), `minor_radius` (float), `major_sections` (int, revolutions around the ring), `minor_sections` (int, divisions of the tube cross-section).
- `plane`: `width` (float), `height` (float), `n` (int, optional, default 4, grid density).
- `lathe`: revolves an explicit profile around the Y-axis. Params: `profile` (required, array of `[radius, axial]` pairs, at least 2), `axis` (str, default `"y"`), `sections` (int).
- `extrude`: sweeps an explicit profile along +Y. Params: `profile` (required, array of `[x, y, z]` points, at least 2), `height` (float), `twist_deg` (float), `rings` (int).

For recipe-generated `lathe` and `extrude` objects, the current executor
retains a source profile spline together with the existing surface generator
and effective degrees in the native project. In the current desktop source,
editing that profile spline's control points changes the generated surface
and supports undo/redo and save/reopen. This is a specific profile workflow;
there is no general desktop patch control-net editor, and moving an unrelated
guide spline does not reshape a baked primitive. See
[`MODELLING_SCOPE.md`](../MODELLING_SCOPE.md).

## 3a. Material Patterns

`materials[].pattern` selects a procedural texture instead of a flat colour.
Valid values: `solid`, `checker`, `gradient`, `noise`, `bricks`. An unrecognized
value is rejected at runtime. Each takes its own optional `params`:
- `solid`: `color`, `size`.
- `checker`: `a`, `b` (colours), `cells` (int), `size`.
- `gradient`: `top`, `bottom` (colours), `size`.
- `noise`: `seed`, `size`, `octaves`, `base` (colour), `contrast`.
- `bricks`: `brick`, `mortar` (colours), `rows`, `cols`, `mortar_px`, `size`.

Recipes may also provide `materials[].graph`, which supersedes `pattern` and
evaluates a limited chain of graph nodes: `source`, `solid`, `checker`,
`gradient`, `noise`, `bricks`, `mix`, `noise_overlay`, and `tint`. This is
chain-based data evaluated and baked by the recipe executor, not a general
graph editor or arbitrary graph topology. In particular, recipe chains do not
provide independently wired inputs to `mix`, so it cannot blend two distinct
generated branches. For example,
`am3d/recipes/test_executor.py::test_graph_material_bakes_through_recipe`
covers a `bricks -> noise_overlay` chain and atlas output.

## 4. Rigging & Bone Rules

- Bone definitions must supply `name`, `head: [x, y, z]`, `tail: [x, y, z]`.
- `parent` references must refer to an earlier or co-defined bone in the same object.
- **Acyclic Hierarchy**: Bone parenting must form an acyclic tree. Circular references (`A -> B -> A` or self-parenting) are rejected.
- Procedural actions (`walk`, `idle`, `jump`) require a rigged character with bones.

For a character split across recipe objects, put the bone definitions on one
geometry-free rig object, then set `objects[].params.skeleton` to that rig
object on **every geometry object that should deform**. The executor copies
the rig bones onto each referenced geometry object and auto-weights that
object's control points to its nearest bones. An action's `character` names
the rig object. Declaring an action and a rig does not bind unrelated objects
automatically: unreferenced geometry remains static.

The current recipe contract skins geometry in each object's local coordinate
frame, then applies `transform`. Keep rigged geometry in the shared rig
coordinate frame and leave those objects' `transform` at identity so weights
and bone positions line up. Put geometry placement in the primitive's
coordinates/profile. A non-identity transform on skinned geometry is not
rebased into the rig frame by recipe v1.

Before calling an action usable, inspect at least two evaluated frames and
confirm the intended geometry changes position or shape. The generated
animation sheet is a flat-color preview; it does not preserve the material
textures. Use the `.am3d` project or textured GLB/OBJ materials to inspect
surface appearance.

## 5. Artifact Formats & Capabilities

- `.am3d`: Native editable project preserving patches, splines, bones, actions, active action, and assignments. Current format 2 may also carry an optional bounded generation envelope. Older explicit-root-field writers can drop that optional metadata when saving; the local generation sidecar remains the history authority.
- `.obj`: Static Wavefront OBJ mesh (bind or posed, whichever pose is active) with normals and UV coordinates. Its optional `.mtl` sidecar carries flat diffuse colours and, for baked procedural/image appearance, `map_Kd` references to PNG texture atlases written beside the OBJ.
- `.glb`: Static binary glTF 2.0 asset (bind or posed). Flat colours use `pbrMetallicRoughness.baseColorFactor`; baked procedural/image appearance is embedded as `baseColorTexture`, so the GLB remains self-contained. These are **static pose snapshots only** — OBJ and GLB do not embed skeletons, weights, or animation data. Do not describe either as an animated export.
- `spritesheet`: Rendered orthographic or perspective **multi-view** sprite grid — one object orbited through `views` camera angles at a fixed pose (`views`, `size`, `color`, `silhouette`).
- `toon_sheet`: Cel-shaded multi-view sprite sheet with ink outlines (`bands`, `ink`).
- `animation_sheet`: Rendered **animation** sprite grid — the whole scene composited at `frames` evenly-spaced times across `action`'s `start`..`end` range (`action`, `frames`, `columns`, `size`, `color`, `start`, `end`). Distinct from `spritesheet`/`toon_sheet`: it samples *time*, not camera angle, and every cell shares the same view.

Recipe `spritesheet`, `toon_sheet`, and `animation_sheet` outputs use the CPU
software rasterizer. The recipe CLI does not route these sheet exports through
the ModernGL GPU renderer.

## 6. External Agent Error-Correction Loop

When a recipe is rejected, inspect `error_records` in the JSON stdout response:

```json
{
  "ok": false,
  "errors": ["object 'hero': duplicate bone name 'arm'"],
  "error_records": [
    {
      "code": "duplicate_bone_name",
      "stage": "schema",
      "path": "recipe.objects[1].bones[2].name",
      "message": "object 'hero': duplicate bone name 'arm'",
      "hint": "Ensure each bone name within an object is unique."
    }
  ]
}
```

Correction workflow:
1. Locate the exact JSON path specified in `record.path` (e.g. `recipe.objects[1].bones[2].name`).
2. Read the error code and correction hint.
3. Fix the offending field in your JSON model output.
4. Retry execution with the updated recipe.

## 7. Examples

- [Minimal Cube Recipe](examples/minimal.json)
- [Fully Rigged Knight Recipe](examples/knight_full.json)
