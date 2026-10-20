# V1 Phase 3 Windows path-normalization follow-up review

Date: 2026-10-13  
Baseline HEAD: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`  
Environment: Windows 10 IoT Enterprise LTSC x86-64, build 19044; CPython 3.12.14; project `.venv`.

## Scope and identity

Fresh independent review of the reopened `_verify_tree` Windows path-normalization change only. I read the approved plan's sections 6 and 12, Phase 3 `INDEPENDENT_REVIEW.md`, `IMPLEMENTATION.md`, `tests.txt`, `identity.json`, and the preserved `identity.initial-review.json`. I reviewed the changed worker and regression source, the unchanged `core/paths.py` helper, and the Windows `ntpath.realpath` implementation. I made no source or test edits. The only file written by this review is this note.

Every hash listed in current `identity.json` matched the working tree. The relevant current hashes are:

| File | SHA-256 |
| --- | --- |
| `am3d/ai/worker.py` | `184df9bf7555ee9496120e30ae4aab3bb1a9e3807326721e092b2313ced7fae7` |
| `am3d/ai/test_worker.py` | `43623bbbc26c10b753e21b79e9d6ae10249a8dd8b1cf111dc87159d327804db9` |
| `am3d/core/paths.py` | `c7287fc36c03a25d58e53640b0de71d1443511e9d05d7f8f581974cad4295f9d` |
| `am3d/core/test_paths.py` | `ddd77f48f5027b472a2676580be68952dfaaf49bf54dc6ce6a0ad9dd6452227c` |

`identity.initial-review.json` retains the pre-correction hashes for the worker, worker tests, and the earlier Phase 3 evidence. The current identity records the later corrections. No commit or push was made.

## Finding and review classification

**Reproduced defect, narrowly scoped: false containment rejection from mismatched Windows path spellings.** The deterministic regression at `am3d/ai/test_worker.py::test_tree_audit_normalizes_transient_extended_realpath_prefix` creates an ordinary-drive root and an extended-prefix child. Raw `ntpath.commonpath` raises `ValueError` (“Paths don't have the same drive”) for this contained file; `_verify_tree` succeeds after passing both `realpath` results through `extended_io_path`. The original intermittent worker failure's traceback was not captured, so this confirms the reported exception mechanism and reproducer, not the exact historical stack.

The installed CPython 3.12.14 `ntpath.py` source at `realpath` (lines 681–731) supports the race explanation. It first calls `_getfinalpathname`, then, when the original input lacked `\\?\`, strips that prefix and probes the ordinary spelling again. If a file disappears before the second probe, the `OSError` winerror differs from the first successful probe's `initial_winerror == 0`, so the function retains the extended spelling for that child. A separate root lookup can successfully strip the prefix. Pairing those results directly in `commonpath` can raise even though the child is under the root. The source confirms the mechanism; no live delete-at-the-probe-window traceback was captured.

**Source-reasoned risk reviewed: no new containment bypass found.** The changed helper calls are restricted to the already resolved host root and resolved tree entries in `_verify_tree`; the raw recipe path policy still uses `classify_portable_relative_path`, and `core/paths.py` is unchanged. The normalization makes ordinary absolute drive/UNC paths and already extended drive/UNC paths comparable before containment checks. Windows `ntpath.commonpath` accepts case differences for a same-drive root and same-share UNC root; different drives, different drive/share forms, and a `GLOBALROOT` device namespace raise `ValueError` in the checks below. Those errors fail the audit/worker instead of becoming a successful containment comparison. `extended_io_path` rejects a `\\.\` Win32 device path. Reparse-point checks still run for the root, walked directories, and files. The existing same-account path-replacement TOCTOU limitation remains the documented boundary for this data-only worker; this normalization does not address it.

Final auditing remains strict: `_verify_tree` is called after child exit with `include_scratch=False`, so a vanished deliverable still raises `FileNotFoundError`. The regression for a vanished live scratch/deliverable entry tolerates it only during live polling, and its final-audit assertion remains strict. Portable filename collision checks remain in `audit_component`; no comparison-normalization change bypasses NFC/casefold collision detection.

**Suggestion, non-blocking:** the checked-in deterministic race test covers the drive-prefix form. The bounded manual check below also covers mixed-prefix UNC case folding. A future test-only extension could parameterize the deterministic regression for UNC paths if a reliable Windows share fixture is available. This review does not request a code or test change.

## Commands and results

The focused path, lifecycle, and ordinary-worker checks passed:

```text
.venv\Scripts\python.exe -m pytest am3d\ai\test_worker.py::test_tree_audit_normalizes_transient_extended_realpath_prefix am3d\ai\test_worker.py::test_live_tree_audit_tolerates_vanished_private_staging_entries am3d\ai\test_worker.py::test_valid_worker_is_private_native_reopens_and_derived_paths_are_opaque am3d\ai\test_worker.py::test_cancelled_worker_is_terminated_promptly_and_never_successful am3d\ai\test_worker.py::test_windows_cancel_terminates_descendant_processes -q -rs
6 passed in 15.79s
```

The host-selected deep output-root regression passed with a staged artifact path longer than 260 characters:

```text
.venv\Scripts\python.exe -m pytest am3d\ai\test_worker.py::test_worker_succeeds_with_deep_host_output_root -q
1 passed in 2.70s
```

The link, junction, and portable-collision checks produced:

```text
.venv\Scripts\python.exe -m pytest am3d\ai\test_worker.py::test_output_root_junction_is_rejected_without_following_it am3d\ai\test_worker.py::test_output_root_symlink_is_rejected_without_following_it am3d\ai\test_worker.py::test_final_tree_audit_rejects_portable_filename_collisions am3d\ai\test_worker.py::test_final_tree_audit_rejects_symlink -q -rs
2 passed, 2 skipped in 1.05s
```

The directory-junction rejection and portable filename collision tests passed. The output-root symlink and final-tree file symlink fixtures skipped because this account lacks Windows symlink privilege (`WinError 1314`); the recorded earlier directory-junction test passed. This review does not claim empirical coverage for the skipped symlink fixtures.

I also ran a PowerShell here-string through `.venv\Scripts\python.exe -`. It asserted that `ntpath.commonpath` treats case-varied extended drive and UNC descendants as contained; rejects different drives, UNC shares, and `GLOBALROOT` device paths with `ValueError`; that `extended_io_path` rejects `\\.\C:\device-path`; that a normal nested file produces the expected manifest; and that a mocked resolved child outside the root raises `PolicyError(code="unsafe_output_tree")`. All assertions passed. The executable check was:

```python
import os, tempfile, ntpath
from pathlib import Path
from unittest.mock import patch
from am3d.ai import worker
from am3d.core.paths import extended_io_path

for root, child in [
    (r"\\?\C:\Root\Attempt", r"\\?\c:\root\attempt\file.png"),
    (r"\\?\UNC\Srv\Share\Root", r"\\?\unc\srv\share\root\file.png"),
]:
    assert ntpath.commonpath((root, child)) == root
for root, child in [
    (r"\\?\C:\Root\Attempt", r"\\?\D:\Root\Attempt\file.png"),
    (r"\\?\C:\Root\Attempt", r"\\?\UNC\srv\share\Root\file.png"),
    (r"\\?\C:\Root\Attempt", r"\\?\GLOBALROOT\Device\HarddiskVolume1\file.png"),
]:
    try:
        ntpath.commonpath((root, child))
    except ValueError:
        pass
    else:
        raise AssertionError("different drive/share/device namespace compared as contained")
try:
    extended_io_path(r"\\.\C:\device-path")
except ValueError:
    pass
else:
    raise AssertionError("Win32 device namespace accepted by host path helper")

with tempfile.TemporaryDirectory() as tmp:
    base = Path(tmp)
    root = base / "attempt"
    nested = root / "nested"
    nested.mkdir(parents=True)
    leaf = nested / "valid.png"
    leaf.write_bytes(b"ok")
    manifest, size = worker._verify_tree(root)
    assert manifest == [{"path": "nested/valid.png", "format": "png", "size_bytes": 2}] and size == 2
    outside = base / "outside.png"
    outside.write_bytes(b"outside")
    original = worker.os.path.realpath
    target = os.path.normcase(os.fspath(leaf))
    def escape_one_leaf(path, *args, **kwargs):
        if os.path.normcase(os.fspath(path)) == target:
            return original(outside, *args, **kwargs)
        return original(path, *args, **kwargs)
    with patch.object(worker.os.path, "realpath", escape_one_leaf):
        try:
            worker._verify_tree(root)
        except worker.PolicyError as exc:
            assert exc.code == "unsafe_output_tree"
        else:
            raise AssertionError("resolved outside artifact accepted")
```

The full `179 passed, 2 skipped` Phase 3 aggregate was not rerun. This review did not exercise frozen spawning, Windows 11, Mint, or Phase 4 publication/checker behavior.

## Local verdict

**PASS for the reopened Phase 3 Windows path-normalization gate, on this source run.** The deterministic mismatched-prefix failure is reproduced and fixed; a valid nested output, deep host root, outside-resolved child, case-varied drive/UNC spelling, different drive/share/device spelling, portable collision, junction check, strict final audit, and worker lifecycle checks behaved as expected. This is local source evidence only. It does not establish Windows 11, Mint, frozen-build, GPU, full-suite-after-fix, or release acceptance.
