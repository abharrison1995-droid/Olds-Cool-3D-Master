# External recipe agent guide — schema version 1

Emit one JSON object matching [`recipe-v1.schema.json`](recipe-v1.schema.json).
The `version` field is optional for backwards compatibility and defaults to
`1`; any other version is rejected. Unknown fields are rejected with a stable
error record instead of being silently ignored.

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
output. It also resolves every export path, checks output-root confinement,
and reports an allocation-free resource estimate. With `--out`, every export
path must be relative and must resolve inside that directory; absolute paths,
drive letters, and traversal escapes are rejected. Without `--out`, relative
exports resolve next to the recipe file.

### Packaged entry points (no Python required)

See [`../SUPPORTED_PLATFORMS.md`](../SUPPORTED_PLATFORMS.md) for current
packaged CLI availability and qualification status. When available, invoke
`./am3d-recipe` with the same options shown above. It is a standalone build
of this entry point for an external process that cannot rely on Python.

When a Windows package is available, invoke it as follows:

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

## 3a. Material Patterns

`materials[].pattern` selects a procedural texture instead of a flat colour.
Valid values: `solid`, `checker`, `gradient`, `noise`, `bricks`. An unrecognized
value is rejected during validation. Each takes its own optional `params`:
- `solid`: `color`, `size`.
- `checker`: `a`, `b` (colours), `cells` (int), `size`.
- `gradient`: `top`, `bottom` (colours), `size`.
- `noise`: `seed`, `size`, `octaves`, `base` (colour), `contrast`.
- `bricks`: `brick`, `mortar` (colours), `rows`, `cols`, `mortar_px`, `size`.

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

- `.am3d`: Native editable project preserving patches, splines, bones, actions, active action, and assignments.
- `.obj`: Static Wavefront OBJ mesh (bind or posed, whichever pose is active) with normals and UV coordinates. Its optional `.mtl` sidecar carries flat diffuse colours and, for baked procedural/image appearance, `map_Kd` references to PNG texture atlases written beside the OBJ.
- `.glb`: Static binary glTF 2.0 asset (bind or posed). Flat colours use `pbrMetallicRoughness.baseColorFactor`; baked procedural/image appearance is embedded as `baseColorTexture`, so the GLB remains self-contained. These are **static pose snapshots only** — OBJ and GLB do not embed skeletons, weights, or animation data. Do not describe either as an animated export.
- `spritesheet`: Rendered orthographic or perspective **multi-view** sprite grid — one object orbited through `views` camera angles at a fixed pose (`views`, `size`, `color`, `silhouette`).
- `toon_sheet`: Cel-shaded multi-view sprite sheet with ink outlines (`bands`, `ink`).
- `animation_sheet`: Rendered **animation** sprite grid — the whole scene composited at `frames` evenly-spaced times across `action`'s `start`..`end` range (`action`, `frames`, `columns`, `size`, `color`, `start`, `end`). Distinct from `spritesheet`/`toon_sheet`: it samples *time*, not camera angle, and every cell shares the same view.

<!-- capability-registry:start -->
## Capability Registry (generated)

Validation accepts the parameter names and types listed here. Limits
apply during validation; `(hidden)` entries remain readable for legacy
recipes but are not offered to AI generation.

### Primitives

| Name | Parameters | AI | Description |
| --- | --- | :---: | --- |
| `sphere` | `radius` `number` (default `1.0`; min 0.0001); `sections` `integer` (default `16`; min 4, max 128); `rings` `integer` (default `8`; min 4, max 128) | yes | Create a UV sphere. Cost: Control-net cost grows with sections × rings. |
| `cylinder` | `radius` `number` (default `0.5`; min 0.0001); `height` `number` (default `1.0`; min 0.0001); `sections` `integer` (default `16`; min 4, max 128); `capped` `boolean` (default `true`); `rings` `integer` (default `4`; min 4, max 128) | yes | Create a capped or open cylinder along +Y. Cost: Control-net cost grows with sections × rings. |
| `cone` | `radius` `number` (default `0.5`; min 0.0001); `height` `number` (default `1.0`; min 0.0001); `sections` `integer` (default `16`; min 4, max 128); `rings` `integer` (default `5`; min 4, max 128) | yes | Create a cone along +Y. Cost: Control-net cost grows with sections × rings. |
| `torus` | `major_radius` `number` (default `1.0`; min 0.0001); `minor_radius` `number` (default `0.3`; min 0.0001); `major_sections` `integer` (default `24`; min 4, max 128); `minor_sections` `integer` (default `12`; min 4, max 128) | yes | Create a torus around the Y axis. Cost: Control-net cost grows with major_sections × minor_sections. |
| `box` | `width` `number` (default `1.0`; min 0.0001); `height` `number` (default `1.0`; min 0.0001); `depth` `number` (default `1.0`; min 0.0001); `n` `integer` (default `4`; min 3, max 128) | yes | Create a six-patch box. Cost: Six grids; each has n × n control points. |
| `plane` | `width` `number` (default `1.0`; min 0.0001); `height` `number` (default `1.0`; min 0.0001); `n` `integer` (default `4`; min 3, max 128) | yes | Create a flat XY plane. Cost: One grid with n × n control points. |
| `lathe` | `profile` `profile2` (required; length 2–4096); `axis` `string` (default `"y"`; one of `x`, `y`, `z`); `sections` `integer` (default `24`; min 4, max 128) | yes | Revolve a 2D radius/height profile. Cost: Control-net cost grows with sections × profile points. |
| `extrude` | `profile` `profile3` (required; length 2–4096); `height` `number` (default `1.0`); `twist_deg` `number` (default `0.0`); `rings` `integer` (default `4`; min 2, max 128) | yes | Extrude a 3D profile along +Y. Cost: Control-net cost grows with rings × profile points. |

### Material patterns

| Name | Parameters | AI | Description |
| --- | --- | :---: | --- |
| `solid` | `color` `color` (default `[0.8,0.8,0.8]`; min 0, max 1, length 3–4); `size` `integer` (default `64`; min 1, max 256) | yes | Fill a texture with one color. Cost: Allocates one square RGBA texture at size × size. |
| `checker` | `a` `color` (default `[0.9,0.9,0.9]`; min 0, max 1, length 3–4); `b` `color` (default `[0.25,0.25,0.28]`; min 0, max 1, length 3–4); `cells` `integer` (default `8`; min 1, max 128); `size` `integer` (default `256`; min 1, max 256) | yes | Create a two-color checker pattern. Cost: Allocates one square RGBA texture at size × size. |
| `gradient` | `top` `color` (default `[1.0,1.0,1.0]`; min 0, max 1, length 3–4); `bottom` `color` (default `[0.2,0.2,0.25]`; min 0, max 1, length 3–4); `size` `integer` (default `256`; min 1, max 256) | yes | Blend a bottom color into a top color. Cost: Allocates one square RGBA texture at size × size. |
| `noise` | `seed` `integer` (default `7`); `size` `integer` (default `256`; min 1, max 256); `octaves` `integer` (default `4`; min 1, max 8); `base` `color` (default `[0.75,0.72,0.68]`; min 0, max 1, length 3–4); `contrast` `number` (default `0.25`; min 0, max 1) | yes | Create seeded value-noise color variation. Cost: Allocates one square RGBA texture at size × size. |
| `bricks` | `brick` `color` (default `[0.62,0.28,0.18]`; min 0, max 1, length 3–4); `mortar` `color` (default `[0.82,0.8,0.76]`; min 0, max 1, length 3–4); `rows` `integer` (default `8`; min 1, max 128); `cols` `integer` (default `4`; min 1, max 128); `mortar_px` `number` (default `4.0`; min 0, max 256); `size` `integer` (default `256`; min 1, max 256) | yes | Create a running-bond brick pattern. Cost: Allocates one square RGBA texture at size × size. |

### Material graph nodes

| Name | Parameters | AI | Description |
| --- | --- | :---: | --- |
| `source` | — | hidden | Pass through an upstream material map. Cost: No texture allocation beyond the current graph map. |
| `solid` | `color` `color` (default `[0.8,0.8,0.8]`; min 0, max 1, length 3–4); `size` `integer` (default `64`; min 1, max 256) | yes | Generate a solid texture in a material graph. Cost: Allocates one square RGBA texture at size × size. |
| `checker` | `a` `color` (default `[0.9,0.9,0.9]`; min 0, max 1, length 3–4); `b` `color` (default `[0.25,0.25,0.28]`; min 0, max 1, length 3–4); `cells` `integer` (default `8`; min 1, max 128); `size` `integer` (default `256`; min 1, max 256) | yes | Generate a checker texture in a material graph. Cost: Allocates one square RGBA texture at size × size. |
| `gradient` | `top` `color` (default `[1.0,1.0,1.0]`; min 0, max 1, length 3–4); `bottom` `color` (default `[0.2,0.2,0.25]`; min 0, max 1, length 3–4); `size` `integer` (default `256`; min 1, max 256) | yes | Generate a gradient texture in a material graph. Cost: Allocates one square RGBA texture at size × size. |
| `noise` | `seed` `integer` (default `7`); `size` `integer` (default `256`; min 1, max 256); `octaves` `integer` (default `4`; min 1, max 8); `base` `color` (default `[0.75,0.72,0.68]`; min 0, max 1, length 3–4); `contrast` `number` (default `0.25`; min 0, max 1) | yes | Generate a noise texture in a material graph. Cost: Allocates one square RGBA texture at size × size. |
| `bricks` | `brick` `color` (default `[0.62,0.28,0.18]`; min 0, max 1, length 3–4); `mortar` `color` (default `[0.82,0.8,0.76]`; min 0, max 1, length 3–4); `rows` `integer` (default `8`; min 1, max 128); `cols` `integer` (default `4`; min 1, max 128); `mortar_px` `number` (default `4.0`; min 0, max 256); `size` `integer` (default `256`; min 1, max 256) | yes | Generate a bricks texture in a material graph. Cost: Allocates one square RGBA texture at size × size. |
| `mix` | `factor` `number` (default `0.5`; min 0, max 1) | hidden | Blend two material maps. Cost: Allocates one square RGBA texture. |
| `noise_overlay` | `amount` `number` (default `0.15`; min 0, max 1); `seed` `integer` (default `7`); `octaves` `integer` (default `3`; min 1, max 8) | yes | Modulate an upstream map with seeded grain. Cost: Allocates one square RGBA texture. |
| `tint` | `color` `color` (default `[1,1,1]`; min 0, length 3–4) | yes | Multiply an upstream map by a color. Cost: Allocates one square RGBA texture. |

### Action kinds

| Name | Parameters | AI | Description |
| --- | --- | :---: | --- |
| `walk` | `stride` `number` (default `0.5`); `amplitude_deg` `number` (default `24.0`); `bob` `number` (default `0.04`) | yes | Generate a looping walk cycle. Cost: Key count scales with the skeleton bone count. |
| `idle` | `sway_deg` `number` (default `2.0`); `breathe` `number` (default `0.012`) | yes | Generate a subtle breathing idle loop. Cost: Key count scales with the skeleton bone count. |
| `jump` | `crouch` `number` (default `-0.22`); `height` `number` (default `0.65`) | yes | Generate a crouch, jump, and landing action. Cost: Key count scales with the skeleton bone count. |
| `custom` | — | yes | Use authored channels and keyframes. Cost: Key count is the number of supplied channel keys. |
| `retarget` | `source_character` `string` (optional); `mapping` `mapping` (optional) | yes | Retarget an earlier action to another skeleton. Cost: Cost scales with source and target bone counts. |

### Export formats

| Name | Parameters | AI | Description |
| --- | --- | :---: | --- |
| `obj` | — | yes | Write a Wavefront OBJ mesh. Cost: Cost scales with evaluated mesh size. |
| `glb` | — | yes | Write a binary glTF mesh. Cost: Cost scales with evaluated mesh size. |
| `am3d` | — | yes | Save an editable project. Cost: Cost scales with project size. |
| `spritesheet` | `views` `integer` (default `8`; min 1, max 16); `size` `integer` (default `256`; min 16, max 256); `color` `color` (default `[0.72,0.74,0.82]`; min 0, max 1, length 3–4); `silhouette` `boolean` (default `false`) | yes | Render orbit views into per-object PNG sheets. Cost: Allocates views × size² pixels per object. |
| `toon_sheet` | `views` `integer` (default `8`; min 1, max 16); `size` `integer` (default `256`; min 16, max 256); `color` `color` (default `[0.85,0.78,0.55]`; min 0, max 1, length 3–4); `bands` `integer` (default `4`; min 2, max 8); `ink` `boolean` (default `true`) | yes | Render toon-shaded orbit views into per-object PNG sheets. Cost: Allocates views × size² pixels per object. |
| `animation_sheet` | `action` `nullable_string` (optional); `frames` `integer` (default `8`; min 1, max 16); `size` `integer` (default `256`; min 16, max 256); `color` `color` (default `[0.72,0.74,0.82]`; min 0, max 1, length 3–4); `start` `number` (default `0.0`); `end` `number` (optional); `columns` `integer` (optional; min 1, max 16) | yes | Render the scene across one action into a PNG frame sheet. Cost: Allocates frames × size² pixels. |

### Channel properties

| Name | Parameters | AI | Description |
| --- | --- | :---: | --- |
| `translate` | — | yes | Animate a bone's translation. Cost: Each key stores a 3D vector, except weight which stores one scalar. |
| `rotate` | — | yes | Animate a bone's rotation. Cost: Each key stores a 3D vector, except weight which stores one scalar. |
| `scale` | — | yes | Animate a bone's scale. Cost: Each key stores a 3D vector, except weight which stores one scalar. |
| `weight` | — | yes | Animate a scalar influence weight. Cost: Each key stores a 3D vector, except weight which stores one scalar. |

### Interpolation modes

| Name | Parameters | AI | Description |
| --- | --- | :---: | --- |
| `linear` | — | yes | Interpolate linearly between keys. Cost: No additional memory. |
| `step` | — | yes | Hold each key until the next key. Cost: No additional memory. |
| `smooth` | — | yes | Interpolate smoothly between keys. Cost: No additional memory. |
<!-- capability-registry:end -->

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
