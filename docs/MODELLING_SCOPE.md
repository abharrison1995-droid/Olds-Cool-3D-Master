# What this app models, and what an export contains

Finding SCOPE-01. Two behaviours surprise people who come from a polygon
modeller, and both are by design rather than defects — but neither was
written down, so an export could look "empty" with no explanation.

## Splines are construction curves, not geometry

A spline on its own is a *profile*: a curve you shape and then turn into a
surface with **Lathe** or **Extrude**. Nothing renders or exports from the
curve itself.

Concretely, an object holding one open 3-point spline and nothing else
evaluates to:

    vertices: 33   triangles: 0

The 33 vertices are the sampled curve, which is what the viewport draws so
you can see and edit it. There are no triangles because no surface has been
built yet.

So an object made only of splines:

- shows in the viewport as a curve,
- renders as nothing,
- exports as an object with no faces.

This is the intended pure-spline workflow: the control net is the document,
and tessellation is an output representation, produced only where a patch
exists.

## Exports are surface-only

OBJ and glTF/GLB are surface formats. The exporters write the tessellated
patch surfaces and nothing else:

- **written**: patch surfaces, their UVs, per-object and per-patch
  materials, flat colours and baked texture atlases;
- **not written**: splines and control points, bones and skin weights,
  actions/keyframes, hooks, and cameras or lights.

A rig is preserved in the project's own `.am3d` file, which round-trips
everything. If you need the animation itself somewhere else, export the
action as `.am3a`, or render a sequence (**File → Render Image /
Sequence…**) rather than expecting it inside an OBJ.

## "My export is empty"

An export with no faces means the scene evaluated to zero triangles. In
order of likelihood:

1. **Every object is still a spline.** Lathe or extrude a profile first
   (Create → Lathe Selected Profile / Extrude Selected Spline).
2. **The objects that do have surfaces are hidden.** Export uses the same
   evaluated scene as the viewport, and hidden objects are excluded — clear
   the visibility checkbox in the Object tab.
3. **The project is empty.** A new project starts with no objects at all.

The same three checks explain an empty render: the render path and the
export path share one scene evaluation
(`am3d.core.scene.evaluate_scene`), so whatever one shows, the other
agrees with.
