# Windows acceptance plan

Windows is outside the Linux Mint 22.3 preview-candidate scope. No Windows
artifact is included or verified. For the later cross-platform release, the
Windows gate in `docs/evidence/desktop-release/phase-e/acceptance-matrix.md`
remains **BLOCKED** until a Windows machine or VM is available. This does not
erase historical Windows packaging work recorded in the V3 evidence. This
document is the route to a Windows artifact accepted on its native platform.

Nothing here marks a check as passed. Stage 0 is the work that could be done
without a Windows host and **has been done**; stages 1–3 each say exactly
which matrix rows they can close and which they cannot.

## Stage 0 — completed here, no Windows host required

`build_windows.ps1` could not have succeeded on a clean Windows machine. It
ran the ambient `python` with no isolated environment, installed only
`requirements.txt` (the runtime set), and then called `pytest` and
`PyInstaller` — neither of which is in that set. On any machine without
those installed globally it died at step 3; on a machine that happened to
have them, it built a release from whatever versions were lying around.
Recorded as **PKG-06**.

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

None of it has been executed. It is reviewed code, not evidence.

## Stage 1 — GitHub Actions `windows-latest`

`.github/workflows/windows.yml` is prepared but has not run from this
workspace. It invokes `build_windows.ps1`, the frozen acceptance harness with
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

Before this stage, select and document the supported minimum Windows release.
Test that minimum and the current supported Windows release; they may be the
same version if that is the declared support range. This adds: a genuinely
clean machine with no Python at all, first-run behaviour,
SmartScreen on an unsigned executable, a real `Program Files` install,
OneDrive-redirected `Documents`, per-monitor DPI at 100/125/150/200%, and
the interactive pass via `interactive_session_check.py`.

Cannot close: the **actual GPU frame** row. GPU passthrough for the
reference machine's integrated Radeon is not realistic, so the VM yields a
software rasteriser. That row stays BLOCKED even after a clean VM run — a
software frame is not evidence about a GPU path, and recording it as one is
exactly the substitution this project has refused elsewhere.

## Stage 3 — one real Windows machine

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

Until stage 3, no Windows artifact is produced or claimed. This restriction
applies to the current Mint preview and remains in force for a later
cross-platform release until the Windows gates pass.
