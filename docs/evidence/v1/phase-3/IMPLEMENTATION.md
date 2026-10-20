# V1 Phase 3: policy and isolated worker implementation

Date: 2026-10-13. Starting implementation HEAD:
`3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`. The Phase 3 files listed below
are uncommitted working-tree changes; there is no Phase 3 commit or release
build identity yet. This evidence describes the current Windows source run,
not a frozen executable or platform acceptance.

Host and interpreter match the Phase 0 baseline: Windows 10 IoT Enterprise
LTSC x86-64 build `10.0.19044`, bundled CPython 3.12.14 in `.venv`.

## Implemented behavior

`am3d.ai.policy.prepare_recipe(raw_recipe, brief=None)` bounds and inspects
data before recipe normalization or geometry allocation. Unsafe destinations,
resource paths, code-like fields, unsupported verbs, oversize data and fixed
resource-limit violations are terminal `PolicyError`s. Typed but repairable
recipe mistakes remain `RecipeValidationError`s. It replaces model-selected
destinations with host-assigned names, always includes `project.am3d`, and
preserves readable Unicode names in the native recipe/project.

The worker API is
`am3d.ai.worker.run_worker(recipe, output_dir, deadline, cancellation, *, check_options=None)`.
It preflights in the parent, creates a unique attempt directory, then starts a
fixed source module (`python -m am3d.ai.worker`) or the frozen GUI's hidden
`--internal-ai-worker` entry before any Qt import. The child receives only a
bounded JSON request, a private temporary directory, and a minimal environment
without provider credentials. It creates a fresh `Session`, exports through the
existing `RecipeExecutor`, reopens the required native project, and returns a
bounded JSON result. The original editor `Session` is never passed to the
worker.

On Windows, the fixed protocol and worker CWD live in a short per-run temporary
workspace because `CreateProcess` rejects extended-length paths as its current
directory. The parent separately creates the host-selected output attempt
root and passes that fixed outer protocol field to the child; recipe data
cannot provide or override it. Worker TEMP/TMP points to the private workspace,
while the executor and checker write to the output attempt root. Both roots are
audited live; only the independently audited output tree appears in the
relative-path manifest. App-owned host roots use Windows extended-length I/O
paths, while model-authored paths continue through the portable path policy.

The worker assigns opaque ASCII component identifiers to OBJ/GLB groups,
per-object sheets, atlas files and texture sidecars when its explicit
`safe_artifact_names=True` executor mode is enabled. Names inside the recipe,
native project and sheet metadata remain readable. That option defaults to
false, preserving trusted CLI/API output naming. The parent checks links and
junctions, approved extensions, portable filename rules, case/normalization
collisions, containment, output sizes and the required native project before
returning a manifest of relative paths.

When the fixed artifact checker is available, only the conjunction
`report.ok is True` and `report.status == "passed"` yields `checked_ok`.
Execution without checks (or before the checker is installed) is
`execution_ok`; failed checks yield `check_failed` with the report and a
bounded manifest, and never set `ok`. Checker metadata is JSON-only and capped
at 256 KiB; the internal request and result caps are 1 MiB, and the checker
report cap is 256 KiB. The worker does not accept a callback, command or module
name in its protocol.

Preflight applies the Phase 3 limits in plan section 6: recipe 512 KiB; 128
objects; 1024 patches; 64 bones per rig and 256 explicit/copied bones; 16
actions; 256 channels; 4096 keys and authored points; subdivisions no greater
than 128; 32 materials and 32 graph nodes per material; 250,000 estimated
triangles at 16x16 tessellation; sheet exports/cells and pixel totals bounded;
64 million atlas pixels; estimated worker memory at or below 1 GiB; output at
or below 256 MiB; and at most 180 seconds. Texture/resource reads are disabled.
The worker does not rasterize a preview itself. When the fixed Phase 4 checker
is present, the child runs it after exporting and reopening the native project;
the checker owns the 512x512 preview render and gates `checked_ok` on its full
report. This Phase 3 path has now been exercised through the real checker and
immutable publication integration.

Windows workers use a kill-on-close Job Object, with `taskkill /T` fallback;
POSIX uses a new process group. The parent checks cancellation/deadline while
the child runs, watches working set where supported and terminates on limit
breach. Scratch staging bytes count toward the live disk budget. A fixed
allowlist controls environment variables and worker entry points. The process
boundary handles lifecycle and resource limits for untrusted data-only
recipes; it is not an OS sandbox and does not contain compromised application
code.

## Verification

| Command | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m py_compile am3d/ai/policy.py am3d/ai/worker.py am3d/ai/test_policy.py am3d/ai/test_worker.py am3d/recipes/executor.py am3d/recipes/test_executor.py am3d/core/paths.py am3d/core/test_paths.py am3d/ui/__main__.py` | Passed. |
| `.venv/Scripts/python.exe -m pytest am3d/ai/test_policy.py am3d/ai/test_worker.py am3d/core/test_paths.py am3d/recipes/test_executor.py -q -rs` | **179 passed, 2 skipped in 128.65s**. Covers policy limits, worker protocol/lifecycle, portable path behavior and the full executor regression suite. The two skips are file/directory symlink fixtures because this account lacks the Windows symlink privilege (`WinError 1314`). The actual Windows directory-junction rejection test passed and preserved its outside sentinel. |
| `.venv/Scripts/python.exe -m pytest am3d/ai/test_orchestrator.py::test_valid_recipe_runs_through_real_worker_checks_and_immutable_publish -q` | The orchestrator agent ran this real `pytest tmp_path` record-store → worker → checker → publish test **five sequential times; all 5 passed** (19.91s, 18.53s, 13.05s, 22.54s, 20.50s). The live audit tolerates vanished concurrent scratch entries and counts only the serializer's exact `.am3d_tmp_<8 chars>` pattern; the final audit remains strict. |
| Source child long-output-root worker test (`test_worker_succeeds_with_deep_host_output_root`) | Passed in the combined suite with a host-selected output root deeper than 260 characters. Protocol/CWD/TEMP remain in a short private workspace because Windows `CreateProcess` does not accept an extended-length current directory. |
| Deterministic Windows live-audit path-form regression (`test_tree_audit_normalizes_transient_extended_realpath_prefix`) | Passed. It models CPython 3.12 `ntpath.realpath` returning a `\\?\\`-prefixed child while the root retains an ordinary drive path, first confirms `commonpath` raises `ValueError`, then confirms `_verify_tree` compares both in normalized extended host-I/O form. Final audits remain strict, including the existing vanished-deliverable regression. |
| Post-review protocol and lifecycle regression: `.venv/Scripts/python.exe -m pytest am3d/ai/test_worker.py::test_internal_child_returns_bounded_early_protocol_error_without_output_root am3d/ai/test_worker.py::test_valid_worker_is_private_native_reopens_and_derived_paths_are_opaque am3d/ai/test_worker.py::test_cancelled_worker_is_terminated_promptly_and_never_successful am3d/ai/test_worker.py::test_windows_cancel_terminates_descendant_processes -q` | **5 passed in 10.59s**. The direct fixed-entry cases cover oversized and truncated JSON requests before output-root parsing; normal execution, cancellation and Windows descendant cleanup also passed. |
| Five-attempt normal-worker reproduction using the same Unicode textured-prop recipe under a deep (>260-character) host output root | First bounded run: attempt 1 returned `worker_error/worker_protocol`; the test-only parent audit wrapper observed a live `_verify_tree` `ValueError`. The partial root snapshot contained the complete six expected exports totaling 325,760 bytes. Attempts 2–5 returned `execution_ok`. A second five-attempt deep-root run returned `execution_ok` on all five attempts, with no parent audit exception. The ValueError location/reason was not captured in the first run, so the cause remains open. |
| Five-attempt normal-worker reproduction under a short host temp root | **5/5 returned `execution_ok`**; each produced six manifest entries totaling 325,760 bytes with no error records. |
| Post-fix deep-root reproduction using the same Unicode textured-prop recipe | **3/3 returned `execution_ok`**, each with six manifest entries and no parent audit exceptions. The test-only harness used a host root whose staged artifact path exceeded 260 characters. The earlier observed live `ValueError` had no saved traceback detail; the deterministic regression now reproduces the path-spelling mismatch and verifies the normalization fix without claiming the original transient's exact stack was captured. |
| Focused worker/audit/lifecycle command after path normalization | `.venv/Scripts/python.exe -m pytest am3d/ai/test_worker.py::test_tree_audit_normalizes_transient_extended_realpath_prefix am3d/ai/test_worker.py::test_live_tree_audit_tolerates_vanished_private_staging_entries am3d/ai/test_worker.py::test_valid_worker_is_private_native_reopens_and_derived_paths_are_opaque am3d/ai/test_worker.py::test_cancelled_worker_is_terminated_promptly_and_never_successful am3d/ai/test_worker.py::test_windows_cancel_terminates_descendant_processes -q -rs` — **6 passed in 9.89s**. |

Exact commands, skip reasons, environment and per-run integration timings are
also recorded in `tests.txt`.

Worker tests exercise a valid Unicode-named textured prop with OBJ, texture
sidecar, atlas, sheet and native exports; reopen the native project and confirm
the Unicode scene name survives; compare an outside sentinel before/after;
reject path/resource attempts before output-root creation; enforce portable
filename collision checks; exercise checker pass/fail predicates; cancel and
time out hung children; verify child death cannot return success; and confirm
the child environment omits credential and home variables. Windows-specific
descendant cleanup is tested using the fixed test worker launcher.

## Limits and pending acceptance

The recorded starting commit is Phase 0's clean baseline; the current shared
working tree also contains other Phase 1 and later-phase changes. No commit was
created for this task. `identity.json` records the exact current Phase 3
working-source hashes and baseline; `identity.initial-review.json` preserves
the exact bytes reviewed before this correction. The independent review
reproduced a P3 diagnostic defect: oversized or truncated protocol input could
reach an exception handler before an output root existed. The worker now keeps
an optional host-validated attempt ID, emits a bounded path-free protocol
result for oversized or malformed input, and does not create the supplied
output root. The direct protocol and lifecycle regression passed; focused
independent re-verification is pending. A normal-worker `worker_error` was
reproduced once in the pytest-root run and once in the first deep-root batch.
The latter had complete expected output files and a test-only wrapper observed
a live parent `_verify_tree` `ValueError`, but the original source line/reason
was not captured. CPython 3.12 `ntpath.realpath` can retain an extended
`\\?\\` prefix when its second final-path probe loses a file; an ordinary
root and that extended child cause `ntpath.commonpath` to raise `ValueError`.
The deterministic Windows regression constructs this path-form mismatch and
confirms comparison-only normalization fixes it. Three fresh same-recipe
attempts under the deep output-root shape then passed with no audit exception.
This source-mechanism match is the supported diagnosis, not a claim that the
original transient traceback was captured. The final audit remains strict,
and the normal-worker test fails on its first failure with the safe result,
bounded relative tree snapshot, and parent audit/child-protocol diagnostics.
The review's source-reasoned same-user path TOCTOU limitation remains outside
the stated data-only threat boundary.
Symlink creation was unavailable, while the Windows junction test passed.
Memory enforcement combines preflight estimates and runtime working-set
monitoring; it is not a hard OS limit. Frozen spawning, native Qt application
behavior, Windows 11, Mint, and release acceptance were not exercised. Without
the checker, `execution_ok` remains distinct from checked completion.
