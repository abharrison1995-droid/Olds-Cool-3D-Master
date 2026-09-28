# Phase 1 — External-agent recipe contract

Date: 2026-09-27
Source base: `f35e4e5` plus the existing uncommitted workspace changes.
Trial agent: fresh tool-enabled `gpt-6-luna` at its highest supported effort (`max`), with a strict allowlist of the shipped external-agent guide, schema, and examples. Luna `xhigh` is not available in this sub-agent runtime.
Asset brief: stylized clockwork beetle with patterned copper shell, darker head, four legs, two antennae, a skeleton and walk action; emit editable `.am3d`, OBJ, GLB, and an animation sheet.

## Result

The agent wrote `clockwork_beetle.json`, invoked the recipe CLI, received a structured runtime rejection for unsupported pattern `scales`, changed the recipe to supported pattern `checker`, and reran the CLI successfully. The final run returned `ok: true` and seven manifest entries. A separate local rerun confirmed every listed artifact exists and resolves under the chosen output root.

The rejected response was:

```json
{"code":"execution_error","stage":"runtime","path":"recipe","message":"ValueError: unknown pattern 'scales' (choose from ['bricks', 'checker', 'gradient', 'noise', 'solid'])"}
```

The final outputs are retained in `artifacts/`: editable `.am3d`, OBJ, MTL, PNG texture sidecar, GLB, animation sheet PNG, and shell atlas PNG. The final CLI report is `run.json`, from the independent local rerun. The schema validation-only report is `validate.json`; it validates `minimal_cube`, not the beetle recipe, and correctly reports success without an artifact manifest. `usage-missing-recipe.stderr` records a missing required `--recipe` argument; it exited 2 with usage text on stderr and no stdout. The agent reported that its deliberate recipe rejection exited 1 with a JSON error record. These are different checks and are not evidence of an unknown-option path.

The trial agent needed host Python dependencies absent from the selected global Miniconda interpreter. It installed NumPy and msgpack into that global interpreter before continuing. That was an unintended environment change. I restored NumPy from 2.5.3 to the documented baseline 2.5.2; msgpack remains at its documented baseline 1.2.2. Future execution uses an isolated virtual environment. The agent was told not to make further global installs.

## Review note

The generated shell atlas is copper-colored and patterned. The 8-frame animation sheet is pale monochrome and mostly shell-dominant. Source inspection found that the animation-sheet renderer uses a flat color path and does not carry material textures into the sheet. This is recorded as a preview-quality concern for the two Phase 1 reviewers to classify; exported GLB/OBJ material files and the editable project are present. It is not hidden as a successful textured animation preview.

## Evidence files

- `clockwork_beetle.json`: final recipe authored and corrected by the trial agent.
- `run.json`: independent local rerun's success manifest.
- `validate.json`: validate-only response.
- `usage-missing-recipe.stderr`: missing required argument response.
- `artifacts/`: generated outputs from the successful agent run.

The trial began from uncommitted source/UI work. This report does not claim a clean source-tree fingerprint; Phase 3 will record a deterministic digest of all build inputs.
