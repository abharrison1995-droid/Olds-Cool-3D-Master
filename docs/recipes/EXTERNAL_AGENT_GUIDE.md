# Recipe v1 agent contract

Emit one JSON object that matches the [full recipe schema](recipe-v1.schema.json).
Provider prompts should use the [compact provider schema](recipe-v1.provider.schema.json),
which omits legacy graph nodes. The `version` field defaults to `1`.

Run it through the host CLI; never emit or execute Python, shell commands,
imports, or filesystem paths. The host owns the private output directory:

```text
am3d-recipe --recipe recipe.json --out private-output --ai-mode
am3d-recipe --recipe recipe.json --out private-output --ai-mode --validate-only
```

AI mode rejects texture file paths and confines derived files to `--out`.
Only registry-listed primitives, patterns, graph nodes, actions, channel
properties, interpolation modes, and export formats are available. Recipe
names must be strings; object names use letters, digits, spaces, `.`, `_`, or
`-`. Keep all requested output paths relative to the supplied output root.

The machine report has `ok`, relative `artifacts`, `warnings`, and structured
`error_records`. On failure, correct the field at each record's `path` using
its expected/received detail and `hint`, then submit the complete recipe again.
`--validate-only` checks the contract, output paths, and resource estimate
without building geometry or writing artifacts.

Coordinates are right-handed, Y-up, X-right, and Z-forward. One unit is about
one metre; durations and key times use seconds; Euler angles in recipe actions
use radians unless a field is explicitly named `*_deg`. Spline patches remain
the editable source; meshes are derived during evaluation and export.

An assigned action must move bound geometry. In AI mode, a recipe that creates
an action with no visible effect fails its deterministic host check. Legacy
`source` and `mix` graph nodes remain readable in old projects but are not
available for new model-generated recipes.

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
