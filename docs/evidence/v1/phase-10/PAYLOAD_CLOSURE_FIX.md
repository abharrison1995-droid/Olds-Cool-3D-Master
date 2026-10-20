# Phase 10 bounded payload-closure corrections

Status: implementation and focused tooling checks complete; a fresh locked
frozen build and all frozen acceptance remain pending. This receipt does not
qualify a release candidate.

The work began from checkout HEAD `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`
with the authorized V1 working-tree changes. The Phase 10 plan requires actual
frozen-payload and target-platform evidence; see section 10 of
`docs/V1_MASTER_IMPLEMENTATION_PLAN.md` and the independent dispositions in
`PACKAGING_REVIEW.md`. The build and investigation artifacts cited below are
from the earlier retry1 source digest `840c4e12518e9d279cf713c4e5f0fba3701c3bf9b4ffb29a85d31ee5eedfe41f`.
They diagnose packaging defects but do not identify the post-fix source or a
candidate.

## Changes

Both PyInstaller specs now exclude the modules shown by the retry1 GUI/CLI
Analysis TOCs and dependency graph to be development-only or optional command
paths: `pytest`, `_pytest`, AnyIO's `pytest_plugin`, HTTPX's `_main` command,
Pygments, `packaging`, `setuptools`, `_distutils_hack`, and `distutils`. In the
GUI graph, `_pytest.outcomes` was reached only from AnyIO's optional
`TestRunner`; Pygments was reached only from HTTPX's optional console command;
`packaging` arrived through those test/build paths; setuptools was present
through PyInstaller's build-time distutils shim. The product's supported
HTTPX/AnyIO request path is retained. The CLI's existing Qt and GPU exclusions
remain in place. Retry2's realized TOCs must still confirm these exclusions
and the runtime closure before payload closure is accepted.

The GUI spec replaces only the generated `pyi_rth_pyside6` source hook with an
owned guarded copy of PyInstaller's normal setup. The two fixed Qt-free
dispatches (`--internal-ai-worker` and `--ai-self-test`) return before importing
PyInstaller's Qt helper; ordinary launches continue through the same binding
check, Qt environment setup and embedded `qt.conf` setup. Source tests exercise
both branches with import-blocking and controlled stubs. The retry1 frozen
self-test had already failed before application dispatch with
`qt_loaded_before_fixed_dispatch`; only a new frozen binary can show that the
guard solves it without weakening the application check.

The runtime notice helper now prefers the exact base-prefix `LICENSE.txt` for
CPython. On Linux only, if that file is absent, it accepts the selected
interpreter's `sysconfig` standard-library `LICENSE.txt` when that configured
directory resolves inside `sys.base_prefix`, or one of three fixed
major/minor-versioned copyright files under that base's `share/doc` tree:
`pythonX.Y/copyright`, `pythonX.Y-minimal/copyright`, and
`libpythonX.Y-minimal/copyright`. A Linux symlink is accepted only when its
resolved target is an approved regular base/stdlib license or one of those
exact versioned copyright files within the selected base. The manifest and human-readable NOTICE record the exact relative source path
and resolved target for aliases; a distro copyright is labeled as such rather
than called an upstream CPython license.
Windows remains fail-closed on the base-prefix `LICENSE.txt`. PyInstaller's
installed wheel `COPYING.txt` is copied verbatim with version and SHA-256, and
is described as coverage for bundled bootloader/runtime-hook code rather than
the entire build tool as runtime. The fixed runtime distribution list remains
unchanged. The retry1 payload inventory is historical; final notice coverage
must be checked against fresh TOCs and staged files.

The Windows build wraps both PyInstaller invocations in a temporary dependency
search `PATH` containing only the selected host Python directory, the isolated
venv Scripts directory and the actual Windows root/System32 directories. It
fails closed if a trusted directory is missing and restores the original PATH
in `finally`; the other build steps run with the original environment. A
focused PowerShell regression injects a fake ambient directory containing an
`icuuc.dll` sentinel, confirms that it is absent from PyInstaller's search
path, and proves exact PATH restoration when the action throws.

The packaging bootstrap's singleton artifact handling now materializes both
`Get-ChildItem` result pipelines as arrays before reading `.Count`. Other
script count sites were checked for array-safe handling. Retry1's CLI emitted
one artifact and then strict mode failed on `$produced.Count` because
PowerShell had returned a scalar `FileInfo`; the one-item regression exercises
that case. A corresponding array materialization was applied to relocated CLI
artifacts after the same scalar review.

## Retry1 diagnosis and limits

The retry1 Analysis/Collect TOCs showed that `QtCore.pyd`, `Qt6Core.dll`,
`pyside6.abi3.dll`, and `shiboken6.abi3.dll` came from the isolated venv's
PySide6/shiboken6 6.11.2 wheels. `Qt6Core.dll` imports unsuffixed ICU symbols,
while the ambient `icuuc.dll` selected into the payload came from the host
Codex runtime's Poppler `Library/bin` directory and exported ICU-78-suffixed
symbols. Retry1's GUI therefore raised `ImportError: DLL load failed while
importing QtCore: The specified procedure could not be found` before smoke
artifact setup. Root's bounded controlled diagnostic temporarily removed only
that candidate's `icuuc.dll` and `icudt78.dll`, ran the same GUI
`--smoke-test`, and observed exit 0 with all 14 steps passing within 60 seconds;
both files were restored with their recorded hashes. This supports the
dependency-resolution diagnosis. It was a modified, unqualified historical
artifact, not a candidate acceptance run; it does not establish startup
latency or clean-host behavior.

Retry2 must inspect the actual GUI and CLI TOCs and staged files to verify that
no ambient Poppler ICU entered the payload and that all Qt dependencies
resolve. The fresh frozen worker/self-test and normal GUI smoke remain
necessary. No dependency versions were changed, no system DLL was copied by
these corrections, and no existing evidence file was rewritten.

## Focused verification

Command:

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
build\windows\venv\Scripts\python.exe -m py_compile scripts\write_runtime_licenses.py scripts\pyi_rth_am3d_pyside6.py scripts\test_phase10_tooling.py; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; build\windows\venv\Scripts\python.exe -m pytest scripts\test_phase10_tooling.py -q --maxfail=1 -k 'runtime_license_writer_copies_exact or linux_interpreter_notice or linux_license_manifest or windows_interpreter_notice or frozen_specs_exclude or guarded_pyside6_runtime_hook or gui_spec_substitutes or windows_build_counts_singleton or windows_pyinstaller_path_excludes' --tb=short
```

Result: **18 passed, 29 deselected in 8.30s**. This includes the Linux
stdlib and fixed distro-copyright layouts, source/hash provenance, containment
and fail-closed cases, Windows-only interpreter notice behavior, frozen spec
exclusions, both guarded runtime-hook branches, the singleton artifact case,
and temporary PyInstaller PATH isolation/restoration. The PowerShell AST parse
for `build_windows.ps1` and `git diff --check` for the owned packaging files
also passed. No source full suite, PyInstaller build, lock promotion, or
release qualification was run by this change owner.

## Preserved retry1 evidence

| Artifact | SHA-256 | Use |
| --- | --- | --- |
| `bootstrap-retry1-payload-inventory.json` | `448efe9bbf16114b9d6e8fc308e35a5e10da3e2152755f232258524f02f7709b` | Historical GUI/CLI inventory; not the post-fix closure |
| `bootstrap-retry1-startup-investigation.json` | `9c071972634731220da70ea1000f0ae0d8bd2678229b72cc37108fcdff679882` | Retry1 GUI startup exception and bounded diagnostic state |
| `bootstrap-retry1-icu-probe.json` | `f796193b765d26a7e75abb15b4bc126e3d64bd11345de7e886a8f7fcc740b5d3` | Controlled ICU-removal smoke probe; modified old artifact |

The GUI smoke manifest SHA-256 is
`4807e1417834b35a4ccf43939725ba0c92ffd32b1550121d1c348365923c6c61`; it
records the 14 smoke steps. The separate root diagnostic receipt
`bootstrap-retry1-icu-probe.json` binds that manifest hash to retry1 source
digest `840c4e12518e9d279cf713c4e5f0fba3701c3bf9b4ffb29a85d31ee5eedfe41f`
and records restoration of `icuuc.dll`
(`a780df139ea375f0791a95178413efe9db0160a353541cfbda9a87ca2c6eab3a`) and
`icudt78.dll`
(`ceb6ff1e834fd7700d05d90e970420ebf3c31dcd5a2b573c6d131bc7bef9dfce`).
