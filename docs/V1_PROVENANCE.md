# V1 provenance and reproducibility

V1 evidence must identify what was requested, which source/configuration ran,
what the host checked, and which immutable artifacts resulted. Historical
build or review evidence certifies only its named commit and artifact.

## Generation records

Use `generations/<run-id>/` as an immutable completed-run directory. A run
contains `record.json`, exact `recipe.json`, `preview.png`, `project.am3d`,
`checks.json`, and exported files. IDs are host-generated. A refinement
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

M2's local record format stores the host run ID, parent ID (null), UTC
start/end times, application version, optional build identity, recipe hash and
version, policy digest, check version, status, warnings, bounded errors,
relative artifact paths/sizes/hashes, preview dimensions, and elapsed time.
Provider, model, prompt, and usage fields are absent because M2 has no model
call. Failed and cancelled diagnostics live under generation-failures/;
they contain no publishable project or export artifacts and are never treated
as completed generations.

Credentials, credential-bearing URLs, raw HTTP responses, and provider
transcripts never enter projects, workers, logs, or records. Sanitize errors
before persistence. Full run sidecars are authoritative; a history list is a
rebuildable index. A copied `.am3d` can still open without a sidecar, with
history reported unavailable. Save As/manual edits retain origin but mark
divergence; provenance never claims later geometry still matches the recipe.

An optional bounded project `generation` envelope may store record version,
run/parent IDs, accepted brief, exact recipe/hash, build/capability identity,
warnings, and relative sidecar references. Choose a format-2 optional field
only after compatibility tests prove old files remain readable and new files
roundtrip; otherwise use a versioned format change with legacy fixtures. Do
not use action metadata for project provenance.

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
