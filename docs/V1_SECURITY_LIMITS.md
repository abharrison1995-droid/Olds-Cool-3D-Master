# V1 security and resource limits

These initial ceilings bound AI-mode validation, estimation, worker execution,
and publication. Apply checks before expensive allocation and again to actual
results. They do not change the trusted offline CLI's existing behavior.

| Resource | Initial ceiling |
| --- | ---: |
| Recipe JSON | 128 KiB |
| Provider JSON response | 1 MiB |
| Objects / patches | 128 / 1,024 |
| Bones per skeleton / total copied bones | 64 / 256 |
| Actions / channels / keys | 16 / 256 / 4,096 |
| Authored profile and control points | 4,096 |
| Primitive sections, rings, or grid subdivisions | 128 each |
| Materials / graph nodes per material | 32 / 32 |
| Tessellation per patch | 32 × 32 |
| Evaluated triangles | 250,000 |
| Preview | 512 × 512 pixels |
| Sheet cells / cell size | 16 / 256 × 256 pixels |
| Combined sheet image pixels | 16 million |
| Atlas cell / combined atlas pixels | 256 / 64 million |
| Published output bytes | 256 MiB |
| Worker memory target | 1 GiB |

Estimate control nets and texture memory before constructing them, then count
the built scene. Convert `MemoryError` to `resource_exhausted` with a useful
message. Use OS memory enforcement when available; on every platform retain
preflight estimates, count limits, process termination, and deadline bounds.
No case may rely solely on OS memory control.

Names are strings. AI object names match
`^[A-Za-z0-9_][A-Za-z0-9_ .-]{0,63}$`. Derived filenames use one sanitizer;
the resolved destination is checked against the host-chosen output root both
before writing and before publication. AI mode accepts no texture file paths.

Every run has at most one generation, two validation repairs, one
execution/check repair, one transport retry, and its provider deadline. Cloud
deadline is 10 minutes; local deadline is about 20 minutes. Logs, recipes,
provider responses, and artifacts have explicit size caps. API adapter, when
enabled, must enforce `$0.10` and 40k tokens per run, `$1` per day, and `$5`
per month before each call and stop at a cap. No automatic retry for auth,
refusal, quota, or policy errors.

The worker receives only recipe, immutable policy snapshot, and private
output root. It never receives provider credentials or access to the active
document. Provider output is hostile input and passes all registry, path,
resource, reopen, geometry, preview, animation, and independent-export
checks. See the active plan for the complete invariants.
