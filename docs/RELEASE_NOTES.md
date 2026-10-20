# 3D MASTER:2005 — 1.0.0.dev1 (development test candidate)

> The current declarations in `am3d/__init__.py` and `pyproject.toml` are
> `1.0.0.dev1`. This is a development test candidate, not a release candidate,
> stable V1 release, built archive, or platform-support claim. At the Phase 9
> UI gate, the owner run passed 23 focused Home/UI tests in 34.04s. Its final
> offscreen set contained 13 screenshots at three Qt logical-size proxies; the
> 16-entry checksum manifest and all eight captured source hashes verified
> with zero mismatches at that gate. The independent UX/docs run passed the
> same 23 tests in 20.44s and verified those captures, then requested two
> documentation corrections. Focused verification passed both corrections;
> see the [Phase 9 review](evidence/v1/phase-9/INDEPENDENT_REVIEW.md) and
> [post-edit record](evidence/v1/phase-9/DOC_REVIEW_FIX.md).
>
> The later Phase 11 percent-encoded credential fixes changed the current
> Settings source, so seven of the eight captured source hashes still match
> and one does not. The existing screenshots remain evidence for the unchanged
> layout only; they were not recaptured to bind the newer Settings source.
> Current Settings privacy behavior has a separate 11-check independent result
> in the [Phase 11 architecture review](evidence/v1/phase-11/ARCHITECTURE_REVIEW.md).
> See the [source-delta reuse disposition](evidence/v1/phase-11/SOURCE_DELTA_REUSE.md)
> for the permitted capture use and its limits, and the [final capture evidence](evidence/v1/phase-9/final/ui-evidence.md)
> for the checksums, manifest, and screenshots. The overwritten preliminary
> capture bindings remain unverifiable. These records do not qualify physical
> DPI/native display, complete integrated regression, or V1 acceptance.
>
> **Historical release records.** This page also preserves two distinct Linux
> artifacts. The older MX beta artifact below is not the later Mint preview
> candidate, and neither artifact qualifies the approved V1 targets. V1
> targets Windows 11 x86-64 and Linux Mint 22.3 x86-64; neither has passed V1
> qualification. See [supported platforms](SUPPORTED_PLATFORMS.md) and the
> [active V1 plan](V1_MASTER_IMPLEMENTATION_PLAN.md).

## Current V1 development test candidate — 1.0.0.dev1

The current source tree contains the first-class **Create with AI...** Home
entry, provider settings, explicitly confirmed generation requests, bounded
local candidate/check work, a checked preview and guarded editor handoff.
The recipe CLI remains available. This source is under active V1 integration.
The source version is not an artifact identity; any local candidate build and
check results are identified in companion provenance, input, checksum, and
acceptance reports. Those results do not alone constitute V1 acceptance.

Phase 0 recorded a Windows 10 IoT Enterprise LTSC build 19044 source baseline
of 738 existing-source tests and 14 Qt offscreen smoke steps. Later bounded
evidence covers the provider contracts and explicit credential stores, brief
and recipe policy, isolated worker and checks, profile editing, desktop
lifecycle, and benchmark tooling. These are source-level results, not a final
stable-source suite or target-platform qualification. Phase 7 owner-run
history/refinement checks and its bounded independent local preservation
review passed: five history UI tests, the four-change measured refinement
node, and the Unicode 286-character preview-path probe. This local Phase 7
gate does not complete external review or final integrated regression. Source
receipts and a local candidate's checks are distinct: frozen/package and
integrated V1 results apply to the exact candidate and source identity in the
companion reports. Phase 8 live runs
and human scores, and Windows 11 and Mint 22.3 qualification remain open. The
current ledger is in
[`PROGRESS.md`](../PROGRESS.md).

No live provider request, default model, provider tariff, dollar cost ceiling
or artistic-quality result is implied. Current local bounds are four
candidate slots, five semantic calls, up to ten HTTP attempts, 90 seconds per
HTTP attempt, 600 seconds per shared run and 180 seconds per worker attempt.
The provider input-token charge and dollar cost remain unknown.

The Phase 4 requested-export correction has a fresh focused review: 12
contract checks, four selected guard checks, and actual worker-path positive
and negative export checks passed. A later strict **source** acceptance also
passed its fixed offline mock flow, including OBJ, GLB, per-object sheet and
whole-scene preview checks; it ran while UI/history edits were still in
flight, so its recorded input digest is a test-time snapshot, not the final
stable-source identity. This source receipt does not qualify a frozen
candidate; candidate-specific frozen results belong in the companion reports.
Phase 6's four deferred close-cancel cases, profile/surface checks and full
focused rerun passed, but one earlier 58-test run had an unexplained eight-second
wait timeout; it is retained as a qualification limit. Phase 8's 13 benchmark
checks plus two receipt/offline-gate checks passed; no live ledgers or human
scores exist.

The latest Phase 10 tooling/credential follow-up reports 30 passed and 4
skipped in its focused suite; the skips are host symlink/reparse capability
cases. A separate explicit Windows source-mode system-credential-store
sentinel CRUD/cleanup probe passed without provider or network use, and two
credential-notice metadata checks passed. These checks do not qualify the
frozen store backend. Earlier Phase 10 snapshots remain separately recorded:
the initial tooling suite was 10 passed/4 skipped, and the later strict
source-focused suite was 11 passed/3 symlink skips. The strict-source receipt
retains the runtime version `0.2.0b1` it observed at that historical test
snapshot; it does not identify the current `1.0.0.dev1` declarations. These
Phase 10 receipts are source checks and do not establish frozen-candidate
qualification. Candidate-specific build, lock, frozen-check, and acceptance
results belong in the companion artifact reports.
See the [Phase 4 review](evidence/v1/phase-4/SHEET_CONTRACT_REVIEW.md),
[Phase 6 review](evidence/v1/phase-6/INDEPENDENT_REVIEW.md),
[close-cancel evidence](evidence/v1/phase-6/close-cancel-fix.md), and
[Phase 7 owner evidence](evidence/v1/phase-7/ui-history-evidence.md),
[Phase 7 independent review](evidence/v1/phase-7/INDEPENDENT_REVIEW.md),
[Phase 8 evidence](evidence/v1/phase-8/IMPLEMENTATION.md). Phase 10's source
acceptance record is in
[`strict-source-followup.json`](evidence/v1/phase-10/strict-source-followup.json),
and [latest tooling review follow-up](evidence/v1/phase-10/tooling-review-followup.json).

## Historical Linux Mint preview artifact — 0.2.0b1

The historical Linux Mint 22.3 preview was built from the source current at
that time and accepted for its recorded offscreen/software preview scope. It
is identified by archive
`release/3D-MASTER-2005-Beta-0.2.0b1-linux-x86_64.tar.gz`, SHA-256
`4d41c0cf7cbf069edf907483cbf16ff4b0f8dcc54130aa791a16a049568d6433`, and
build-input digest
`6e62c8cdf6ecfb578885f852391b5d8b50d118a6405b9f4817cb36aa0fd60283`.
Its GUI checks used Qt offscreen mode and software rendering. Full details
are in `docs/evidence/implementation-roadmap/phase-3/PHASE3_REPORT.md` and
`docs/evidence/implementation-roadmap/CANDIDATE_REVIEW.md`.

## Historical MX beta artifact — `b96c922`

The older MX build below was accepted as a standalone desktop application:
no Python, no pip, no checkout on the user's machine. Its archive checksum
and platform evidence apply only to that artifact.

## What was in the historical MX release

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

## Verified on — historical MX artifact only

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
  Reading it closely enough to plan a Windows run found that it could not
  have completed on a clean Windows machine at all -- it installed only the
  runtime requirements and then called `pytest` and PyInstaller (PKG-06).
  That is fixed by review only; the fix has still never run.
  `docs/WINDOWS_ACCEPTANCE_PLAN.md` is the route from here to a Windows
  artifact that has actually been accepted.
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

## Latest local development acceptance

The final local locked Windows10 development candidate subsequently passed1048 source tests/2 privilege skips/4 existing warnings, GUI14/CLI/fixed offline AI/relocation, retained frozen Windows credential sentinel CRUD/cleanup and independent static OBJ/GLB reader checks. Exact source2be687b3… and ZIP36970e05… passed independent final local packaging/product verification. Earlier phase-scoped statements above retain their historical scope; they do not mean the current local integrated regression is pending. Required selected-target/native/GPU/read-only/live/human/committed-RC gates remain open. See PROGRESS and phase-11/FINAL_ACCEPTANCE.md for exact identities/dispositions; no cross-platform V1 or release acceptance is claimed. This note is unbundled and does not alter the delivered artifact.
