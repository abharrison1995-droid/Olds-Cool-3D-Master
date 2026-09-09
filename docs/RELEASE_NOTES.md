# 3D MASTER:2005 — 0.2.0b1 (beta)

First release built and accepted as a standalone desktop application: no
Python, no pip, no checkout on the user's machine.

## What is in this release

| Artifact | Platform |
| --- | --- |
| `3D-MASTER-2005-Beta-0.2.0b1-linux-x86_64.tar.gz` | Linux x86-64 (MX 25.2 KDE / Debian 13) — GUI + recipe CLI + examples + docs |
| Windows portable ZIP | **Not produced.** No Windows machine was available; see "Blocked" below |

```
3D-MASTER-2005-Beta-0.2.0b1-linux-x86_64.tar.gz
SHA-256  ad36d7ef798d3fd3bd7dc68bd15a8540a8c535655b2e8ec1e7fe6e86eefc4cdf
built from commit b96c922a3c9d6461f0e4888ce47dbc28b3449067 (clean tree), CPython 3.13.5, PyInstaller 6.22.2
```

The complete pinned build set is in `release/BUILD_PROVENANCE-linux.txt`,
which ships beside the archive; a copy is kept under
`docs/evidence/desktop-release/phase-e/`.

Start here: `docs/QUICK_START.md` (also `QUICK_START.md` inside the bundle).
What each surface can do: `docs/CAPABILITY_MATRIX.md`.

## Fixed in this release

Every entry was reproduced before it was fixed and has a regression test;
the full record, with measurements, is in
`docs/evidence/desktop-release/FINDING_LEDGER.md`.

**Data you could have lost**

- Quitting one document deleted *every* document's recovery snapshot
  (DATA-01). Recovery is now per document.
- The recovery prompt offered whichever snapshot sorted first by filename,
  with no way to tell which document it belonged to (DATA-02). There is now
  a chooser showing each document's name, original location, time and size;
  the ones you do not pick are kept.
- Autosaves were written to the generic `PySideApp` directory Qt gives an
  unnamed application, shared with any other such application (PATH-01).
  They now live in this application's own directory; anything left in the
  old one is still offered for recovery.

**Editing that did not do what it showed**

- Moving a control point on a lathed or extruded profile moved the visible
  curve but not the surface that was rendered and exported (EDIT-01). The
  surface is regenerated live, and undo/redo is exact.
- A lathe built from a three-point profile produced an object that could
  not be rendered or exported at all (EDIT-02).
- Clicking a visible object selected nothing, because the software renderer
  and the picking code did not share a projection (VIEW-01).
- Closing a project left playback running and stale selection behind
  (LIFE-01); an empty scene re-queued a render on every paint (LIFE-02).

**Rendering and export correctness**

- On real AMD/radeonsi hardware the GPU pipeline drew a completely blank
  frame while every software test passed — matrices were uploaded in the
  wrong order for the shader (GPU-04).
- The standalone render API ignored visibility, transforms and poses
  (GPU-01), drew only the first object when the GPU was unavailable
  (GPU-02), and framed every object with its own camera (GPU-03).
- A forced-software render framed the scene differently from the GPU render
  of the same scene (GPU-05), and a smooth curved surface was flooded with
  outline and came out as a black disc (RENDER-01).
- Two differently coloured patches on one object collapsed into one colour
  through rendering and export (MAT-02); baked texture atlases never
  reached OBJ/MTL or GLB, so an independent viewer showed flat white
  (MAT-01).

**Things the GUI could not do**

- At 200% display scaling the window is short enough that the Properties
  panel clipped its own controls, with the visibility checkbox unreachable
  (UI-05). The panels scroll now.

- There was no way to create a bone: a model built in the GUI could only be
  rigged by writing a script or a recipe (UI-01). There is now a Rig menu
  with add/parent/delete bone, geometry binding with automatic weights, and
  clear pose.
- There was no way to produce a finished image or an animation at all
  (UI-02). **File ▸ Render Image / Sequence… (F12)** renders a still or a
  frame range, with progress, cancellation that keeps the frames already
  written, and a forced-software option.
- Creating a second action left the first one active, so keys went to the
  wrong action, and keying with no action did nothing without saying why
  (UI-04). Entering the Render workspace did not show the render settings
  (UI-03).
- The bundle shipped recipe *outputs* but no recipe, so the documented
  "run a recipe, then open it in the GUI" journey could not be done with
  the bundle alone (PKG-04). The frozen CLI also printed usage for
  `python -m am3d.recipes`, which a bundle user cannot run (CLI-01).

**Environment and packaging**

- A Windows drive-relative export path (`D:outside_file`) passed the escape
  check on Linux (ENV-03a); `jsonschema` was undeclared, so the suite could
  not pass from a clean install (ENV-03b). Test/build dependencies are now
  separate from runtime dependencies, with a captured transitive lock.
- The release folder carried the build's own smoke-test manifest, stdout
  and stderr, so every user received a file full of absolute build-machine
  paths (PKG-05). Those now go to a scratch directory, and both build
  scripts fail if anything in the payload mentions the build root.
- There was no Linux build pipeline at all (PKG-01). `build_linux.sh` now
  builds from an isolated venv, runs the suite, freezes both executables,
  checks the Qt Wayland and xcb plugins are present, runs the packaged
  smoke test and the bundled recipe, verifies a relocated copy from a path
  with spaces and non-ASCII characters, and writes the archive, checksum
  and provenance.

## Verified on

MX-25.2 KDE x86-64 (Debian 13 trixie), kernel 6.12.90, KDE Plasma 6.3.6 on
Wayland, Ryzen 7 5700U with integrated AMD Radeon (amdgpu/radeonsi), Mesa
26.1.4, OpenGL 4.6, 32 GiB RAM, 1920×1080.

All three graphics routes were exercised on that machine: native Wayland,
xcb/XWayland, and forced software rendering. See
`docs/evidence/desktop-release/phase-e/` for the executed commands and
their output, and `docs/SUPPORTED_PLATFORMS.md` for the support statement.

## Blocked — not shipped, not claimed

- **Windows.** No Windows machine was available in this environment, so no
  Windows executable was built or tested. `build_windows.ps1` is maintained
  in step-for-step parity with the Linux script, but an unbuilt, untested
  pipeline is not a release artifact and this release does not claim one.
- **Older Linux baselines.** Only MX 25.2 / Debian 13 userspace was tested.
  The bundle carries its own Qt, but it does not carry glibc.
- **Fractional-scaling appearance beyond the captured screenshots.** The
  100/150/200% screenshots in the evidence folder show startup and the
  editor; they are not a substitute for prolonged use at those scales.

## Known limitations

OBJ and GLB exports are static, tessellated snapshots of one pose and carry
no skeleton, weights or keyframes — this is not a skeletal-animation
interchange. Open construction splines are curves and produce no triangles.
There is no video encoding, no import of third-party 3D formats, no IK, and
no weight painting. `docs/CAPABILITY_MATRIX.md` is the complete list.
