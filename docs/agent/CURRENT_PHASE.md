# Current handoff — M1a / H2

**Status:** H2 ready for review; base checkpoint `v0.3.0-dev.1` (`897dba3`).

H2 implements the capability registry and registry-driven recipe validation
for issue [#3](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/issues/3).
Keep this handoff to one reviewable PR, based on H1 branch `v1/m0-context`.

**Acceptance:** one accurate entry for every primitive, material pattern and
graph node, action kind, export format, and channel property. Entries include
typed params, defaults, ranges/enums, cost hints, and model-facing descriptions.
Test name/default parity with builders and validate unknown/mistyped params,
names, and enums with full paths. Keep legacy recipe behavior intact.

**Implemented:** `am3d/recipes/capabilities.py`, registry-driven parameter and
enum validation, TRS shorthand compilation, path-safe derived filenames,
validate-only path resolution/resource estimates, generated guide summary,
signature-parity tests, and schema enum checks.

**Validation:** focused recipe/path/export tests: 191 passed. Full pinned Linux
suite: 747 passed, 4 deprecation warnings. H3 adds the M1b defects, resource
ceilings, compact CLI contract, and defect probes.
