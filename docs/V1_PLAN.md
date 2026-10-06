# 3D MASTER:2005 — V1 plan (rev. 3)

6 Oct 2026 · Alex Harrison · baseline `3f6f7f0`

This is the approved active V1 plan. It supersedes the old V1 draft and the
roadmap scheduling in archived V2/V3, desktop-release, and implementation
roadmap documents. Their evidence remains historical and only applies to its
named source and artifact. This plan is deliberately compact; supporting
limits, benchmark candidates, and provenance requirements live in
[`V1_SECURITY_LIMITS.md`](V1_SECURITY_LIMITS.md),
[`V1_BENCHMARK.md`](V1_BENCHMARK.md), and
[`V1_PROVENANCE.md`](V1_PROVENANCE.md).

## Basis and changes from rev. 2

The architecture is unchanged. Source checks confirmed three defects: recipe
execution discards primitive patch degrees (so patches default to `(3,3)` and
can differ from GUI primitives); atlas dimensions are read from nonexistent
NumPy array attributes and therefore default to 256; and graph `mix` blends a
node with itself. V1 removes `mix` from model-visible capabilities while
retaining backward-compatible handling.

| Decision | V1 direction |
| --- | --- |
| Recipe hardening before AI | Keep; registry first, then registry-driven validation. |
| Names, paths, validation-only, full-path errors | Keep strict AI names, one filename sanitizer, root re-checks, typed values and collected errors. |
| CI | Move fast pinned Linux CI to M0; keep it green at every checkpoint. |
| Deterministic success checks | Move before the orchestrator so worker, preview, and bake-off share a definition of success. |
| Model bake-off | Run after repair works; measure repair counts. |
| Capability context | One stable compact cached contract; revisit dynamic context only if measured cost warrants it. |
| Recipe repair format | Defer bespoke deltas; use full recipe first, then a strict RFC 6902 subset only if measured token cost warrants it. |
| Transforms | Add host-compiled `{translate, rotate_deg, scale}` shorthand in M1; add arrays/mirror only on benchmark evidence. |
| Lathe/extrude provenance | Move to M5 editability work; fix patch degrees in M1. |
| Reviews | Independent review for M1 security, worker, credentials, and release; self-check plus CI for docs. |
| Windows | Use GitHub Windows runner from M2; prepare physical Windows 11 PC at M5 for M6. |
| Handoffs | Split the initial handoff into three reviewable changes; one review round and one verification round per milestone. |

## Invariants

- `recipe-v1` and host-compiled shorthand are the only model-controlled execution inputs. No model code, commands, imports, or paths.
- Spline patches are authoritative; meshes are derived. Keep one scene model.
- Provider output is untrusted; deterministic host checks decide success.
- Background work never replaces the current or dirty document. Snapshots are immutable; the editor opens a writable copy.
- Credentials never reach the worker, project, logs, or run records.
- Every run has attempt, time, memory, and output bounds.
- Manual and CLI workflows continue to work offline.
- Historical evidence never certifies changed source.

## Milestones

Each milestone ends with a pushed, tagged checkpoint and green fast CI. Time
estimates are rough and assume Alex plus coding agents.

### M0 — Repository and context (½–1 day; handoff H1)

- Inventory branches, unpushed commits, and stashes; push or record each; delete nothing.
- Add `AGENTS.md` (≤80 lines) and two-line `CLAUDE.md`; add `docs/agent/CURRENT_PHASE.md` (≤800 tokens, updated each handoff). Keep orientation to about 2–4k tokens; fold a context index into `AGENTS.md` unless it grows beyond 20 lines.
- Commit this plan as `docs/V1_PLAN.md`; move the old draft's limits, benchmark, and provenance detail into the three companion docs above. Archive superseded V1/V2/V3, desktop-release, and roadmap plans under `docs/archive/`.
- Rewrite `PROGRESS.md` as a table (≤1.5 KB). Keep platform caveats only in `docs/SUPPORTED_PLATFORMS.md` and design authority in `DESIGN.md`; fix the `am3d/__init__.py` docstring.
- Add pinned fast Linux CI: offscreen pytest, on pushes and pull requests. Check real Windows workflow runs and action versions.
- Commit the build-input manifest needed to reproduce a candidate. Reconcile package versions and adopt checkpoint tags, e.g. `v0.3.0-dev.N`.
- Open a GitHub V1 milestone with one issue for each M1–M6 milestone.

**Exit:** orientation works from `AGENTS.md` + `CURRENT_PHASE.md`; Linux fast CI is green.

### M1 — Model-safe recipe contract (1–2 weeks)

**M1a / H2 — Registry and validation.** Add `am3d/recipes/capabilities.py`, with entries for every primitive, pattern, graph node, action kind, export format, and channel property. Each entry records params, types, defaults, ranges, enums, resource-cost hints, and a one-line model description. Check registry names/defaults against builder signatures and generate or verify guide tables from it. Drive one-pass validation from the registry: unknown/mistyped params; enums for `channel.property` (`translate|rotate|scale|weight`) and `interp`; pattern/node names; sheet params; full error paths, expected/received values, and valid keys. Enforce string names and AI regex `^[A-Za-z0-9_][A-Za-z0-9_ .-]{0,63}$`; use one sanitizer for derived filenames and re-check final paths against output root. `--validate-only` performs validation, path resolution, and resource estimation without building. Compile TRS shorthand to the canonical matrix on the host.

**M1b / H3 — Defects and resource bounds.** Estimate ceilings before allocation (see `V1_SECURITY_LIMITS.md`); convert `MemoryError` to a useful `resource_exhausted` error. An assigned action that moves no bound geometry warns in CLI and errors in AI mode. Preserve primitive `degree_u/degree_v` through recipe/save/reopen/tessellation, with GUI parity. Read atlas dimensions from array shape, write atlases only for exports that use them, and use unique staging names. Fix or remove the wrong `idx` in the bone-parent error. Remove `mix` from model-visible capabilities, keep legacy handling, and fix the capability matrix claim about recipe graphs. Add compact CLI output (`ok`, relative artifacts, warnings, error records; no duplicate messages or machine paths). Trim `EXTERNAL_AGENT_GUIDE.md` to contract and registry-backed tables; derive a compact provider schema. Add one regression fixture per reproduced defect.

**Exit:** independent M1 review passes. Every review probe fails in `--validate-only` with a precise path, or succeeds and does what it says.

### M2 — Local generation without a model (1–2 weeks)

- Add `am3d/ai/policy.py`: strict AI profile layered on M1 validation; recipe ≤128 KiB, no texture file paths, host-chosen outputs.
- Launch a terminable worker from a fixed internal frozen-app entry point. Give it only recipe, policy snapshot, and private output root.
- Add `am3d/ai/checks.py`: reopen; finite geometry/bounds; nonblank whole-scene preview (always produced); animation sampled at 0/25/50/75%; independent export parsing; path confinement.
- Write immutable `generations/<run-id>/` with `record.json`, `recipe.json`, `preview.png`, `project.am3d`, `checks.json`, and exports.
- Desktop “Generate from recipe…” flow: recipe picker/paste → policy → worker → checks → result → guarded “Open in Editor” using a writable copy and dirty-document guard.
- Run worker spawn/cancel tests on Windows CI and Linux.

**Exit:** end-to-end local pipeline with cancellation on both CI platforms; independent worker-boundary review passes.

### M3 — AI loop (1–2 weeks)

- One `Provider` interface with three adapter kinds. Agent-CLI is default: `codex`, `claude`, or `opencode` noninteractive subprocess, empty temp workspace, tools disabled or read-only sandbox, prompt on stdin and JSON on stdout. Verify exact flags, JSON shape, and subscription terms before supporting each CLI. CLI uses its own login; the app stores no CLI secrets.
- Local adapter uses the same OpenAI-compatible HTTP code against llama.cpp `llama-server`, Ollama, or LM Studio on localhost, with JSON-schema/grammar decoding. Optional API adapter is off by default; store keys in Windows Credential Manager or Secret Service, bind to origin, enforce hard spend caps.
- Treat all output as untrusted; extract strict JSON and apply all M1/M2 checks. A CLI that tries tools has no useful workspace; recipes still execute only through the worker.
- Per-provider deadline, attempt, and context profiles. Local deadline about 20 minutes with live stages; cloud deadline 10 minutes. Log usage per call: tokens, latency, quota/rate errors; use `null` when unknown, never zero.
- Prompt returns `{intent, assumptions, approximations, required_components, recipe}`. Keep fixed instructions, compact contract, and two examples in a stable cached prefix; brief last.
- Bound orchestrator to 1 generation, up to 2 validation repairs, 1 execution/check repair, 1 transport retry, and profile deadline. Use real stage names; repairs receive current recipe plus all error records. Never retry auth failure, refusal, quota exhaustion, or policy denial.
- Offline CI uses fake provider and fake CLI (canned JSON, hang, nonzero exit), plus API credential-sentinel leak test.
- Compare 2–3 current local candidates with llama.cpp and grammar-constrained JSON on the RTX 3060 Ti 8 GB / 48 GB DDR4 setup: a roughly 30B-total/3B-active 4-bit MoE with RAM offload, or dense 8–14B at 4–5-bit. Choose by brief pass rate, not speed alone. GLM 3.8 was not found; Z.ai's current line is GLM-5.x including Flash.
- Bake-off: 20 runs = 5 discovery briefs × 4 providers, one run each: Codex Luna xhigh, Claude Code Sonnet 5.5 low, opencode/DeepSeek v4.1 medium or high, and best local model. Spread over 2–3 days for subscription quotas.

**Exit:** select default cloud and local model from measured first-pass validity, final check success, time, and recorded quota use. CLI sandbox passes independent review.

### M4 — Baseline and evidence-driven contract (about 1 week)

- Development baseline on about 15 benchmark-style briefs with chosen model.
- Spike deterministic rig-frame rebasing for transformed skinned geometry. Ship only if translation/rotation/scale/parented/save-reopen/export tests pass; otherwise reject before execution with repair hint.
- Add array/mirror host compilers only if baseline shows repeated-part or symmetry failures.
- Add JSON Patch repair only if logs show repairs cost over about 30% of run tokens.
- Freeze release benchmark, rubric, and thresholds from baseline. `27/30` remains an aspiration until then; see `V1_BENCHMARK.md`.

### M5 — Product workflow (2–3 weeks)

At M5 start, begin the Windows 11 PC setup (clean install, current GPU driver,
no Python, standard user); it is needed in M6, about 2–3 weeks later.

- Home: New/Open/Create with AI. AI workspace leads with brief + Generate; advanced fields collapsed. Result shows stage/time, Cancel, preview, assumptions, approximations, warnings, files, and guarded Open in Editor. No chat feed.
- Show provider settings/privacy notice before first cloud call.
- Add history list and simple refinement: child run from stored parent recipe plus change request; parent bytes stay identical. Give a plain warning when the editor copy has manual edits.
- Add lathe/extrude profile provenance so recipe-built profiles regenerate when edited, as GUI ones do.
- Usability gate: 1280×820, 100/150/200% scaling, full keyboard path.

V1 includes Create with AI, Open in Editor, history, and simple refinement. V1.1
holds side-by-side compare, change-summary diffs, three-way divergence dialog,
and refinement of projects not generated by the app.

### M6 — Qualification and release (1–2 weeks; hardware dependent)

- Two complete frozen-benchmark runs; failures stay in denominator.
- Test exact RC artifacts on Windows 11 and Mint 22.3: clean machine/no Python; worker; credentials including locked/absent Secret Service; generation/refinement/exports; Unicode and space paths; scaling; software and real GPU.
- Update user docs once from RC; tag, hash, record provenance, and publish only artifacts that passed their gate.
- Animated GLB is the first V1.x item.
- Run budget: two full default-cloud frozen runs (60 generations) and one default-local run (30). Other subscriptions repeat only the five discovery briefs; spread runs over days to respect quotas.

## Order and review

Critical path: `M0 → M1a → M1b → M2 → M3 → M4 → M5 → M6`. M5 UI work may
start after M2's result panel exists, in parallel with M3. Until the physical
PC is ready, use the GitHub Windows runner for builds and worker tests.

For each handoff: implement → focused tests → full suite → risk-sized review
→ classify findings (defect, material risk, suggestion, false positive) → fix
→ verify → push checkpoint. One review and one verification round per
milestone; reopen only when changed evidence invalidates the review. Reviewers
get the diff, acceptance list, and test output, not the whole docs tree.

## Recorded decisions (6 Oct 2026)

1. Subscriptions first; API optional and disabled by default. If enabled, the host enforces before every call: `$0.10` and 40k tokens per run, `$1` per day, `$5` per month. Stop on cap. Subscription quota is the real constraint; budget benchmarks in runs.
2. Physical Windows 11 is needed only in M6. Start setup at M5; until then use GitHub's `windows-latest` runner.
3. V1 cut line is the product scope above; compare UI, three-way divergence, and refining nongenerated projects are V1.1.
4. Every model output stays inside the bounded recipe pipeline; manual and CLI paths remain usable offline.
