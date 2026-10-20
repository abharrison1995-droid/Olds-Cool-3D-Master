# Supported platforms

Scope note: a row is only marked **Verified** when the check was actually
executed in this environment. This document separates preview-candidate
evidence from a platform support claim.

V1 target note: Windows 11 x86-64 and Linux Mint 22.3 x86-64 are the approved
V1 targets. Neither has passed V1 qualification. The current implementation
workstation is Windows 10 IoT Enterprise LTSC, build 19044, x86-64; it is not
the Windows 11 target. Current source declarations are `1.0.0.dev1`, a
development test candidate only, not a release candidate, stable V1, or built
artifact identity. A Windows artifact may be built as a test candidate, but
supported publication requires the actual Windows gates.

Artifact-scope note: the accepted Linux Mint preview candidate is identified
by archive SHA-256
`4d41c0cf7cbf069edf907483cbf16ff4b0f8dcc54130aa791a16a049568d6433` and
build-input digest
`6e62c8cdf6ecfb578885f852391b5d8b50d118a6405b9f4817cb36aa0fd60283`. Its GUI
checks used Qt offscreen mode and software rendering. They do not certify
native desktop interaction, DPI scaling, physical GPU rendering, MX Linux,
general Linux support, or V1. Earlier MX acceptance below applies only to a
separate historical artifact built from `b96c922`, SHA-256
`ad36d7ef798d3fd3bd7dc68bd15a8540a8c535655b2e8ec1e7fe6e86eefc4cdf`. See
the [active V1 plan](V1_MASTER_IMPLEMENTATION_PLAN.md); the older
[preview roadmap](IMPLEMENTATION_ROADMAP.md) is historical.

## Standalone desktop distributions (no Python required)

| Target | Status |
| --- | --- |
| Windows 11 x86-64 | Selected V1 target; V1 qualification remains open. Windows 10 IoT Enterprise LTSC build 19044 is the current workstation, not the target. Candidate identity and checks are artifact-specific; supported publication awaits all target gates. |
| Linux Mint 22.3 (Zena), x86-64 | Selected V1 target; historical preview candidate accepted at the exact identity above. Its offscreen/software scope does not qualify V1 or native desktop/GPU use. |
| Linux x86-64, Debian 13 / MX Linux 25.2 KDE | Separate historical artifact from `b96c922` was accepted on the reference machine; current-source candidate not qualified there. Not a selected V1 target. |

The historical Mint preview bundle contains the windowed GUI application and
the standalone `am3d-recipe` console CLI. Neither requires Python on the
target machine. Its GUI was checked offscreen, not in a native desktop
session. It predates the current in-app AI source workflow and does not
qualify that workflow or V1.

## Current V1 implementation workstation

| | |
| --- | --- |
| Distribution | Windows 10 IoT Enterprise LTSC |
| Build | 19044 |
| Architecture | x86-64 |
| V1 qualification | Not performed; this is not the Windows 11 target |
| Source baseline | Phase 0: 738 existing-source tests and 14 smoke steps passed in Qt offscreen mode; later bounded source checks are recorded per phase |

The Phase 0 source baseline used CPython 3.12.14 on this Windows 10 host.
Later phase-scoped checks ran on the source environment; integrated regression
results apply to their recorded source identity. This workstation record does
not establish Windows 11 target qualification or native desktop, DPI, GPU, or
frozen behavior; those checks require candidate- and target-specific evidence.

## V1 packaging preparation status

Packaging scripts and local preparation checks exist. The initial Phase 10 preparation ran 10
checks and skipped 4. A later strict source acceptance passed its fixed
offline mock flow and reported 11 passed with 3 host symlink skips in the
focused tooling suite. The latest tooling/credential follow-up reported 30
passed and 4 skipped in its focused suite; the skips were host symlink/reparse
capability cases. Two separate credential-notice metadata checks passed, and
an explicit Windows source-mode system-credential-store sentinel CRUD and
cleanup probe passed without provider or network use. These are source checks
only; they do not qualify frozen secure-store behavior. Candidate-specific
build, lock, frozen-check, and acceptance results belong in the companion
artifact reports and do not alone establish V1 qualification. Linux target
wheels were cross-resolved on the Windows source host; native Mint target
checks require their own evidence. Earlier source digests remain test-time
snapshots, not final artifact identities. See the [initial tooling preparation](evidence/v1/phase-10/tooling-preparation.json),
[strict source follow-up](evidence/v1/phase-10/strict-source-followup.json),
and [latest tooling review follow-up](evidence/v1/phase-10/tooling-review-followup.json).

## Historical Mint preview build host

| | |
| --- | --- |
| Distribution | Linux Mint 22.3 (Zena) |
| Architecture | x86-64 |
| Kernel | 6.8.0-139-generic |
| Archive SHA-256 | `4d41c0cf7cbf069edf907483cbf16ff4b0f8dcc54130aa791a16a049568d6433` |
| Build-input digest | `6e62c8cdf6ecfb578885f852391b5d8b50d118a6405b9f4817cb36aa0fd60283` |
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
Linux desktop support. The Mint preview candidate's native display and
graphics routes require follow-on qualification.
The frozen build bundles its own Qt, so the host's Qt version does not matter,
but a working `libGL`/`libwayland-client` from the host is still required.

## Python version policy (finding ENV-01)

Source installs declare `requires-python = ">=3.10"` in `pyproject.toml`.
The pinned NumPy in `requirements-lock-linux.txt` (2.4.6) requires Python
3.11 or newer, so a Python 3.10 source install must resolve a compatible
older NumPy. The current Windows development checks used CPython 3.12.14; the
historical Mint preview source/package evidence used Python 3.13.5. These
records do not establish every Python version in the declared source range.

The historical Mint preview embedded its own CPython runtime; its runtime
identity applies only to that archive. A frozen candidate's Python and
resolved packages must be read from its build provenance, not inferred from
an older bundle or a build script. `requirements.txt` is runtime-only; `requirements-dev.txt` adds test
and build tooling. The Linux lock received a target-wheel cross-resolution on
the Windows host; no native Mint lock install or build is recorded.

## Optional components

| Component | Effect if absent |
| --- | --- |
| `moderngl` + a working GL 3.3+ context | The GPU deferred renderer is unavailable; the application selects its software toon rasterizer. GPU performance and parity require the separate native-GPU gate. |
| `numba` | Pure-NumPy paths are used; this can be slower. |
