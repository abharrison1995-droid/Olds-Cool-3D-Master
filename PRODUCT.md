# Product

<!-- impeccable:product-schema 1 -->

## Platform

desktop

## Users

The primary user is an AI agent generating 3D assets from JSON recipes. The desktop editor supports people inspecting, refining, and animating those assets.

## Product Purpose

3D MASTER:2005 combines a desktop 3D modeling and animation editor with a recipe pipeline for automated asset generation. An AI agent can produce a JSON recipe and generated project/assets; a person can then open the project in the editor to inspect or continue working on it. The user-confirmed primary use is AI agents generating 3D assets.

## Positioning

The product position is an integrated editor and recipe pipeline. Its distinct mechanism is a pure spline-patch model, where B-splines define smooth surfaces and tessellated polygon meshes are generated for rendering and export. A JSON recipe pipeline lets AI agents generate geometry, rigs, actions, and supported output assets, with projects available for further work in the desktop editor.

## Operating Context

- The desktop editor is organized into Layout, Model, Rig, Animate, and Render workspaces.
- The recipe CLI accepts declarative JSON and writes project files and supported asset exports.
- Artifact availability and platform qualification are maintained in `docs/SUPPORTED_PLATFORMS.md`.

## Capabilities and Constraints

- The native `.am3d` project format stores editable project data. OBJ and GLB exports are static, tessellated snapshots; they do not carry skeletons, skin weights, or keyframes.
- Supported workflows include spline profile lathe/extrusion, patch editing, rigging with automatic proximity weights, forward-kinematic posing, keyframed actions, rendering, and OBJ/GLB export. The recipe interface additionally supports procedural primitives, generated actions, and sprite/toon/animation sheets.
- Repository documentation lists third-party 3D format import, inverse kinematics, hand-painted weights, video encoding, and ray-traced rendering as unavailable.
- Platform support claims are maintained only in `docs/SUPPORTED_PLATFORMS.md`.

## Brand Commitments

- The user wants the editor to feel like Blender meets the early 2000s: a dense, serious 3D workbench with period desktop character.

## Evidence on Hand

- Product and workflow documentation: `README.md`, `docs/QUICK_START.md`, `docs/USER_GUIDE.md`, `docs/CAPABILITY_MATRIX.md`, `docs/MODELLING_SCOPE.md`, and `docs/SUPPORTED_PLATFORMS.md`.
- Sample project and action files: `assets/vase_demo.am3d`, `assets/walk.am3a`, and the examples under `assets/demo/` and `docs/recipes/examples/`.
- A previous desktop screenshot is under `docs/evidence/desktop-release/`; current early-2000s UI previews are under `docs/previews/`.
- No customer testimonials, external adoption data, or measured product outcomes are documented in the repository.

## Product Principles

- Treat the JSON recipe as a machine-readable interface for AI asset generation.
- Keep generated assets available as editable native projects that people can inspect and continue working on in the desktop editor.
- Keep spline patches as the authoritative model; treat tessellated meshes as render and export outputs.
