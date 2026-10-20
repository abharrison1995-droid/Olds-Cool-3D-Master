# What the app models, and what its exports contain

3D MASTER:2005 stores an editable scene built from spline patches, supported
source profiles, materials, rigs and actions. Renderers and surface exporters
evaluate patch geometry into triangles. They do not turn every spline or
control point in the project into an exported surface.

## Profiles and generated surfaces

An open spline is a construction curve. By itself it has no faces: a tested
open three-point spline evaluates to 33 sampled vertices and zero triangles.
It appears as a curve in the viewport so that its points can be selected and
edited, but it contributes no surface to a render or OBJ/GLB export until a
surface is built from it.

Recipe-generated `lathe` and `extrude` objects retain their authored source
profile as a collision-safe spline together with the existing generator
parameters and effective degrees. Editing that profile through the existing
spline control-point commands changes the generated surface triangles.
Focused source checks cover the profile edit, exact undo/redo, and native
save/reopen round trip. The lathe profile follows the established
radius/axial convention for its selected revolution axis; an extrusion keeps
its three-dimensional profile.

This is a specific source-profile editing path, not a general patch control
net editor. Moving an unrelated guide spline does not reshape a baked patch,
and the desktop UI does not expose direct array/net editing of arbitrary
patches. Primitive objects can be transformed and assigned materials. Direct
access to other control-net data is a scripting/API task rather than a
general-purpose GUI surface-editing workflow. See
[`PROFILE_EDIT_GAP.md`](evidence/v1/phase-6/PROFILE_EDIT_GAP.md) for the
scoped correction and its tests.

## Surface-only exports

OBJ and GLB contain tessellated patch surfaces at the pose selected for
export. Supported per-object and per-patch material assignments, flat colors,
UVs and baked atlas data are carried where the writer supports them. They do
not contain construction splines, control points, bones, skin weights,
actions, keyframes, hooks, cameras or lights. OBJ and GLB are static pose
snapshots, not skeletal-animation interchange.

The `.am3d` project is the editable scene format and retains supported scene,
rig and action data. Format 2 has an optional bounded generation-metadata
envelope; a writer using older explicit root fields can drop that optional
metadata when it saves. AI generation records and their manifests are stored
as local sidecars. Exported OBJ/GLB files do not become an authoritative
history record.

## When an export or preview has no visible surface

An empty surface output means that the evaluated scene has no visible surface
triangles. Check these conditions:

1. The object may contain only construction splines. Build a lathe or
   extrusion surface from a supported profile.
2. Surface objects may be hidden. Check **Visible in viewport** in the Object
   properties.
3. The project may contain no objects, or no visible surfaces.

The AI checker rejects an empty or structurally invalid whole-scene result
before publication. Its 512×512 preview checks decoded image bounds and
nonblank occupancy. This establishes structural visibility only; it does not
prove that the image is attractive or that the intended design was achieved.

## Animation and appearance limits

The native project stores rig and action data. OBJ and GLB take one static
pose. The recipe CLI can make CPU-rendered sprite, toon and animation sheets;
those are images rather than rigged interchange files. The AI preview uses
fixed-camera software rendering and represents texture patterns by their base
material color, so it does not demonstrate full texture appearance. Physically
transparent/refractive glass and animated GLB are outside the current tested
recipe capability.
