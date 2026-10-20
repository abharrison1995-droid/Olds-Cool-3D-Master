# Root integration after review fixes

Date: 2026-10-13. Windows 10 IoT Enterprise LTSC 19044 x64, CPython 3.12.14,
source checkout, Qt offscreen. Baseline HEAD remains
`3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`; changes are uncommitted.

The root ran these integration checks with fake provider responses and the
actual subprocess worker, checker, record store and immutable publication:

```powershell
$env:QT_QPA_PLATFORM='offscreen'
.venv\Scripts\python.exe -m pytest am3d/ai/test_orchestrator.py::test_valid_recipe_runs_through_real_worker_checks_and_immutable_publish am3d/ai/test_refinement.py::test_four_refinements_change_measured_reopened_native_geometry_and_material -q --tb=short
```

Result: **2 passed in 71.23s**; stdout is in
`integration-component-refinements.txt`. The second case checks a flatter roof,
each longer arm, dark green body material and increased wheel-radius proxies
in reopened native projects, retaining the immutable parent's byte hash. This
run overlapped the final small RecordStore hardening and is integration
evidence, not an exact final release-source freeze.

After the owner declared runtime code stable, the root captured source bytes
in `integration-source-identity.json` and ran:

```powershell
.venv\Scripts\python.exe -m pytest am3d/ai/test_orchestrator.py::test_valid_recipe_runs_through_real_worker_checks_and_immutable_publish -q --tb=short
```

Result: **1 passed in 7.06s**; stdout is in `integration-final-headless.txt`.
After this run, a SHA-256 comparison found all captured runtime files and the
executed test inputs unchanged. The only changed captured file was
`am3d/ai/test_worker.py`, which a separate owner was enhancing for failure
diagnostics; that file is not imported by this selected integration test.

These executions do not establish live-provider quality, desktop adoption,
artist scoring, a frozen binary, either target platform or physical GPU
acceptance. The final full regression/build will use its own exact source and
artifact identities. The separately recorded intermittent execution-only
worker failure remains under bounded investigation.
# Current headless follow-up after final numeric-resource contract

On 2026-10-13 root captured `integration-current-headless-identity.json`
before running:

```text
QT_QPA_PLATFORM=offscreen
.venv\Scripts\python.exe -m pytest am3d/ai/test_orchestrator.py::test_valid_recipe_runs_through_real_worker_checks_and_immutable_publish -q --tb=short
1 passed in 9.78s
```

Complete output is `integration-current-headless.txt`. SHA-256 rechecking
all 88 existing captured source/test files after the command found no changes.
This exercises the current real data-only child, checker, manifest and immutable
publication with an offline fixture. It is a narrow integration check, not a
live-provider, desktop, frozen, final full-suite or target-platform acceptance.
Later UI/benchmark/packaging additions are not covered by this receipt.

