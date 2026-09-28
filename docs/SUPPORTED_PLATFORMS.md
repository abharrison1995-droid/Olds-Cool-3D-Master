# Supported platforms

Scope note: a row is only marked **Verified** when the check was actually
executed in this environment. This document separates preview-candidate
evidence from a platform support claim.

Artifact-scope note: the current-source preview candidate was built and
checked on Linux Mint 22.3. Its GUI checks used Qt offscreen mode and software
rendering. They do not certify native desktop interaction, DPI scaling,
physical GPU rendering, MX Linux, or general Linux support. Earlier MX
acceptance below applies only to the historical artifact built from
`b96c922`. See `docs/IMPLEMENTATION_ROADMAP.md` for the active preview scope.

## Standalone desktop distributions (no Python required)

| Target | Status |
| --- | --- |
| Linux Mint 22.3 (Zena), x86-64 | Current-source preview candidate built; source suite and packaged checks passed. GUI checks used Qt offscreen mode/software paths; this is not a native-desktop support claim. |
| Linux x86-64, Debian 13 / MX Linux 25.2 KDE | Historical artifact from `b96c922` was accepted on the reference machine; current-source candidate not qualified there. Follow-on release qualification. |
| Windows x86-64 (minimum version not yet selected) | No Windows artifact is verified. Build definition and reviewed CI workflow exist; native execution and host acceptance are follow-on work. |

The Linux preview bundle contains the windowed GUI application and the
standalone `am3d-recipe` console CLI. Neither requires a Python installation
on the target machine. This preview has not been accepted on a native desktop
session. No Windows artifact is included or verified.

## Current preview build host

| | |
| --- | --- |
| Distribution | Linux Mint 22.3 (Zena) |
| Architecture | x86-64 |
| Kernel | 6.8.0-139-generic |
| GUI check | Qt offscreen mode; no native compositor interaction |
| Renderer check | Software path; no physical-GPU acceptance |

The checks establish that this candidate builds and that its packaged GUI
smoke and recipe CLI work in the recorded environment. They do not establish
that the UI has been interactively tested in Mint's native desktop session.

## Historical MX Linux reference acceptance (artifact `b96c922` only)

These details document the earlier MX acceptance only. They do not describe
the machine used for the current Mint preview candidate.

| | |
| --- | --- |
| Distribution | MX-25.2_KDE_x64 (Debian GNU/Linux 13, trixie) |
| Kernel | 6.12.90+deb13-amd64, x86_64 |
| Desktop | KDE Plasma 6.3.6 (kwin 6.3.6) |
| Session | Wayland (`wayland-0`), with XWayland available on `:0` |
| CPU | AMD Ryzen 7 5700U with Radeon Graphics |
| Memory | 32 GiB installed |
| GPU | AMD Lucienne (Renoir), `amdgpu` kernel driver, `radeonsi` |
| Mesa / GL | Mesa 26.1.4, OpenGL 4.6 core, direct rendering |
| Display | 1920x1080 |

### Linux graphics routes

For the historical artifact, the application was exercised on the following
routes. Current-source Mint preview evidence does not repeat these checks.

| Route | How to select it |
| --- | --- |
| Native Wayland | default on a Wayland session |
| XCB / XWayland | `QT_QPA_PLATFORM=xcb` |
| Forced software rendering | `LIBGL_ALWAYS_SOFTWARE=1` (and the app's own software rasterizer fallback, which engages automatically when no GL context can be created) |

The xcb route additionally needs the host's `libxcb-cursor0` (present on the
reference machine); Qt's xcb plugin warns and refuses to start without it.
The native Wayland route does not need it. A route launched from a context
that does not export `XAUTHORITY` (some `sudo` and systemd units) will fail
with "could not connect to display" -- that is the environment, not the
package.

Scaling: the GUI was exercised on the reference display at `QT_SCALE_FACTOR`
1, 1.5 and 2 (100/150/200%), on both the Wayland and the xcb route, with
screenshots in `docs/evidence/desktop-release/phase-e/`. At 200% the
compositor grants a window only about 500 logical pixels tall, which is what
exposed finding UI-05; the panels scroll rather than clip since that fix.

The historical MX checks do not establish current-source MX support or broad
Linux desktop support. The current candidate's native display and graphics
routes require follow-on qualification.
The frozen build bundles its own Qt, so the host's Qt version does not matter,
but a working `libGL`/`libwayland-client` from the host is still required.

## Python version policy (finding ENV-01)

Two different things are being versioned, and they do not have to match:

- **Frozen artifacts** are built with, and embed, **CPython 3.13**. Users of
  the standalone distributions install nothing and are unaffected by this.
- **Source installs** declare `requires-python = ">=3.10"` in `pyproject.toml`.
  That range is deliberately wider than the pinned build environment. Note
  that the pinned NumPy in `requirements-lock-linux.txt` (2.4.6) itself
  requires Python >= 3.11, so a 3.10 source install must resolve an older
  NumPy. Only the pinned set in `requirements-lock-linux.txt` is tested.

The reproducible dependency set used for the Linux build is
`requirements-lock-linux.txt`. `requirements.txt` is runtime-only;
`requirements-dev.txt` adds the test and build tooling.

## Optional components

| Component | Effect if absent |
| --- | --- |
| `moderngl` + a working GL 3.3+ context | The GPU deferred renderer is unavailable; the application falls back to its own software toon rasterizer and remains fully usable. |
| `numba` | Pure-NumPy paths are used; slower, identical results. |
