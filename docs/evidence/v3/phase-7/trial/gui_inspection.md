# Phase 7 trial — inspecting results in the shipped desktop application

The plan requires exercising the shipped command and inspecting results
"in the shipped desktop application." Two things were attempted, in order:

## 1. Interactive GUI via computer-use (not possible in this environment)

`3D MASTER 2005.exe` was launched from the built release folder
(`release/3D MASTER 2005 Beta/3D MASTER 2005.exe`) and confirmed running
with window title `3D MASTER:2005` (process `3D MASTER 2005`, PID 21328,
via `Get-Process`). However, this session's computer-use tool only grants
access to applications it can resolve against the Start Menu / installed-app
list; `3D MASTER 2005` is a standalone executable run directly from a build
output folder, not an installed/registered application, and
`request_access` returned `notInstalled` for it with no close match. This is
recorded as an environment exclusion, not a skipped step — genuine
click-through GUI inspection of this build was not possible from this
session.

## 2. Headless inspection via the real, unmocked `MainWindow` (performed)

As the legitimate fallback — the same technique the project's own packaged
smoke test (`am3d/ui/smoke.py`, Phase 6 bullet 4) uses for its own
save/reopen verification — both trial `.am3d` project files were opened
through the actual shipped `am3d.ui.app.MainWindow` class (not a mock, not
a re-parse of the JSON; the real `doc_ctrl.do_open()` load path), under
`QT_QPA_PLATFORM=offscreen`, and the loaded `Project` plus a real software-
rendered frame were inspected directly:

**`garden_lantern_project.am3d`**
- Objects loaded: `base`, `frame_body`, `frame_collar`, `shade` (all 4).
- Materials loaded: `amber_glass`, `wrought_iron` (both).
- Software-rendered frame produced: yes, 4 meshes in the rendered scene.

**`sentinel_bot_project.am3d`**
- Objects loaded: `head`, `leg_l`, `leg_r`, `torso`, plus the `sentinel`
  skeleton container (all 4 mesh objects).
- Materials loaded: `chassis_metal`.
- Actions loaded: `idle`, `walk` (both).
- Skeleton `sentinel` loaded with bones `hip`, `spine`, `leg_l`, `leg_r`
  (all 4, correctly named/parented per the recipe).
- Software-rendered frame produced: yes, 5 meshes in the rendered scene.

Both files round-trip correctly through the real application's load path
and render without error. This confirms the CLI-produced `.am3d` artifacts
are genuinely usable by the shipped desktop application, not just
structurally valid JSON/binary that happens to satisfy the CLI's own
success check.

Scripts used (ad hoc, not committed — scratch verification only):
`inspect_trial_am3d.py` / `inspect_trial_am3d2.py`, run from the repo root
with `python <script>`.
