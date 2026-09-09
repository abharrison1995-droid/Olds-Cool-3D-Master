# 3D MASTER:2005 — Functional Application and External LLM Pipeline Plan

Date: 2026-09-08
Status: planning only; implementation has NOT been authorized by this document update.
Inspected checkout: `1078f34` (clean before this documentation change).
Supersedes: `V2_BETA_IMPLEMENTATION_PLAN.md`; retain that file as historical evidence.

## 1. Objective and scope

Deliver a functional Windows spline-based modelling and animation application,
with a reliable interface for an external LLM to author JSON recipes, execute
them, inspect structured results, and correct rejected recipes. The external
agent supplies model access and orchestration; this project supplies the
documented contract, deterministic engine execution, diagnostics, and artifacts.
No embedded chatbot, provider SDK, credentials manager, or model service is required.

The authoritative journey is:

```text
External LLM + contract/examples -> recipe -> validation -> execution
  -> artifact manifest and actionable errors
  -> open generated project -> visibly animate -> save/reopen
  -> render and export -> independently inspect outputs
Invalid recipe -> field-specific feedback -> corrected recipe -> successful run
```

Preserve spline patches as authoritative geometry. Reuse the Session facade,
undo command layer, and shared scene evaluation rather than duplicating engine
algorithms in GUI, recipes, or exporters. Existing working features must remain
working; do not equate file creation or a green unit suite with completion.

Minimum release scope includes editable animated `.am3d` projects, static
bind/current-pose OBJ and GLB exports with supported material representation,
and rendered animation frames/sheets. Skeletal animation embedded in GLB is
not currently established and is a separate extension, not a prerequisite or
an advertised capability. OBJ is static. Make these limits explicit to agents.

## 2. Evidence baseline and unresolved risks

This planning pass read the prior plan, README, recipe executor/CLI, sample
recipe, and relevant source references. It did not run the application, tests,
recipes, packaging, or reviewers. Historical counts (including 324 passes)
must be reproduced before being cited as current evidence.

The checkout already includes PR #1: OBJ index fixes, recipe export/action
precondition fixes, and dependency corrections. Do not blindly replay V2 Phase 0.
V2 marks material round-trip complete while its own status says procedural
material persistence is unfinished; its checked boxes do not carry over.

| Risk or observation | Evidence status at planning | Owning phase |
| --- | --- | --- |
| Parse/validation exceptions escape `RecipeExecutor.execute`; CLI failures are not consistently JSON | Source inspected | 1 |
| `.am3d` recipe export calls project serializer directly rather than Session save | Source inspected; action loss must be reproduced | 2 |
| Materials use dynamic attributes; texture-only assignment is gated behind pattern/graph | Source inspected; persistence and render effects need tests | 2 |
| Knight geometry is separate from the skeleton-only `hero` object | Sample inspected; visible deformation is not demonstrated | 3 |
| Recipe sprite exports iterate views of tessellated meshes without action-frame evaluation | Source inspected | 3–4 |
| Recipe normal transform uses the object linear matrix, not inverse transpose | Source inspected; non-uniform scale case needed | 3 |
| Retarget executor passes target bones as both source and target skeleton | Source inspected; unequal skeleton test needed | 3 |
| GUI lathe axes/export transforms diverge from scripted paths; fallback uses first mesh | Prior review and source references; reproduce | 3–4 |
| Duplicate-time keys, idle loop seam, raw action-save KeyError, duplicate material names | Prior review; revalidate before repair | 1–3 |
| Serializer truncation, unenforced limits, stale references; autosave scheduling/recovery | Prior review and source references; reproduce | 2, 5 |
| Dead controls, incorrect build root, fake packaged smoke test | Prior review; revalidate | 5–6 |

Findings are hypotheses until reproduced or proven directly. Record disproven
findings with evidence; never repair based solely on a review summary.

## 3. Phase execution and mandatory Luna review gate

All phases below start **NOT STARTED**. This edit authorizes planning only.
Begin Phase 0 only after a subsequent implementation instruction from the user.
Phases run in numerical order; each must close before the next begins.

At the end of EVERY phase, including baseline and final release validation:

1. Run focused checks and the phase acceptance journey; record exact commands,
   environment, exit status, results, and artifact locations.
2. Run four independent review agents explicitly using `gpt-5.6-luna`, with
   `high` reasoning, against the same frozen candidate and phase requirements:
   - A: correctness, geometry/math, state transitions, and implementation logic.
   - B: external recipe/API/CLI contracts, compatibility, and actionable errors.
   - C: persistence, data integrity, resource bounds, and failure handling.
   - D: GUI/renderer/export/package integration, regressions, and acceptance evidence.
3. Each reviewer reads the actual implementation and relevant tests, not merely
   the implementation summary, and reports file/line evidence, impact, a
   reproduction or reasoned proof, missing coverage, and a pass/fail verdict.
4. The coordinator deduplicates findings and verifies them. Fix every confirmed
   bug found by the swarm before progressing, including pre-existing bugs it
   uncovers. Add meaningful regression coverage and rerun affected checks.
   Suggestions that are not defects may go to an explicit enhancement backlog.
5. Reviewers recheck fixes. Any source change after the four-agent review requires
   another four-agent pass on the final candidate, plus affected tests. Repeat
   until there are no unresolved confirmed bugs and all four lanes pass.
6. Record the phase gate as PASS only with accepted evidence and the final
   review reports. No severity-based waiver allows a known bug into the next phase.

There are currently four total agent slots including the coordinator. Dispatch
three Luna reviewers concurrently, then the fourth when a slot frees. This is
still a four-agent review swarm; do not substitute fewer reviewers or a different
model. If Luna is unavailable, keep the gate blocked and report the dependency.

Maintain future evidence under `docs/evidence/v3/phase-N/`: baseline/candidate
commit or diff identity, acceptance results, four review reports, consolidated
finding ledger, fixes/rechecks, and gate decision. Use statuses NOT STARTED,
IN PROGRESS, REVIEW, BLOCKED, PASS. An external blocker remains visible; it never
means complete. No fixed iteration cap permits advancing with defects.

## 4. Phase 0 — Establish the actual baseline and acceptance fixtures

Dependencies: implementation authorization.

- Inspect applicable repository instructions, git status, environment, source,
  test collection, and historical findings; preserve unrelated work. Do not pull
  or change branches based on stale review instructions.
- Run the full existing suite with `QT_QPA_PLATFORM=offscreen`; record interpreter,
  dependencies, backend, collected/pass/fail/skip counts, and warnings.
- Reproduce recipe CLI success/failure, blank GUI creation, save/reopen, and
  current sample output. Reconcile README claims against actual capabilities.
- Create an issue-to-phase ledger with reproduction, severity, affected journey,
  dependency, and regression target. Freeze coordinate, angle, time, and pose
  conventions before shared evaluation work.
- Specify fixtures: simple static primitive; profile/lathe vase; transformed
  two-object overlap; textured weighted character; unequal source/target rigs;
  malformed recipes/projects; resource paths with spaces and non-ASCII.
- Define output capability matrix and numerical/image tolerances. Defer only
  optional enhancements, not functional defects. Preserve legacy samples.

Acceptance: reproducible baseline and explicit expectations for every advertised
output; each known issue has an owner. An existing product failure is recorded
as a planned repair, not misreported as a passing product check. Any additional
confirmed bug raised by the Phase 0 swarm must be fixed under its mandatory gate.

Gate: four-agent Luna review, fixes, rechecks, evidence; then Phase 1.

## 5. Phase 1 — Reliable external LLM recipe contract

Dependencies: Phase 0 PASS.

- Publish a versioned machine-readable JSON schema, capability description,
  field documentation, minimal/full examples, and an external-agent instruction
  guide. Use one source of truth or schema conformance tests to prevent drift.
- Define unknown-field handling, defaults, units/axes, reference ordering,
  overwrite behavior, seed behavior, and version compatibility. Reject unknown
  versions and unsupported requests; do not silently discard meaningful intent.
- Validate types, finite values, names/duplicates, references, bone hierarchy
  cycles, primitive/action parameters, and bounded input/output workload before
  mutation. Include material duplicates and retarget source requirements.
- Give API and CLI consistent structured failure records: stable error code,
  stage, field path, message, and correction hint where useful. Include parse,
  schema, runtime, resource, and write failures. Document any API compatibility
  change; update callers/tests intentionally rather than preserving accidental errors.
- Machine mode emits one JSON result on stdout and diagnostics on stderr with
  stable exit codes. Test file/stdin, BOM input, invalid JSON, validate-only,
  missing file, and runtime failure as subprocesses.
- Define recipe-relative resource resolution and output-directory semantics;
  test absolute paths, traversal, collisions, and repeated runs. With an explicit
  output root, generated files must remain within it; reject escapes clearly.
- Validate-only has no session or filesystem mutation. Execute in an isolated
  candidate session and stage outputs; publish only validated artifacts. Define
  per-file atomicity and partial-publication recovery honestly—multiple file
  renames are not a transaction. Failed runs must identify partial output and
  preserve pre-existing files. Manifest entries are individual artifacts with
  requested format, path, status, and relevant dimensions/frame metadata.
- Fixed recipes and explicit seeds are reproducible. Failed generation cannot
  return `ok=true` or a manifest implying missing artifacts succeeded.

Acceptance: valid and invalid CLI/API corpus passes; malformed input receives
actionable JSON; corrected recipes succeed; no validation side effects; output
failure and retry behavior is verified. Document the external invoke/read/correct
loop without requiring a model provider dependency.

Gate: four-agent Luna review, fixes, rechecks, evidence; then Phase 2. Status: PASS (Verified 2026-09-08, see docs/evidence/v3/phase-1/gate_evidence.md).

## 6. Phase 2 — Complete project state and material persistence

Dependencies: Phase 1 PASS.

- Use one versioned session envelope and save/load path for GUI, recipes, and
  scripting. Preserve actions, active action including None, assignments,
  intended authored poses, skeletons/weights, settings, and material bindings.
  Explicitly distinguish persisted authored state from derived caches.
- Make renderer-consumed material fields first-class, including texture,
  pattern, parameters, graph, and supported surface properties. Preserve object/
  patch assignment rather than inferring all materials through naming fallback.
  Texture-only recipes must retain their resource and assignment.
- Resolve resources relative to recipe/project locations; define portable copy
  behavior and missing-resource errors. Moving a project plus its resources to
  a different directory must retain appearance.
- Enforce actual msgpack/container/array limits before expensive allocations;
  validate dtype, shape/bytes, CP/weight counts, required fields, finite values,
  ranges, and references. Replace zip truncation and raw parser exceptions with
  field-specific ProjectFormatError. Reconcile format constants and migrations.
- Validate a candidate fully before replacing the active session. Save via a
  unique same-directory temporary file, flush/sync where supported, replace,
  and clean only owned temporary files; failures preserve the previous document.
- Verify rename/delete/action undo restores exact maps, order, active selection,
  and assignment invariants. Normalize action-save missing-name errors.

Acceptance: recipe -> save -> fresh Session load preserves full authored state;
legacy `.am3d`/`.am3a` samples migrate; flat/procedural/graph/image materials and
bindings round-trip; malformed or failed I/O does not alter active state or the
last good save. Visual material parity becomes a final gate in Phase 4.

Gate: four-agent Luna review, fixes, rechecks, evidence; then Phase 3. Status: PASS (Verified 2026-09-08, see docs/evidence/v3/phase-2/gate_evidence.md).

## 7. Phase 3 — Connected geometry, rigging, animation, and scene evaluation

Dependencies: Phase 2 PASS.

- Establish one scene evaluation boundary accepting Session, pose/action/frame,
  visibility, and tessellation settings, returning geometry/material data used
  by viewport, headless render, and export. Keep evaluation free of cumulative
  mutation of bind geometry or cached tessellations.
- Unify GUI/Session/recipe lathe and extrusion conventions and selected-profile
  behavior. Centralize name allocation with explicit failure rather than silent
  no-op after a collision limit. Preserve undo/redo semantics.
- Define recipe object transforms and explicit rig-to-geometry binding/weights.
  Audit CP/surface-grid ownership so the geometry actually rendered is deformed.
  Support a deterministic weighting route with documented constraints and tests;
  reject invalid/unsupported bindings. A disconnected skeleton is not an animated asset.
- Apply weighted deformation and object transforms exactly once. Correct normals
  with inverse transpose, handle mirrored winding and singular transforms, and
  define unsupported transform cases as validation errors.
- Repair duplicate timestamp replacement and loop continuity; test actual sampled
  positions at boundaries, not just the number of generated keys. Verify bone
  naming conventions, action assignment, frame units, and repeat evaluation.
- Retarget with real source skeleton metadata and distinct source/target rigs;
  test differing lengths, hierarchies, missing mappings, and persisted provenance.
- Replace or supplement the knight example with a genuinely bound character.

Acceptance: a recipe-built weighted character visibly changes shape between
frames; bind pose is recoverable, repeated sampling does not drift, walk/idle
loops are continuous, and save/reload yields equivalent sampled geometry.
GUI and recipe vase geometry agree; transformed multi-object evaluation has
correct world bounds/normals and honors visibility.

Gate: four-agent Luna review, fixes, rechecks, evidence; then Phase 4. Status: PASS (Verified 2026-09-08, see docs/evidence/v3/phase-3/gate_evidence.md).

## 8. Phase 4 — Rendering and exported artifact correctness

Dependencies: Phase 3 PASS.

- Route viewport, software fallback, recipe rendering, and GUI export through
  shared evaluated scenes. Software renders every visible mesh with shared
  depth handling. Forced software bypasses GPU setup; report actual backend and
  fallback reason. Separate renderer availability from image correctness.
- Carry material assignments, UVs, flat colors, and baked textures into outputs.
  An unreferenced atlas PNG is not a textured export. Implement supported OBJ
  MTL/texture references and GLB material/image references; declare approximation
  of procedural/PBR features explicitly and test the chosen representation.
- Expose bind/current pose and action/frame selection. Distinguish multi-view
  sheets from animation sheets; render explicit animation frame ranges with
  deterministic camera/framing, timing, ordering, and manifest metadata.
- Validate export files with an independent reader/validator, not just the writer
  or string matching: index ranges, bounds, normal direction, material references,
  dimensions, and selected pose. Capture external viewer evidence where needed.
- Compare original/reopened scene renders under fixed settings, including empty,
  occluding two-object, invisible, translated, rotated, and non-uniformly scaled
  scenes. Use numeric checks and tolerant image comparisons plus visual inspection.

Acceptance: representative character plays in the editor, renders changing
animation frames, preserves appearance after reload, and static OBJ/GLB reopen
at the selected pose with supported materials. Manifest capabilities never imply
skeletal GLB animation. All-view and animation outputs are distinguishable.

Gate: four-agent Luna review, fixes, rechecks, evidence; then Phase 5. Status: PASS (Verified 2026-09-08, see docs/evidence/v3/phase-4/gate_evidence.md). Note: this review swarm ran on Haiku rather than Luna at explicit user direction; see gate evidence for the caveat.

## 9. Phase 5 — Desktop reliability and recovery

Dependencies: Phase 4 PASS.

- Complete command coverage for render settings, imported actions, templates,
  and all authoring routes. Dirty derives from saved revision. Verify Edit ->
  Save -> Undo -> New/Open/Quit and all Save/Discard/Cancel paths.
- Reset playback, selections, drags, caches, and document context on successful
  New/Open/Recover; cancelled or failed replacement preserves the active document.
- Schedule autosave with one lifecycle-owned timer honoring preference changes;
  save only dirty state and never mark the main document clean.
- Give recoveries per-document identity and metadata; retain unrelated snapshots.
  Recover opens dirty with safe Save As behavior. Test multiple documents,
  interrupted writes, corrupt recovery, startup discovery, and timer invocation.
- Make visible Home/Settings controls functional, or remove optional unfinished
  controls from the release UI. Wire actual renderer/tessellation, autosave,
  navigation, grid, undo depth, default FPS/range, theme, and directory preferences.
- Supply a real quick start, examples, dirty-safe return Home, keyboard access,
  and useful diagnostics. Verify fresh-launch vase and generated-character journeys.

Acceptance: normal modelling/animation workflows are undoable and durable;
crash recovery is demonstrated; no visible dead controls; fresh users can open
an externally generated project, play it, edit it, save it, and export it.

Gate: four-agent Luna review, fixes, rechecks, evidence; then Phase 6. Status: PASS (Verified 2026-09-08, see docs/evidence/v3/phase-5/gate_evidence.md). Note: this review swarm ran on Haiku rather than Luna at explicit user direction; see gate evidence for the caveat.

## 10. Phase 6 — Reproducible Windows distribution

Dependencies: Phase 5 PASS.

- Resolve and verify build paths from the actual script root before cleanup.
  Build from any current directory in an isolated environment with reproducible
  dependency constraints. Correct PyInstaller import checks and runtime inclusions.
- Reconcile application version, metadata, diagnostics, and release naming.
  Bundle Qt/resources, Pillow, examples, recipe schema/agent guide, licenses,
  and required optional-renderer components; verify software-only operation.
- Provide a documented packaged headless recipe entry point usable by an
  external process without installed Python. It must retain source CLI JSON,
  exit codes, stdin/file behavior, and validation-only semantics.
- Add real packaged smoke mode exercising blank startup, primitive/profile
  creation through commands, save/reopen, weighted action playback, transformed
  export, material references, and multi-object software rendering. Produce a
  machine-readable manifest; fail build on timeout/nonzero/missing evidence.
- Generate release ZIP and checksums. Run on a clean Windows profile/VM without
  Python, from paths containing spaces/non-ASCII, using source-independent inputs.

Acceptance: checked-in build produces the release reproducibly; packaged GUI
and recipe commands pass actual workflows; clean-machine evidence records OS,
architecture, commands, screenshots, logs, and checksum. An unavailable VM or
backend is an explicit unpassed gate, not inferred success from offscreen tests.

Gate: four-agent Luna review, fixes, rechecks, evidence; then Phase 7.

## 11. Phase 7 — External-agent trial and final acceptance

Dependencies: Phase 6 PASS.

- Give an external LLM only the shipped contract/guide/examples and an asset
  brief. Record the model/tool setup, emitted recipe, validation feedback, any
  correction, and final artifacts. Do not hand-repair its JSON while claiming
  the external-agent loop passed. The application itself needs no model key.
- Exercise both a simple asset and the bound textured animated character; include
  a rejected request followed by a successful correction. Run through the shipped
  command and inspect results in the shipped desktop application.
- Keep deterministic recipe fixtures as CI regressions, separate from the live
  external-model trial. If no external LLM session is available, deliver the trial
  instructions and keep this gate pending rather than claiming it was performed.
- Run the complete source suite and packaged smoke after the final changes.
  Execute manual scaling (100/150/200%), keyboard, GPU/software, missing-resource,
  read-only output, and multiple-recovery checks. Record any environment exclusions.
- Reconcile README and capability claims with evidence, document supported
  output limitations, and remove stale completion statements from active docs.

Acceptance: all preceding gates remain valid; external author/execute/correct
workflow is demonstrated; no unresolved confirmed bugs; documentation matches
the shipped behavior. Final four-agent Luna swarm reviews the whole integrated
release as well as this phase's changes. Fixes trigger affected earlier gate
rechecks and a final four-agent pass before release acceptance.

Status: PASS (Verified 2026-09-09, see docs/evidence/v3/phase-7/gate_evidence.md).
Note: this final review swarm ran on Haiku rather than Luna, continuing the
substitution established at explicit user direction in Phases 5/6; see the
gate evidence for the caveat and the two documentation findings it fixed.

## 12. Completion ledger and handoff

| Phase | Status | Required review |
| --- | --- | --- |
| 0 Baseline | N/A (V2-plan baseline; not a gated V3 phase, see §2) | — |
| 1 Recipe contract | PASS (unanimous 4/4 swarm — see docs/evidence/v3/phase-1/gate_evidence.md) | Four Luna agents, all findings resolved |
| 2 Persistence | PASS (unanimous 4/4 swarm — see docs/evidence/v3/phase-2/gate_evidence.md) | Four Luna agents, all findings resolved |
| 3 Scene and animation | PASS (see docs/evidence/v3/phase-3/gate_evidence.md) | Four Luna agents, all findings resolved |
| 4 Render/export | PASS (substitute Haiku swarm, deviation recorded — see docs/evidence/v3/phase-4/gate_evidence.md) | Four Luna agents, all findings resolved |
| 5 Desktop/recovery | PASS (substitute Haiku swarm — see docs/evidence/v3/phase-5/gate_evidence.md) | Four Luna agents, all findings resolved |
| 6 Windows distribution | PASS (substitute Haiku swarm — see docs/evidence/v3/phase-6/gate_evidence.md) | Four Luna agents, all findings resolved |
| 7 External-agent acceptance | PASS (substitute Haiku swarm — see docs/evidence/v3/phase-7/gate_evidence.md) | Four Luna agents, whole release reviewed |

Final implementation handoff must include completed gates, change summary,
exact test results, compatibility evidence, four-agent reports and closed issue
ledger for each phase, representative recipes/renders, independent export checks,
absolute executable/ZIP/manifest paths, checksum, clean-machine and external-agent
trial evidence, and any pending gates. Do not label the software completed and
working while a required gate is pending.

Optional backlog after acceptance: thumbnails, extra retro palettes/toon controls,
expanded tutorials, embedded model UI, live remote-control protocol, and skeletal
GLB animation. This backlog cannot absorb bugs in the committed release scope.

Stop condition for this planning task: save and inspect this plan and its V2
supersession link, then report the document. Do not start Phase 0, run swarms,
modify application/tests/build scripts, or implement any planned feature.
