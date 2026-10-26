# Refactoring and context cleanup plan

Date: 2026-10-25 (Europe/London). Status: mechanical refactor and the R2/R3
optimizations are implemented locally on `codex/refactor-context-cleanup`.
R1 diagnostics, a reproduced live-audit deletion-race correction, and a separate
Windows reserved-name correction are implemented. The older unclassified
failure cannot be retrospectively attributed with certainty. Final
source/frozen verification of this follow-up passed; see the [optimization receipt](../evidence/refactor/2026-10-25-optimizations/IMPLEMENTATION.md). Independent review
has not been performed; publication CI belongs to the maintenance PR and
its exact head. The user authorized commit/push/merge on October 26. Earlier immutable records: [initial validation](../evidence/refactor/2026-10-25/VALIDATION.md)
and [functional review](../evidence/refactor/2026-10-25-functional-review/REVIEW.md).
Inspected source: `ffe82ef0f96aed557075a312b40647ab96c6be2b`, clean `master`,
matching `origin/master` at the start of this task.

This maintenance plan sits under the approved [V1 master plan](../V1_MASTER_IMPLEMENTATION_PLAN.md).
It does not replace product scope or release gates. Preserve manual editing,
offline CLI, generation, history, refinement, native files and supported exports.

## Follow-up scope and implementation status

The user requested fresh function testing and another review. The full locked
suite again passed 1,180 tests, skipped 6 and reported 4 existing Qt warnings.
Fresh packaged smoke/CLI/export checks passed. The first frozen offline AI run
failed with `worker_error/unsafe_output_tree`; two frozen reruns and two source
diagnostic runs passed. Its cause is unresolved. Retain that failure in the
assessment; matching-length reruns do not prove it fixed. Runtime source was
not changed during this review.

### R1 — Live containment failure reproduced; deletion race corrected

- Evidence: the failed fixed-mock run produced no checker report or published
  result, with one candidate and no active document replacement. Its state and both
  successful frozen reruns are retained in the functional review evidence.
- Scope: `ai/worker.py` live parent audits around `_verify_tree` and the
  `except PolicyError` branch. The guard itself was unchanged by this refactor;
  whether changed execution timing contributes is unknown.
- First add bounded host-authored reason categories for audit failures, without
  retaining raw exception strings, private paths, provider output or credentials.
  Distinguish path syntax, collision, link, containment and unexpected-file
  checks. Preserve the existing external failure code unless a versioned
  contract change is justified.
- Use controlled worker lifecycle tests around temporary-file publication,
  replacement/removal and Windows path spelling/length. Keep the final post-exit
  audit strict. A real escape/link/collision must still fail; passing retries
  are not grounds to loosen guards.
- Done when the failing condition is reproduced and explained, a meaningful
  regression proves its correction, and source plus frozen checks pass with
  every failure retained. If reproduction remains unavailable, leave this
  item open with its diagnostic evidence rather than declaring a fix.

### R2 — Shared animation evaluation and rendering implemented

- Measured before and after refactoring: checking three deforming components
  at four times makes **25 core scene evaluations and 12 whole-scene renders**.
  This duplication predates the refactor; comparison reports/artifact hashes
  are identical. Instrumented timings under concurrent load are diagnostic,
  not production speed measurements.
- Scope: `_animation_checks.py`. Evaluate each unique sample once, share it
  across component displacement checks, and render the whole scene once per
  sample. `gpu.resolve_scene` already accepts `EvaluatedScene`, so the public
  rendering boundary can consume an evaluated sample without a second
  tessellation. Keep one fixed camera and matching evaluation options.
- Stream one sample at a time instead of retaining four full scenes. Keep
  component-specific assignment/missing/nonfinite/motion failures and their
  ordering. Explicitly define logical component-sample counts versus unique
  renderer calls; preserve existing fields or version/document semantic changes.
- Target for this fixture: **5 evaluations and 4 renders**, not a promised
  wall-time percentage. Validate identical geometry/images and equivalent
  success/failure evidence, including render failures, unassigned/shared rigs,
  missing components, cancellation/resource outcomes and immutable parents.
- Measure warm/cold wall time and peak memory in a separate bounded process
  after the call-count change; then run affected and full/frozen regression.

### R3 — Transaction-local static export reuse implemented

- Measured in both versions: OBJ, GLB and toon-sheet export of one recipe
  evaluates the same static scene **three times**.
- Scope: `_export_staging.py`. Consider one lazy evaluation owned by that
  private export transaction. Verify writers do not mutate shared mesh arrays;
  establish invalidation around any state-changing operation. Do not cache
  across runs, editor documents or animation times.
- Target for this static fixture: **one evaluation**. Keep independent readers,
  exact artifact geometry/materials/sidecars, destination validation, duplicate
  checks, publication failure behavior and session commit ownership unchanged.
- Gate on deterministic output comparisons for textured/patch-material,
  transformed, profile-generated and mixed static/animation/native exports.
  Confirm the frozen CLI remains independent of Qt.

An additional frozen run using the new diagnostics failed with
`audit_phase=live` / `audit_reason=containment`. Three bounded source attempts
passed. A controlled test then reproduced that guard failure with a real NTFS
handle: deleting a temporary file/directory while resolution holds the handle
can return a `$Extend/$Deleted` path outside the private root. The old audit
rejected it before reaching its existing vanished-file size-check tolerance.

R1 now skips a live containment mismatch only when `lstat` confirms the
original entry name is absent. If an atomic replacement already occupies that
name, one bounded retry independently rechecks all link components and resolves
the current name inside the private root. A persistent escape or link still
fails, and the final post-exit audit never retries or skips these mismatches.
Native-handle tests cover files and directories for both removal and replacement;
cross-platform tests enforce the retry bound, reject a link takeover, distinguish
missing from present escaped entries, and keep final auditing strict. Fixed `audit_reason`/`audit_phase`
fields survive the worker and sanitized generation-record boundaries. Portable
names are checked before Windows resolves reserved basenames such as `CON.png`.
Existing live/final external failure codes are retained. Both frozen failures
remain evidence; the original unclassified failure has no retrospective proof
of this particular mechanism. Final post-correction validation passed: 1,207 source tests, the focused worker
regressions, fresh GUI/CLI builds and three bounded frozen acceptance runs. See
the [new receipt](../evidence/refactor/2026-10-25-optimizations/IMPLEMENTATION.md).

R2 now streams four samples once, shares whole-scene renders, preserves the
logical component-sample `rendered_sample_frames` field and assembles issues in
component order. A failed shared render fails every participating valid
component at that sample and stops its later samples. Successful comparison
reports and image/native hashes remain identical; physical work reaches the
5-evaluation/4-render target. Component geometry defects and unavailable-camera
behavior have explicit regressions.

R3 lazily retains one static scene within `ExportStager`; a native save
invalidates it because saving synchronizes session/project state. Animated
frames bypass it. Real writers accept read-only shared geometry; textured,
patch-material, transformed, profile-generated and mixed export comparisons
match the uncached execution. A late writer failure preserves existing files
and the active session. The static fixture reaches one evaluation.

Do not restart the completed mechanical stages or introduce a global cache,
generic pipeline, shared security abstraction or more large module moves
without new evidence. Independent review, Linux CI and the existing V1
target/live/human qualification gates remain separate.

## Audit findings

These were the maintenance concerns at the planning baseline, not reproduced
runtime defects. Their dispositions and verification are in the validation
record. Line counts describe that original source, not size targets.

| Priority | Finding | Proposed response |
| --- | --- | --- |
| First | `CURRENT_PHASE.md` still schedules the master merge; `PROGRESS.md` describes convergence as ongoing, although merge `cd8214a` and CI corrections are on master. | Refresh entry documents; link exact evidence instead of copying old status. |
| First | Open GitHub issues #6 and #7 still name the October 6 plan as active. `docs/V1_BENCHMARK.md` calls 27/30 aspirational, while the approved master plan makes it a release gate. | Reconcile supporting contracts and issue scope against approved authority; do not weaken gates or infer issue completion. |
| First | `.impeccable/surface-briefs/main-workspace.md` still describes an AI agent as the primary product user. | Align maintained design context with `PRODUCT.md` and `DESIGN.md`; retain visual references. |
| High | `ai/checks.py`: 1,686 lines; `check_artifacts`: 615 lines combining filesystem, scene, exports, preview and animation. | Extract cohesive check stages behind the current callable/report contract. |
| High | `ai/orchestrator.py`: 1,024 lines; `generate`: 339 lines combining bounded generation, repair, records and outcomes. | Extract stage operations and report normalization; retain one budget/state owner. |
| High | `recipes/executor.py`: 1,106 lines; `_run_exports`: 321 lines across formats and publication. | Separate export preparation and format writers from execution/publication ownership. |
| High | `ui/app.py`: 1,499 lines; constructs current AI and legacy recipe-generation flows. | Extract integration responsibilities while preserving Qt ownership and document lifecycle. |
| Later | `ai/worker.py` combines protocol, filesystem checks, Windows Job Objects and monitoring; `records.py` also checks links/manifests/publication. | Compare trust assumptions before extracting narrowly shared helpers. Similar checks may intentionally differ. |
| Later | `ai/benchmark.py`: 1,663 lines; policy, schema and serializer are also large. | Reassess after initial extractions; length alone does not justify restructuring. |

The legacy tree is **not unused**. References include `ui/app.py`,
`ui/generation_dialog.py`, `ui/document_controller.py`, `ui/__main__.py`,
adoption tests and Windows worker CI. Preserve `am3d.ai.m3.*`, its stored
artifacts and worker entry point. Do not remove working features or merge
incompatible APIs as cleanup.

## Context disposition

| Document or group | Action |
| --- | --- |
| `AGENTS.md` | Stable orientation, invariants, package boundaries and platform-specific verification commands. Keep changing status in the handoff. |
| `CLAUDE.md` | Keep its existing short redirect to `AGENTS.md`; no duplicate instructions. |
| `docs/agent/CURRENT_PHASE.md` | One concise current task, next action, verification scope and open gates. Replace obsolete next steps as work advances. |
| This plan | Maintenance sequence and completion criteria, subordinate to V1 product authority. |
| `docs/V1_MASTER_IMPLEMENTATION_PLAN.md` | Preserve approved contract; distinguish dated baseline findings from present implementation without rewriting history. |
| `PROGRESS.md` | Current product status and exact evidence pointers. Historical test counts must retain source scope. |
| README, user guides, capability and platform docs | Maintain current user behavior and qualification limits; reduce repeated artifact history through evidence links. |
| `V1_SECURITY_LIMITS.md`, `V1_PROVENANCE.md`, `V1_BENCHMARK.md` | Audit against V1 source, fixtures and master plan. Separate current contracts from legacy M-stage records. |
| `V1_PLAN.md`, V2/V3 plans, preview roadmap, desktop-release plan | Keep historical content and supersession notices. Avoid moves that break existing links; any necessary move requires incoming-link checks and an old-path redirect. |
| `docs/evidence/**`, `docs/archive/**`, `.agents/artifacts/**` | Preserve historical records and bytes; exclude from routine orientation. Old evidence is not obsolete merely because it is old. |
| `.impeccable/` | Correct maintained surface briefs; inspect consumers before modifying generated design data; retain dated screenshots. |
| Generated capability table/provider schema | Use existing generation scripts when inputs change; no hand-editing generated output. |
| Ignored build/release/work/environment folders | Leave intact. Context cleanup is not disk cleanup. |

Delete maintained guidance only after proving redundancy, retaining useful
content and accounting for incoming references. No file currently meets that
deletion bar. Remove obsolete active instructions while retaining historical
originals at their established locations.

## Staged implementation

Stages 0–6 are implemented or reassessed as specified below. Stage 7 local
source/tooling/generator/frozen checks passed; independent review and Linux CI
remain separate follow-up gates. The sequence is retained for traceability;
do not restart completed extractions from its imperative wording. GitHub issue
authority updates are prepared in the validation record and remain unpublished.

### Stage 0 — Plan and truthful entry context

Deliver this plan; refresh `AGENTS.md`, the handoff and the stale convergence
paragraph in `PROGRESS.md`. Leave runtime source and historical evidence intact.
Check local Markdown links and `git diff --check`.

Done when a new agent can find authority, maintenance scope, compatibility
boundaries and the next action without loading old phase logs.

### Stage 1 — Reconcile contracts and establish baseline

- Read each relevant issue before touching its package. Reconcile issues #3–#8
  against current source and the master plan; prepare proposed issue updates
  locally. This planning task does not post comments or edit GitHub issues.
- Resolve benchmark status/threshold drift using the master plan,
  `benchmarks/v1/` and `ai/benchmark.py`. Compare security ceilings and record
  layouts separately for current V1 and legacy APIs. Record unresolved product
  decisions instead of inventing requirements.
- Correct maintained surface briefs and check README/help/platform links.
  Clarify superseded baseline findings in active plans without altering results.
- Map imports, public re-exports, monkeypatch seams, hidden worker entry points
  and frozen imports before selecting extraction module names. Include a short
  dependency map with each implementation change.
- Run the locked Windows full source suite once on pre-refactor source, record
  interpreter/lock/source identities and skip reasons, and run generator checks.
  Existing historical results are not a fresh maintenance baseline.

Done when active contracts agree and each extraction has a bounded scope and
baseline. Fix confirmed runtime failures separately from structural changes.

### Stage 2 — Artifact check stages

Targets: `ai/checks.py`, its worker consumers and `ai/test_checks.py`.
Keep `check_artifacts` as the facade. Extract filesystem/manifest, independent
export/material verification, and scene/animation/preview responsibilities as
dependencies permit. Preserve check order, short-circuit behavior, resource
accounting, report keys/codes and sanitization. Keep export readers independent
of writers.

Verify existing check, sheet-contract and worker tests. Compare report
structure, deterministic artifact hashes and failure outcomes with baseline
fixtures; do not require identical timestamps/run IDs. Add regressions only
for meaningful uncovered behavior affected by extraction.

### Stage 3 — Orchestration mechanics

Targets: `ai/orchestrator.py`, prompt/record consumers, orchestration/refinement
tests. Extract error/report normalization and bounded stage helpers. Preserve
`GenerationOrchestrator`, `GenerationOutcome`, worker/clock injection, and one
owner of deadlines, attempts and semantic-call budgets. Do not introduce a
generic pipeline framework or second run-state model.

Verify orchestration, provider, prompt, record and refinement tests plus the
real offline worker/store path. Cover cancellation/late events, publication
failure, restart recovery and parent preservation. Provider tests stay offline.

### Stage 4 — Export execution

Targets: `recipes/executor.py`, recipe/export tests and check consumers.
Extract format-specific preparation/writing behind `RecipeExecutor`; retain
explicit destination validation, staged publication and session-commit
ownership. Preserve trusted CLI versus AI-mode behavior, safe artifact names,
source profiles, materials, sidecars, action poses and the CLI machine contract.
Do not describe existing multi-file CLI publication as atomic.

Verify executor/capability/primitive/animation/path/serializer/export tests,
independent OBJ/GLB readers and textured outputs; exercise the knight CLI recipe
and profile-edit/save/reopen tests. Failures must preserve the caller's session
and confine output to the host root where that policy is requested.

### Stage 5 — Main-window integration

Targets: `ui/app.py`, `ui/ai_controller.py`, `ui/document_controller.py` and
`ui/generation_dialog.py`. Extract legacy-generation integration and current
AI workspace/adoption wiring into explicit UI collaborators. Keep one
DocumentController and scene/session model. Preserve public window hooks,
Qt affinity, signal disconnection, timer shutdown and close/cancel behavior.

Verify document/adoption/workspace/history/profile-edit/home/smoke tests and
the full UI suite. Offscreen coverage cannot certify native editing, DPI or GPU.

### Stage 6 — Worker and storage reassessment

Targets: `ai/worker.py`, `ai/records.py`, `core/paths.py` and frozen launch paths.
Compare path syntax, links/reparse points, limits, manifests and publication
contracts before sharing helpers. Extract only code with identical trust
assumptions and failure semantics. Keep OS process behavior explicit. Do not
route legacy policy through V1 policy or weaken either to share implementation.

Verify lifecycle/resource/cancel, record/tamper, legacy-worker and Windows
tooling tests. Run payload audit and frozen worker/offline acceptance whenever
entry points or imports change. Ordinary regression excludes real ACL denial
experiments and native GPU opt-in.

### Stage 7 — Completion

Run the full locked source suite, affected build-tool tests and generator checks.
Require Linux fast CI for portability when runtime changes are pushed. Exercise
frozen GUI/CLI and offline acceptance if imports/packaging changed, recording
exact artifact identities. Review final diffs for behavioral changes, broken
references and obsolete instructions; update progress/handoff with actual results.

Done means preserved external behavior, meaningful boundaries, passing relevant
checks, truthful current context and intact evidence. Maintenance success does
not qualify V1. Follow the master plan's bounded independent-review policy at
implementation gates; reviewers do not implement their reviewed changes. This
planning audit has not received independent review.

## Verification and scope of evidence

On Windows, first verify the existing build interpreter against
`requirements-lock-windows.txt`; do not upgrade dependencies as a refactor side effect.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
build/windows/venv/Scripts/python.exe -m pytest am3d/ -q
build/windows/venv/Scripts/python.exe -m pytest scripts/test_phase10_tooling.py -q
build/windows/venv/Scripts/python.exe scripts/generate_recipe_capabilities.py --check
build/windows/venv/Scripts/python.exe scripts/build_recipe_provider_schema.py --check
git diff --check
```

Use the Linux lock and existing Linux fast workflow for Linux regression.
Keep `AM3D_TEST_REAL_GPU` unset for ordinary checks. Run focused checks per
extraction; repeat full suites only at baseline/final gates or when new risks
justify it. Record exact source, commands, results and skip reasons per stage.

Evidence consulted: Phase 11 final acceptance, the acceptance ledger, and the
October 21 master-push CI follow-up. The last records the corrected candidate
rerun and local 1,180-pass/6-skip result for its recorded source, not a future
refactor. Windows 11, Mint V1, native interaction/GPU, complete ACL denial,
live-provider benchmarks and human scores remain open under approved gates.

GitHub checked October 25: [issue #6](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/issues/6),
[issue #7](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/issues/7),
and [draft PR #16](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/pull/16).
The unmerged CLI adapter remains outside this maintenance scope.
