# Phase 1 — External-agent recipe contract

Date: 2026-09-27; status updated 2026-09-28.
Status: implementation evidence and both-agent review passed.
Source base: `f35e4e5` plus the existing uncommitted workspace changes.
Trial agent: fresh tool-enabled `gpt-6-luna` at its highest supported effort (`max`); Luna `xhigh` is not available in this sub-agent runtime. The agent read only the external-agent guide, schema, and two shipped recipe examples, then received the asset brief.

## Result

Attempt 1 failed functional acceptance: its recipe named a `walk` action but the leg objects did not bind to the rig. Its initial review findings and evidence remain under `attempt-1/`.

For attempt 2, the fresh agent deliberately used unsupported pattern `scales`, invoked the CLI, read the structured `error_records[0]`, and changed only `materials[0].pattern` to `checker`. It then ran validate-only on the corrected recipe and exported successfully. Full stdout, stderr and exit codes are retained for all three invocations in `attempt-2/`; the corrected recipe and all generated files are retained there as well.

The agent's validate-only and export invocations both exited 0. Export produced seven manifest entries: editable `.am3d`, OBJ, MTL, OBJ texture sidecar PNG, GLB, animation sheet PNG, and shell atlas PNG. I independently reran the corrected recipe; all seven files resolved inside the chosen output directory, and every file was byte-identical to the agent's outputs. The manifest reported no errors, warnings, or partial publication.

I loaded the saved `.am3d` and evaluated `clockwork_walk` at 0 and 1 second. All eight leg segments had copied, weighted rigs and each showed a maximum vertex displacement of 0.25 units. The 12-frame animation sheet also shows their silhouettes shifting. The shell is visually dominant and the animation sheet is flat-color, so the sheet is useful for motion review but not material review. Textured appearance is present in the atlas and OBJ/GLB material data. The requested result is a deliberately simple beetle, not a polished sculpt.

The trial agent made no package installs or global environment changes. After the first attempt's unrequested NumPy change, the host was restored to the recorded baseline: NumPy 2.5.2 and msgpack 1.2.2.

## Scope and follow-up evidence

- The trial is a same-family `gpt-6-luna` agent run, not a separate-vendor LLM trial.
- The Phase 1 agent trial used the source CLI. Current-source packaged CLI
  acceptance was completed in Phase 3 and is recorded in
  `../phase-3/PHASE3_REPORT.md`.
- Two independent Luna reviewers passed the corrected contract and generated
  result before Phase 2 began; see `PHASE1_REVIEW.md`.

## Evidence map

- `attempt-1/`: failed first recipe run and the independent review findings.
- `attempt-2/recipe-initial.json`, `recipe-corrected.json`: agent-authored recipe before/after its error correction.
- `attempt-2/failed.*`, `validate.*`, `export.*`: complete captured CLI streams and exit codes for the three agent invocations.
- `attempt-2/successful-output/`: retained project, exports, preview, and texture atlas.
- `attempt-2/walk_frames_inspection.png`: agent's animation-sheet inspection capture.
- `attempt-2/independent.*`: independent rerun result and captured streams.
