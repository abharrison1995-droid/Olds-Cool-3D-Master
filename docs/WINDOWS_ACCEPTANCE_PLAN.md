# Windows acceptance plan

Windows 11 x86-64 is an approved V1 target. The current implementation
workstation is Windows 10 IoT Enterprise LTSC, build 19044, x86-64; it is not
the selected target. No Windows 11 V1 qualification evidence is recorded.
The current source declares `1.0.0.dev1` as a development test candidate,
not a release candidate or stable V1 build. Candidate identity and check
results belong in companion build provenance, inputs, checksum and acceptance
reports; they do not alone establish V1 qualification. A supported Windows
publication claim requires the actual target gates below. Historical
Windows packaging work recorded in V3 remains evidence for its named artifact
only.
See the [active V1 plan](V1_MASTER_IMPLEMENTATION_PLAN.md).

Local Phase 10 tooling checks are source probes, not a Windows build or
target-acceptance run. The initial tooling suite reported 10 passed and 4
skipped. The later strict source acceptance passed its fixed offline mock
flow, with 11 passed and 3 symlink-creation skips in the focused suite. The
latest tooling/credential follow-up reported 30 passed and 4 symlink/reparse
capability skips, plus two credential-notice metadata checks. Its separate
Windows source-mode system-credential-store sentinel CRUD and cleanup probe
passed without provider or network use. These source probes do not establish
frozen credential-store behavior, a target build, platform-lock capture,
frozen acceptance, Windows 11 qualification, or Windows CI results. Preparation
and test input digests are snapshots, not candidate build identities. See the
[initial tooling preparation](evidence/v1/phase-10/tooling-preparation.json),
[strict source follow-up](evidence/v1/phase-10/strict-source-followup.json),
and [latest tooling review follow-up](evidence/v1/phase-10/tooling-review-followup.json).

The source checks above do not mark any Windows target row as passed. Stage 0
is the preparation work that can be done before running the target build and
**has been done**; stages 1–3 each say exactly which matrix rows they can
close and which they cannot.

## Stage 0 — completed here, no Windows host required

**PKG-06** records the initial `build_windows.ps1` defect: it used ambient
`python` without an isolated environment, installed only `requirements.txt`
(the runtime set), and then called `pytest` and `PyInstaller`, neither of which
was in that set. A host with those tools installed globally could also have
built from unpinned versions. The completed Stage 0 items below address that
historical finding.

Done:

- **Isolated build venv.** `build\windows\venv`, created from a host Python
  the script verifies is 3.11+ (ENV-01), preferring the `py -3` launcher
  because the bare `python.exe` on `PATH` is often the Microsoft Store alias
  stub. Nothing after step 1 uses the ambient interpreter.
- **`requirements-dev.txt`, not `requirements.txt`.** The split is
  deliberate — nothing in the dev set may reach a payload — and the bug was
  installing one half and calling tools from the other.
- **PyInstaller output confined to `build\windows\`** via `--distpath` /
  `--workpath`, so a build cannot pick up another's leftovers.
- **Bundled Qt platform plugins are hard-checked** (`qwindows.dll`,
  `qoffscreen.dll`), the counterpart of the Linux Wayland/xcb/offscreen
  check. A bundle missing one starts on the build machine and dies on the
  user's.
- **`BUILD_PROVENANCE-windows.txt`**, matching the Linux file: archive,
  SHA-256, version, commit and clean/dirty state, OS, both Python versions,
  PyInstaller version, whether the suite ran, and the resolved package set.
- **`-CaptureLock`** writes `requirements-lock-windows.txt` from the build
  venv. It has to be captured on Windows rather than hand-written: the
  transitive set genuinely differs (`pefile`, `pywin32-ctypes`).
- **`-SkipTests`** for packaging iteration, which marks the build
  "not release-qualified" in its own provenance file.
- **Acceptance harness**, in `docs/evidence/desktop-release/phase-f/`:
  `frozen_acceptance.ps1` (sections 1–8 mirroring the Linux run, plus
  Windows-only long-path, drive-relative-path and `%LOCALAPPDATA%` checks)
  and `export_check.ps1`. `interactive_session_check.py` needs no port.

The source-mode helper checks above validate selected tooling paths; they do
not establish a candidate's build, archive, lock capture, frozen checks or
Windows 11 qualification. Candidate-specific outcomes are recorded with the
companion artifact provenance and acceptance reports.

## Stage 1 — GitHub Actions `windows-latest`

The `.github/workflows/windows.yml` acceptance stage invokes
`build_windows.ps1`, the frozen acceptance harness with
`-SkipInteractive`, and the independent export checker; on success it uploads
the staged bundle, ZIP, checksum, provenance and Windows dependency lock. The
build, acceptance and export logs travel with the artifact, and failure logs
plus any lock are retained for diagnosis. The first run captures
`requirements-lock-windows.txt`; review and commit that artifact before later
runs consume the lock. A successful native run is required before marking
Stage 1 complete.

Two independent Luna reviewers passed the local CI preparation. Their review
does not substitute for executing the workflow on the native runner.

Closes: the build pipeline itself, the full suite on Windows, both
executables freezing, the packaged smoke run (all 14 steps, including
autosave recovery, corrupt-project handling and posed export), the recipe
CLI's success and failure shapes, relocation, read-only install, Unicode
paths, payload hygiene, long paths and the drive-relative path check.

Cannot close: **real GPU rendering** (hosted runners have no GPU — ModernGL
falls back, which tests the fallback and not the GPU path), **interactive
usability**, or **DPI scaling**. Run it with `-SkipInteractive`, which
reports those as SKIP. A green CI build is not a Windows support claim.

Expect friction from Defender on the onefile CLI and from the runner's
short-path `TEMP`.

## Stage 2 — a clean Windows VM

The supported minimum is Windows 11 x86-64. Test a clean Windows 11 machine
with no Python at all, first-run behaviour,
SmartScreen on an unsigned executable, a real `Program Files` install,
OneDrive-redirected `Documents`, per-monitor DPI at 100/125/150/200%, and
the interactive pass via `interactive_session_check.py`.

Cannot close: the **actual GPU frame** row. GPU passthrough for the
reference machine's integrated Radeon is not realistic, so the VM yields a
software rasteriser. That row stays BLOCKED even after a clean VM run — a
software frame is not evidence about a GPU path, and recording it as one is
exactly the substitution this project has refused elsewhere.

## Stage 3 — one real Windows 11 machine

The only thing that closes the last row: confirm the status bar reports
`GPU (moderngl)` rather than the software fallback, run the interactive
pass, capture screenshots at each scale factor, and diff a GPU render
against a forced-software render of the same scene — the comparison that
found GPU-05 and RENDER-01 on Linux.

## Exit criteria

Each Windows row in the acceptance matrix flips only with the executed
command and its output stored under
`docs/evidence/desktop-release/phase-f/`. No row flips on the strength of
CI or a VM standing in for hardware. `RELEASE_NOTES.md`,
`SUPPORTED_PLATFORMS.md` and `CAPABILITY_MATRIX.md` are updated per stage
as rows actually close, not in advance.

Stages 1–3 may produce Windows test candidates and logs. A candidate is not a
supported release. Publish Windows as a supported V1 target only after the
required CI/build, clean-machine, interactive, scaling, and physical-GPU gates
pass for the target Windows 11 configuration. This status is tracked
separately from the Mint preview and from the historical MX artifact.
