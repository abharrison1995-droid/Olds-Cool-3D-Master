# Current handoff — M1c review remediation

**Status:** Six blockers from the independent M1 exit review have been
remediated on `v1/m1c-review-remediation`. M1 remains blocked pending focused
independent verification of M1-01 through M1-06. M2 has not started.

Starting candidate: `fb01f0be7bde8de2fbf01182535390cd18bfdcb9`
(`v1/m1b-defects`). The M1c evidence record is
[`docs/evidence/v1/m1/m1c-review-remediation.md`](../evidence/v1/m1/m1c-review-remediation.md).

**Validation:** Linux recipe suite: 182 passed; full `am3d/` suite: 787 passed,
4 existing Qt deprecation warnings. Provider-schema generation, capability
guide generation, and `git diff --check` pass. Eleven direct blocker
reproductions pass.

**Windows:** The existing Windows candidate workflow fails during pytest
collection with the known ModernGL access violation at
`am3d/gpu/test_scene_render.py::_has_gl`. This is pre-existing and outside
M1c; no Windows qualification is claimed.

**Gate:** Do not start M2 until a focused independent review verifies all six
M1c findings. Keep the review scoped to the candidate diff, acceptance list,
and recorded test output.
