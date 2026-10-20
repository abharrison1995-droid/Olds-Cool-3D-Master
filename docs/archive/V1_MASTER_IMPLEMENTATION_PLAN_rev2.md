# 3D MASTER:2005 — V1 master implementation plan

Status: **proposed; independent repository review required before implementation**.
Planning date: 2026-10-04. This pass changes documentation only.

## 1. Source binding and authority

- Repository: https://github.com/abharrison1995-droid/Olds-Cool-3D-Master
- Local checkout: `/home/alex/Desktop/Olds-Cool-3D-Master`.
- Branch: `master`.
- Inspected engine/editor HEAD: `02d9443fc55b96fa469fbef98e55caea7b78eed7`.
- Starting working tree: clean, including untracked files reported by Git.
- Version: `0.2.0b1`, matching `pyproject.toml` and `am3d/__init__.py`.
- Origin: `git@github.com:abharrison1995-droid/Olds-Cool-3D-Master.git`.
- The planning commit containing this document changes no implementation; obtain its identity with `git log -1 --format=%H -- docs/V1_MASTER_IMPLEMENTATION_PLAN.md`. Do not confuse it with the inspected implementation HEAD.

Once approved, this document supersedes V1 scheduling in `docs/IMPLEMENTATION_ROADMAP.md`, `docs/DESKTOP_RELEASE_PLAN.md`, and the historical V2/V3 plans. Their execution records remain evidence of their named source/artifact, not current acceptance. Until approval, the existing roadmap remains the published milestone record. Do not delete or rewrite historical evidence. No implementation phase is already PASS merely because the external-agent preview passed.

The change in product direction is deliberate: the desktop will offer first-class natural-language generation, provider settings, bounded orchestration and refinement. External recipe authors and the standalone CLI remain supported. “No embedded model” can still mean no model weights bundled; “no provider/prompt interface” will no longer describe V1.

## 2. Repository archaeology and readiness

The foundation is substantial and should be extended. There is no in-app natural-language pipeline, provider adapter, credential store, generation history, or prompt benchmark today. This is an external-agent/editor preview, not the requested V1. There is no justification for an engine rewrite, web frontend, arbitrary generated Python, or a second scene model.

### Evidence map: implementation wins over labels

| Area | Authoritative files and observed behavior | Consequence for V1 |
| --- | --- | --- |
| Project/session | `am3d/core/project.py`, `core/script.py`: spline/patch dataclasses, objects/materials/skeletons; Session owns actions, assignments, poses and evaluated state | New orchestration uses isolated Session and native Project; do not create another scene graph |
| Persistence | `core/serializer.py`: msgpack format 2, array/depth/count/file limits, explicit field encoding, atomic writes; Session save/load restores action/pose state | Generic generation metadata is absent; adding attributes alone will not persist it. Add a bounded explicit optional field and compatibility tests |
| Evaluation | `core/scene.py:evaluate_scene`, `gpu/__init__.py:resolve_scene`: shared world-space geometry, visibility, skinning, action sampling, materials | Reuse for preview, structural checks, animation checks and export consistency |
| Geometry | `spline/kernel.py`: B-spline/rational evaluation, patch grids, lathe/extrude nets; `core/generators.py`: profile generation/regeneration | Keep patches authoritative. Curves alone are not renderable assets |
| Primitive recipes | `recipes/primitives.py`: box, sphere, cylinder, cone, torus, plane, explicit lathe/extrude profiles; transform supports translation or 4×4 matrix | Props and assembled hard-surface approximations are feasible without new primitives |
| Rig/animation | `core/rigging.py`: FK, proximity weights and deformation; `core/animation.py`, `core/retarget.py`; `recipes/animation.py`: walk/idle/jump/custom/retarget | Basic stylised rigs only. Multi-object rig geometry needs `params.skeleton`; all such geometry must share the rig coordinate frame |
| Materials | `core/material_graph.py`, `renderer/materials.py`, `renderer/uv_mapping.py`, `export/textures.py`: procedural maps/graph evaluation and atlas baking | Existing graph vocabulary is usable data, not a reason to build a node editor |
| Rendering | `renderer/toon.py`, `renderer/sprite.py`; `gpu/` deferred pipeline and software fallback; `render_job.py` still/sequence progress/cancel | Reuse whole-scene rendering. Sheets differ: orbit sheets are per object; animation sheets are composited but flat colour |
| Export | `export/obj.py`, `export/gltf.py`, `export/validate.py`: OBJ/MTL/atlas and GLB; independent readers/validators | Static pose snapshots only. Native file keeps editable rig/actions; no animated GLB promise |
| Recipe contract | `recipes/schema.py`, `docs/recipes/recipe-v1.schema.json`: unknown-field rejection, names/references, numeric checks, structured code/stage/path/hint | Reuse; params dictionaries and graph entries are still broadly typed. Validation-only is not a complete resource/runtime check |
| Execution | `recipes/executor.py:execute`, `_resolve_output_path`, `_run_exports`: new candidate Session; commit only on success; staged exports and manifest; portable path checks when output_root supplied | Preserve transactional session behavior. Publication copies files individually and can fail partially; add outer private-run publication |
| CLI | `recipes/cli.py`, `__main__.py`: stdin/file/BOM support, validate-only, JSON report; `--verbose` mixes stdout | Keep existing machine contract. Do not scrape verbose output for desktop progress |
| Desktop | `ui/app.py:MainWindow`, `home.py`, `workspaces.py`, `area_layout.py`, `viewport3d.py`; `viewport.py` is compatibility shim | Add compact AI work area to the existing Qt workbench, not another application |
| Editing | `ui/operators.py`, `tools_spline.py`, `tools_bone.py`, `properties.py`, `dopesheet.py`, `timeline.py`: QUndoStack commands, CP/net editing, transforms, rig/keyframe/material edits | Adopt completed project through document lifecycle; existing undo starts with subsequent manual edits |
| Lifecycle | `ui/document_controller.py`: single current Session, dirty/save-discard-cancel, clean undo revision, document-specific autosave/recovery; `settings.py`: QSettings | Never swap Session from background worker or write keys to QSettings. Protect current unsaved work |
| Packaging | `build_linux.sh`, `build_windows.ps1`, `am3d.spec`, `am3d_recipe.spec`, platform locks and Windows workflow | Extend frozen payload/provenance/acceptance; recipe executable deliberately excludes Qt/GPU |

Tests inspected include schema/executor/primitives/animation, core serializer/scene/rigging/render roundtrip, spline kernel, renderer, independent export readers, GPU scene tests, and UI home/document/edit/rig/render/smoke tests. Existing tests cover portable traversal rejection, transform/export parity, rig deformation, serialization/undo, atlas appearance and render fallback. These are useful regression gates, not evidence of successful prompt generation.

### Findings that challenge assumptions

1. **recipe-v1 is sufficient to start; not sufficient as a security policy.** It already covers transforms, explicit profiles, named materials, skeleton references and custom actions. No recipe-v2 is justified now. Bound and validate params before allocation, then measure real benchmark failures.
2. **Not all exposed Python helpers are product features.** `core/rigging.py:ik_two_bone` and `core/animation.py:ActionBlender` exist, despite matrix exclusions. There is no integrated recipe/desktop IK/constraint workflow. Leave integrated IK/blending out of V1.
3. **Material graph documentation is inconsistent.** `MaterialRecipe.graph`, JSON schema, executor material assignment and `_bake_atlases` accept/evaluate graphs, while the matrix says recipe graphs are unavailable. Verify supported chains and correct documentation; do not implement duplicate graph machinery.
4. **Generated primitives differ from GUI profile construction.** Executor `_build_objects` writes returned nets into Patch but does not retain builder splines/generator provenance or explicitly copy returned degrees; GUI Lathe/Extrude commands preserve generator/degree data. Effective degree clamping exists, so this is a source-reasoned parity/editability risk, not a reproduced corruption claim. Verify a recipe lathe/extrude can be edited through net controls; profile-preserving improvement is IMPORTANT unless benchmark/manual-edit gates expose a blocker.
5. **Rig placement is constrained.** The external-agent guide explicitly warns against nonidentity transforms on shared-rig geometry. A rig/action existing is insufficient; test actual intended parts at multiple times. Character capability must stay modest.
6. **Schemas are stricter at some levels than others.** Primitive/material/export params remain open dictionaries; unsupported patterns can pass validate-only and fail during baking. Trial 2 repaired `scales` to `checker`. Typed preflight is warranted; another general validator/executor is not.
7. **Success is not visual adequacy.** A curve-only or rig-only project can be structurally valid. Mandatory surface/nonblank/brief checks must precede promotion to a completed generation.
8. **No general generation provenance field exists.** Action metadata is not project provenance. Format 2 is explicitly encoded; choose optional namespaced data, not a loosely attached attribute or unrelated Action metadata.
9. **Platforms are not qualified.** Current docs record a Mint 22.3 offscreen/software preview. Historical MX acceptance applies to artifact `b96c922`. Windows workflow preparation is not an executed workflow or accepted executable; no committed Windows lock exists. Current-source native desktop/GPU acceptance remains open.
10. **Documentation drift already exists.** The external-agent guide still says the current archive awaits Phase 3, while the roadmap records Phase 3 complete; RELEASE_NOTES has historical MX verification language. Reconcile identities and scope, never combine evidence from different builds.

### Planning verification (not release qualification)

Initial ambient `python -m pytest am3d/ -q` failed collection because PySide6 is absent (four collection errors). A narrower ambient run gave 418 passed / 16 failed, all reported failures importing PySide6-dependent UI commands. This is an environment mismatch, not a basis for engine fixes. Existing `build/linux/venv/bin/python` is Python 3.13.5 with PySide6 6.11.2 and NumPy 2.4.6; use its results recorded below. No dependencies were upgraded or installed.

Source CLI execution of `docs/recipes/examples/knight_full.json` into `/tmp/am3d-v1-planning-knight` returned exit 0, `ok:true`, native/OBJ/MTL/GLB/sheet artifacts and no warnings/errors. Full suite and offscreen smoke results are appended in section 14. No new frozen build, Windows run, desktop interaction, live provider call or physical GPU acceptance was performed. Prior trial/review reports were read as historical evidence, including corrected clockwork-beetle trial 2 and the final Mint candidate review.

## 3. V1 product contract and scope classes

**Audience:** indie/retro game developers, hobbyists and asset prototypers seeking an editable stylised asset without first learning a large DCC. These are intended users, not researched market segments.

**Promise:** describe a supported asset and have an LLM use 3D MASTER's structured spline-patch capabilities to construct and check it, returning an editable native project, a meaningful preview and requested supported exports. Inspect it, edit it manually, or generate a recoverable refinement. Keep compact early-2000s desktop character and retro output style.

**Supported:** assembled props, household/fantasy/industrial objects, furniture, retro technology, simple architecture/street furniture and simplified vehicle exteriors. Basic stylised multipart characters and short FK animation are bounded capability tiers, not professional character-production parity. “Worn metal”, glass and damage may be stylised colour/pattern/geometry approximations; report compromises. Do not promise physically accurate transparent glass, arbitrary topology, recognisable likenesses or watertight fabrication meshes.

| Classification | Features |
| --- | --- |
| V1 BLOCKER | In-app brief-to-recipe workflow; one working provider; OS credential boundary; bounded repair/cancel/timeouts; isolated execution/resource/path policy; native project/whole-scene preview/provenance; guarded editor adoption; recoverable refinement; deterministic checking; frozen benchmark; Windows 11 and Mint qualification; truthful documentation |
| V1 IMPORTANT | Token usage and available cost estimates; side-by-side thumbnails; descriptive component naming; profile/generator preservation if useful; export affordances; accessibility/DPI usability beyond minimum gate |
| V1.x | Additional provider adapters and local endpoints; optional vision critique; semantic recipe patches; safe selected-part operations; arrays/components only if measured; richer character guidance; more platform qualification including MX |
| POST-V1 | Blender/DCC parity, sculpting, CSG/boolean/subdivision systems, FBX/third-party import, animated GLB, weight painting, integrated advanced IK/constraints/blending, node-editor UI, ray tracing/render research, video encoding, marketplace, collaboration/accounts/cloud backend, macOS |

Existing limited material graph and IK helpers remain available as currently implemented; these exclusions concern expanding product workflows. Existing manual workflows and external CLI must keep working offline without credentials.

## 4. Execution architecture and interfaces

```
Qt brief form -> GenerationController -> ProviderAdapter (network only)
                                  -> normalized AssetBrief + exact recipe-v1
                                  -> recipe validation + AI policy preflight
                                  -> isolated worker / RecipeExecutor / Session
                                  -> deterministic checks + whole-scene preview
                                  -> immutable run directory + run record
                                  -> guarded DocumentController open
```

Keep **recipe-v1 canonical for executable instructions**. An `AssetBrief`/`GenerationRequest` envelope describes intent, expected components, constraints and policy, but is not a second geometry language. An orchestrator coordinates bounded stages and translates structured reports; it cannot run model-supplied Python, shell, imports, callbacks, URL fetches or arbitrary application verbs. Existing Python scripting supplements recipes only through trusted host code calling named APIs. No general agent-command layer or MCP server is necessary for V1.

Suggested small new package `am3d/ai/`: `contracts.py`, `providers.py`, `credentials.py`, `policy.py`, `records.py`, `orchestrator.py`, `worker.py`, `checks.py`, `prompts.py`. Split provider transport into `providers/` only if it grows. Keep module roles explicit:

- `AssetBrief`: schema version, brief text, style/use, dimensions/units, material intentions, rig/action requests, supported exports, named required components, declared approximations. Required checks derive from user request and frozen benchmark fixtures, never solely from model assertions.
- `ProviderAdapter.generate(request, deadline, cancellation) -> ProviderResponse`: constrained JSON text/data, provider/model/request ID, usage when available, finish/refusal state; no Session access or credential persistence.
- `GenerationEvent`: run ID, sequence, stage, attempt, progress where measurable, message. Monotonic state transitions; late events from cancelled/older jobs cannot change UI or active document.
- `GenerationRecord`: terminal/in-progress states and content-addressed recipe/brief/artifact metadata. Version independently from recipe and native format.
- worker input: validated recipe, private output directory, approved resource map and policy limits. Worker output: ExecutionResult plus check report and preview manifest. No API key, prompt network access or active document.

Headless contracts/providers/orchestrator/checks must not import Qt. Qt controller owns signals and lifecycle only. Provider IO uses cancellable background IO; geometry is a separately terminable process because a Qt thread cannot safely stop a blocked NumPy/rasterizer call. Prefer a hidden fixed internal worker mode in the existing GUI executable/source entry point, avoiding dependence on an installed Python interpreter. Preserve standalone recipe CLI for external users. Internal worker protocol is separate from public CLI JSON, uses bounded messages and fixed trusted entry points, and needs frozen Windows spawning tests. Worker rendering can reuse software `render_job`/scene path; never depend on a desktop GL context in a child process.

## 5. Provider, secrets, privacy and operational policy

Smallest scope: one **OpenAI-compatible JSON HTTP adapter**, with one explicitly tested HTTPS endpoint/model configuration chosen in Phase 1. Transport compatibility is not a support claim for OpenRouter/every local server. Use the same interface with deterministic fake transport in tests and retain external-agent/CLI mode. No vendor SDK in geometry, no auto model switching, no model list fetched without user action.

At implementation, verify the selected endpoint's current documented request/response/structured-output contract, supported model and refusal behavior. Choose and lock a minimal cancellable HTTP dependency if required; avoid adopting multiple SDKs. This planning document does not pin a speculative model name or tariff. Generic strict JSON parsing remains mandatory even where provider structured output is available.

Provider settings: endpoint, model, request timeout, supported output budget, credential alias and privacy text. Nonsecret preferences in QSettings; actual key in Windows Credential Manager and Linux Secret Service through a narrowly qualified credential abstraction (e.g. pinned keyring backend). Allowlist these secure backends; reject plaintext fallback. If Linux has no unlocked Secret Service, offer a visibly session-only key with no disk persistence or an actionable setup message. GUI retains key only for provider IO and never sends it to worker. Test rotation/delete/restart/backend locked/unavailable.

Send user brief, normalized intent, capability/schema context, prior recipe for refinement and bounded sanitized errors. Do not send unrelated files, full native project, images or machine paths. Before first cloud request, show destination/model and what will be sent; explicit Generate authorizes it. No hidden telemetry. Local history contains user briefs and may be sensitive: disclose storage location and provide deletion. Diagnostics export is allowlisted and excludes raw prompts/provider payloads by default. Never log Authorization, key values, provider response bodies unchecked, credential URLs/query strings, or secret-bearing exceptions. Crash-report and GUI diagnostics paths must use the same redaction boundary. Test a sentinel secret across all artifacts/logs/errors.

Default bounds (freeze after baseline measurement; raising any bound requires evidence/review):

- One initial brief interpretation call and one initial recipe call; **2 validation repairs**, **1 execution/result-check repair** shared across runtime and deterministic-result failures. At most 5 recipe candidates and 6 semantic provider calls. A candidate repair reruns all validation/checks.
- Each semantic provider call may retry once for transient network/429/5xx with capped backoff and Retry-After bounded by remaining deadline. No retry for authentication, refusal, unsupported model or deterministic policy denial; at most 12 HTTP attempts. All retries consume the same run deadline.
- 90 seconds per HTTP attempt; 180 seconds per worker execution/check attempt; 600 seconds total wall-clock run. UI shows elapsed time and actual stage, not fabricated percentages.
- Cancellation interrupts network request or closes its transport, then terminates worker after up to 2 seconds cooperative grace. No completion/adoption after cancellation; target UI cancellation acknowledgement within 3 seconds. Test Windows process-tree cleanup. User-triggered Retry creates a new run ID, never resets counters invisibly.
- Default response cap 1 MiB and recipe cap 512 KiB; reject truncated, duplicate-key, nonfinite JSON. Provider token limit is configuration/model-dependent and recorded. Record unavailable token/cost fields as null, never zero. Cost estimate only from identified dated rate configuration; V1 can display “unavailable”.

User states distinguish credentials/network/refusal/schema/policy/runtime/check/publication failures. Retain useful sanitized error evidence and recipe candidates. Unsupported requests receive a concrete limitation/approximation choice before execution; do not claim completion by silently deleting requirements.

## 6. Security and resource preflight

Extend existing recipe validation with typed primitive/material/action/export params and AI-policy checks; reuse `core/paths.py`, serializer limits and executor output_root. Do not weaken legacy trusted CLI behavior merely to fit cloud generation. AI mode always supplies a fresh private output root and constructs approved exports/paths itself. Model may select approved formats, never arbitrary filesystem destinations. Convert object/component names to opaque safe filenames; preserve readable names inside recipe/native project.

Starting AI limits: 128 objects, 1024 patches, 64 bones per skeleton/256 total copied bones, 16 actions, 256 channels, 4096 keys, 4096 authored profile/CP points, 128 primitive sections/rings/grid subdivisions, 32 graph nodes per material, 32 materials, tessellation <=32×32 per patch and <=250,000 evaluated triangles. Track estimated control nets/texture memory before allocation as well as actual counts. Preview 512×512; export sheets <=16 cells at <=256 pixels each, total image <=16 million pixels, atlases <=256 cell size with <=64 million pixels total. Limit output bytes to 256 MiB and worker memory target to 1 GiB, with process termination for excess where host monitoring supports it. No unbounded work when OS memory enforcement is unavailable: estimator/count limits and deadline remain mandatory on both platforms.

AI-generated image/file texture paths disabled in V1; use flat/procedural appearance. Later user-approved inputs must be copied into a run-specific resource directory, decoded with image-size limits and resolved by IDs; never arbitrary base_dir reads. Audit graph/params nested paths and all derived writer outputs (OBJ/MTL/texture/sheet/atlas names), symlinks/junctions, path collisions, reserved Windows names, Unicode and cross-platform separators. Check final extension changes and generated filenames, not just original export.path. Keep run roots private; recheck confinement at publication. Do not claim current derived-name behavior is a reproduced escape without a test.

Schema checking is insufficient against giant allocations; reject over-budget inputs before `_build_objects`, atlas bake or render. Policy denials such as absolute paths, resource access, oversized work and code-like unsupported verbs terminate with explanation rather than repeatedly asking the model to bypass policy. Safe malformed values may be repaired within budget. Independent security tests must prove no file outside temporary test root changes.

## 7. Provenance, reproducibility and publication

Use per-user app data `generations/<run-id>/` with a private attempt subtree, relative artifact paths, `record.json`, `brief.json`, `recipe.json`, `preview.png`, `project.am3d`, exports and bounded sanitized failed candidates. IDs are host-generated UUIDs; retain `parent_generation_id` for refinements. State record writes are atomic. Terminal success occurs only after native reopen, all mandatory checks and manifest verification; promote a completed directory on the same filesystem. Failed/cancelled runs never appear as successful or replace prior generations. Executor partial publication inside a private attempt directory is recorded, not offered as completion. If moving across volumes, copy to a private destination staging directory, verify, then rename; do not pretend rename is atomic across filesystems.

Record generation ID, UTC timestamp, parent ID, user/normalized briefs, provider/endpoint label/model, recipe version, exact original/accepted recipes, canonical SHA-256, application version, implementation/build identity, capability/prompt-template/policy versions, random seeds, request IDs (nonsecret), attempts/errors/warnings, check results, duration, usage/cost availability, and artifact sizes/hashes. No separate invented engine semver: engine identity is application version plus source/build identity until genuinely independently versioned. Record renderer route/tessellation/preview camera and export pose/time. Same recipe/environment/seeds should recreate equivalent geometry; new model calls are not reproducible promises. Timestamp/run-ID fields are excluded from deterministic comparisons.

Native project: optional bounded `generation` envelope with record version, run/parent IDs, accepted brief and exact recipe/hash, app/build/capability identity, warnings and resource-relative artifact references. Prefer additive optional format-2 field only after proving existing loader ignores it and new loader accepts old files; otherwise introduce format 3 with explicit old-reader behavior. New reader must roundtrip legacy format 1/2 fixtures. Never store credentials, endpoint credential query strings, raw HTTP responses or attempt transcripts there. Full attempt evidence stays sidecar; application history is a rebuildable index of records, not another authority. Plain `.am3d` copying preserves brief/recipe, while missing sidecar gives “run history unavailable” and manual editor still works. Save As/manual editing preserves provenance but marks project divergence; provenance never implies the recipe exactly describes later manual edits.

Default retention: never automatically delete successful native projects/refinement parents in V1. Failed-attempt evidence may be explicitly deleted through history; show disk use and allow deleting selected runs with parent-reference warnings. Recovery on startup marks interrupted runs Interrupted, retains prior successes, and allows an explicit new retry.

## 8. Desktop user journey and refinement

Use Home's current native actions/recent/recovery structure: New Project, Open Project, **Create with AI**. AI is also reachable through a menu/workspace from an existing document. Provider not configured leads to compact settings; manual use is always available. Preserve square beveled controls, steel/graphite palette, amber selection/focus, Tahoma/fallback and resizable areas from DESIGN.md. No generic chat feed, SaaS cards, glass, decorative animations or web shell.

AI work area: brief multiline field; optional collapsed style, use, meter-scale dimensions, appearance, rig/action requirements and supported export checkboxes; compact task list and elapsed time; central preview; history list; collapsible read-only recipe/report view. Generate and Cancel are clear keyboard-accessible buttons. Limit initial visible decisions to brief and Generate; advanced fields disclose support limitations.

Stages: Understanding brief → Planning/Building recipe → Validating → Correcting (only if needed) → Building geometry → Applying appearance → Rigging/animation (only if requested) → Rendering preview → Checking artifacts → Complete. Executor hooks should emit real stage events, or display “Executing recipe” until hooks exist. No fake progress or stage claims. Empty, busy, auth/refusal, quota/network, invalid, timed-out, cancelled, interrupted and failed-check states need explicit recoverable messages.

Completion shows whole-scene preview, object/material/rig/action summary, approximations, requested files, source recipe/report and **Open in Editor** / **Refine**. Generating does not replace current document. Open in Editor first creates a distinct writable working copy (host-named, outside the immutable snapshot subtree), then calls the existing dirty abandonment gate and `DocumentController.do_open` on that copy, followed by existing UI reset/camera fit/refresh. Never point the active document save path at the immutable history snapshot. Copy failure leaves the original document and snapshot intact; cancelled adoption can discard only the unused working copy. Save writes the working copy; Save As is also available. If user cancels opening, retain candidate/history and current document. Generation replacement is document navigation, not a giant QUndoCommand; subsequent CP/material/transform/key edits reuse normal undo/redo. Autosave identity/recovery and late-worker safety must be tested.

Refinement V1: choose a completed parent recipe, provide a bounded change request, and regenerate into a new immutable child. Give model accepted parent brief/recipe and request; require names and unrelated components be retained where possible. Full replacement recipe is validated/executed as usual; show changed component/material/parameter summary derived deterministically from recipes, plus parent/child thumbnails. Exact structural changes (roof height, arm extent, green material, wheel radius) have targeted fixtures, not just a prose claim. Reopening/restoring parent creates a fresh writable copy from its saved immutable native file and uses the document guard; ordinary editor Save cannot overwrite a parent snapshot. Failed refinement cannot change parent bytes/hash.

Manual divergence is explicit: refinement operates on the selected generation's stored recipe, **not current manually edited geometry**. Before refinement from a modified project, explain this and offer Save manual copy / Refine original generation / Cancel. Do not silently overwrite edits or promise automatic merging. Persist recipe hash plus generation project hash to detect divergence; handle external Save As and missing sidecars. Refinement of arbitrary nongenerated projects is V1.x. Branch tree UI, semantic selection mapping and operation-level patching are deferred.

Minimum UX gate: usable at 1280×820 and at 100/150/200% display scaling within available logical viewport, scrolling rather than clipped controls; keyboard path Home→brief→Generate→Cancel/Result→Editor; accessible labels/focus/status, no secret echoed in error; user understands static export limitations and manual-divergence rule. Pixel polish follows functional gates.

## 9. Deterministic result checks

`am3d/ai/checks.py` coordinates existing scene, serializer, render and independent export readers; it does not recreate their geometry or writers. Each check returns stable code/path/severity/details. Required checks:

1. Reload generated `.am3d` in fresh Session; verify objects/materials/rig/actions/assignments match accepted recipe intentions; save/reopen again and compare evaluated geometry/material/action state.
2. Require visible surface triangles, finite positions/normals, valid indices and finite nonzero bounds. Curves/rig objects are allowed alongside geometry. Degenerate triangles may exist at lathe poles; measure/report them, do not blanket-reject existing sphere topology.
3. Check brief dimensions within a frozen tolerance (default 20% where specified), named components and material assignments. Benchmark expected attributes are independently authored; model cannot certify itself by inventing easy checks.
4. Auto-fit whole-scene camera with margin, render software preview; validate decoded PNG and foreground occupancy >=0.5%, <=95%, finite pixels and visible colour/alpha contrast. Use renderer foreground mask/alpha where available; fixed-background image difference as tested fallback. A silhouette-only image is not material correctness. Threshold fixtures include thin poles, dark props and empty scenes. No vision-model dependency.
5. For requested animation, require bound affected parts, assigned requested action and finite deformation at 0, 25%, 50%, 75% duration (not just endpoints of a loop). Require intended-part vertex displacement >max(1e-6, 0.1% scene diagonal), report per part. Render sample frames with one fixed camera; avoid camera motion masquerading as animation. Human review confirms useful visible motion.
6. Independently parse OBJ/MTL/textures through `export/validate.py`, GLB headers/accessors/primitives/material/image references, sheets through Pillow; require faces, valid indices, requested material associations, file existence/size/hash and bounded dimensions. Use one external reader/viewer during final qualification as additional evidence.
7. Verify every manifest and sidecar/output path resolves within run root, no missing required export, no key sentinel/credential fields. Failure is not Complete. Disk/publication/auth errors receive direct user recovery, not geometry repair.

Checks prove integrity and selected intent, not artistic quality, topology suitability or perfect prompt fidelity. Warnings and unsupported compromises remain visible. Optional vision critique is V1.x.

## 10. Frozen prompt benchmark and recipe gap policy

Introduce `benchmarks/v1/prompts.json` with immutable IDs/full texts, user-level constraints, required components/materials/relative geometry, dimensions where meaningful, exports and animation checks. `benchmarks/v1/rubric.md`; trusted runner e.g. `scripts/run_ai_benchmark.py`. No hardcoded asset templates to make the advertised prompt test pass. Freeze fixtures/rubric/provider/model/prompt context before release measurement. Live calls are opt-in/cost-bounded; recorded/fake tests run offline in CI. Keep discovery prompts separate from held-out release briefs; publish prompt-template or fixture changes and rerun all release items.

Thirty release briefs (write these as full frozen briefs in Phase 2; wording below establishes required scope):

| ID | Brief | Required independently checked attributes |
| --- | --- | --- |
| 01 | Chunky blue enamel mug with side handle for an isometric RPG | body + handle, blue body; OBJ/GLB |
| 02 | Red low-poly-looking desk lamp on a round base | base, stem, head; colour |
| 03 | Brown wooden crate with visible reinforcement slats | box + at least four distinct slats |
| 04 | Green metal watering can with spout and handle | three parts; spout beyond body |
| 05 | Round red stool with three wooden legs | seat + three supports; relative positions |
| 06 | Compact wooden writing desk with four legs and drawer | top + four legs + drawer/front |
| 07 | Early-2000s grey office chair on a simplified wheeled base | seat/back/stem/base/wheels |
| 08 | Medieval blacksmith anvil, worn dark iron on wood block | block/body/horn; profile approximation declared |
| 09 | Wooden treasure chest with brass straps | base/lid/straps, separate materials |
| 10 | Stylised iron lantern with yellow insert | cage/base/top/insert, distinct colours |
| 11 | Fantasy sword with leather handle and simple crossguard | blade/guard/grip, long axis |
| 12 | Industrial barrel with two dark hoops | cylinder + two hoops |
| 13 | Chunky factory pipe with right-angle elbow and flanges | two directions + elbow/flanges; no CSG claim |
| 14 | Yellow road barrier with two feet and black markings | beam + two feet, colours |
| 15 | A 2001 beige CRT monitor with dark screen and stand | case/screen/base; material difference |
| 16 | Retro grey game console with two cartridge slots | shell + two slot approximations; report recess limitation |
| 17 | Small red British telephone kiosk | frame/roof/panels; red frame |
| 18 | Simple cottage with flatter pitched roof, chimney and front door | walls/roof/chimney/door; relative bounds |
| 19 | Stone arch gateway made from separate chunky blocks | two posts/top arrangement/open passage |
| 20 | Early-2000s British bus shelter, green frame, glass-like panels, bench, exaggerated PC-game proportions | frame/roof/panels/bench; disclose stylised glass |
| 21 | Grey park bench with wooden slats | supports + seat/back slats |
| 22 | Green litter bin with dark opening and small feet | body/opening approximation/supports |
| 23 | Simplified red compact car with four black wheels | body/cabin/four wheels, static exterior |
| 24 | Chunky blue delivery van with larger rear cargo body | cabin/cargo/four wheels; relative size |
| 25 | Stylised unrigged toy robot, red torso, long arms | torso/head/paired arms/legs |
| 26 | Simple rounded green creature with a basic rig | renderable body/limbs, bones/weights |
| 27 | Chunky humanoid robot waving its right arm | rig/custom action; right-arm deformation; sheet/native |
| 28 | Copper clockwork beetle with moving legs walking in place | shell/multiple legs, shared-rig binding, motion |
| 29 | Simple blue mascot doing a small jump | torso/legs, rig/jump, geometry motion |
| 30 | Simple rigged guard with an idle breathing movement | torso/limbs, idle action, visible deformation |

Challenge/discovery set (not silently added/removed from denominator): spiral staircase with 20 steps, bicycle with thin spokes, worn shelter requiring truly transparent glass, face with expressive lip motion, rigged character with translated limbs, 5000 repeated bolts, negative scale mirrored textured chair, animated GLB request. Expect some explicit refusals/approximations/policy rejections; record why. These expose composition/resource/rig/export limits without committing to engine expansion.

Metrics per prompt: raw schema pass, semantic/preflight pass, direct executable candidate, repair success with counts, checked candidate, nonblank preview, reopen/save/reopen, structural/material attributes, animation deformation, export parse, security limits, duration/usage, independent human score. Failures stay in denominator. Infrastructure/provider failures are reported separately but do not disappear from end-to-end success. Pin reported model version where available; disclose provider drift.

Release target: >=27/30 checked candidates within bounds in **two complete runs** with the declared configuration; >=80% within each static versus rig/animation tier (25 static, 5 rig/animation; require >=20/25 and >=4/5). At least 24/30 in each run meet human acceptable-candidate rubric: recognisable silhouette, essential components, useful proportions/appearance and editability, each scored 0–2 with >=6/8 and no essential component absent. Two human reviewers independently score stored previews/native inspection samples, then document disagreements; subjective score is separate from deterministic pass. These are proposed gates, not claims about today's capability. If baseline fails badly, revise product tier/rubric transparently before freeze, or fix evidence-backed gaps; never quietly lower thresholds or omit hard prompts after freeze.

Recipe gap decisions:

- Symmetry/mirroring: explicit paired objects + matrices already express placement/reflection; verify negative-determinant normals/export tests before claiming reliable mirroring. No new verb initially.
- Repetition/arrays: explicit repeated objects work within policy; only add a bounded compile-to-v1 helper if token/error metrics on slats/steps show repeated failure. Definitions/naming/expansion limits and deterministic tests required.
- Group/hierarchy: neither ObjectRecipe nor Object3D has general object parenting; bones do. Naming and absolute placement suffice for V1 assembled props. Do not introduce scene hierarchy just for prompt convenience.
- Relative placement/components: normalized planning may describe relationships, recipe remains concrete coordinates. New high-level reusable representation would duplicate semantics; defer unless measured generation reliability justifies a small trusted compiler.
- Materials: named targets, patterns and graphs already exist. Tighten parameter contracts and references. No new material engine.
- Manual direct patch nets: engine/GUI support them; recipe offers primitives/profiles/curves, no direct PatchRecipe. If benchmark exposes shapes impossible through existing profiles, evaluate a bounded net field as an IMPORTANT extension with finite/degree/size constraints, not arbitrary operations.

Every extension requires failed frozen/discovery use case, minimal reproduction, explanation why existing composition/profile/matrix approach cannot meet it, source impact, compatibility contract, tests, schema/guide/examples update and full affected benchmark rerun. Preserve existing v1 samples. Optional additive fields can remain v1 only if semantics are backward compatible and new emitters negotiate capability; older readers reject unknown fields today, so do not claim forward compatibility. New incompatible semantics require recipe-v2 reader/compiler plus explicit migration fixtures; v1 remains supported. No automatic migration rewriting stored exact recipes.

## 11. Small implementation phases

Every phase below is planning, not work performed. Each produces one reviewable behavior; split further if diff crosses unrelated responsibilities. Tests named under new modules are proposed tests, not existing files. All phases preserve offline/editor/external CLI regression tests. Evidence lives in `docs/evidence/v1/phase-N/` and includes exact commit, dirty diff/input digest if any, commands, complete results, fixtures/run IDs, reviewer dispositions. No secrets/raw personal prompts in committed evidence.

### Phase 0 — Approve contract and reconcile document authority

- Objective: one agreed V1 product contract and truthful source baseline.
- Impact/work: this plan; after approval update README, PRODUCT, PROGRESS, roadmap headers and acceptance links per section 12; record initial full-suite/smoke/source identity and platform ledger.
- Non-goals: implement AI, retrospectively certify historical builds.
- Tests: links/document consistency; repeat baseline only if source changed.
- Acceptance/evidence: independent plan review accepted; capability claims trace to source; snapshot commands/results stored.
- Review gate: architecture/product owner verifies scope and legacy reuse; no coding until accepted.
- Dependencies: none; this planning pass supplies proposed baseline.

### Phase 1 — Define AI contracts and qualify one provider/credential transport

- Objective: bounded structured request works with fake and one real provider safely.
- Impact/work: new `ai/contracts.py`, `providers.py`, `credentials.py`, minimal HTTP/keyring dependencies and deliberate lock changes; provider settings data only. Freeze one supported endpoint/model and transport contract; redact errors and declare privacy/budgets.
- Non-goals: geometry, multiple vendors, new settings screen, tariffs service.
- Tests: proposed `ai/test_providers.py`, `test_credentials.py`: malformed/truncated/refusal/429/auth/timeout/cancel, secure backend unavailable, no plaintext persistence, mock secrets absent in exceptions/logs.
- Acceptance/evidence: headless fake roundtrip plus opt-in sanitized real JSON request; API key remains only in credential backend/provider process.
- Review gate: independent boundary/privacy reviewer checks dependencies, retry ceiling and credential backend selection.
- Dependencies: 0.

### Phase 2 — Interpret briefs and produce recipe-v1 candidates

- Objective: brief produces normalized intent and canonical recipe without execution.
- Impact/work: `ai/prompts.py`, contracts, schema/guide context loading; `benchmarks/v1/` full 30 briefs/rubric + discovery set. Capability context derived from tested engine vocabulary; generate JSON rather than code; host supplies export destinations. Freeze request versions.
- Non-goals: repairs, geometry changes, semantic hierarchy.
- Tests: proposed `ai/test_prompts.py`: minimal/complex/rig briefs, unsupported exports, dimension convention, valid JSON, refusal, injected system-command text, requirement preservation. Existing schema conformance tests retained.
- Acceptance/evidence: fake transcript and small cost-bounded live baseline (at least prop/shelter/rig), candidate errors retained; initial failures guide later work.
- Review gate: recipe/source reviewer verifies grounding and benchmark assertions are independent of model output.
- Dependencies: 1.

### Phase 3 — Enforce policy and isolated deterministic worker

- Objective: untrusted recipe executes within confinement and deadline without touching editor.
- Impact/work: `ai/policy.py`, `worker.py`, fixed internal entry in `ui/app.py` or trusted launcher; typed preflight in existing recipe validator; narrowly audited derived paths/writer names; event hooks if needed in executor. Keep Executor API/session transaction.
- Non-goals: GUI prompt or repair autonomy; general sandbox/interpreter.
- Tests: proposed `ai/test_policy.py`, `test_worker.py`: huge nets/textures/graphs/frames, NaN, texture reads, derived path traversal/symlinks/junctions/collisions, memory estimate, child death/cancel, untouched active Session; existing recipe path and transactional tests.
- Acceptance/evidence: malicious fixtures fail before allocation; valid sample builds privately; terminated worker leaves no successful publication or stray child.
- Review gate: independent security/resource and frozen-spawn design review. A thread-only cancel design fails gate.
- Dependencies: 0 contracts; can develop after 1, uses candidates from 2 for integration.

### Phase 4 — Check artifacts, preview and publish provenance

- Objective: completed candidate has verified native file, whole-scene preview and recoverable run record.
- Impact/work: `ai/checks.py`, `records.py`, bounded optional generation field in Project/serializer; use scene/render_job/export validators; staged run promotion/history index and interrupted-run handling.
- Non-goals: visual LLM critique, chat UI, full history browser.
- Tests: proposed `ai/test_checks.py`, `test_records.py`; core serializer compatibility/limits/roundtrip; empty curves/rig-only, finite bounds, dark/thin preview, moving bone with static skin, loop endpoints, invalid/missing exports, disk-full/copy failure, secret sentinel, relocated native file/missing sidecar.
- Acceptance/evidence: sample native save/reopen and independently parsed exports; deliberately bad asset never reaches Complete; interrupted run preserves earlier success.
- Review gate: data-integrity/serialization and result-check reviewers; review format-version decision before merge.
- Dependencies: 3.

### Phase 5 — Orchestrate bounded repair and cancellation

- Objective: headless prompt→checked project recovers from actionable model mistakes.
- Impact/work: `ai/orchestrator.py`, event/state contracts, errors to provider repair input; share run deadline/counters across schema/runtime/check repair and transport retry. No prompts with raw local paths.
- Non-goals: infinite retries, automatic model changes, expensive visual critique.
- Tests: proposed `ai/test_orchestrator.py`: exact call/attempt ceilings; initial pass, two invalid repairs, runtime/check repair, refusal/auth/policy/publication failure, cancellation at every stage and stale events, failure record consistency.
- Acceptance/evidence: fresh fake failure→repair→checked output; live small set through pipeline; exhausted run explains failure and retains evidence without changing previous run.
- Review gate: independent state-machine/repair review checks counters mathematically, not just happy path.
- Dependencies: 1–4.

### Phase 6 — Create with AI and guarded editor handoff

- Objective: launch→brief→candidate→manual editing without terminal/JSON.
- Impact/work: `ui/home.py`, `app.py`, `workspaces.py`, `settings.py`, new `ui/ai_workspace.py`/`ai_controller.py`; controller-owned worker/network lifecycle; reuse document open/reset/dirty gate.
- Non-goals: history comparison/refinement or pixel polish.
- Tests: proposed `ui/test_ai_workspace.py` with fake provider: config/generate/stages/cancel/retry/errors/closing app; existing home/document/smoke tests; manually edit generated CP/transform/material, undo/redo, save/reopen, cancel dirty-document replacement.
- Acceptance/evidence: desktop workflow works with software renderer and remains responsive; current dirty document unaffected until guarded adoption; first configured real provider run recorded.
- Review gate: independent Qt lifecycle and user-journey reviewer verifies thread affinity, stale signals and offline startup.
- Dependencies: 5.

### Phase 7 — History and versioned natural-language refinement

- Objective: refine stored generation and recover parent without losing manual work.
- Impact/work: records/orchestrator parent handling, AI workspace history/refine/change summary; provenance divergence checks; document_controller integration only through existing guards.
- Non-goals: merge manual CP edits, arbitrary existing-project refinement, semantic patch engine, branch graph UI.
- Tests: proposed `ai/test_refinement.py`, `ui/test_ai_history.py`: flatter roof, longer arms, dark green body, larger wheels; parent byte/hash unchanged, failed/cancelled child, restart/missing sidecar, manual divergence/Save As/dirty gate, restore parent then undo manual edits.
- Acceptance/evidence: at least four targeted refinement scenarios pass measurable checks; a user can inspect child and return to parent after restart.
- Review gate: independent preservation/refinement reviewer checks “recipe-based” explanation and recovery path.
- Dependencies: 6.

### Phase 8 — Run benchmark and resolve measured capability gaps

- Objective: known supported breadth and quantified failure limits.
- Impact/work: trusted benchmark runner, fixtures/rubric/evidence, minimal recipe/guide/executor/engine changes only justified by section 10 process.
- Non-goals: speculative arrays/hierarchy/new renderer, changing prompts to hide failures.
- Tests: full source suite; every justified extension has focused schema/executor/compatibility/manual-edit tests; two frozen 30-prompt runs plus separate challenge ledger and four refinement fixtures.
- Acceptance/evidence: section 10 targets met or explicit scope decision returned for review before RC; human and deterministic outcomes reported separately with no dropped failures.
- Review gate: independent benchmark methodology/capability reviewer audits denominator, failed cases, held-out prompts, human rubric and each extension's necessity.
- Dependencies: 7; discovery baseline began in 2, so gaps are not first found at release.

### Phase 9 — Cohesive UX and documentation pass

- Objective: AI feels native to the retro workstation and limitations are understandable.
- Impact/work: AI work area/layout/settings and small theme adaptations; documents listed in section 12; keyboard/focus/scrolling, report copy, static export and privacy/refinement explanations.
- Non-goals: redesign engine/editor visual identity, feature expansion, decorative motion.
- Tests: existing UI suite + focused keyboard/compact pane/status tests; one batched native inspection at target sizes/scales and one correction verification; fake and real failure states.
- Acceptance/evidence: novice can complete brief/result/editor/refinement without JSON; no clipped core actions at required scales; screenshots reflect actual state and renderer route.
- Review gate: independent UX/product review; preserve DESIGN identity and manual workflows.
- Dependencies: 8, with functional accessibility incorporated already in 6.

### Phase 10 — Package and qualify Windows 11 / Mint 22.3

- Objective: clean supported hosts launch complete V1 without Python and securely generate assets.
- Impact/work: both build scripts/specs, locks, Windows workflow, frozen acceptance harnesses, platform docs; include schemas/templates/internal worker/HTTP CA and secure credential backend dependencies; keep CLI usable headlessly.
- Non-goals: macOS/MX/general Linux claim, mandatory installer/AppImage, cloud service.
- Tests: locked full source suite; frozen GUI/CLI + worker/provenance/provider/refine tests; relocation spaces/Unicode/read-only installation; no Python clean VM; native display 100/150/200%; real GPU plus forced software; credential service locked/unavailable; TLS/auth/network failures and cancellation; exported independent reader.
- Acceptance/evidence: qualification ladder below complete for exact archive/checksum/source/input digest on both targets; Windows lock captured/reviewed/committed after real successful build; never equate CI/offscreen with native desktop.
- Review gate: independent packaging/platform reviewer verifies actual executed evidence and no build-path/secrets leakage.
- Dependencies: 9; early Windows worker packaging spike in 3 can reduce late risk.

### Phase 11 — Release candidate acceptance and authoritative release docs

- Objective: one exact source/artifact candidate meets core promise without known blockers.
- Impact/work: version in pyproject/__init__, final release/platform/quick-start/status documents, evidence/review ledger; rebuild final artifacts after any code or bundled-doc change.
- Non-goals: backlog implementation, speculative reviewer suggestions.
- Tests: final gates in section 13; reuse exact valid evidence when source/payload unaffected, rerun affected and full RC suite if implementation changes.
- Acceptance/evidence: independent bounded reviewers accept exact RC identities; every blocker closed, residual limitations visible; signed-off release checklist.
- Review gate: independent architecture/data-security and product/platform reviews; publication is separately authorized.
- Dependencies: 0–10.

## 12. Document reconciliation and review policy

After plan approval (not during this planning-only pass), update these entry points together:

| Document/interface | Required reconciliation |
| --- | --- |
| README.md | Lead with in-app promise once shipped; retain external CLI section; remove final-V1 “no provider/prompt” assertion; source/artifact platform claims |
| PRODUCT.md | Human brief author becomes primary user; AI agent is execution mechanism; editable assets, refinement constraints and intended audience |
| DESIGN.md and associated surface briefs/config where present | AI workspace/history/settings fit existing workbench; do not rewrite visual system |
| PROGRESS.md | New authoritative plan link; separate foundation/preview completion from new phases |
| docs/IMPLEMENTATION_ROADMAP.md | Historical external-agent preview header and supersession link; preserve named phase evidence |
| docs/DESKTOP_RELEASE_PLAN.md and V2/V3 historical plans | Supersession note for scheduling; historical source/scope retained; no replay of old phases |
| docs/CAPABILITY_MATRIX.md | Add AI desktop column/rows when implemented; correct graph/helper versus reachable product distinctions; accurately separate recipe CPU sheets and GPU rendering |
| docs/MODELLING_SCOPE.md | Keep surface-only semantics; explain generated component/profile edit limits and export pose |
| docs/USER_GUIDE.md | Home/AI workspace/provider/keys/privacy/stages/result/history/refine/manual-divergence/cancel/recovery shortcuts |
| docs/QUICK_START.md + bundled Home/Help quick start | First generation without JSON; credential setup/session-only fallback; manual and CLI alternatives |
| docs/RELEASE_NOTES.md | New V1 entry with exact qualification; preserve historical MX release section clearly labelled |
| docs/SUPPORTED_PLATFORMS.md, WINDOWS_ACCEPTANCE_PLAN.md | Select Windows 11 x86-64 and Mint 22.3 x86-64; ladder, secure backend/network/worker checks; MX later |
| docs/recipes/EXTERNAL_AGENT_GUIDE.md, schema/examples | CLI remains supported; document policy versus trusted CLI, typed params, graph support, rig placement, bounded host workflow, current package identity |
| am3d/__init__.py/core module docstrings, GUI About/Diagnostics, specs/bundled documents | Remove misleading product/external-only or “no polygon meshes anywhere” descriptions; no unsupported API/packaging claims; sanitized diagnostics |
| Historical trial/review files | Do not alter results; link with source/artifact scope and same-family/vendor limitation |

Later independent reviewers receive exact commit, base commit/diff/changed files, phase requirements/non-goals, named tests with output, source/input and artifact hashes, platform mode and acceptance evidence. They report **reproduced defect**, **source-reasoned risk**, **suggestion**, or **false positive**, with file/line or reproducible commands and severity/impact. Suggestions do not automatically become scope. Owner dispositions: fix confirmed blockers, investigate material risks with bounded reproductions, accept/defer suggestions, document false positives. No endless reviewer loop: one independent review round and one focused verification round per phase; unresolved blockers stop progression until evidence/design changes. Reopen gate if material changes invalidate reviewed evidence. Reviewers must be independent contexts and must not implement changes while reviewing. No requirement to use a particular model or vendor to pass; record reviewer identity/configuration/limitations.

## 13. V1 release gates and platform ladder

Release is blocked until all of these hold for one identified candidate:

- Fresh desktop launch, provider setup and natural-language generation requires no JSON/terminal; failures/cancel are comprehensible and bounded.
- Benchmark: two complete frozen runs >=27/30 deterministic checked success each, tier floors and >=24/30 human acceptable candidates per run. All successful runs meet every mandatory integrity/security check; failure rate cannot excuse corrupted files or key leakage.
- Native project: generated candidate opens, manual CP/net/transform/material edit works, exact undo/redo works for exercised commands, save/reopen preserves scene/rig/action/material/provenance. Check representative props/profile/rig cases in native UI, not only headless serialization.
- Refinement: four targeted requests measured; at least one live-provider child per supported refinement style family; previous project/history recoverable after restart; manual divergence surfaced and protected. No silent merge promise.
- Animation: requested bound geometry moves at appropriate sampled times and human observes useful motion; all successful animated benchmarks pass. Native action/weights persist; exports explicitly static where appropriate.
- Supported requested exports independently parse with expected geometry/materials, required sidecars present; all outputs confined and manifests true. Preview whole asset is meaningful and nonblank.
- Security: hostile params/paths/resources cannot execute code, exceed bounds unnoticed, write outside root, or leak sentinel credential through native/recipe/export/log/diagnostic/crash paths. Real keys never committed in evidence; test with sentinel and mocked backend.
- Stability: no known reproducible data loss, corruption, crash, path escape, stale-job adoption or unrecoverable generation blocker. Interrupted/failed runs preserve previous success and current manual document.
- Distribution: clean Windows 11 x86-64 and Linux Mint 22.3 x86-64 systems launch frozen GUI and CLI without Python; internal worker and provider credentials/network workflow also work. Software rendering remains usable; native GPU checks recorded separately.
- Docs and shipped payload agree with exact source/platform/capabilities; no old external-only V1 contract remains in active entry points.

Qualification ladder, recorded separately for each platform: **(1)** source tests in locked environment; **(2)** executed CI/build; **(3)** exact frozen CLI/GUI offscreen acceptance and relocation; **(4)** clean VM with no Python/developer tools, interactive desktop and secure credential/network workflow; **(5)** native physical desktop with scaling/keyboard/manual edit/recovery; **(6)** physical GPU rendering, diagnostics and software fallback. Mint preview historically reaches selected lower rungs; Windows currently has definitions, not evidence of rung 2. VM software rendering cannot satisfy physical GPU. Record OS build/desktop/driver/renderer, machine, dates and command artifacts. Avoid asserting every GPU/vendor is supported from one machine.

Windows 11 and Mint 22.3 are proposed minimum V1 release targets, based on user's desired direction and existing Mint evidence/build paths; Windows minimum is a new product selection, not a discovered support claim. MX 25.2 historical evidence stays visible but current requalification is V1.x unless product owner explicitly requires it. If a target host is unavailable, gate stays unpassed: ship a clearly named platform preview only through an explicit scope decision, never call it the agreed cross-platform V1.

Genuine outstanding blockers are the absent first-class prompt/provider/orchestrator/history/refinement/checking workflow, unqualified AI execution/credential policy, unmeasured frozen benchmark, and missing current native Windows/Mint qualification. Documentation reconciliation is part of those gates. No evidence currently justifies making advanced modelling, rendering research or DCC interchange blockers.

## 14. Planning command record and handoff

Inspection used Git identity/status/remotes, `rg --files`, file/function searches and targeted reads of all product/release/recipe/editor/engine paths cited above. No source modifications, dependency changes, rebuild, network provider call or Git push during planning. Generated test artifacts are under `/tmp/am3d-v1-planning-*`; the existing GUI smoke also exercised the normal per-user autosave path and cleared its own snapshot. Existing tests may exercise their isolated settings/test fixtures. No repository source was changed.

Verification completed on the inspected implementation:

| Command | Result |
| --- | --- |
| `git status --short`, `git branch --show-current`, `git rev-parse HEAD`, `git remote -v` | Clean starting tree; identities in section 1 |
| `QT_QPA_PLATFORM=offscreen python -m pytest am3d/ -q` | Exit 2; four missing-PySide6 collection errors in ambient interpreter |
| Ambient focused core/spline/recipe/renderer/export suite | Exit 1; 418 passed, 16 missing-PySide6 failures; environment diagnosis only |
| `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/ -q` | Exit 0; **738 passed, 4 Qt mouse-event deprecation warnings**, 59.28 seconds |
| `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m am3d.ui --smoke-test --out /tmp/am3d-v1-planning-smoke.json` | Exit 0; **14/14 steps**, `ok:true`; offscreen/source evidence only |
| `build/linux/venv/bin/python -m am3d.recipes --recipe docs/recipes/examples/knight_full.json --out /tmp/am3d-v1-planning-knight` | Exit 0; native, OBJ/MTL, GLB and sprite artifacts; no errors/warnings |
| Fresh Session native reopen and `export.validate.validate_obj/validate_glb` on the generated knight | Two objects, 450 triangles; both validators return empty error lists |

Visually inspected the committed layout preview `docs/previews/blender-early-2000s-layout.png` against current DESIGN/workspace/theme/source conventions: square controls, graphite viewport, steel panes, amber selection, outliner/properties and timeline. This is a committed visual reference, not a fresh native desktop acceptance screenshot. Impeccable context launcher returned permission denied; product/design context was read directly; no UI edited.

 A planning-only commit is authorized by this run if Git remains otherwise clean. Stage only this document. If unrelated user work appears, do not commit it and leave this plan uncommitted with explanation. Do not push without explicit user instruction.

Next action: push the planning-only commit when authorized, then independently review this plan against the exact commit before implementation. A remote reviewer cannot read an unpushed local commit; provide its file/diff or push first. Never claim it has been pushed when it has not.
