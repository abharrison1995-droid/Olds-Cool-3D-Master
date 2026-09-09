# Phase 6 bullet 5 — release ZIP, checksums, and relocated verification

Evidence for: "Generate release ZIP and checksums. Run on a clean Windows
profile/VM without Python, from paths containing spaces/non-ASCII, using
source-independent inputs." (`docs/V3_FUNCTIONAL_IMPLEMENTATION_PLAN.md`
Phase 6.)

Raw artifacts referenced below are under `docs/evidence/v3/phase-6/bullet5/`.

## What was implemented

Added two new steps to [build_windows.ps1](../../../../build_windows.ps1),
after the existing packaged-smoke-mode step:

- **Step 8 — Release ZIP and checksum.** Reads the app version from
  `am3d.__version__`, zips the staged release folder
  (`release\3D MASTER 2005 Beta\`) as a single top-level entry into
  `release\3D-MASTER-2005-Beta-<version>-win64.zip` via `Compress-Archive`,
  then computes its SHA-256 with `Get-FileHash` and writes it next to the
  ZIP in `sha256sum`-compatible format (`<hash> *<filename>`).
- **Step 9 — Verification from a relocated path.** Extracts that ZIP to a
  throwaway directory under `%TEMP%` whose name deliberately contains a
  space and a non-ASCII character, independent of the repo/build/dist/release
  directories the build itself just produced. From there it: (a) copies the
  bundled minimal recipe example to a *new* file inside the verify directory
  (not a path back into the repo) and validates it with the relocated
  `am3d-recipe.exe`, and (b) re-runs `--smoke-test --out <spaced/non-ASCII
  path>` against the relocated `3D MASTER 2005.exe` under
  `QT_QPA_PLATFORM=offscreen`, checking exit code, manifest presence, and
  that every step is `"ok"` — the same failure conditions Step 7 already
  enforces. The verify directory is removed in a `finally` block regardless
  of outcome.

## Full build run (includes Steps 8 and 9)

```powershell
cd C:\Users\P50\Desktop
& "C:\Users\P50\Desktop\Olds-Cool-3D-Master\build_windows.ps1"
```

Full transcript: `bullet5/build_windows_full_log_with_packaging.txt`. Tail:

```
Step 8: Packaging release ZIP and checksum...
  Release ZIP: C:\Users\P50\Desktop\Olds-Cool-3D-Master\release\3D-MASTER-2005-Beta-0.2.0b1-win64.zip
  SHA-256: 1BE2C694A7FEF522D922AB62C84E9E091D8CE297559E40D24DA6B8AD740F7E4D

Step 9: Verifying release contents from a relocated path...
{"ok": true, "validated": true, "name": "minimal_cube", "version": 1, "error_records": []}
  Verified from: C:\Users\P50\AppData\Local\Temp\am3d verify éé 58368bc2
  Relocated recipe CLI and GUI smoke test both passed.

=== Build complete! ===
```

(The "Verified from" path shown in the PowerShell/terminal log as
`Ã©Ã©` is a console-encoding display artifact of relaying non-ASCII text
through this session's terminal capture, not a functional failure — the
directory was genuinely created and used with the literal `é é` characters:
`Compress-Archive`/`Expand-Archive`/`.NET` process launch all operated on the
actual Unicode path, and the extraction, recipe validation, and GUI smoke
test all completed successfully against it.)

## Independent checksum verification

The build machine's own `Get-FileHash` and a separately invoked `sha256sum`
(via the Bash tool, a different hashing implementation) were compared against
the checksum file the build wrote:

```
$ sha256sum release/3D-MASTER-2005-Beta-0.2.0b1-win64.zip
1be2c694a7fef522d922ab62c84e9e091d8ce297559e40d24da6b8ad740f7e4d *release/3D-MASTER-2005-Beta-0.2.0b1-win64.zip

$ cat release/3D-MASTER-2005-Beta-0.2.0b1-win64.zip.sha256
1be2c694a7fef522d922ab62c84e9e091d8ce297559e40d24da6b8ad740f7e4d *3D-MASTER-2005-Beta-0.2.0b1-win64.zip
```

Hashes match. Full recompute output: `bullet5/independent_sha256sum_recompute.txt`.

## ZIP contents verification

Inspected programmatically with Python's `zipfile` (independent of the
PowerShell `Compress-Archive` that created it):

- 304 entries total.
- Single top-level folder: `3D MASTER 2005 Beta` (so extracting reproduces
  the same layout Step 5 staged, not loose files at the archive root).
- Contains `3D MASTER 2005.exe`, `am3d-recipe.exe`, and the smoke-mode
  outputs (`smoke_manifest.json`, etc.) from the build that produced it.

Full listing: `bullet5/zip_contents_listing.txt`.

## Packaged recipe entry point and software-only operation

Re-verified from the *relocated, extracted* copy (Step 9), not just in place
in the release folder:

- `am3d-recipe.exe --recipe <source-independent copy> --validate-only` →
  `{"ok": true, "validated": true, "name": "minimal_cube", "version": 1,
  "error_records": []}`, exit code 0. The recipe file was copied into the
  throwaway verify directory rather than referenced from the repo, so this
  does not depend on the repo tree still being present at its original path.
- `3D MASTER 2005.exe --smoke-test --out <verify dir>\verify_smoke_manifest.json`
  under `QT_QPA_PLATFORM=offscreen` (i.e. no GPU/display driver involved) →
  exit 0, manifest present, all 8 steps `"ok"`. This is the same
  software-only rendering path bullet 4 already exercises
  (`multi_object_software_rendering` forces `win.viewport.force_software =
  True`), now proven to work after the app has been moved off the build
  machine's own directory tree.

## Limitations — explicit unpassed gate items

Per the plan's acceptance note ("An unavailable VM or backend is an explicit
unpassed gate, not inferred success from offscreen tests"), the following
were **not** performed and are recorded as pending, not passed:

- **Clean Windows profile/VM without Python.** All verification above ran on
  the same development machine that has Python 3.14.6, PySide6, and the full
  toolchain installed. No clean VM or fresh user profile without Python was
  available in this environment. This means dependency bundling correctness
  (e.g. a DLL PyInstaller silently picked up from the dev machine's Python
  install rather than truly embedding it) is not fully ruled out by this
  evidence alone.
- **GPU/hardware-accelerated rendering path.** Both the in-place and
  relocated smoke runs used `QT_QPA_PLATFORM=offscreen` (software Qt
  platform plugin) and `viewport.force_software = True` (software
  rasterizer). The optional GPU/ModernGL renderer path referenced in Phase 6
  bullet 2 ("verify software-only operation") is exercised as
  software-only by design here, but a real GPU-backed render was not
  separately verified in this pass.
- The spaces/non-ASCII path requirement is satisfied (see above); a fully
  non-ASCII (no ASCII characters at all) path and a true clean-profile run
  remain open if a suitable environment becomes available.
