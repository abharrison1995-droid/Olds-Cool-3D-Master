# Current handoff — M1b / H3

**Status:** implementation ready; full pinned Linux suite passes (763 tests,
4 existing Qt deprecation warnings). GitHub fast CI is pending this push.

H3 completes M1b for issue [#3](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/issues/3),
stacked on H2 commit `4cd0322` / PR #11. Keep this as one reviewable PR.

**Implemented:** AI-mode ceilings before build plus constructed-scene recount;
bounded action-effect sampling; patch-degree persistence and GUI parity;
atlas dimensions/conditional baking/per-export staging; safe bone-parent path;
hidden legacy graph nodes in the compact provider schema; relative compact CLI
reports; shorter agent contract; regression tests for reproduced defects.

**Checks:** `QT_QPA_PLATFORM=offscreen build/linux/venv/bin/python -m pytest am3d/ -q`
→ 763 passed. Provider schema and guide generators are current; `git diff --check`
passes. Existing Windows candidate runs on H1/H2 fail in ModernGL context setup
(`_has_gl`); the Linux fast jobs passed. Do not claim Windows qualification.

**Exit gate:** independent review of the combined M1 changes must pass before
starting M2. Review the PR diff, M1 acceptance list, and CI evidence.
