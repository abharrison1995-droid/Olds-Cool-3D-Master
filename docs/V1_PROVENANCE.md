# V1 provenance and reproducibility

V1 evidence must identify what was requested, which source/configuration ran,
what the host checked, and which immutable artifacts resulted. Historical
build or review evidence certifies only its named commit and artifact.

Authority: [V1 master plan](V1_MASTER_IMPLEMENTATION_PLAN.md), section 7.
Current V1 records are owned by `am3d/ai/records.py`. The preserved M2/M3.1
storage API has a separate layout and must not be interpreted as V1 records.

## Generation records

Use `generations/<run-id>/` as an immutable completed-run directory. A run
contains `record.json`, exact `recipe.json`, `preview.png`, `project.am3d`,
`brief.json`, `check-report.json`, and exported files. IDs are host-generated. A refinement
records its parent run ID and produces a child; never edit parent bytes.
Persist stages/times, app/build/capability identity, provider/model/prompt
version where known, usage and quota fields (`null` when unknown), policy
snapshot/digest, assumptions, approximations, required components, checks,
and relative artifact paths/hashes. Bound record, recipe, and failure sizes.

Write records atomically. A run succeeds only after fresh project reopen,
mandatory checks, and manifest verification. Failed/cancelled work remains a
failed record and cannot appear successful. Keep executor partial output in a
private attempt directory. Publish on the same filesystem by promoting a
verified completed directory; for cross-volume copy, stage privately, verify,
then rename. No active document is replaced. The editor opens a separate
writable copy after the ordinary dirty-document guard.

Current V1 private attempts live in `.generation-attempts/<canonical-UUID>/`
with atomic `state.json` and isolated candidate directories. Completed snapshots
live in `generations/<canonical-UUID>/`. Publication copies only checked files
into private staging, verifies hashes before/during/after copy, writes bounded
sidecars and `record.json`, then atomically renames on the history volume.
The orchestrator outcome uses `completed`; the durable successful record uses
`complete`. Interrupted attempts recover without relabeling a published result.
Never make these status spellings interchangeable across APIs.

Legacy M2/M3.1 records under `am3d.ai.m3.storage` retain their earlier IDs,
`checks.json` and `generation-failures/` conventions. Provider fields are absent
from the M2-only format. Preserve legacy adoption and writable-copy safeguards;
this distinction is not a record migration instruction.

Credentials, credential-bearing URLs, raw HTTP responses, and provider
transcripts never enter projects, workers, logs, or records. Sanitize errors
before persistence. Full run sidecars are authoritative; a history list is a
rebuildable index. A copied `.am3d` can still open without a sidecar, with
history reported unavailable. Save As/manual edits retain origin but mark
divergence; provenance never claims later geometry still matches the recipe.

The implemented optional format-2 `generation` envelope stores bounded
run/parent IDs, accepted brief, exact recipe/hash, application identity, warnings
and relative artifact references. `core/serializer.py` validates and preserves
it through current save/reopen. Older readers may ignore it on load and drop
it on save; copying to an older reader does not preserve full provenance.
Legacy format-1/2 files remain readable. Action metadata is not provenance.

## Build candidate evidence

Commit `scripts/build_input_digest.py`'s input manifest for each candidate
checkpoint. The manifest must enumerate every included tracked or untracked
build input with SHA-256 and include the canonical aggregate digest. Pair it
with source commit, package version, OS/architecture, Python version, exact
dependency lock, build/test/smoke commands and results, and SHA-256 of each
published archive. Do not describe an artifact as qualified unless its exact
candidate passed its target gate.

The release build scripts already record dependency provenance. V1 extends
this with a committed build-input manifest and immutable run evidence; never
rewrite old manifests or claim old evidence covers changed source. Platform
status and caveats belong only in `docs/SUPPORTED_PLATFORMS.md`.
