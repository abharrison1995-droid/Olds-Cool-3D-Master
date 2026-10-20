# Product

<!-- impeccable:product-schema 1 -->

## Platform

Desktop

## Users

The primary user is a person prototyping stylised assets for indie or retro
games. External agents can still author recipes through the machine-readable
interface; they are an execution path rather than the product's primary user.

## Product purpose

3D MASTER:2005 combines a spline-patch modeling and animation editor with
structured asset generation. The current development source includes a
first-class brief-and-provider workflow in the Home screen. It builds bounded
`recipe-v1` candidates, runs them through the local policy, worker and
deterministic-check pipeline, and preserves editable `.am3d` projects for
review in the editor. The source version declarations are `1.0.0.dev1`, a
development test candidate rather than a release candidate or stable V1
release. This version is not a built-artifact identity or V1 qualification.
Local frozen/test results apply only to the candidate identified in its
companion build provenance, input, checksum, and acceptance reports; they do
not alone qualify V1. Live-model capability, human quality and selected-target
acceptance remain open.

## Positioning

The product is an integrated editor and asset-generation workflow. B-spline
patches and their profile splines are native editable data; tessellated meshes
are derived for display, preview, rendering and supported export. The
`recipe-v1` JSON interface remains the structured execution contract used by
the in-app workflow and the standalone recipe CLI.

## Operating context

- The editor is organized into Layout, Model, Rig, Animate and Render workspaces.
- The Home screen includes **Create with AI...**, New/Open, recent projects,
  examples, recovery and help actions. The natural-language workflow is in
  current source; historical accepted bundles do not qualify it.
- The configured provider uses one OpenAI-compatible Chat Completions adapter
  and an explicit model name. The current host allowlist contains
  `api.openai.com`; no model or tariff is chosen by default.
- A run makes no provider request until the user selects **Send request**
  after seeing the destination, model, data disclosure and limits.
- Windows 11 x86-64 and Linux Mint 22.3 x86-64 are the selected V1 targets.
  Neither has passed V1 qualification. The current source checks use Windows
  10 IoT Enterprise LTSC build 19044 x86-64 in offscreen mode.
- The accepted Linux Mint preview and older MX archive are different
  historical artifacts. Their identities and tested scope are recorded in
  `docs/RELEASE_NOTES.md` and `docs/SUPPORTED_PLATFORMS.md`.

## Capabilities and constraints

- Primitive patches support object transforms and material edits. Recipe
  lathe/extrude objects retain a source profile whose control points can shape
  the generated surface through existing spline commands. The desktop editor
  does not provide a general arbitrary patch control-net editor; unrelated
  guide-spline movement does not reshape a baked surface.
- The native `.am3d` project stores the editable scene, supported rig/action
  data, and local resource references. Format 2 can carry an optional bounded
  generation envelope. Older explicit-root-field writers may drop that
  optional metadata on save; the generation sidecar is the history authority.
- OBJ and GLB are static tessellated snapshots of one selected pose. They do
  not carry skeletons, weights or keyframes. Recipe sprite, toon and animation
  sheets use the CPU rasterizer.
- AI runs allow at most four candidates and five semantic provider calls, with
  up to ten HTTP attempts, a 90-second HTTP-attempt limit, a 600-second shared
  run deadline, and a 180-second worker-attempt limit. These bounds do not
  bound provider input-token charges or dollar cost; cost is unknown.
- Provider keys use the OS credential store or explicit process-memory-only
  session storage. Keys are not written to application preference files.
  Generated briefs, recipes, check results and artifacts are stored locally.
  See `docs/USER_GUIDE.md` for the request disclosure.
- Deterministic checks establish structural and selected semantic conditions,
  file integrity, native reopenability and a nonblank preview. They do not
  measure artistic quality or guarantee a useful asset.
- Third-party 3D format import, hand-painted weights, video encoding, ray
  tracing, and integrated IK/constraint/action-blending workflows are
  unavailable. Python helper APIs do not imply a reachable GUI workflow.
- macOS is outside the selected V1 platform scope.

## Brand commitments

The editor should feel like a serious Blender-meets-early-2000s desktop
workbench: dense, tactile, direct and centered on the scene rather than a
decorative chat surface.

## Evidence on hand

The active plan and phase ledger are `docs/V1_MASTER_IMPLEMENTATION_PLAN.md`
and `PROGRESS.md`. Phase evidence is under `docs/evidence/v1/`. Product and
workflow references include `README.md`, `docs/QUICK_START.md`,
`docs/USER_GUIDE.md`, `docs/CAPABILITY_MATRIX.md`, `docs/MODELLING_SCOPE.md`,
and `docs/SUPPORTED_PLATFORMS.md`. No customer outcomes or live-provider
quality measurements are recorded.

## Product principles

- Put the person's natural-language intent first while keeping `recipe-v1`
  and the standalone CLI available for structured work.
- Keep generated work available as editable native projects that people can
  inspect and continue in the desktop editor.
- Keep spline patches and associated profiles as authoritative source data;
  treat evaluated triangles and static exports as derived outputs.
- Describe source capability, checked-asset status, benchmark evidence and
  supported release status as separate things.
