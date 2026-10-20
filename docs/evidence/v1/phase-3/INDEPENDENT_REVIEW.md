# V1 Phase 3 independent security/resource review

Date: 2026-10-13  
Baseline HEAD: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`  
Working tree: uncommitted Phase 3 source and shared later-phase changes; no source or test files were changed by this reviewer.

## Reviewer identity and scope

Independent reviewer: Codex agent in a fresh review context (GPT-6 family per session metadata). The exact served model build and reasoning configuration are not exposed for independent verification.

Reviewed the approved plan's sections 4–6, 9, Phase 3, and section 12; `am3d/ai/policy.py`, `worker.py`, and their focused tests; the changed path helper and executor/writer paths and tests; the hidden UI entry dispatch; and the worker's checker-result gate. This was a source review on Windows 10 build 19044, AMD64, CPython 3.12.14. I did not repeat the focused suite or the five-run integration. Every file hash listed in `identity.json` matched the current working-tree bytes.

## Findings

**Reproduced defect — P3, invalid worker-protocol diagnostics.** In `am3d/ai/worker.py:301` an oversized input raises before `output_root` is assigned. The `PolicyError` handler at lines 407–410 then reads `output_root.name`, producing `UnboundLocalError` and no bounded result file. Reproduction: create a private current-working-directory containing `.ai_worker_input.json` with 1,048,577 bytes, then call `internal_worker_main([input_path, result_path])`. Observed: `UnboundLocalError: cannot access local variable 'output_root' where it is not associated with a value`; result file absent. This is fail-closed: it occurs before recipe execution or output-root writes, and the parent `run_worker` independently caps its protocol and reports a dead worker. It affects diagnostics for malformed/direct internal-protocol invocation, not policy enforcement or successful publication. Initialize the attempt identity independently of parsed request data, or omit it in this handler.

**Source-reasoned limitation — path-check TOCTOU.** `worker.py:131–149` and `152–199` audit links and real paths by pathname before and after child execution; the executor also resolves output paths at `executor.py:198–235`. A concurrent same-account process able to replace a checked directory between these operations could race a write. The model cannot select the outer output root or execute code, and this process boundary is explicitly not an OS sandbox or compromised-code boundary. I found no recipe-driven escape in the reviewed path derivation. Treat cross-process same-account races as outside the stated threat model; handle-based writes and explicit ACL enforcement would be a separate hardening scope if that model changes.

**Coverage limitation — symlink fixtures skipped.** The evidence records two skipped Windows symlink cases (`WinError 1314`); the directory-junction rejection test and outside sentinel check passed. The same `_has_reparse_point` check covers Windows reparse points in source, but the skipped output-root-symlink and file-symlink cases were not empirically exercised on this host. Keep that limitation visible; the source review did not establish an escape.

No other blocking Phase 3 policy, typed-limit, derived-name, output-tree, worker-lifecycle, or fixed-entry finding was reproduced. The reviewed worker requires both `report.ok is True` and `report.status == "passed"` for `checked_ok`, then performs its own strict output-tree and required-native-file audit. Its child receives a fresh `Session`, bounded JSON fields, a private output attempt root, and a reduced environment; model data cannot supply a module, command, callback, resource path, or export destination. Opaque artifact names are applied to path-bearing object-derived outputs while the legacy trusted executor default remains unchanged.

## Evidence and verdict

The recorded verification is 179 passed and 2 skipped in 128.65 seconds, plus five documented successful record-store → worker → checker → publication integrations. I did not rerun those tests. This review's only execution was the focused malformed-protocol reproduction above. The evidence correctly limits its claims to the Windows 10 source run; frozen spawning, Windows 11, Mint, and release acceptance remain unverified.

**Local-only verdict: provisional pass for the stated data-only Phase 3 boundary, with one non-blocking P3 diagnostic defect and the symlink-test coverage limitation above. This is not end-to-end completion evidence.** The coordinating parent reports that the separate Phase 4 review found four publication/checking blockers—publication adopting mutated bytes, OBJ `mtllib` resolution escaping the candidate/private-path report, wrong material associations passing, and intended rig actions passing through the engine's fallback assignment. I did not reproduce those Phase 4 findings; their owner is fixing them. Do not rely on this Phase 3 `checked_ok` integration as a complete gate until those changes receive the planned focused verification.

## Focused verification after the Phase 3 correction

Date: 2026-10-13. I reviewed only the changed worker protocol handling and direct tests, then repeated the original malformed-input reproduction and the focused protocol/worker lifecycle checks. No source or test files were edited by this reviewer.

The original oversized-input reproduction now returns exit code 2 and a 305-byte bounded result with `status: policy_error`, code `response_too_large`, and `attempt_id: null`; it no longer raises `UnboundLocalError`. A separate valid-JSON top-level array (`[]`) returns `policy_error/worker_protocol` with `attempt_id: null`. The new parameterized fixed-entry test covers oversized input and truncated JSON carrying an untrusted output-root string; both assert bounded/path-free results and that the output root was not created. Source review confirms `attempt_id` is initialized to `None` and only assigned after link, directory, and `attempt-[0-9a-f]{32}` identity checks (`worker.py:293–323`). The error handlers no longer dereference a possibly unassigned output root (`worker.py:417–425`).

Focused commands and results:

```text
.venv\Scripts\python.exe -m pytest am3d/ai/test_worker.py::test_internal_child_returns_bounded_early_protocol_error_without_output_root am3d/ai/test_worker.py::test_valid_worker_is_private_native_reopens_and_derived_paths_are_opaque am3d/ai/test_worker.py::test_cancelled_worker_is_terminated_promptly_and_never_successful am3d/ai/test_worker.py::test_windows_cancel_terminates_descendant_processes -q
4 passed, 1 failed in 9.97s; the failed case was the normal worker case returning worker_error.

.venv\Scripts\python.exe -m pytest am3d/ai/test_worker.py::test_internal_child_returns_bounded_early_protocol_error_without_output_root -q
2 passed in 0.69s

.venv\Scripts\python.exe -m pytest am3d/ai/test_worker.py::test_valid_worker_is_private_native_reopens_and_derived_paths_are_opaque -q
1 passed in 7.31s
```

The original direct reproduction used `.venv\Scripts\python.exe -c $code` in PowerShell with a temporary private current directory, wrote `b'{' + b' ' * (1024 * 1024)` to `.ai_worker_input.json`, and called `internal_worker_main([str(input_path), str(result_path)])`. It asserted exit code 2, bounded result size, `policy_error/response_too_large`, and `attempt_id is None`. The invalid-shape check used the same invocation with request bytes `b'[]'` and asserted `policy_error/worker_protocol`.

The combined command covering those direct cases, the normal worker case, cancellation, and Windows descendant cleanup produced `4 passed, 1 failed in 9.97s`; the one failure was the normal worker test returning `worker_error`. An immediate direct `run_worker(_recipe(), ..., CancellationToken())` diagnostic returned `execution_ok` with the expected manifest, and an isolated rerun of that same normal-worker test passed. I could not establish a cause for the single combined-run failure, so it remains recorded as an unexplained transient rather than a clean combined result. The owner separately records the same combined selection passing 5 tests in 8.22 seconds. The full 179-pass suite was not rerun.

The preserved `identity.initial-review.json` matches the initial review's source snapshot. Current `identity.json` hashes all match the working tree. Only the worker and worker tests changed among source/test files: `worker.py` is now `2c5ef82d700b452d3add632ae842613fb494f804723434c2e1e518d351457be6`, and `test_worker.py` is `79b2ccbe2cc1419cebf84ddbb665659cc617a134887d4de0dc5de2e276f0435f`; the updated `IMPLEMENTATION.md` and `tests.txt` hashes are `18b5d900a6dc8139aa765e7d3e7cbec5967618408b7aada9df38d08839489d56` and `f400693027dcc48ac9b818956566cfd0d724e7afb5f119f7e11e77dc199b23a7`, respectively. Runtime observed: Windows 10 build 19044, AMD64, CPython 3.12.14. The exact served model and reasoning configuration remain unavailable for verification.

**Updated local-only verdict: the reproduced P3 malformed-protocol defect is fixed and the direct rejection behavior is verified. The ordinary valid worker succeeds in isolated verification, with the unexplained combined-run failure noted above. This supports the Phase 3 data-only worker protocol locally; it does not clear release/platform acceptance or the separate Phase 4 `checked_ok` and publication blockers.**
