# M2 local-generation implementation candidate

## Source

- Base: verified M1 `81f9a979af6534d08f2c4803a2430fa24471451f`.
- Implementation commit under review: `20b97b448f206a64faed1b7b59a90f120379e671` on `v1/m2-local-generation`.
- Scope: local recipe-v1 generation only. No provider, prompt, model, credential, orchestration, history, refinement, or benchmark work was added.

## Implementation

- Strict bounded JSON and M1 AI-policy validation run in the desktop process; the worker receives only a recipe, a digest-bound policy snapshot, and a private output root.
- A fixed source/frozen-app entry point launches one terminable child process with a minimal runtime environment, cancellation, a 20-minute deadline, bounded IPC, and structured failure records.
- The worker builds through the existing recipe executor, reopens the saved project, runs geometry, animation, bounds, export, and path checks, and always produces a whole-scene preview.
- Verified artifacts are atomically published as read-only per-user snapshots with hashes and relative paths. The editor opens a verified writable copy through the ordinary dirty-document guard.
- Added a GPU-independent Windows worker lifecycle workflow. It is separate from the existing Windows suite's pre-existing ModernGL collection failure.

## Validation

- `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/ai/ am3d/ui/test_generation_adoption.py -q` — **39 passed**.
- `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/ -q` — **826 passed, 4 existing QMouseEvent deprecation warnings**.
- `build/linux/venv/bin/python scripts/build_recipe_provider_schema.py --check` — passed, no output.
- `build/linux/venv/bin/python scripts/generate_recipe_capabilities.py --check` — passed, no output.
- `git diff --check` — passed.

## Gate and limitations

M2 implementation is ready for focused independent worker-boundary review, but **M2 remains blocked pending that review**. M3 has not started. The Windows worker workflow is submitted with the branch; its CI result is reported separately when available. This is not Windows qualification. Linux applies a best-effort address-space limit after imports; Windows relies on policy limits and forced process termination. Physical Windows 11 and Mint qualification remains an M6 activity. The independent M2 review has not yet recorded any additional non-blocking suggestions.
