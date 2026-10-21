# Master push CI follow-up — 2026-10-21

The authorized fast-forward moved `master` from `16e333c946643ddf01c2aa16f26812912567fb3d`
to `b72aaf92a1975740ad406e80fc3fae697e7f4c3b`. The source tree was clean after the push.

## Initial push runs

For commit `b72aaf92a1975740ad406e80fc3fae697e7f4c3b`:

- Windows local-generation worker — passed (run `39527022638`).
- Linux fast tests — running at first inspection (run `39527022601`).
- Windows candidate — failed during setup-python before build/acceptance began (run `39527022653`).

The Windows candidate log identifies the cause: workflow input `3.12.14` was unavailable
for the `windows-2025` runner. No application test, build, frozen acceptance, or independent
export check ran in that job. This is distinct from a product-test failure.

## Workflow correction

The candidate workflow now requests Python `3.12` rather than a specific patch. The official
`actions/setup-python` documentation specifies that a major/minor input selects the latest
patch preinstalled on each runner; the exact patch can be recorded from the action output.
Source: <https://github.com/actions/setup-python/blob/main/docs/advanced-usage.md#specifying-a-python-version>

The correction requires a new Windows candidate run. Until that run finishes, this note does
not claim the candidate CI gate passed. The Windows 10 local evidence and unpassed Windows 11,
native interaction, graphics, ACL, live-provider, and human-scoring gates remain governed by
`ACCEPTANCE_LEDGER.md`.

## Second push runs and native-context failure

The corrected setup selected CPython `3.12.10` on Windows 2025. Linux fast tests and the
Windows local-generation worker passed for commit `4e27ce81d833b776172d771392b18e17fce762bd`
(runs `39527234842` and `39527234847`). The Windows candidate then reached pytest collection
and failed at `am3d/gpu/test_scene_render.py::_has_gl` with a native ModernGL access violation
(run `39527234862`). This is a separate failure from the unavailable exact Python patch; the
build, frozen acceptance, and export verification did not run.

The CI-only safety boundary was then applied from the independently reviewed GPU-gate change
(`132ce3c`) and smoke-probe change (`87579da`), without importing their unrelated M3.2 adapter
files. Unless a qualified test host sets `AM3D_TEST_REAL_GPU=1`, the test suite now uses the
software fallback, skips real-context tests before context creation, and records GPU parity as
skipped in smoke evidence. The native GPU gate remains unpassed.

Focused verification on the Windows 10 execution host, with Qt offscreen and real-GPU opt-in
unset:

```text
python -m pytest -q am3d/gpu/test_gpu.py am3d/gpu/test_scene_render.py am3d/ui/test_smoke.py
35 passed, 3 skipped in 67.10s
```

The next master push is required to rerun the full Windows candidate build. This focused result
does not qualify physical GPU rendering or Windows 11.
