# Current handoff — M1b / H3

**Status:** PR #12 pushed; Linux fast CI is green. M1 independent review is
the remaining exit gate before M2.

H3 commit `06f22c7` is stacked on H2 / PR #11 for issue
[#3](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/issues/3).

**Implemented:** AI-mode estimates and constructed-scene recount; `MemoryError`
mapping; no-op action checks; patch-degree persistence and GUI parity; correct
atlas dimensions and OBJ-only sidecars with per-export staging; bone-parent
path fix; compact path-relative CLI; hidden legacy nodes in provider schema;
three regression recipe fixtures.

**Validation:** full pinned Linux suite: 763 passed, 4 Qt deprecation warnings;
recipe suite: 158 passed. Both Linux fast jobs pass on [PR #12](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/pull/12).
Both Windows candidate jobs fail during pytest collection with the same
ModernGL access violation at `_has_gl` seen on H1/H2. This is recorded as an
existing runner issue; Windows qualification is not claimed.

**Exit gate:** independent review of the combined M1 changes must pass before
starting M2. Review the PR diff, M1 acceptance list, and CI evidence.
