# Maintenance refactor validation — 2026-10-25

Scope: behavior-preserving refactor and context cleanup, subordinate to the
approved [V1 master plan](../../../V1_MASTER_IMPLEMENTATION_PLAN.md). Source
base: `ffe82ef0f96aed557075a312b40647ab96c6be2b`; implementation is the dirty
tree on `codex/refactor-context-cleanup`, identified by the accompanying input
manifest. No commit, push, PR, issue edit, live call or release is claimed.

## Dependency boundaries

| Owner | Extracted responsibility | Retained contract |
| --- | --- | --- |
| `ai/checks.py` | `_scene_checks.py`, `_animation_checks.py`, `_preview_checks.py`, shared `_check_report.py` | Public checker, native roundtrip, resource/path guards, independent export parsing, final report/manifest; existing helper/limit hooks remain available. |
| `ai/orchestrator.py` | `_generation_reports.py` | One explicit generation state machine and one owner of deadline/candidate/repair budgets. No reverse import from reporting into orchestration. |
| `recipes/executor.py` | `_export_staging.py`, shared `_export_paths.py` | Schema/path validation, duplicate destinations, output budget, publication and session commit. Format writers only accumulate private staged artifacts. Checker imports shared naming directly, without depending on writer orchestration. |
| `ui/app.py` | `GenerationIntegration` in `ui/generation_integration.py` | Window owns Qt objects, document and runner state; original action signatures forward to the collaborator. No second session or document controller. |

The main checker shrank from 615 to 197 lines and export orchestration from
321 to 62 lines. The orchestrator's transition loop remains explicit rather
than introducing another pipeline/state abstraction. No mesh/geometry engine,
schema, native serialization or release-threshold change was made.

## Worker/storage reassessment

| Area | Distinction | Decision |
| --- | --- | --- |
| Worker path guard | Protocol lifecycle, fixed private child tree, `PolicyError` failures, Windows reparse/process cleanup semantics. | Retain. |
| Checker path guard | Existing output/native files, portable derived paths, pre-parser byte limits and report-level failures. | Retain. |
| Record store guard | Private metadata and immutable publication snapshots, pre/post-copy hashes, journal recovery and cancellation commit point. | Retain. |
| Legacy M3 | Different worker, IDs, statuses and stored record layout; still used by UI adoption and CI. | Preserve implementation and compatibility integrations; clarify package docstring only. |

Similar functions do not have identical failure or trust contracts. No shared
security abstraction was justified. The benchmark, schema and serializer were
reassessed and left structurally unchanged; size alone is not a refactor goal.

## Context cleanup

Updated agent orientation/handoff, current progress, benchmark protocol,
resource limits, provenance, active-plan baseline caveats and the maintained
workspace brief. Removed obsolete merge instructions, old bake-off/model
requirements from current benchmark guidance, incorrect recipe/deadline/name
limits, optional-but-already-implemented provenance wording, and unrelated
design brainstorming. Preserved historical plans, evidence, screenshots and
local build/release outputs. Frozen fixtures/rubric were not rewritten.

## GitHub issue reconciliation proposals

Read open issues #3–#8 on October 25. All six link the superseded October 6
plan. No issue was closed or edited. Apply this authority preface when issue
updates are separately requested:

> Authority update (2026-10-25): the approved October 13 V1 master implementation
> plan on master supersedes the October 6 M-stage schedule linked below.
> Original milestone scope remains historical context. Source implementation
> does not establish live-provider, human, frozen-target or release acceptance.

| Issue | Proposed current-scope note |
| --- | --- |
| #3 Model-safe recipe contract | Registry/schema and host preflight exist. Preserve trusted CLI versus strict AI-mode semantics; maintenance changed export staging, not the accepted recipe language. Reconcile remaining acceptance against current source/evidence before closing. |
| #8 Local worker/checks | Earlier M2/M3.1 API remains namespaced under `am3d.ai.m3`; V1 uses `am3d.ai`. Both remain supported by existing integrations. Current maintenance extracts check stages without changing worker contracts. |
| #6 Provider adapters/AI loop | Current V1 has the bounded configured API provider and repair loop. The draft CLI adapter in PR #16 is separate and unmerged; the historical four-provider bake-off/default selection is not current V1 authority. Live-provider qualification remains open. |
| #5 Benchmark/recipe contract | Thirty release fixtures, eight discovery fixtures, journals and scoring machinery exist. Actual live runs/human scores remain open. Approved thresholds govern; new recipe features require measured gaps, not the old queued milestone label. |
| #4 Product workflow/history/refinement | Home/Create with AI, immutable history, guarded adoption, recipe-based refinement and profile edit preservation exist in source. Native keyboard/DPI/target qualification remains open. |
| #7 Frozen/release qualification | Keep open. Exact offline development artifacts do not qualify Windows 11, Mint V1, native interaction/GPU, complete ACL denial, live benchmarks or human scoring. Do not add an old local-model benchmark requirement to the approved two-run V1 gate. |

## Verification

Interpreter: existing locked Windows build environment, Python 3.12.14,
pytest 9.1.1. Every installed pin matched `requirements-lock-windows.txt`,
SHA-256 `0a9a1b4086add4515dab3eed56cb585331b6526ef4de72e9fa83e4c38024d4d6`.
Qt offscreen; `AM3D_TEST_REAL_GPU` unset. Commands and complete results are
retained alongside the input manifest and checksums. Focused stage logs describe intermediate trees; the final full-suite and frozen results are bound to the final input manifest.

| Check | Result |
| --- | --- |
| Full pre-refactor `pytest am3d/ -q -ra` | 1,180 passed, 6 skipped, 4 existing Qt warnings; 639.67 seconds. |
| Check/sheet/worker selection | 57 passed, 2 symlink skips; 92.45 seconds. |
| Orchestration/refinement/provider/prompt/record selection | 131 passed; 54.29 seconds. |
| Recipes, exports, paths, serializer, generated-profile editing | 349 passed; 61.47 seconds. |
| Document/adoption/workspace/history/Home/smoke selection | 81 passed; 124.07 seconds. |
| Packaging tooling | 45 passed, 4 symlink skips; 64.98 seconds. |
| Capability table/provider schema generation checks | Passed; no generated fixture edits. |
| Before/after behavior comparison | Passing and failing reports identical; all six native/export/image artifact hashes identical. |
| Mechanical move review | 34 moved top-level definitions retain identical ASTs. Seven UI method bodies match after window-reference substitution; five writer branches match after loop-continue/method-return substitution. This is source equivalence checking, not independent review. |
| Final full source suite | 1,180 passed, 6 skipped, 4 existing Qt warnings; 759.15 seconds. |
| Frozen GUI/CLI and offline acceptance | Both builds passed; 14-step offscreen smoke, offline parent/child generation/refinement, pre-Qt worker dispatch, CLI knight, independent OBJ/GLB readers and full payload path audit passed. |

Ordinary source skips are three unavailable symlink cases and three intentionally
disabled physical-GPU cases. Tooling skips are four unavailable symlink cases.
No skip is counted as a qualified platform/security gate.

## Remaining qualification

No Linux host/CI execution, independent reviewer, native interaction/DPI/GPU,
restore-capable ACL denial target, clean Windows 11/Mint host, live-provider
benchmark or human scoring was supplied by this maintenance run. These remain
explicit follow-up gates. Local source/frozen maintenance checks cannot mark
V1 release acceptance passed. No publishing or remote mutation occurred.

## Exact final binding

The tested dirty source and isolated frozen snapshot share build-input digest
`817f8e1d2176c7ddcbae02e18cbcbe3b2c8c2f6f4cde69ed6f12a10fb9bbf3aa`.
The [input manifest](final-inputs.json) enumerates each included source/input
hash. [Frozen validation](frozen-validation.json) records build/check commands
and executable hashes; [payload manifest](frozen-payload-manifest.json) binds
all 249 files (191,362,477 bytes), canonical manifest SHA-256
`4f091dee21f13038843cbf0842f43492cc429504869ac9a7942c4c640ed6c55b`.
The full GUI bundle and CLI passed the original-workspace path audit too.
Artifacts remain under ignored `work/refactor/frozen-dist/`; existing user
build/release folders were not replaced. These are maintenance artifacts, not
published or target-qualified distributions.

The [baseline log](baseline-tests.log), [final source log](final-tests.log),
[tooling log](tooling-tests.log), [frozen smoke](frozen-smoke.json),
[offline acceptance](frozen-offline-acceptance.json), and
[independent export checks](frozen-export-validation.json) retain full results.
`CHECKSUMS.json` binds this record and its companion evidence files. New evidence
is additive; no pre-existing evidence/archive/artifact record was modified.
