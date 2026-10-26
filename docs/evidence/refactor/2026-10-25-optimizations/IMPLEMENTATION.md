# Maintenance optimization and worker-race validation — 2026-10-25

Scope: enact R1/R2/R3 of the [maintenance plan](../../../agent/REFACTOR_PLAN.md),
under the approved [V1 master plan](../../../V1_MASTER_IMPLEMENTATION_PLAN.md).
Uncommitted local work on `codex/refactor-context-cleanup`, based on
`ffe82ef0f96aed557075a312b40647ab96c6be2b`. No push, issue/PR update, live
provider call or release is claimed. The final build-input digest is
`294e131a5cfedb0fc20bd68a10a9f418779b02c71c8ac76c2a0263b01e51f2ec`; `source-inputs.json` binds the complete
inventory, including present untracked implementation files and tests.

## R1: reproduced containment failure and corrected lifecycle race

After adding fixed, sanitized audit reasons, one pre-correction frozen run
passed and an additional run failed with `worker_error/unsafe_output_tree`,
`audit_phase=live`, `audit_reason=containment`. Its result, state and log are
retained here. Three bounded source diagnostic attempts passed; they are not
proof that the frozen failure was fixed. The earlier unclassified failure in
the functional-review receipt also remains unchanged.

A controlled NTFS probe reproduced the live containment rejection: a temporary
entry deleted while path resolution holds its handle resolves into Windows'
`$Extend/$Deleted` namespace. This behavior is also described in the
[CPython Windows filesystem investigation](https://bugs.python.org/msg359981).
The guard rejected that resolution before reaching its existing vanished-entry
size-check tolerance. Atomic replacement can leave a new entry at the old name
while the resolver still refers to the unlinked old entry.

The same native-handle regression was run against both workers: the pre-fix
worker rejected all four live cases (file/directory × removal/replacement);
the corrected worker accepted their current safe state and rejected all four
strict final-audit cases. `native-lifecycle-comparison.json` preserves these
results without private paths. This establishes the reproduced mechanism; it
cannot retrospectively prove the first unclassified failure had that cause.

For a live mismatch, the worker skips only an entry confirmed absent by
`lstat`. A present replacement receives **one** independent recheck of link
components and resolved containment. A persistent escape, link takeover or
remaining mismatch fails. The final audit never retries or ignores these
mismatches. Normal contained entries incur no additional retry. Existing live
and final external failure codes remain, with fixed reason/phase metadata
sanitized again before generation-record persistence.

A new diagnostic test also exposed reserved Windows names being resolved before
the portable-name guard. Names such as `CON.png` are now rejected first. The
initial failing test is retained as `initial-audit-test-failure.log`.

Worker regressions: **45 passed, 2 host symlink-permission skips**. These include
real NTFS handles, missing/present escapes, retry bounds, link takeover,
portable collisions, junctions, atomic serializer staging, vanished scratch
entries, extended path spellings, cancellation and resource/protocol outcomes.

## R2/R3: measured work reduction with preserved outputs

| Fixture | Before | Implemented |
| --- | --- | --- |
| Three deforming components, four sample times | 25 core scene evaluations; 12 full-scene renders | 5 evaluations; 4 renders |
| OBJ + GLB + two-object toon sheets | 3 static scene evaluations | 1 evaluation |

Animation checks stream one scene per sample, use one fixed camera and render
that evaluated sample directly. Component evidence is accumulated in original
component order. `rendered_sample_frames` retains its logical component-sample
meaning (12 in this fixture); physical render calls are measured separately.
A failed shared render fails/stops every participating valid component at that
sample. Shape, missing, nonfinite, missing-camera and invalid-frame behavior have
explicit regressions; existing rig-assignment/resource checks remain in force.
Both profiled optimized reports, including thresholds and image/native hashes,
match the pre-optimization report exactly. All four static fixture artifacts
match byte for byte across both optimized repeats.

The static cache belongs only to one `ExportStager` transaction. Native saves
invalidate it; animated frame evaluation bypasses it. Real writers are exercised
with read-only shared mesh arrays. Textured/patch-material, transformed,
profile-generated and mixed native/animation/static outputs match uncached
execution. A later writer failure preserves existing files and the editor
session. All six format/atlas writer methods are AST-identical to the mechanical
refactor baseline; publication, confinement, duplicate destinations, budgets
and session commit remain executor responsibilities.

Separate sequential processes measured three unprofiled samples per workflow:
first in-process sample designated cold, median of the last two designated warm.
Imports/setup are outside workflow timers; load/thermal conditions were not
controlled. Warm export medians were 4.92 → 2.61 seconds; animation check medians
were 101.32 → 18.42 seconds. Process peak working sets were 102,031,360 and
102,252,544 bytes, including imports and both fixtures; no memory reduction is
claimed. All samples remain in `timing-comparison.json`; these local diagnostics
do not promise a production speed percentage. Only worker implementation/tests changed after these measurements; the full
profiled export/check pipeline is unchanged (`performance-binding.json`).

## Final source and artifact validation

Python 3.12.14 / pytest 9.1.1, existing pinned Windows environment, Qt offscreen,
`AM3D_TEST_REAL_GPU` unset. Every installed lock pin matched; lock SHA-256:
`0a9a1b4086add4515dab3eed56cb585331b6526ef4de72e9fa83e4c38024d4d6`.

| Check | Result |
| --- | --- |
| Final `python -m pytest am3d/ -q -ra` | 1207 passed, 6 skipped, 4 existing Qt warnings; 931.90 seconds |
| Packaging tooling | 45 passed, 4 skipped in 38.20s |
| Capability and provider schema generation checks | Passed with `--check` |
| Fresh frozen GUI and standalone CLI | Built from the final input snapshot |
| GUI smoke | 14 steps, offscreen/software |
| Fixed-mock generation/history/refinement | Three post-correction frozen runs passed; two additional roots match the failed pre-fix root's length |
| Worker dispatch | Qt not loaded before internal dispatch in all three acceptance reports |
| Knight CLI output | Independently parsed OBJ and GLB; no issues |
| CLI payload | No Qt entries among 576 archive entries/modules |
| Payload inventory | 249 files, 191,365,334 bytes; all SHA-256 values retained |
| Earlier immutable receipts | All 26 initial and 23 functional-review companion files still match |

The earlier traversal and superseded verification snapshots are not final-source
certification. This final suite and rebuilt artifacts follow both deletion and
replacement corrections. Current runtime inputs match the final build manifest.

Self-review covered sample lifetime/options, shared-render failure fan-out,
component order, transaction cache invalidation, unchanged writers, immutable
parent/refinement outcomes, and the live/final audit distinction. Only eight
build inputs changed since the mechanical refactor baseline: four runtime
modules and their four test files (`scope-review.json`). No independent reviewer
was used. No more module moves, global caches or pipeline abstraction are
justified by the present evidence.

Windows 10 workstation/offscreen/software results do not qualify Windows 11,
Mint V1, native interaction/DPI/GPU, complete ACL denial, credential-store CRUD,
live-provider benchmarks, human scoring or release signoff. Independent review
and Linux CI remain separate. Existing build/release outputs and all historical
evidence were preserved. `CHECKSUMS.json` binds this new receipt and companions.
