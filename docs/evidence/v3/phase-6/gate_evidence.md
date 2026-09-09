# Phase 6 gate — status

Required by `docs/V3_FUNCTIONAL_IMPLEMENTATION_PLAN.md`: "Gate: four-agent
Luna review, fixes, rechecks, evidence; then Phase 7."

## Status: PASS (substitute Haiku swarm, by explicit user direction)

No "Luna" reviewer agent type is available in this environment. Phase 5's
gate substituted four Haiku review agents for Luna, explicitly noted as done
"at explicit user direction" (see `docs/evidence/v3/phase-5/gate_evidence.md`).
The user was asked directly whether to leave this gate pending or substitute
a reviewer swarm for Phase 6, and explicitly chose the Haiku substitute
(matching the Phase 5 precedent) over leaving it pending.

### Swarm composition and lanes

Four independent `general-purpose` agents, model `claude-haiku-4-5`, run in
parallel with no visibility into each other's work, each covering a distinct
slice of the full Phase 6 diff (`git diff df6b224..47324d1`):

| Lane | Focus | Verdict |
|------|-------|---------|
| A | Bullets 1–2: build-path resolution, dependency pinning, version/metadata reconciliation | ✅ No findings |
| B | Bullet 3: packaged headless recipe CLI (am3d-recipe.exe) — CLI contract fidelity, packaging | ✅ No findings |
| C | Bullet 4: packaged GUI smoke mode — argument parsing, cleanup, Windows path/quoting, timeout/failure detection | ✅ No findings |
| D | Bullet 5 + overall acceptance: release ZIP/checksum, relocated-path verification, and honesty of the evidence docs themselves (no overclaiming, no silently swallowed errors) | ✅ No findings |

All four lanes reported no confirmed bugs. Lane D specifically checked the
evidence documents in this directory for overclaiming (e.g. inferring a
clean-VM pass from offscreen testing, or claiming the Luna gate itself
passed) and found none — the "Limitations" sections were confirmed accurate
as written.

**Phase 6 gate: ✅ PASS** — substitute four-agent Haiku swarm, all four lanes
clean, no fixes required as a result of this final gate pass. (Two defects
were found and fixed earlier, during this session's own implementation
review before the gate swarm ran — see "Defects found and fixed" in
`bullet4_smoke_mode.md` — and are reflected in the code the swarm reviewed.)

## What is ready for review

- Bullet 4 (packaged GUI smoke mode): `bullet4_smoke_mode.md`
- Bullet 5 (release ZIP/checksum/relocated verification): `bullet5_release_zip.md`
- Bullets 1-3 (build-path resolution, version reconciliation, packaged recipe
  CLI): already committed at `dded94c`, `a56a865`, `6571b35` respectively; no
  separate evidence file exists for these yet in this directory.
- Full source suite: 484 passed, 4 warnings (`bullet4_smoke_mode.md` for the
  command and full context).
- Two source-level defects were found and fixed in this pass (see
  "Defects found and fixed" in `bullet4_smoke_mode.md`):
  1. `main()`'s unconditional `QApplication(raw_argv)` crashed on any second
     in-process construction.
  2. A bare `--out` with no path value raised an uncaught `IndexError`
     before any diagnostic could be printed.
  Both are covered by new regression tests in `am3d/ui/test_smoke.py`.

## What is explicitly not covered (recorded, not inferred as passing)

These remain open regardless of the gate swarm's PASS verdict — the gate
swarm reviewed code correctness, not environment coverage:

- No clean Windows profile/VM without Python was available to validate
  dependency bundling independent of the development machine's own Python
  installation.
- No real GPU-backed render was exercised in the packaged smoke run; both
  the in-place and relocated verifications used
  `QT_QPA_PLATFORM=offscreen` plus the software rasterizer path.
- The review ran on a substitute Haiku swarm, not an actual Luna-capable
  reviewer, per the explicit user direction recorded above.

## Next step

Phase 6's gate has passed on the terms above. Phase 7 (external-agent trial)
may begin, carrying forward the clean-VM and GPU-render gaps as known,
recorded limitations rather than as silently-assumed passes.
