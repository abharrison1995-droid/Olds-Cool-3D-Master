# Capability matrix

This matrix separates the current development source from historical bundles
and from supported-release status. The current source tree contains the
in-app **Create with AI...** workflow. The exact locked Windows development
candidate passed the full source regression and bounded offline frozen
checks. Those local results do not qualify a live provider, artistic quality,
Windows 11 or Mint support, or V1 release acceptance.
The source declarations identify it as `1.0.0.dev1`, a development test
candidate, not a release candidate or stable V1. This is not a build/archive
identity. The accepted Mint preview bundle is a different, older artifact.

| Surface | What it is | Current evidence |
| --- | --- | --- |
| Engine / Python API | `import am3d` from a source environment; frozen bundles do not expose a general Python interpreter. | Phase-scoped source checks; integrated regression status belongs to its recorded source identity. |
| Recipe CLI | `python -m am3d.recipes` from source, or `am3d-recipe` in the historical Mint preview bundle. | Declarative JSON in, checked recipe execution and outputs. |
| Desktop GUI | Home, the spline editor, and the in-source AI creation workspace. | Windows 10 offscreen/source evidence; local candidate results are artifact-specific and do not alone establish V1 acceptance. |
| Benchmark tooling | `scripts/run_ai_benchmark.py` with the fixed V1 fixtures. | Offline methodology and tamper-path tests only; no live benchmark or human scores. |

“Current source” means implementation is present in this development tree.
It does not mean the feature shipped in an accepted archive or passed a V1
gate. “No” means that surface does not expose the capability.

## In-app generation and trust boundaries

| Capability | Engine / API | Recipe CLI | Current desktop source |
| --- | --- | --- | --- |
| Interpret a natural-language brief and build recipe candidates | Yes; offline contract and prompt tests | No; accepts a recipe | Yes; live provider qualification pending |
| Provider configuration | Explicit `ProviderConfig`; model required | No provider call | **AI Settings…** requires an explicit model; current endpoint host allowlist is `api.openai.com` |
| Credential options | Explicit OS store or session store | No provider credential | System credential store or session-only key in memory; keys are not saved to app preferences |
| Request disclosure and explicit send authorization | No UI | No network request | Shows destination, model, payload categories, limits and cost unknown; **Send request** is the explicit authorization action |
| Local recipe policy and bounded isolated worker | Yes | No AI worker | Used by in-app generation; process/data isolation is not an operating-system sandbox |
| Structural artifact checks and whole-scene preview | Yes | The standalone CLI uses its recipe/schema validation contract, not the AI checker | Yes, before generated output is published or offered for editor handoff |
| Local generation history and recipe refinement | Record-store and recipe-refinement APIs | No | **Refresh History**, verified details, writable-copy restore, delete confirmation, and checked-parent child refinement are implemented; owner checks and bounded independent local review passed. The exact locked Windows candidate also passed the full source regression and fixed offline frozen history/refinement checks; repository `PROGRESS.md` and `docs/evidence/v1/ACCEPTANCE_LEDGER.md` record current review dispositions and candidate identity |
| Provider cost ceiling | No | No | No. Dollar cost is unknown; output reservations do not bound input-token billing |

The provider adapter sends one JSON-mode OpenAI-compatible Chat Completions
request contract to the allowlisted `api.openai.com` host. The user chooses
the model; no default model or current price is implied. A request may include
the user's brief, normalized requirements, candidate recipes, fixed schema
and capability context, plus bounded sanitized repair or check feedback. A
new generation does not send the current project, project files, images or
local filesystem paths. The API key is sent in the authorization header.
The confirmation dialog describes these categories before transmission.
Generation records and assets are stored locally; do not enter secrets or
private information into a brief unless you intend to send it to the provider.

Current orchestrator and worker bounds are: four candidate slots, five
semantic provider calls, up to ten HTTP attempts by the adapter, 90 seconds
per HTTP attempt, a 600-second shared run deadline, and 180 seconds per worker
attempt. The provider contract does not expose actual HTTP-attempt counts.
These limits bound local work, not provider input-token use or dollar spend.

The checker establishes selected structural and semantic requirements,
file-path and size safety, artifact hashes, native reopenability, and a
bounded nonblank preview. It does not measure artistic quality or guarantee
that a person will find the result useful. Benchmark methodology and its
unpassed live/human gates are in
[`docs/evidence/v1/phase-8/IMPLEMENTATION.md`](evidence/v1/phase-8/IMPLEMENTATION.md).

The **Saved generations and refinements** panel verifies a selected completed
record's manifest, native project and checked preview before enabling restore
or refinement. **Restore Selected in Editor** opens a separate writable copy;
the history snapshot remains immutable. A refinement sends the selected
parent's accepted brief and recipe, its verified lineage, and the explicit
change request, then creates a new child using a full replacement recipe.
The current project and manual edits are not sent or automatically merged.
When the current authored session (including action state) differs from the
saved generation, **Save manual copy**, **Refine original generation**, and
**Cancel** are the explicit choices. The change field is limited to 4 KiB.
Parent deletion has a separate confirmation and never cascades to children.
Phase 7 owner-run offline evidence is available in
[`ui-history-evidence.md`](evidence/v1/phase-7/ui-history-evidence.md);
the bounded local independent preservation/refinement review also passed. Its
five history UI tests, measured four-change refinement node, and Unicode
286-character preview-path probe are recorded in
[`INDEPENDENT_REVIEW.md`](evidence/v1/phase-7/INDEPENDENT_REVIEW.md) and
[`ROOT_ACCEPTANCE.md`](evidence/v1/phase-7/ROOT_ACCEPTANCE.md). The exact locked
Windows development candidate has since passed the full source regression and
fixed offline frozen history/refinement checks. The repository `PROGRESS.md`
and `docs/evidence/v1/ACCEPTANCE_LEDGER.md` record current independent-review
dispositions and the exact local candidate identity.
Windows 11 and Mint target qualification, native/read-only/GPU gates,
live-provider and human-quality gates, and overall V1/RC acceptance remain
open.

### Benchmark tooling status

The developer runner [`scripts/run_ai_benchmark.py`](../scripts/run_ai_benchmark.py)
uses the fixed release fixture of 30 cases (25 static, 5 rig/animation) and a
separate eight-case discovery fixture. Failed/interrupted attempts remain in
the denominator. Fake and replay modes never qualify a result and always
report `NONQUALIFYING`. A release gate requires two complete live runs; each
must reach at least 27/30 deterministic successes, with at least 20/25 static
and 4/5 rig cases, then two independent complete reviewer score files per
run with at least 24/30 acceptable assets in each review. Only artifacts with
verified generation receipts, manifests, native reopen/save/reopen and
decoded nonblank previews are eligible for score templates. No live run,
reviewer identity or score is recorded. The runner's output-token reservation
does not cap input tokens or dollar cost; actual cost and HTTP-attempt counts
may remain unknown.

## Modeling

| Capability | Engine / Python API | Recipe CLI | Desktop GUI |
| --- | --- | --- | --- |
| Primitive patches: box, sphere, cylinder, cone, torus and plane | Yes | Yes | Yes (Create menu) |
| Construction/profile splines | Yes | Yes | Yes (Create → Profile/Spline; spline control points) |
| Lathe/extrude from a profile | Yes | Yes | Yes (Create menu) |
| Edit recipe-generated lathe/extrude source profile and regenerate surface | Yes | Declarative input | Yes in current source through spline-point commands; focused undo/redo/save/reopen checks |
| Transform and assign material to an object | Yes | Yes | Yes (Object and Material properties) |
| Direct generic patch control-net editing | API/data access | No interactive editor | **No general-purpose GUI editor**; a guide spline does not reshape a baked patch |
| Boolean/CSG, subdivision and sculpting | No | No | No |

Spline-patch/profile semantics and empty-surface behavior are described in
[`MODELLING_SCOPE.md`](MODELLING_SCOPE.md). The Phase 6 correction specifically
covers recipe-produced profiles; it does not add a general net editor.

## Materials and appearance

| Capability | Engine / Python API | Recipe CLI | Desktop GUI |
| --- | --- | --- | --- |
| Flat albedo color per material | Yes | Yes | Yes (Material tab) |
| Per-patch material assignment carried through checked render/export | Yes | Yes | Source display/edit support; see the named material evidence |
| Procedural pattern baking to texture atlas | Yes | Yes | No graph or procedural-atlas editor; the GUI edits colors and map fields |
| Baked atlas in OBJ/MTL and embedded GLB texture | Yes | Yes | Can inspect/use a project that already contains supported baked data |
| Recipe material graph | Limited chain | Limited `materials[].graph` chain | No graph editor |

The supported material graph is a limited evaluated chain, not a general node
editor or arbitrary topology. In particular, the recipe chain does not expose
independently wired `mix` inputs. See the recipe guide and
`am3d/recipes/test_executor.py::test_graph_material_bakes_through_recipe`.
The AI preview represents textures and patterns by base material color and
does not establish full texture fidelity.

## Rigging and animation

| Capability | Engine / Python API | Recipe CLI | Desktop GUI |
| --- | --- | --- | --- |
| Create, parent and delete bones | Yes | Yes | Yes (Rig menu and Bone properties) |
| Bind geometry with automatic proximity weights | Yes | Yes | Yes |
| Hand-painted weights | No | No | No |
| Pose bones and forward-kinematic deformation | Yes | Yes | Yes |
| Actions, keyframes, interpolation, playback and scrubbing | Yes | Yes | Yes (Animate/timeline) |
| Import `.am3a` action file | Yes | No recipe import action | Yes (File → Import Action) |
| Analytic two-bone IK helper | Yes (`core.rigging.ik_two_bone`) | No integrated workflow | No |
| Action blending helper | Yes (`core.animation.ActionBlender`) | No integrated workflow | No |
| Integrated IK, constraints or action-blending workflow | No | No | No |

## Rendering

| Capability | Engine / Python API | Recipe CLI | Desktop GUI |
| --- | --- | --- | --- |
| Software toon rasterizer | Yes | Yes; sheet outputs use CPU | Yes |
| ModernGL/OpenGL renderer | Yes | No; recipe sheets remain CPU-rendered | Yes when a usable context is available |
| Software fallback | Yes | Not applicable | Yes |
| Still PNG and numbered PNG frame sequence | Yes | No; recipe exports image sheets | Yes (File → Render Image / Sequence…, F12) |
| Sprite, toon and animation sheets | Yes | Yes; CPU rasterizer | No sheet-authoring command |
| Video/container encoding | No | No | No |
| Ray tracing, global illumination and shadow maps | No | No | No |

## Exchange, projects and provenance

| Capability | Engine / Python API | Recipe CLI | Desktop GUI |
| --- | --- | --- | --- |
| Native `.am3d` save/load | Yes | Yes | Yes |
| OBJ/MTL export | Yes; tessellated surfaces | Yes | Yes |
| GLB export | Yes; static glTF 2.0 pose | Yes | Yes |
| `.am3d` rig/action persistence | Yes | Yes | Yes |
| OBJ/GLB skeletal animation | No | No | No |
| Optional bounded generation envelope in native format 2 | Yes | Yes | Preserved by current writer; older explicit-root-field writers can drop it on save |
| Authoritative checked generation history sidecars | Yes | No | Current source verifies history; owner evidence and bounded independent local review passed. The exact locked Windows candidate passed the full source regression and frozen history/refinement checks; repository `PROGRESS.md` and `docs/evidence/v1/ACCEPTANCE_LEDGER.md` record current review disposition and candidate identity; overall release acceptance remains open |
| Import OBJ, FBX, glTF or another third-party model format | No | No | No |

OBJ and GLB are static tessellated snapshots of one selected pose; they do not
carry a skeleton, skin weights or keyframes. See
[`MODELLING_SCOPE.md`](MODELLING_SCOPE.md) for construction curves, profiles
and export contents.

## Platform availability

| | Linux Mint 22.3 x86-64 | Windows 11 x86-64 | Current source workstation |
| --- | --- | --- | --- |
| V1 status | Selected target; historical preview artifact accepted for its Qt offscreen/software scope only. No V1, native desktop or physical-GPU qualification. | Selected target; V1 qualification remains open. Candidate identity and checks are artifact-specific; supported publication requires all target gates. | Windows 10 IoT Enterprise LTSC build 19044 x86-64; not a selected V1 target. |
| Source checks | Historical preview test record only; it is not current V1 source evidence. | Target-specific test results are recorded against their exact source/artifact identity; they do not alone establish V1 qualification. | Phase 0 baseline: 738 existing-source tests and 14 offscreen smoke steps; later bounded AI, profile, lifecycle and benchmark suites have their own evidence. |
| Exact artifact identity | Historical Mint preview archive `4d41c0cf7cbf069edf907483cbf16ff4b0f8dcc54130aa791a16a049568d6433`, inputs `6e62c8cdf6ecfb578885f852391b5d8b50d118a6405b9f4817cb36aa0fd60283`. | Candidate identity and check results are artifact-specific; consult companion provenance, inputs, checksum, and acceptance reports. | Source checkout; any local candidate identity and checks belong in its companion artifact reports. |

The separate historical MX 25.2 artifact has source commit
`b96c922a3c9d6461f0e4888ce47dbc28b3449067` and archive SHA-256
`ad36d7ef798d3fd3bd7dc68bd15a8540a8c535655b2e8ec1e7fe6e86eefc4cdf`. It is
not the Mint preview artifact and neither artifact qualifies current V1.
Details and exact platform ladder are in
[`SUPPORTED_PLATFORMS.md`](SUPPORTED_PLATFORMS.md),
[`WINDOWS_ACCEPTANCE_PLAN.md`](WINDOWS_ACCEPTANCE_PLAN.md), and
[`PROGRESS.md`](../PROGRESS.md).
