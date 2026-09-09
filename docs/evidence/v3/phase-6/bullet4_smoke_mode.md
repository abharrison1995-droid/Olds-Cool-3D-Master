# Phase 6 bullet 4 — packaged GUI smoke mode

Evidence for: "Add real packaged smoke mode exercising blank startup,
primitive/profile creation through commands, save/reopen, weighted action
playback, transformed export, material references, and multi-object software
rendering. Produce a machine-readable manifest; fail build on
timeout/nonzero/missing evidence." (`docs/V3_FUNCTIONAL_IMPLEMENTATION_PLAN.md`
Phase 6.)

Raw artifacts referenced below are under `docs/evidence/v3/phase-6/bullet4/`.

## What was implemented

- [am3d/ui/smoke.py](../../../../am3d/ui/smoke.py) — `run_smoke_test()` drives a
  real `MainWindow` through 8 steps (`STEPS`): `blank_startup`, `new_project`,
  `primitive_and_profile_creation`, `material_reference`,
  `rig_and_weighted_action_playback`, `multi_object_software_rendering`,
  `save_and_reopen`, `transformed_export`. Each step is recorded independently
  (`not_run` → `ok`/`failed`) and the run stops at the first failure, so a
  partial run is visible as incomplete rather than silently absent.
- [am3d/ui/app.py](../../../../am3d/ui/app.py) `main()` — a packaged
  `--smoke-test [--out PATH]` mode that runs the workflow headlessly, prints
  the JSON manifest to stdout, optionally writes it to `PATH`, and returns
  `0`/`1` for pass/fail without ever showing a persistent window.
- [am3d/ui/__main__.py](../../../../am3d/ui/__main__.py) — switched to an
  absolute import; PyInstaller's frozen bootstrap runs this as `__main__`
  without `__package__`, so the previous relative import raised at startup in
  the packaged build only (a windowed/`console=False` build swallows that
  silently instead of showing a traceback).
- [build_windows.ps1](../../../../build_windows.ps1) Step 7 — after staging the
  release folder, launches the real packaged `.exe` with
  `--smoke-test --out <releaseDir>\smoke_manifest.json` under
  `QT_QPA_PLATFORM=offscreen`, with a 60s timeout. It fails the build on: a
  timeout (process killed, non-zero exit), a non-zero exit code, a missing
  manifest file, or any manifest step whose `status != "ok"`.
- [am3d/ui/test_smoke.py](../../../../am3d/ui/test_smoke.py) — source-level
  regression tests for the same code path (all steps pass; a monkeypatched
  failure is recorded and halts the run; `--out` writes to a spaced path;
  malformed `--out` fails cleanly). These run under the ordinary pytest suite,
  not just at packaging time.

## Defects found and fixed during this review pass

1. **`QApplication` double-construction crash.** `main()` unconditionally did
   `QApplication(raw_argv)`. Any second in-process call (e.g. a test, or an
   embedder) crashed with `RuntimeError: libshiboken: Please destroy the
   QApplication singleton before creating a new QApplication instance.` This
   was caught by the new `test_main_smoke_test_writes_manifest_to_out_path`
   regression test (it failed until fixed, because an earlier smoke test in
   the same process already held a `QApplication`). Fixed to
   `QApplication.instance() or QApplication(raw_argv)`, matching the pattern
   `am3d/ui/smoke.py` already used.
2. **Unhandled `IndexError` on a bare `--out`.** `raw_argv[i + 1]` with no
   following argument raised an uncaught `IndexError` before `QApplication`
   was even constructed. In the packaged `console=False` build this is a
   crash with no attached console to show the traceback in. Fixed to validate
   and print `"error: --out requires a PATH argument"` to stderr with exit
   code 2. Verified against the actual packaged `.exe` (see "Malformed
   arguments" below) — exit code 2, correct stderr message, no hang.

## Full source suite

```bash
python -m pytest am3d/ -q --tb=short
```
Result: **484 passed, 4 warnings** in ~48-54s (pre-existing `QMouseEvent`
deprecation warnings in `test_dopesheet.py`, unrelated to this change). This
is 482 (recorded before this session) + 2 new tests added here
(`test_main_smoke_test_writes_manifest_to_out_path`,
`test_main_out_without_value_errors_cleanly`).

## Build from outside the repo root

Run from `C:\Users\P50\Desktop` (not the repo root, which is
`C:\Users\P50\Desktop\Olds-Cool-3D-Master`):

```powershell
cd C:\Users\P50\Desktop
& "C:\Users\P50\Desktop\Olds-Cool-3D-Master\build_windows.ps1"
```

Full transcript: `bullet4/build_windows_full_log.txt`. Relevant tail:

```
Step 5: Staging release folder...
Release staged at: C:\Users\P50\Desktop\Olds-Cool-3D-Master\release\3D MASTER 2005 Beta

Step 6: Running packaged smoke test...
  Executable found: ...\3D MASTER 2005.exe
  File size: 12 MB
  Recipe CLI found: ...\am3d-recipe.exe
  Recipe CLI validated the bundled example recipe.

Step 7: Running packaged GUI smoke mode...
  Smoke test passed: 8 steps, all ok.

=== Build complete! ===
```

`$PSScriptRoot`-based path resolution means the script correctly resolved the
repo root and build/dist/release paths despite being invoked from `Desktop`.
(Note: pip's "new release available" notice under PowerShell 5.1's
`NativeCommandError` wrapping — see `build_windows.ps1`'s `Invoke-Native`
comment — appears in the log as an apparent error line but does not fail the
build; `$LASTEXITCODE` after the pip/PyInstaller calls was checked and was
`0` throughout.)

## Packaged manifest produced by the build

`bullet4/packaged_smoke_manifest.json` (copied from
`release\3D MASTER 2005 Beta\smoke_manifest.json`): `"ok": true`, all 8 steps
`"status": "ok"`, `artifacts.rendered_objects: 3`,
`artifacts.export_size_bytes: 330393`. stdout/stderr captured to
`bullet4/packaged_smoke_stdout.txt` (the same JSON manifest) and
`bullet4/packaged_smoke_stderr.txt` (empty).

## Manual verification: `--out` to a path containing spaces

Independent of the release folder itself already containing spaces
(`3D MASTER 2005 Beta`), the packaged `.exe` was invoked directly with
`--out` pointing at a different path also containing spaces:

```
exe:  C:\Users\P50\Desktop\Olds-Cool-3D-Master\release\3D MASTER 2005 Beta\3D MASTER 2005.exe
out:  C:\Users\P50\Desktop\am3d smoke evidence dir\manual_smoke_manifest.json
```

via a raw `System.Diagnostics.ProcessStartInfo` (as `build_windows.ps1` does,
for the same quoting reasons documented in its Step 7 comment), under
`QT_QPA_PLATFORM=offscreen`, 60s timeout.

Result: `finished=True exitcode=0`, manifest written to the spaced path, all 8
steps `"ok"`, stdout carried the manifest JSON, stderr empty. Copies:
`bullet4/manual_spaced_path_manifest.json`,
`bullet4/manual_spaced_path_stdout.txt`,
`bullet4/manual_spaced_path_stderr.txt`.

## Manual verification: build-failure detection

Ran the same packaged `.exe` with a malformed `--smoke-test --out` (no path
value) to confirm the fix above holds in the actual frozen build, not just
under pytest:

```
exitcode=2
stderr: error: --out requires a PATH argument
```

No manifest was written and the process did not hang — `build_windows.ps1`'s
Step 7 would correctly report this as a build failure (non-zero exit code and
missing manifest, both explicit failure conditions in the script).

The timeout path (a genuine hang) and the "manifest present but a step
failed" path were not separately re-triggered against the real `.exe` in this
pass — they are exercised by `test_smoke_test_manifest_records_a_failing_step`
in `am3d/ui/test_smoke.py` at the source level, and Step 7's own
`$incompleteSteps`/timeout logic was read and is unchanged from the prior
session's implementation review.

## Release package listing

`bullet4/release_package_listing.txt` — top two levels of
`release\3D MASTER 2005 Beta\`: `3D MASTER 2005.exe`, `am3d-recipe.exe`,
`_internal\` (PyInstaller's onedir payload), `examples\`, `LICENSES\`,
`README.txt`, plus the smoke-mode outputs (`smoke_manifest.json`,
`smoke_stdout.txt`, `smoke_stderr.txt`) that Step 7 produced.

## Limitations

- All verification above ran on the build machine itself (Windows
  10.0.19044), not a clean VM/profile without Python — that is Phase 6
  bullet 5's explicit requirement, tracked separately below.
- The GUI smoke mode runs under `QT_QPA_PLATFORM=offscreen`; it does not
  verify on-screen rendering with a real display driver, only the software
  rasterizer path already forced by `win.viewport.force_software = True` in
  `multi_object_software_rendering`.
- The required Phase 6 gate (four-agent Luna review) has not been run — see
  `gate_evidence.md` in this directory for its status.
