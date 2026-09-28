# Phase 2 — Independent review gate

Two independent `gpt-6-luna` reviewers ran at the highest available effort
(`max`; this runtime does not support the requested `xhigh`). Both returned
**PASS** on the final Phase 2 source and evidence.

## Findings and resolution

| Finding | Resolution / evidence |
| --- | --- |
| Preview initially cropped the beetle at the top. | Acceptance camera is framed before capture; both 1280×820 and 1440×900 Layout/Animate captures show the full model. See `acceptance_run.py` and the four PNGs. |
| Status bar could label a software fallback as GPU because the module imported. | `am3d.gpu.render_frame(..., return_backend=True)` returns the backend used, including context, pipeline, and final-`None` software fallbacks. The viewport forwards this metadata to the status bar. |
| Diagnostics described renderer availability as the active renderer. | Diagnostics now reports the last rendered backend separately from the configured renderer preference. |
| Offscreen result could be mistaken for compositor or physical GPU acceptance. | `PHASE2_REPORT.md` explicitly limits the result to Qt offscreen and leaves native compositor, DPI, and physical GPU acceptance pending. |

## Review checks

- Both reviewers inspected current source, tests, acceptance JSON, and all four
  screenshots independently.
- Four focused checks passed: context-creation fallback metadata, defensive
  last-resort fallback metadata, viewport status reporting, and Diagnostics
  reporting.
- The final acceptance run records `renderer_used: "software (toon)"`,
  `undo_restored_before: true`, `redo_restored_after: true`, and
  `saved_and_reopened_after_transform: true`.
- Reviewers found no remaining Phase 2 blocker. Native platform and hardware
  checks remain outside the offscreen claim.
