# Agent orientation

- Product: 3D MASTER:2005, an editable spline-patch modeling and animation application with a recipe CLI.
- Active plan: [`docs/V1_PLAN.md`](docs/V1_PLAN.md); current handoff and exact task: [`docs/agent/CURRENT_PHASE.md`](docs/agent/CURRENT_PHASE.md).
- Design authority: [`DESIGN.md`](DESIGN.md). Platform support and caveats: [`docs/SUPPORTED_PLATFORMS.md`](docs/SUPPORTED_PLATFORMS.md).
- Before changing source, inspect current phase, relevant GitHub issue, and the touched package. Preserve all local and historical work.
- Default full test command: `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/ -q`. Fresh pinned env: `python -m pip install -r requirements-lock-linux.txt`, then `QT_QPA_PLATFORM=offscreen python -m pytest am3d/ -q`.
- Fast CI uses the Linux pinned lock and offscreen pytest on every push and pull request.

## Package map

- `am3d/spline/`: spline geometry and patch evaluation.
- `am3d/core/`: document/session model, serialization, paths, and scripting facade.
- `am3d/recipes/`: recipe schema, validation, builders, execution, and CLI.
- `am3d/ai/`: planned V1 policy, worker checks, providers, and orchestration; add only in its milestone.
- `am3d/ui/`: PySide6 desktop editor and document controller.
- `am3d/export/`, `am3d/renderer/`, `am3d/rig/`: export readers/writers, rendering, skeletons and actions.
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
