# Implementation roadmap: AI-generated 3D assets

Updated: 2026-09-28
Git head: `f35e4e5`; the candidate also includes the uncommitted build inputs
enumerated in `release/BUILD_INPUTS-linux.json`.

## Candidate scope decision (2026-09-28)

The active deliverable is a **Linux Mint 22.3 x86-64 preview candidate
validated on this workstation**. It is not a claim of general Linux support,
MX Linux support, Windows support, native compositor coverage, DPI coverage,
or hardware-GPU coverage. The preview milestone is complete when the current
source bundle and the end-to-end agent-to-editor workflow pass the checks
below on this host and two independent reviewers accept the final candidate.

MX Linux 25.2 and Windows qualification move to follow-on release work. The
full cross-platform ship criteria remain in
`docs/DESKTOP_RELEASE_PLAN.md`; this preview milestone does not waive or
replace them. The workstation is Linux Mint 22.3 (Zena), x86-64, kernel
`6.8.0-139-generic`.

## Product outcome

An external AI agent receives an asset brief and the shipped recipe contract,
produces a JSON recipe, uses structured errors to correct it, then creates an
editable `.am3d` project and useful renders/exports. A person can open that
project in the desktop editor and inspect or continue editing it. The default
workflow is code-first: generate from the brief, then use the editor to review
or refine the result.

The application does not currently host a language model or provide its own
prompt box. The external agent drives the versioned recipe interface through
the CLI. Keep that boundary explicit; add a provider or MCP integration only
when a concrete host requires one. The visual direction is Blender's dense
workbench with early-2000s desktop character.

## Definition of done

- A tool-enabled, context-limited agent receives only the shipped guide,
  schema, examples and brief; it invokes the CLI itself, recovers from an
  actionable recipe rejection, and needs no person to repair its JSON.
- A successful recipe produces a manifest, an editable `.am3d` project and
  the requested supported previews/exports. Static OBJ/GLB output is clearly
  distinguished from animated project data.
- The generated project opens in the desktop editor, retains its meaningful
  scene/material/rig/action state, and can be saved again.
- The Linux x86-64 bundle is rebuilt from the final preview source state and
  passes its full source suite, packaged CLI checks, GUI smoke, relocation,
  and payload checks on Linux Mint 22.3. GUI acceptance is explicitly Qt
  offscreen/software-path evidence, not native desktop interaction or
  hardware-GPU evidence.
- Docs identify this as a Mint-hosted preview candidate and separate later
  MX/Windows qualification from this milestone. The product remains honest
  about the external-agent integration boundary and unverified platforms.

## Current state at the start of this run

- The schema v1, external-agent guide, JSON examples, machine-readable CLI,
  structured error records, validation-only mode, artifact manifest, and
  `.am3d`/OBJ/GLB/sheet outputs already exist.
- The historical Phase 7 trial exercised two fresh same-family substitute
  agents (lantern and sentinel); both corrected a real rejection using the
  CLI output. It was not an independent-vendor trial. See
  `docs/evidence/v3/phase-7/trial/TRIAL_REPORT.md`.
- Desktop release findings through Phase E have been implemented and recorded
  in `docs/evidence/desktop-release/FINDING_LEDGER.md`. Historical MX 25.2
  evidence passes for the older artifact built at `b96c922`; it does not
  certify the current source tree or UI restyle.
- The previous current-source Mint candidate passed package checks, but its
  staged documentation must be rebuilt after this scope update.
- `docs/evidence/desktop-release/phase-f/` contains an unexecuted Windows
  build-acceptance harness. No Windows host is available in this workspace.
- Entry-point docs will describe the external-agent boundary, Mint preview
  evidence, and later MX/Windows qualification. Two independent Luna review
  rounds previously found and resolved plan and documentation gaps; see
  `docs/evidence/implementation-roadmap/phase-0-review.md`.

## Phases and review gates

Each phase ends with a concrete artifact and an acceptance check. Before
moving to the next phase, two Luna agents review the completed phase
independently. They must give file/line evidence and distinguish reproduced
defects from concerns. Resolve confirmed issues, record disproven concerns,
and rerun the affected checks. Do not merge the two reviews into a single
shared-context review.

The requested `xhigh` effort is not supported by the available Luna sub-agent
runtime. Use Luna's highest available effort (`max`) for both reviewers and
record that setting with each review.

### Phase 0 — Establish one current plan and truthful product context

**Status: complete.**

- Keep this roadmap as the active implementation plan.
- Make `PROGRESS.md`, `README.md`, the capability matrix, platform docs and
  plan headers agree on the external-agent workflow, preview scope, and
  follow-on platform qualification. Point superseded plans to this roadmap while
  preserving historical evidence.
- Preserve the user's existing uncommitted interface work; do not overwrite
  or reset it.

**Gate:** product outcome, preview scope, and plan ownership are consistent
across the entry-point docs; the roadmap passes two independent Luna reviews.
Evidence: `docs/evidence/implementation-roadmap/phase-0-review.md`.

### Phase 1 — Verify the external-agent contract on the current source

**Status: complete — fresh-agent run passed; both independent Luna reviewers passed.**

- Check schema, guide, examples, source CLI, error records and output
  manifest for drift. Reconcile guide text against the schema, executor and
  exporter behavior; include patterned-texture outputs. Defer packaged CLI
  invocation to Phase 3, which builds the first current-source bundle.
- Give a fresh, tool-enabled agent only the shipped guide/schema/examples and
  an asset brief. The agent itself must invoke a CLI, encounter one rejected
  recipe, use the returned error record to correct its own recipe, then rerun
  it successfully. Do not count the two Luna reviewers as this agent trial.
- Confirm outputs remain under the chosen output directory and include the
  native project plus the requested preview/export files.

**Gate:** the agent itself completes the correction loop; final recipe also
passes validate-only; validation/rejection is machine-readable; a textured
rigged result and its output files match the manifest and remain in-root.
The requested action must visibly deform its intended geometry across
sampled frames, confirmed from evaluated scene data and the animation sheet.
The Phase 1 agent trial used the source CLI; Phase 3 later verified packaged
CLI acceptance. Label this a same-family agent trial unless a separate
vendor/model is actually used.

### Phase 2 — Verify the editor handoff and current interface

**Status: complete in Qt offscreen mode; two independent Luna reviews passed. Native compositor check remains external.**

- Open a generated `.am3d` project through the real desktop MainWindow path;
  confirm object, material, rig/action data and a rendered preview survive.
- In the editor, make a concrete change to the generated project, undo and
  redo it, save, and reopen; confirm the intended state survives.
- Confirm the current Blender-meets-early-2000s UI remains usable at the
  documented target window sizes.
- Keep the recipe CLI as the fast default. The editor is the integrated
  inspect/refine/animate step, not a required manual modeling stage.

**Gate:** a visible generated-asset edit is correctly removed by undo and
restored by redo, then survives save/reopen; both existing preview sizes
remain legible; current-source MainWindow checks pass. Evidence was captured
with Qt offscreen because this host lacks the xcb cursor runtime library, so
native compositor interaction remains part of the external target acceptance.
See `docs/evidence/implementation-roadmap/phase-2/PHASE2_REPORT.md` and
`docs/evidence/implementation-roadmap/phase-2/PHASE2_REVIEW.md`.

### Phase 3 — Rebuild and accept the Linux Mint preview candidate

**Status: complete — final-scope candidate passed two fresh independent Luna reviews.** The current-source candidate contains the updated staged docs and passed the source and packaged checks on Linux Mint 22.3.

- Build from the current source in the isolated pinned Linux environment.
- Run the full current-source suite, packaged smoke workflow, recipe CLI
  success/failure paths, relocation and payload-hygiene checks. Capture exact
  source identity, including a deterministic digest over tracked and
  untracked build inputs, dependency provenance, checksum and logs.
- Record the host as Linux Mint 22.3 (Zena), x86-64, kernel
  `6.8.0-139-generic`. GUI acceptance uses Qt offscreen mode/software paths.
  Do not infer native compositor, DPI, physical GPU, MX, or broad Linux
  support from these checks.

**Gate:** one identifiable current-source preview archive contains the
updated staged docs, passes the full suite and packaged checks on this build
host, and has matching provenance. Two independent fresh Luna reviews pass
the candidate identity, evidence, product-scope claims, and limitations.
Evidence: `docs/evidence/implementation-roadmap/phase-3/PHASE3_REPORT.md`;
the earlier candidate review remains in `PHASE3_REVIEW.md`, and the final
candidate review is recorded in
`docs/evidence/implementation-roadmap/CANDIDATE_REVIEW.md`.

### Phase 4 — MX Linux qualification (follow-on release work)

**Status: deferred; not a gate for the Linux Mint preview candidate.**

- Run the current-source candidate through native Wayland and xcb/XWayland,
  actual GPU and software rendering, real interaction, and 100/150/200% scale
  checks on the documented machine.
- Record exact candidate checksum, source commit, screenshots and logs.

**Gate:** the candidate tested is byte-identical to the artifact named in its
provenance and the target-specific matrix passes. Until then, current-source
MX support remains unverified.

### Phase 5 — Windows qualification (follow-on release work)

**Status: local CI preparation complete and passed two independent Luna reviews; workflow execution and Windows host gates remain pending.**

- **Stage 1 — Windows CI:** run `.github/workflows/windows.yml` on a native
  `windows-latest` runner for the isolated build, full suite, frozen CLI/GUI
  smoke and Phase F noninteractive checks. The workflow is prepared but has
  not run from this workspace. Its first run captures a Windows dependency
  lock and preserves build/acceptance logs; inspect and commit that lock
  before later runs consume it.
  This can verify packaging, recipe results, path handling and relocation; it
  cannot verify interactive usability, DPI scaling, or a hardware GPU.
- **Stage 2 — clean Windows VM:** run the artifact with no Python installed;
  first select and document the supported minimum Windows release, then test
  that minimum and the current supported Windows release. Verify GUI
  interaction, read-only install, OneDrive/user-data paths, and scaling. This
  still cannot close the real-GPU row.
- **Stage 3 — real Windows GPU host:** verify `GPU (moderngl)`, interactive
  workflows, scale captures and GPU/software image parity.
- At each stage, capture the Windows dependency lock where possible and run
  the matching Phase F frozen-acceptance and independent-export checks.
- Until that happens, ship no Windows artifact and keep Windows marked
  unverified in README, quick start and platform docs.
- Publish the final workflow, generated sample, Linux artifact/checksum and
  exact remaining Windows/external-vendor limitations.

**Gate:** Windows claims become supported only after native artifact and
acceptance evidence exist. This work is outside the Mint preview milestone.

## Preview milestone result

The preview handoff consists of the rebuilt Linux Mint 22.3 x86-64 archive,
its checksum and provenance, the agent recipe trial and packaged acceptance
evidence, two independent final Luna reviews, and documentation that names
the exact verified scope. MX Linux and Windows stay visible as future product
qualification, not as work required to complete this candidate.

## Execution ledger

| Phase | State | Evidence / next action |
| --- | --- | --- |
| 0 — Context and plan | Complete | Two independent Luna reviewers confirmed findings resolved; see Phase 0 review evidence |
| 1 — Agent contract | Complete | Two independent Luna reviewers passed; see `docs/evidence/implementation-roadmap/phase-1/PHASE1_REVIEW.md` |
| 2 — Editor handoff | Complete; two independent Luna reviewers passed | Offscreen edit/undo/redo/save/reopen and both preview sizes captured; native compositor check remains external |
| 3 — Linux Mint preview candidate | Complete; two fresh independent Luna reviews passed | Final candidate passed 738 tests, 14-step GUI smoke, packaged CLI success/structured failure, plugin/payload/relocation checks; identity and review evidence are recorded in Phase 3 |
| 4 — MX target qualification | Deferred; not a preview gate | Requires the documented MX 25.2 reference machine before making an MX support claim |
| 5 — Windows qualification | CI preparation complete; two independent Luna reviews passed; workflow not run; deferred from preview | Run the workflow on GitHub Actions, then perform clean VM and real-GPU acceptance before making a Windows support claim; see `phase-5/PHASE5_REVIEW.md` and `phase-f/` |
