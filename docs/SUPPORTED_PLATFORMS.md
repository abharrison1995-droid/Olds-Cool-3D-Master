# Supported platforms

Scope note: a row is only marked **Verified** when the check was actually
executed in this environment. Rows that could not be executed are marked
**Blocked** and are not claims of support.

## Standalone desktop distributions (no Python required)

| Target | Status |
| --- | --- |
| Linux x86-64, Debian 13 / MX Linux 25.2 KDE | Primary; built and acceptance-tested on the reference machine below |
| Windows x86-64, Windows 10/11 desktop | Build definition present (`am3d.spec`, `am3d_recipe.spec`, `build_windows.ps1`); **no Windows machine is available in this environment, so no Windows artifact has been produced or tested here** |

Each platform ships two artifacts: the windowed GUI application and the
standalone `am3d-recipe` console CLI. Neither requires a Python installation
on the target machine.

## Linux reference acceptance machine

This is the machine the Linux artifacts are verified on. It is the reference
configuration named in the release plan.

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

The application is expected to run on all three of these routes; each is
tested separately, because a fault on one does not necessarily appear on the
others.

| Route | How to select it |
| --- | --- |
| Native Wayland | default on a Wayland session |
| XCB / XWayland | `QT_QPA_PLATFORM=xcb` |
| Forced software rendering | `LIBGL_ALWAYS_SOFTWARE=1` (and the app's own software rasterizer fallback, which engages automatically when no GL context can be created) |

Older or non-KDE Linux desktops are not a supported target for this release.
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
