# Main Editor Workspace

## Mode

Operate

## User and job

The primary product user is a person creating and editing stylised 3D assets.
Home offers Create with AI alongside manual New/Open and examples. The in-app
workflow turns a natural-language brief into checked, editable `.am3d` projects;
the editor supports inspection, manual editing, rigging, animation and rendering.
The external recipe CLI remains available for scripts and external agents.
Product and visual authority are `PRODUCT.md` and `DESIGN.md`.

## Success

The first view communicates a real spline-based 3D workbench and makes the scene, selected object, editable properties, and animation timeline easy to locate. Existing workspace functions, menus, shortcuts, and file formats remain available.

## Visual direction

User-pinned: Blender meets the early 2000s. Use Blender's compact, task-first multi-area structure with the tactile metal-gray chrome and beveled native controls of early desktop software. Keep the center viewport graphite, object selection amber, and the surrounding editing surfaces cool steel gray.

## First viewport

- Keep the File/Edit/Create/Rig/Workspace/Settings/Help menu row.
- Place Layout/Model/Rig/Animate/Render in the top workspace rail, with a clear active marker.
- Give the current workspace one compact tool row.
- Preserve the large center canvas, stacked Outliner and Properties on the right, and full-width timeline at the bottom.
- Use an actual project scene; selection must be visible in both the viewport and the Outliner.

## Signature interaction and motion

Selecting an object in the Outliner or viewport keeps the selection synchronized and exposes its Properties. Splitters and collapse controls resize the work areas. State changes remain immediate; no decorative motion is added.

## Product-specific constraints

- Keep all existing editing and file workflows working.
- The GUI must truthfully reflect generated spline projects; never present unsupported modeling or export controls as implemented.
- Preserve legibility at 100%, 150%, and 200% display scaling; native target
  qualification remains open as recorded in `docs/SUPPORTED_PLATFORMS.md`.
