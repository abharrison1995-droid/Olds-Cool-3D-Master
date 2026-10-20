# V1 Phase 9 — UX and documentation reconciliation

Status: assigned documentation reconciliation is complete against the stable
Phase 7 source, owner evidence, and bounded independent local review. The
local Phase 7 preservation/refinement gate passed. This record is not an
independent UX/docs review, external review, full integrated regression, or
overall V1 acceptance.

At this documentation check, `am3d/__init__.py` and `pyproject.toml` both
declare `1.0.0.dev1`. The docs identify it as a development test candidate,
not a release candidate or stable V1 build. The UI owner reports 21 focused
Home/Phase 9 tests passed; visual capture completion, independent UX/docs
review, and the final stable-source test identity remain open.

## Authority and working scope

Authority: [`V1_MASTER_IMPLEMENTATION_PLAN.md`](../../../V1_MASTER_IMPLEMENTATION_PLAN.md)
section 12 and [`work/v1/phase9-docs-task.md`](../../../../work/v1/phase9-docs-task.md).
The Phase 9 task authorized edits only to the assigned entry-point/product
documents and this evidence directory. The repository was already dirty with
authorized V1 work; baseline HEAD at inspection was
`3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`. The requested Luna/xhigh/none
configuration was accepted as task metadata; runtime model and reasoning
effort are not independently introspectable.

Owned documents reconciled so far:

- `README.md`, `PRODUCT.md`, `DESIGN.md`
- `docs/CAPABILITY_MATRIX.md`, `docs/MODELLING_SCOPE.md`
- `docs/USER_GUIDE.md`, `docs/QUICK_START.md`, `docs/RELEASE_NOTES.md`
- `docs/SUPPORTED_PLATFORMS.md`, `docs/WINDOWS_ACCEPTANCE_PLAN.md`
- `docs/recipes/EXTERNAL_AGENT_GUIDE.md`

No `PROGRESS.md`, master-plan, UI, runtime, package/version, fixture,
historical-result, or Phase 10 source file was edited in this documentation
task. Root updated the version declarations; this task only aligned the docs
to the verified `1.0.0.dev1` value and did not invent a candidate artifact
hash. The development test candidate is distinguished from the historical
0.2.0b1 Mint preview and older MX artifact by their separately preserved
identities.

## Source and evidence inspected

Source labels and behavior were read from `am3d/ui/home.py`,
`am3d/ui/ai_workspace.py`, `am3d/ui/ai_settings.py`, `am3d/ui/ai_controller.py`,
`am3d/ui/app.py`, `am3d/ai/contracts.py`, `providers.py`, `credentials.py`,
`orchestrator.py`, `policy.py`, `worker.py`, `checks.py`, `records.py`,
`benchmark.py`, and `am3d/recipes/executor.py`. The documented UI labels are
from source, including **Create with AI...**, **AI Settings…**, **Generate…**,
**Send request**, **Open in Editor**, **System credential store**, and
**Session-only key (memory)**.

Phase evidence reviewed includes:

- Phases 1–3 provider, credential, prompt, policy and worker evidence;
- Phase 4 requested-export fix and fresh independent contract review;
- Phase 5 orchestration bounds, worker and publication evidence;
- Phase 6 profile-edit correction, UI implementation, deferred-close fix and
  independent lifecycle review;
- Phase 7 history/refinement source and owner-run UI evidence;
- Phase 7 bounded independent local preservation/refinement review and root
  integration decision;
- Phase 8 benchmark implementation, P1 correction and focused verification;
- Phase 10 initial tooling preparation, strict source follow-up, and latest
  tooling/credential follow-up.

The docs record the implementation/source facts without promoting them to
live-provider, artistic-quality, frozen-package, target-platform or release
acceptance. Current host evidence is Windows 10 IoT Enterprise LTSC build
19044, x86-64, using Qt offscreen tests. No live model, key, network call,
provider spend, human asset score, physical desktop/GPU, Windows 11, native
Mint build, frozen acceptance, publication or release was performed here.

## Reconciled claims

The current source contains a brief/provider UI while historical accepted
bundles remain distinct and do not qualify it. The docs state that a model is
required explicitly, the configured endpoint host is allowlisted, request
transmission requires the visible **Send request** action, keys use an
explicit OS credential store or memory-only session store, and keys are not
saved in application preferences. New-generation data disclosure, local
record storage, and the distinction between local call/time bounds and
unknown input-token/dollar cost are documented.

The modelling scope now describes recipe-generated lathe/extrude source
profile control-point edits and the tested undo/redo/save/reopen path. It does
not claim a general patch control-net editor; baked primitives support
transforms and materials, while unrelated guide-spline edits do not reshape
their surfaces. The recipe CLI remains documented as a declarative, offline
alternative and not an operating-system sandbox. OBJ and GLB remain static
pose outputs; `.am3d` format-2 provenance is optional and the generation
sidecar remains authoritative.

Benchmark tooling documentation names the frozen 30-case release and separate
8-case discovery fixtures, fixed failure denominator, offline `NONQUALIFYING`
behavior, live/two-reviewer thresholds, artifact evidence required for
scoring, and the limitations on cost and HTTP-attempt reporting. No live
benchmark result or human score is claimed.

Historical Mint and MX identities remain separate. Windows 11 and Mint 22.3
are the selected V1 targets and both remain unqualified. The Windows 10
offscreen/source baseline, Phase 10 initial 10-pass/4-skip preparation, later
strict-source 11-pass/3-symlink-skip tooling snapshot, and latest focused
30-pass/4-skip tooling/credential follow-up are described as source checks,
not native/frozen support. The latest follow-up also records two credential
notice metadata checks and a separate Windows source-mode system-credential
store sentinel CRUD/cleanup probe; no provider or network was used. These are
source checks and do not identify or qualify a frozen candidate. Candidate
build, lock, frozen-check, and acceptance results belong in companion artifact
reports. Earlier fixed-source and tooling receipts retain their own
version/digest snapshots; they do not identify the current `1.0.0.dev1` source.
The current source hash snapshot is documentation identity, not test identity;
the UI owner has not reported the final stable test source.

Phase 7 owner evidence is
[`ui-history-evidence.md`](../phase-7/ui-history-evidence.md). It records five
history UI tests, six combined measured-refinement/history tests, and a
58-test lifecycle run, all on the Windows 10 offscreen source path. The
independent reviewer separately passed the five history tests in 20.86
seconds, the single measured four-change refinement node in 74.02 seconds,
and a Unicode path probe whose preview path was 286 characters. The root
accepted this bounded local Phase 7 gate. The review did not rerun the owner’s
58-test lifecycle suite or explain Phase 6's earlier timeout, and it does not
cover external review or final integrated regression. See
[`INDEPENDENT_REVIEW.md`](../phase-7/INDEPENDENT_REVIEW.md) and
[`ROOT_ACCEPTANCE.md`](../phase-7/ROOT_ACCEPTANCE.md).

## Checks and evidence limits

The final documentation check covers the 11 assigned global documents and
this Phase 9 implementation record; its identity JSON is checked separately.
Relative links and whitespace checks pass, and scoped `git diff --check`
reports only Git's LF-to-CRLF advisories for edited text files. These are
document checks, not application tests. No application test suite was run for
this documentation task.

Phase 7 source controls and behavior are documented from source: **Refresh
History**, **Restore Selected in Editor**, **Delete Selected**, **Refine
Selected…**, and the divergence choices **Save manual copy**, **Refine
original generation**, and **Cancel**. The docs preserve the owner-evidence
status separately from the passed bounded local independent review. The
Phase 7 gate is locally accepted; external review, full integrated regression
and overall V1 decision remain open. A scoped relative-link audit and
`git diff --check` pass are recorded after each documentation update. The
exact source at this check, review evidence hashes, current owned-document
hashes, and the preserved original Phase 9 documentation/source snapshot are
hashes, Phase 10 receipt hashes, and preserved earlier Phase 9
documentation/source snapshots are in [`SOURCE_IDENTITY.json`](SOURCE_IDENTITY.json);
the identity record does not hash itself. Version declarations are source
metadata only. Exact candidate identity and checks are tied to companion build
provenance, input, checksum, and acceptance reports.
