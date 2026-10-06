# M2 independent acceptance

Date: 2026-10-06

## Accepted source and disposition

- Accepted branch: `v1/m2-local-generation`.
- Exact accepted SHA: `0f3413adebe1b07c582c4617aa0c18053fda1e1a`.
- M2 implementation commit: `20b97b448f206a64faed1b7b59a90f120379e671`.
- Verified M1 base: `81f9a979af6534d08f2c4803a2430fa24471451f`.
- PR #14: open, based on `v1/m1c-review-remediation`; retained as part of the existing stacked milestone-PR chain.
- Checkpoint tag: `v0.3.0-dev.2`, pointing to the exact accepted SHA above.
- Independent worker-boundary review: **PASS**. No M2-blocking defect was found. M2 is formally complete and its execution boundary is frozen; change it only for a specific reproducible defect exposed by M3.
- M3 had not begun at the point M2 was accepted.

The prior [M2 implementation candidate record](m2-local-generation.md) is preserved unchanged. This addendum records the later independent acceptance and does not alter the reviewed source.

## Validation evidence

- `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/ai/ am3d/ui/test_generation_adoption.py -q` — **39 passed**.
- `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/ -q` — **826 passed, 4 existing QMouseEvent deprecation warnings**.
- Provider-schema generation/check, capability generation/check, and `git diff --check` passed.
- Linux fast CI passed on [run 37517099800](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/actions/runs/37517099800) and [run 37517119247](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/actions/runs/37517119247).
- GPU-independent Windows worker-boundary CI passed on [run 37517099952](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/actions/runs/37517099952) and [run 37517119211](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/actions/runs/37517119211).
- Existing Windows build-and-accept runs [37517099790](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/actions/runs/37517099790) and [37517119213](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/actions/runs/37517119213) failed during collection with the known ModernGL access violation at `am3d/gpu/test_scene_render.py::_has_gl`. This remains a separate known limitation, not an M2 worker failure. No physical Windows qualification is claimed.

## Accepted non-blocking observations

- Worker IPC also carries the host-generated run ID and bounded check configuration alongside recipe, policy snapshot, and private output root.
- “Preview always produced” means preview is mandatory/attempted in the deterministic check path for a generation that reaches successful checks; a project failing before preview fails closed.
- Windows CI covers the source worker lifecycle. Frozen-artifact qualification remains later work, especially M6.

## Next milestone

M3.1 begins on a branch based on the accepted M2 SHA. Provider responses remain untrusted structured data and must pass the existing M1/M2 AI policy, M2 worker, and deterministic checks. No provider calls were made for M2 acceptance.
