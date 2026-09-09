# 3D MASTER:2005 — interface and keyboard guide

Every menu item, panel and shortcut the desktop build exposes. Written
against the shipped code, not a design document: if something is listed
here it exists, and if a control is missing from this list it does not
exist yet.

## The window

| Area | What it is |
| --- | --- |
| Workspace tabs (top) | Layout, Model, Rig, Animate, Render — each a saved arrangement of panels plus a hint line |
| Viewport (centre) | The 3D view. Draws surfaces, spline control points and bones |
| Outliner (right, top) | Every object, with its bones nested beneath it. Selecting a row sets what the menus act on |
| Properties (right, bottom) | Tabs: Object, Bone, Material, Render. The workspace brings the relevant tab forward |
| Timeline / dope sheet (bottom) | Playback and keyframes. Present in Layout and Animate |
| Status bar | Current selection, current frame, and the reason a command declined to run |

## Menus

**File** — New (Ctrl+N), Open .am3d (Ctrl+O), Save (Ctrl+S), Save As,
Close Project, Close Editor, Import Action (.am3a), **Render Image /
Sequence… (F12)**, Export OBJ, Export GLB, Quit (Ctrl+Q).

**Edit** — Undo (Ctrl+Z), Redo (Ctrl+Y or Ctrl+Shift+Z). Every modelling,
rigging, material, keyframe and render-setting change is undoable.

**Create** — Sphere, Box, Cylinder, Cone, Torus, Plane; Profile/Spline;
Lathe Selected Profile; Extrude Selected Spline; Duplicate Object.

**Rig** — Add Bone, Add Child Bone, Delete Selected Bone, Bind Geometry to
Skeleton, Clear Pose.

**Workspace** — switch to any of the five workspaces.

**Settings** — Preferences (render backend, autosave).

**Help** — Quick Start, Diagnostics, About. *Diagnostics* reports the
versions, the active render backend and why it was chosen, the document's
identity, and the paths the app reads and writes — paste it into a bug
report.

## Viewport keys

| Key | Action |
| --- | --- |
| MMB drag | Orbit (LMB drag also orbits, for A:M familiarity) |
| Shift + MMB drag | Pan |
| Wheel | Zoom |
| 1 / 3 / 7 / 0 | Front / Side / Top / Perspective view |
| W | Translate gizmo |
| E | Rotate gizmo |
| X | Delete the selected control point, or drop the gizmo if none is selected |
| Delete | Delete the selected control point |
| A | Add a control point (Model workspace) |
| G / R / S | Modal translate / rotate / scale of the selection |
| Enter | Confirm a modal transform |
| Esc | Cancel a modal transform |
| Shift + G | Toggle the grid |
| Shift + W | Toggle wireframe |

## Dope sheet keys

| Key | Action |
| --- | --- |
| I | Key the selected bone at the current frame |
| Delete / X | Delete the selected key |
| Space | Play / pause |

Keying needs an active action. Without one, the status bar says so rather
than the key press doing nothing.

## Rigging a model

1. Select the object (Outliner or viewport).
2. **Rig → Add Bone** places a root bone spanning the lower half of the
   object. It becomes the selection.
3. **Rig → Add Child Bone** chains a bone from the selected bone's tail.
   Repeat for the rest of the skeleton.
4. Adjust head/tail numerically in the Bone tab, and re-parent with the
   Bone tab's Parent combo. The combo never offers a choice that would
   make a cycle.
5. **Rig → Bind Geometry to Skeleton** assigns proximity skin weights.
   *Until you do this the geometry does not follow the bones* — posing
   moves the bone alone. The status bar reports how many control-point
   weights were assigned.
6. Pose by dragging a bone's ring in the viewport (Rig workspace), or
   clear it with **Rig → Clear Pose**.

Deleting a bone moves its children up to its parent rather than deleting
them with it, and undo restores the bone together with its keyframes.

## Rendering a final image or sequence

**File → Render Image / Sequence… (F12)** opens the render dialog:

- **Mode** — a single still, or a frame sequence.
- **Destination** — the file to write (a still) or the pattern for the
  sequence; frame numbers are zero-padded so they sort correctly.
- **Size** — width × height in pixels.
- **Camera** — the current viewport camera, or the scene camera.
- **Frames** — start, end and fps (sequence mode).
- **Force software rendering** — bypass the GPU pipeline. Use it if the
  GPU output looks wrong, and please report it if the two disagree.
- **Stop** cancels; frames already written are kept.

## Empty states

| You see | Why | What to do |
| --- | --- | --- |
| "(No examples installed)" on the Home screen | The bundled `assets/` folder is missing from this install | Reinstall, or use File → New |
| "No selection" in the status bar | Nothing is selected, so the menus have no target | Click an object in the Outliner |
| An export or render with nothing in it | The scene evaluated to zero triangles | See [MODELLING_SCOPE.md](MODELLING_SCOPE.md) |
| A bone that moves nothing when posed | The geometry is not bound yet | Rig → Bind Geometry to Skeleton |
| "…has no bones yet" in the status bar | Bind was invoked on an unrigged object | Rig → Add Bone first |

## Where the app stores things

Preferences and the recent-projects list live in the platform's standard
settings location; autosaves and crash-recovery snapshots live under the
application data directory. Help → Diagnostics prints both paths for the
running build.
