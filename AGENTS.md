# Agent orientation

- Product: 3D MASTER:2005, an editable spline-patch modeling and animation application with a recipe CLI.
- Active plan: [docs/V1_MASTER_IMPLEMENTATION_PLAN.md](docs/V1_MASTER_IMPLEMENTATION_PLAN.md); current handoff and exact task: [docs/agent/CURRENT_PHASE.md](docs/agent/CURRENT_PHASE.md).
- Maintenance record: [docs/agent/REFACTOR_PLAN.md](docs/agent/REFACTOR_PLAN.md). It preserves the active V1 product contract; current state belongs in the handoff. Do not restart completed stages.
- The 6 Oct M0 plan at docs/V1_PLAN.md is historical context; the approved 13 Oct V1 master plan supersedes it.
- Design authority: [`DESIGN.md`](DESIGN.md). Platform support and caveats: [`docs/SUPPORTED_PLATFORMS.md`](docs/SUPPORTED_PLATFORMS.md).
- Before changing source, inspect current phase, relevant GitHub issue, and the touched package. Preserve all local and historical work.
- Default full test command: `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/ -q`. Fresh pinned env: `python -m pip install -r requirements-lock-linux.txt`, then `QT_QPA_PLATFORM=offscreen python -m pytest am3d/ -q`.
- Windows PowerShell: set `$env:QT_QPA_PLATFORM = 'offscreen'`, then `build/windows/venv/Scripts/python.exe -m pytest am3d/ -q`. Verify the existing environment against `requirements-lock-windows.txt`; use that lock for a fresh Windows environment.
- Ordinary tests use software rendering. Leave `AM3D_TEST_REAL_GPU` unset unless running a separately qualified native-GPU check.
- Fast CI uses the Linux pinned lock and offscreen pytest on every push and pull request.

## Package map

- `am3d/spline/`: spline geometry and patch evaluation.
- `am3d/core/`: document/session model, serialization, paths, and scripting facade.
- `am3d/recipes/`: recipe schema, validation, builders, execution, and CLI.
- `am3d/ai/`: authoritative V1 policy, worker checks, provider and orchestration implementation. `am3d/ai/m3/` preserves the incompatible earlier M2/M3.1 API. Existing UI compatibility integrations and the legacy worker still use it; preserve those boundaries and do not mix contracts or remove it as dead code.
- `am3d/ui/`: PySide6 desktop editor and document controller.
- `am3d/export/`, `am3d/renderer/`, `am3d/gpu/`: export readers/writers and rendering. Skeletons and actions live in `am3d/core/rigging.py` and `am3d/core/animation.py`.
- `docs/`: active contract and user docs; `docs/evidence/` is immutable historical evidence.

## Invariants

- Only validated `recipe-v1` and host-compiled shorthand can execute; never execute model code or model-selected paths.
- Spline patches are authoritative; meshes are derived; retain one scene model.
- Provider output is untrusted. Host-side deterministic checks decide success.
- Background jobs never replace current/dirty documents; snapshots stay immutable and editor opens a writable copy.
- Credentials never reach workers, projects, logs, or records. Bound every run's attempts, time, memory, and output.
- Manual and CLI workflows work offline. Historical evidence applies only to its recorded source/artifact.

## Do not read by default

- Do not load all of `docs/evidence/**`, `docs/archive/**`, or old plan drafts for orientation. Open only evidence named by the active issue or phase.
- Do not treat archived plans, old PASS labels, or generated output as current acceptance. The active plan and issue define scope.
