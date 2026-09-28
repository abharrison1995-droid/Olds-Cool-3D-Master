# Phase 2 — Editor handoff and current interface

## Result

The generated project passed the current `MainWindow` handoff path in a pinned
isolated Python environment using Qt's offscreen platform plugin. The run used
the current early-2000s theme and captured the Layout and Animate workspaces at
1280×820 and 1440×900.

The acceptance script made a visible head transform edit through the editor's
undo stack, verified undo restored the original transform, verified redo
restored the edit, saved the `.am3d` project, reopened it through the editor's
document controller and confirmed the edit, material, rig, and action
assignment survived. The MainWindow viewport produced a finite, nonblank
rendered frame. The compact Animate screenshot shows all four rig action
buttons, including **Bind Geometry**, within the properties panel.

## Evidence

- Run script: `acceptance_run.py`
- Machine result: `acceptance.json`
- Edited and reopened project: `clockwork_beetle_refined.am3d`
- Layout: `layout-1280.png`, `layout-1440.png`
- Animate: `animate-1280.png`, `animate-1440.png`
- Python environment: `/tmp/am3d-roadmap-phase2-venv`, installed from the
  repository's pinned `requirements.txt`
- Command: `XDG_CONFIG_HOME=/tmp/am3d-phase2-config XDG_DATA_HOME=/tmp/am3d-phase2-data QT_QPA_PLATFORM=offscreen /tmp/am3d-roadmap-phase2-venv/bin/python docs/evidence/implementation-roadmap/phase-2/acceptance_run.py`
- Fallback/status/diagnostics check: `QT_QPA_PLATFORM=offscreen /tmp/am3d-roadmap-phase2-venv/bin/python -m pytest am3d/gpu/test_gpu.py::test_render_frame_reports_context_fallback am3d/gpu/test_gpu.py::test_render_frame_reports_last_resort_software_fallback am3d/ui/test_ui.py::test_status_bar_reports_context_fallback am3d/ui/test_home.py::test_diagnostics_menu_action_is_wired_and_does_not_raise -q` — 4 passed

## Scope and limitation

The machine has no `xcb-cursor` runtime library, so the native xcb window could
not be started. The successful check exercises the actual `MainWindow`,
document controller, undo stack, theme, and viewport renderer under Qt
offscreen mode; it is not evidence for compositor-specific input, scaling, or
hardware GPU behavior. The renderer setting was Auto (GPU preferred, software
toon fallback), so the screenshots must not be treated as GPU acceptance.
Native compositor, DPI, and GPU checks remain assigned to the target-platform
acceptance phases.

The status bar now reports the backend that produced the most recent frame.
`am3d.gpu.render_frame` returns backend metadata on request, including when it
quietly falls back to software after context or pipeline failure;
`acceptance.json` records that result and the configured preference. This run
used `software (toon)`. Four focused fallback/status/diagnostics checks
passed, including the defensive last-resort fallback. The diagnostics view
now reports the last actual renderer separately from the configured
preference. The viewport evidence is framed to show the full generated asset.
A successful ModernGL render in an offscreen process would still not
establish that a physical GPU was used.

## Review gate

Two independent Luna reviewers passed after the identified issues were
resolved: camera framing now includes the full asset; the status bar and
Diagnostics report the actual renderer result; and context, pipeline, and
defensive software fallbacks are covered. See `PHASE2_REVIEW.md` for the
review record. Luna's available effort was `max`; requested `xhigh` is not
supported by the configured sub-agent runtime.
