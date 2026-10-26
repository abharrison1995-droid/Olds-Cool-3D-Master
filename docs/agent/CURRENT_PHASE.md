# Current handoff — maintenance refactor and follow-up verified locally

Updated: 2026-10-26 (Europe/London).

**Authority:** the [V1 master plan](../V1_MASTER_IMPLEMENTATION_PLAN.md) governs
product scope and release gates. The [maintenance plan](REFACTOR_PLAN.md) is
implemented locally on `codex/refactor-context-cleanup`, based on master
`ffe82ef0f96aed557075a312b40647ab96c6be2b`. Publication and merge status belong to Git history and the maintenance PR.
The user authorized committing, pushing and merging this work on October 26. Windows V1/master convergence completed in `cd8214a`; do not resume
that merge or superseded M-stage schedules from older issues.

**Completed:** reconciled current context; extracted scene/animation/preview
checks, sanitized generation reports, format writers and window integration.
Preserved both V1 and legacy M2/M3.1 workflows, security boundaries, history
and local work. R2 shares evaluated animation samples/renders; R3 lazily reuses
static geometry inside one export transaction, invalidating on native saves
and bypassing the cache for animation frames. Measured three-component work
fell from 25 evaluations/12 renders to 5/4; the static fixture fell from 3 to 1.
Comparison reports, images and export bytes match their recorded baselines.

**Reliability correction (R1):** fixed sanitized audit reasons identified a
frozen live-containment failure. Real NTFS-handle probes reproduce deletion and
replacement resolving to the deleted-file namespace. Live audits now skip only
confirmed absent entries or independently validate a current replacement once;
links, persistent escapes and strict final audits still fail. Reserved portable
names are checked before Windows resolves them. Both historical frozen failures
remain evidence; the first unclassified event cannot be retrospectively
attributed with certainty.

**Latest validation:** [optimization and worker-race receipt](../evidence/refactor/2026-10-25-optimizations/IMPLEMENTATION.md).
Final locked Windows source suite: **1,207 passed, 6 skipped, 4 existing Qt
warnings**. Tooling: **45 passed, 4 skipped**. Fresh final GUI/CLI builds,
14-step offscreen smoke, three fixed-mock generation/history/refinement runs,
pre-Qt worker dispatch, independent OBJ/GLB readers and Qt-free CLI archive
checks passed. Recorded October 25 frozen-artifact build-input digest (before new files
became tracked):
`294e131a5cfedb0fc20bd68a10a9f418779b02c71c8ac76c2a0263b01e51f2ec`.

**Prior evidence:** [initial refactor](../evidence/refactor/2026-10-25/VALIDATION.md)
and [functional review](../evidence/refactor/2026-10-25-functional-review/REVIEW.md)
are immutable and apply only to their recorded source/artifacts. Their 49
companion files still match their original checksums. Do not reuse older
counts/PASS labels as acceptance for current work.

**Publication validation:** the October 25 receipt records local author review;
independent review was not performed. GitHub CI results belong to the maintenance
PR and its exact head, rather than the historical local receipt. Do not restart completed refactor stages or add
more module moves/global caches without evidence. A new worker failure should
be investigated through its fixed reason/phase metadata, preserving the failed
run. GitHub issue-authority proposals remain local; PR #16 is still draft and
unmerged.

**Open release gates:** Windows 11/Mint V1, native editing/keyboard/DPI/GPU,
complete restore-capable ACL denial, credential-store qualification, live
provider benchmarks, human scores and release signoffs. This Windows 10
workstation run used offscreen/software rendering and fixed offline transport;
it establishes neither target qualification nor V1 release acceptance.
