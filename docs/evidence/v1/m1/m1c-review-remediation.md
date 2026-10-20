# M1c review-remediation evidence

Date: 2026-10-06
Starting branch: `v1/m1b-defects`
Starting SHA: `fb01f0be7bde8de2fbf01182535390cd18bfdcb9`
Remediation source checkpoint: `e7aa5ff22a5e34ff307d2b1213679451b5791bbb`
Branch: `v1/m1c-review-remediation`
Stacked PR: [#13](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/pull/13), based on `v1/m1b-defects`.

## Findings

| Finding | Result | Remediation and regression |
| --- | --- | --- |
| M1-01 padded animation-sheet pixels | Fixed | Shared sheet-layout helper drives estimates and allocation; tests cover padding, malformed dimensions, exact limit, over limit, and the 17-sheet review reproduction. |
| M1-02 derived output collisions | Fixed | Derive object sheets from explicit stem/suffix; reject duplicate canonical final destinations before publication. Tests cover explicit/dotted `.png`, sanitized names, duplicate targets, and distinct directories. |
| M1-03 predictable semantic failures | Fixed | Shared graph-start prerequisite; non-negative noise seeds; skeleton references require declared bones and resolve forward references; explicit sheet actions must exist. Each returns a path-addressed preflight error. |
| M1-04 AI limits restrict trusted recipes | Fixed | Registry separates intrinsic constraints from optional AI ceilings; one validator applies either profile. Trusted `sections=129` runs; AI mode rejects it. Other subdivision, profile, pattern, and sheet ceilings are profile-specific. |
| M1-05 unassigned action rejected | Fixed | No-effect checking applies only to assigned actions. Tests cover unassigned, moving, ineffective, and unrelated geometry cases. |
| M1-06 provider schema exposes texture paths | Fixed | Provider schema drops `material.texture`; complete schema and trusted validation retain it; provider validation rejects it and AI host validation rejects it. |

## Validation

- `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/recipes/test_m1c_review_remediation.py -q` — 24 passed in 0.64s.
- `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/recipes/ -q` — 182 passed in 6.75s.
- `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/ -q` — 787 passed, 4 Qt deprecation warnings, in 62.89s.
- `build/linux/venv/bin/python scripts/build_recipe_provider_schema.py --check` — passed.
- `build/linux/venv/bin/python scripts/generate_recipe_capabilities.py --check` — passed.
- `git diff --check` — passed.
- Direct ephemeral reproductions of the six findings — 11 assertions passed.

## CI and scope

- Linux fast tests: [run 37499422399](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/actions/runs/37499422399), passed on the source checkpoint.
- Windows candidate: [run 37499422495](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/actions/runs/37499422495), failed during pytest collection with the pre-existing ModernGL access violation in `am3d/gpu/test_scene_render.py::_has_gl`. The same failure is recorded on the M1b candidate. No Windows qualification is claimed; no broad ModernGL changes were made.
- Non-blocking suggestions left for later: capability-specific parameter objects in JSON Schema; collecting every structural coercion error; more TRS examples; more detailed graph-guide prose.
- M2 and later work remain untouched. M1 remains blocked pending focused independent verification of M1-01 through M1-06.
