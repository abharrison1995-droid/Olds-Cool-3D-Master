# 3D MASTER:2005

3D MASTER:2005 is a spline-patch modeling and animation editor with a recipe
pipeline and an in-app natural-language creation workflow in the current
development source. B-spline surfaces and construction profiles are native
project data; polygon triangles are evaluated outputs used for previews,
rendering, and export.

## Current development test candidate — 1.0.0.dev1

Both `am3d.__version__` and the project metadata declare `1.0.0.dev1`. This
identifies the current development/test source only; it is not a release
candidate, stable V1 release, built archive, or platform-support claim.

The Home screen exposes **Create with AI...**. The source workflow collects a
brief, requires an explicit provider model and request confirmation, generates
recipe candidates, checks the resulting project and exports, and offers a
guarded path into the editor. It remains a development test candidate: live
provider/model performance, measured human quality, and selected-target
acceptance remain open. Any local frozen or test result applies to the exact
candidate named by its companion build provenance, input, checksum, and
acceptance reports; those results do not alone establish V1 qualification.
The accepted Linux Mint preview archive described below is an older, separate
artifact and does not contain or qualify this V1 source workflow.

The provider dialog has no preselected model. Its current endpoint allowlist
contains `api.openai.com`; the prompt, endpoint, configured model, and request
contents are shown for confirmation before a call. The API key is stored in
the selected OS credential store or explicitly in memory for the session; it
is not stored in application preferences. Cost is unavailable. See the
[quick start](docs/QUICK_START.md), [user guide](docs/USER_GUIDE.md), and
[supported platforms](docs/SUPPORTED_PLATFORMS.md) for the development-source
scope and limits.

## The editor

The desktop editor has Layout, Model, Rig, Animate, and Render workspaces. It
uses a dense, early-2000s desktop-workbench visual direction. See
[DESIGN.md](DESIGN.md) and [PRODUCT.md](PRODUCT.md).

The in-app generator and the external recipe CLI share `recipe-v1` as their
structured asset contract. The CLI remains available for scripts and external
agents; it validates recipe JSON and writes an editable `.am3d` project plus
the requested outputs.

From a source checkout:

```bash
python -m am3d.recipes \
  --recipe docs/recipes/examples/knight_full.json \
  --out ./generated/knight
```

For the standalone Linux executable in the historical Mint preview bundle,
invoke `./am3d-recipe` with the same arguments. Standard output contains the
JSON result and artifact manifest; diagnostics go to standard error.
`--validate-only` checks a recipe without generating files. The
[external-agent guide](docs/recipes/EXTERNAL_AGENT_GUIDE.md) describes the
schema and correction loop.

The recipe surface supports primitives, lathe/extrude profiles, materials and
patterns, bones, actions, native projects, OBJ/GLB, and sprite/toon/animation
sheets. OBJ and GLB are static tessellated pose snapshots; `.am3d` retains the
editable scene and animation. Recipe sheets use the CPU software rasterizer.
The [capability matrix](docs/CAPABILITY_MATRIX.md) separates engine, recipe,
and GUI access, including the current profile-edit boundary.

## Platform and artifact status

Windows 11 x86-64 and Linux Mint 22.3 x86-64 are the selected V1 targets;
neither is qualified for V1. Source checks run on Windows 10 IoT Enterprise
LTSC build 19044 x86-64 in Qt offscreen mode. That is not Windows 11 or native
desktop acceptance.

The historical Linux Mint 22.3 preview archive has SHA-256
`4d41c0cf7cbf069edf907483cbf16ff4b0f8dcc54130aa791a16a049568d6433` and
build-input digest
`6e62c8cdf6ecfb578885f852391b5d8b50d118a6405b9f4817cb36aa0fd60283`. Its GUI
checks used Qt offscreen mode and software rendering. The older MX 25.2
artifact is a separate historical build. Neither artifact qualifies current
V1 source, Windows 11, native Mint interaction, physical GPU rendering, or
general Linux support. A Windows artifact may be built as a test candidate;
publication as supported requires its actual acceptance gates. See
[supported platforms](docs/SUPPORTED_PLATFORMS.md), the
[active V1 plan](docs/V1_MASTER_IMPLEMENTATION_PLAN.md), and the
[historical preview roadmap](docs/IMPLEMENTATION_ROADMAP.md).

## Development

Python source installs declare Python 3.10+ and runtime dependencies; the
frozen build environments have their own platform-specific Python and
dependency requirements. See `requirements.txt`,
`requirements-lock-linux.txt`, and the [platform policy](docs/SUPPORTED_PLATFORMS.md).
Install development dependencies with:

```bash
python -m pip install -r requirements-dev.txt
```

Run the source suite with:

```bash
python -m pytest am3d/
```

Build scripts and acceptance instructions are in
[the Windows acceptance plan](docs/WINDOWS_ACCEPTANCE_PLAN.md) and the
historical preview roadmap. The active V1 phase ledger is maintained in
[PROGRESS.md](PROGRESS.md).
