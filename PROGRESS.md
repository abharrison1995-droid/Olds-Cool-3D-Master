# 3D MASTER:2005 — current progress

Updated: 2026-10-26 (Europe/London).

The [approved V1 master plan](docs/V1_MASTER_IMPLEMENTATION_PLAN.md) remains
product authority. Source version is `1.0.0.dev1`: a development test candidate,
with the in-app brief/provider/check/history/refinement workflow and offline
manual/recipe CLI support. Implementation and the Windows lock are on master.
Windows 11 and Mint 22.3 V1 qualification remain open.

## Current maintenance result

The [maintenance plan](docs/agent/REFACTOR_PLAN.md) and R1/R2/R3 follow-up are
implemented locally on `codex/refactor-context-cleanup`, based on master
`ffe82ef`. The user authorized committing, pushing and merging this work on October 26;
Git history and the maintenance PR record publication status. Check stages, generation
reporting, export staging and window integration have explicit module owners;
current context is reconciled and both generation APIs/history are preserved.

Animation checking now shares sample evaluation and rendering: the measured
three-component fixture uses **5 evaluations/4 renders**, previously 25/12.
The static multi-format export fixture uses **1 evaluation**, previously 3.
Output reports/images/hashes match; native saves invalidate the transaction
cache and animation frames bypass it. A reproduced NTFS deletion/replacement
race in the live worker audit is corrected with bounded independent revalidation;
strict final auditing remains unchanged. Fixed sanitized reason/phase metadata
supports future diagnosis. Earlier failures remain in their evidence records.

Final locked Windows suite: **1,207 passed, 6 skipped**, with four existing Qt
warnings. Tooling: **45 passed, 4 skipped**. Fresh final GUI/CLI builds, 14-step
offscreen smoke, three fixed-mock generation/history/refinement runs,
independent export readers, pre-Qt dispatch and Qt-free CLI archive checks
passed. The [new receipt](docs/evidence/refactor/2026-10-25-optimizations/IMPLEMENTATION.md)
binds final source inputs/artifacts, control regressions and every retained
failure. The [initial refactor](docs/evidence/refactor/2026-10-25/VALIDATION.md)
and [functional review](docs/evidence/refactor/2026-10-25-functional-review/REVIEW.md)
remain immutable historical records. The local receipt records author review; GitHub CI results belong to the
maintenance PR and exact head. Independent review was not performed. Follow [the current handoff](docs/agent/CURRENT_PHASE.md).

## Product implementation and release status

| Area | Status |
| --- | --- |
| V1 workflow implementation | Implemented with phase-scoped local receipts; maintenance checks preserve existing behavior. |
| Master convergence | Completed in `cd8214a`; corrected candidate CI rerun and ACL limits are recorded in the [October 21 follow-up](docs/evidence/v1/master-push-ci-followup-2026-10-21.md). |
| Windows development artifacts | Exact earlier candidate identities and limits remain in the [acceptance ledger](docs/evidence/v1/ACCEPTANCE_LEDGER.md) and [Phase 11 report](docs/evidence/v1/phase-11/FINAL_ACCEPTANCE.md). They are separate from maintenance artifacts. |
| M3.2 CLI adapter | PR #16 remains draft and unmerged; it is outside current V1 maintenance. |
| V1 release acceptance | Open: native editing/recovery/keyboard/DPI/GPU, complete ACL denial, approved live-provider runs and human scores, clean Windows 11/Mint targets and release signoffs. |

## Historical previews

The accepted Mint preview and older MX artifact remain separate, source/artifact-
bound results. Their [preview roadmap](docs/IMPLEMENTATION_ROADMAP.md),
[Mint review](docs/evidence/implementation-roadmap/CANDIDATE_REVIEW.md), and
[MX evidence](docs/evidence/desktop-release/phase-e/) are retained. They do not
qualify current V1 source. Current support limits remain in
[SUPPORTED_PLATFORMS.md](docs/SUPPORTED_PLATFORMS.md); historical test counts
and hashes belong with their original receipts rather than this current handoff.
