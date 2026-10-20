# Phase 10 bootstrap lock-proposal scope fix

Status: bounded script correction and focused regression pass. The Phase 10
bootstrap retry2 remains an overall failed script invocation; this follow-up
does not relabel it as complete or qualify a candidate.

## Retry2 finding and preserved limits

The retry2 bootstrap used `-CaptureLock` before
`requirements-lock-windows.txt` existed. `build_windows.ps1` defined its
`$normalizeLock` scriptblock only inside the existing-lock branch, then later
called it while writing the proposal. Under that intended no-lock bootstrap
path, PowerShell strict mode reported an unbound variable at
`build_windows.ps1:964`. The root invocation returned exit code 1.

A subsequent exactness audit found that the same normalizer also dropped
`setuptools` and `wheel` from both the installed-freeze comparison and the
proposed lock. Retry2 had 38 resolved build packages, including
`setuptools==84.0.0`; the old filter would have proposed only 37 entries and
would not have enforced the installed setuptools version. The original
retry2 invocation had already failed before completing lock capture, and no
incomplete lock was promoted.

The failure came after the retry2 source suite (1048 passed, 2 privilege skips,
4 warnings in 634.06 seconds), GUI and CLI builds, CLI validation/build and
structured malformed-input check, all 14 GUI smoke steps, the fixed offline AI
check, payload inventory, relocation checks, and archive creation. The actual
inventory recorded 916 GUI modules and 685 CLI modules, with no unexpected
test modules, no missing runtime-notice candidates, and no ambient Poppler
binaries. The relocated read-only write-denial check remains `UNPASSED` because
the host could not prove ACL restore capability; no ACL mutation was applied.
These successful subchecks remain evidence about their specific gates, not a
successful retry2 script or a locked candidate.

The preserved start record is
[`BOOTSTRAP_RETRY2_START.md`](BOOTSTRAP_RETRY2_START.md), with its frozen input
manifest in
[`BOOTSTRAP_RETRY2_SOURCE_INPUTS.json`](BOOTSTRAP_RETRY2_SOURCE_INPUTS.json).
The redirected console log is
[`bootstrap-build-retry2.log`](bootstrap-build-retry2.log) (SHA-256
`9dbdae3d8d7377fe836a628559c0212bf08fdbb51001d850d516d11e93c91fd3`). That
log contains the successful gate output and final input digest but not the
PowerShell host's strict-mode exception text; the failure line and exit code
were captured by the root runner separately.

## Bounded correction

`Normalize-Phase10LockEntries` now exists before the lock-presence branch. Both
the source-lock versus installed-freeze comparison and bootstrap proposal use
that same production function. It preserves trim/comment handling, exact
`name==version` validation, package-name normalization, and sorted output.
It filters out `pip` if a freeze input contains it, while retaining every
other pinned package, including `setuptools` and `wheel`. No lock file was
written or promoted by this fix.

The new regression extracts the marked production function from
`build_windows.ps1` and executes it under PowerShell strict mode. It begins
with a missing source lock, checks that the normalized bootstrap proposal
retains the retry2 `setuptools==84.0.0` and a `wheel` entry, installs an
equivalent fixture lock and verifies that the production lock/installed
comparison agrees with the proposal, then confirms that `setuptools==84.0.1`
remains detectably different. Source assertions also require the function to
be defined before the lock branch and used at all three production call sites.

## Verification

```powershell
.venv\Scripts\python.exe -m py_compile scripts\test_phase10_tooling.py
.venv\Scripts\python.exe -m pytest scripts\test_phase10_tooling.py -q --maxfail=1 -k windows_bootstrap_and_locked_build_share_lock_normalizer_under_strict_mode --tb=short
```

The first run verified the normalizer-scope correction before the package
completeness audit: **1 passed, 47 deselected in 2.70s**. After extending the
fixture to assert retained `setuptools`/`wheel` entries and a rejected
setuptools version mismatch, the final rerun against the retry2 setuptools
version reported **1 passed, 47 deselected in 1.82s**. The PowerShell AST parse of `build_windows.ps1` and
`git diff --check` for the owned files also passed. No full test suite, build,
lock capture, lock promotion, or release qualification was run for this
correction. The original retry2 remains failed; a fresh complete build using
the exact promoted lock remains required.
