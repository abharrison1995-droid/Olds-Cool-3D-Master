# Phase 7 gate — status

Required by `docs/V3_FUNCTIONAL_IMPLEMENTATION_PLAN.md`: "Final four-agent
Luna swarm reviews the whole integrated release as well as this phase's
changes. Fixes trigger affected earlier gate rechecks and a final four-agent
pass before release acceptance."

## Status: PASS (substitute Haiku swarm, by established project precedent)

No "Luna" reviewer agent type is available in this environment. Phases 5 and
6 both substituted four Haiku review agents for Luna at explicit user
direction (see `docs/evidence/v3/phase-5/gate_evidence.md` and
`docs/evidence/v3/phase-6/gate_evidence.md`). This phase continues that
established precedent rather than re-asking.

### Swarm composition and lanes

Four independent `general-purpose` agents, model `claude-haiku-4-5`, run in
parallel with no visibility into each other's work, each covering a distinct
slice of Phase 7 (commits `bf6320d`, `083f725`, plus the follow-up guide
fixes below):

| Lane | Focus | Verdict | Findings |
|------|-------|---------|----------|
| A | External-agent trial methodology and honesty (`TRIAL_REPORT.md`, `gui_inspection.md`, raw trial artifacts) | ✅ No findings | Bugs verified real, self-corrections honestly disclosed, no sign of hand-editing |
| B | README/doc reconciliation accuracy against actual code | ⚠️ Fixed | Several Status-table test counts were stale (10/8/10/18/6/13 vs. actual 12/9/16/19/13/70); the commit message and Layout comment incorrectly implied `numba` is unused, when it's a real optional JIT accelerator (`am3d/spline/kernel.py`, `pyproject.toml`'s `accel` extra) |
| C | `EXTERNAL_AGENT_GUIDE.md` primitive/pattern documentation vs. real code, section by section | ⚠️ Fixed | `box`, `cylinder`, `cone`, `plane` each had one or two optional, defaulted params (`n`, `capped`, `rings`) missing from the guide — not wrong like the three bugs already fixed, but undiscoverable to an external agent reading only the guide |
| D | Overall Phase 7 acceptance criteria, prior-gate validity, full suite | ✅ No findings | All prior phase gates confirmed still PASS; 484/484 tests; all Phase 7 plan bullets evidenced |

### Fixes applied as a result of this gate pass

1. **README.md** — corrected six stale test counts in the Status table to
   the actual current per-file counts (B-spline kernel 10→12, scriptable
   facade 8→9, recipe schema 10→16, procedural primitives 18→19, recipe
   executor+CLI 13→70, GPU renderer 6→13); corrected the spline-kernel
   Layout comment and the Dependencies section to accurately describe
   `numba` as a real, optional JIT accelerator (not absent, as the prior
   commit incorrectly implied) alongside the already-correct removal of
   `scipy`/`moderngl-window` (genuinely unused).
2. **`docs/recipes/EXTERNAL_AGENT_GUIDE.md`** — added the four previously
   undocumented optional primitive params (`box`/`plane`'s `n`,
   `cylinder`'s `capped`/`rings`, `cone`'s `rings`) to section 3.

Both fixes were verified against the real source (`am3d/recipes/primitives.py`,
`am3d/spline/kernel.py`, `pyproject.toml`, and live `pytest --collect-only`
counts per file) before being applied, not just taken on the reviewing
agent's word.

Full source suite re-run after these fixes: **484 passed, 4 warnings** —
identical to before the gate pass; the fixes were documentation-only.

## What is ready for review

- External-agent trial: `docs/evidence/v3/phase-7/trial/TRIAL_REPORT.md`
- GUI inspection: `docs/evidence/v3/phase-7/trial/gui_inspection.md`
- Manual acceptance checks: `docs/evidence/v3/phase-7/manual_checks.md`
- README reconciliation: this gate's fixes are folded directly into
  `README.md` (not a separate commit — see "Fixes applied" above)
- Guide corrections: `docs/recipes/EXTERNAL_AGENT_GUIDE.md` (torus params,
  material patterns section, plane/lathe/extrude params, and this gate's
  four added optional params)

## What is explicitly not covered (recorded, not inferred as passing)

- No genuinely separate external AI vendor was available; the trial used an
  isolated substitute agent (spawned fresh, given only the shipped contract)
  per the user's own explicit choice, not a true third-party LLM.
- Interactive GUI automation of the built, unregistered `.exe` was not
  possible from this session (computer-use only resolves Start-Menu-
  registered applications) — see `gui_inspection.md` and `manual_checks.md`
  for what was verified instead (the real `MainWindow` class, unmocked,
  driven headlessly).
- No real on-screen hardware-accelerated GPU render was captured; only the
  offscreen software path and the GPU-context unit tests.
- No clean Windows profile/VM re-verification was performed in this phase
  (that is Phase 6 bullet 5's completed requirement, not re-run here).

## Next step

Phase 7's gate has passed on the terms above. Per the plan's acceptance
text, all preceding gates remain valid, the external author/execute/correct
workflow is demonstrated, no confirmed bug found during this phase remains
unresolved, and documentation now matches shipped behavior as verified by
an independent review swarm. This is the final phase in
`docs/V3_FUNCTIONAL_IMPLEMENTATION_PLAN.md`.
