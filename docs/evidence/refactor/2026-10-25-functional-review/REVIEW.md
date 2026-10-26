# Functional retest and author review — 2026-10-25

The user requested fresh function testing, another review of the refactor,
and a plan for justified improvements. Production code was unchanged during
this pass. The tested source is the uncommitted maintenance tree on
`codex/refactor-context-cleanup`, based on `ffe82ef0f96aed557075a312b40647ab96c6be2b`,
with build-input digest
`817f8e1d2176c7ddcbae02e18cbcbe3b2c8c2f6f4cde69ed6f12a10fb9bbf3aa`.
The earlier [validation record](../2026-10-25/VALIDATION.md) remains unchanged.

## Functional results

| Exercise | Result |
| --- | --- |
| Fresh locked full source suite | **1,180 passed, 6 skipped, 4 existing Qt warnings**, 857.77 seconds. |
| Fresh packaged GUI smoke | Passed all 14 steps, Qt offscreen/software. |
| Frozen offline generation/refinement, first run | **Failed:** `worker_error/unsafe_output_tree`; no checker report or published parent result. Failed state and error log retained. |
| Frozen offline rerun 1 | Passed the full acceptance report at a matching-length fresh output path. PowerShell invocation did not provide a reliable waited exit code, so this finding relies on the completed acceptance report. |
| Frozen offline rerun 2 | Passed with waited exit code 0 and full acceptance report; Qt remained unloaded before fixed worker dispatch. |
| Source-mode diagnosis | Two fixed-mock runs passed: one matching the first output-path length and one deeper. No parent tree-audit exception was captured. |
| Frozen CLI knight | Exit 0; independent OBJ/GLB validators passed. |
| Frozen CLI malformed JSON | Expected exit 1; no native project created. |
| Before/after three-component animation comparison | Check reports, measurements and artifact hashes identical. |

Command for the full source suite, using the existing Windows locked environment:

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
build/windows/venv/Scripts/python.exe -m pytest am3d/ -q -ra
```

The six source skips are three unavailable symlink cases and three deliberately
disabled native-GPU cases. The four warnings are the existing Qt mouse-event
deprecations. Profiling and other diagnostic processes ran concurrently, so
suite duration is not a controlled before/after performance comparison.

The previously built GUI/CLI were exercised against fresh output directories;
these were retests, not new builds. Before execution, the helper checked all
249 files against the existing payload manifest and all runtime/build inputs
against the source manifest. No provider network traffic or billable call was
used. Source-mode diagnostics and frozen acceptance used fixed mock transport.

## Review findings and disposition

### Observed reliability failure — cause unresolved

The first frozen fixed-mock run failed on its first candidate, recorded as
`worker_error/unsafe_output_tree`. The parent guard collapses several
`PolicyError` conditions into that result at `am3d/ai/worker.py`'s live-audit
exception branch. The state does not preserve the particular audit reason.
Consequently the evidence does not distinguish a transient-file race, path
spelling, a real unsafe entry, or another guard condition.

One generated PNG path was 276 characters. Ordinary Windows path access failed
for that leaf while extended-path access succeeded; a direct audit using the
extended root also succeeded. Valid source and frozen matching-length runs
subsequently passed. **Path length is not established as the cause.** The
worker guard was unchanged by the refactor, but that alone does not establish
whether changed timing contributes. This is not a diagnosed refactor defect
or a fixed failure. Keep the original failure in the run denominator.

The next reliability task is bounded, sanitized audit-reason instrumentation
and a controlled lifecycle/path reproduction. Do not relax confinement or
post-exit checks on the basis of successful retries. The specific failure is
retained in [the original state](frozen-initial-state.json) and
[error log](frozen-initial-failure.log).

### Measured efficiency opportunities — pre-existing duplication

The profile harness used real host-authored recipes and the original source
from `git archive HEAD` in an isolated directory, followed by the refactored
source. Original workload: three repetitions of each case; refactored workload:
one bounded comparison. Counts were identical across every repetition.

| Workload | Original | Refactored | Proposed target |
| --- | --- | --- | --- |
| Three static export formats: OBJ, GLB, toon sheet | 3 core scene evaluations | 3 | 1 per private static export transaction |
| Three deforming components, four animation times | 25 core scene evaluations, 12 whole-scene renders | 25 evaluations, 12 renders | 5 evaluations, 4 renders, streaming samples |

These counts support removing repeated work; they do not establish a slowdown
introduced by refactoring or a future wall-time improvement percentage.
`cProfile` adds overhead and host load varied. The animation report and artifact
hashes match exactly between original and refactored source. See
[profile comparison](profile-comparison.json), [original profile](profile-before.json),
and [current profile](profile-after.json). The profile script is retained for
reproduction; `--repeats` defaults to three and accepts one to three.

Animation reuse can use the existing renderer's `EvaluatedScene` support;
there is no need for a second evaluator or global scene cache. Stream samples
to preserve memory bounds and define component-sample versus unique-render
measurements explicitly. Static export reuse requires proof that writers do
not mutate shared meshes and that mixed native/animation operations invalidate
any affected state.

### Refactor structure and compatibility

The review followed checker stage ordering/short-circuits, report/error
sanitization, export staging/publication/session commit, and window parenting,
signal callbacks, document guards and shutdown ownership. Existing public
action signatures and the separate legacy workflow remain. No additional
reproduced functional regression was found in these covered paths.

The generation collaborator still depends on window internals, and the
orchestrator still has one explicit transition loop. Neither fact justifies
another broad rewrite here. Small typing/import/formatting cleanup is optional;
it is not a demonstrated speed optimization. This was the author's review,
not independent review, native desktop qualification or Linux CI.

## Improvement plan

The [updated maintenance plan](../../../agent/REFACTOR_PLAN.md) prioritizes:

1. **R1:** explain the intermittent audit failure and add a reproducing
   regression before claiming a fix.
2. **R2:** share animation samples and renders within a check invocation.
3. **R3:** reuse static evaluated geometry within an export transaction.

R2/R3 require stable artifact/geometry comparisons, preserved failure evidence
and resource bounds, followed by affected/full/frozen verification. These are
proposed changes; no optimization or worker-policy change was implemented in
this pass. The successful source suite and retries do not erase the unresolved
frozen failure or qualify the V1 release/platform/live/human gates.

`summary.json`, the complete test/profile/failure/acceptance receipts and
`CHECKSUMS.json` bind this additive record. No earlier evidence was rewritten.
