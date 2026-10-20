# Phase 2 independent source and fixture review

Date: 2026-10-13. Fresh read-only reviewer, requested Luna/xhigh; spawning tool
accepted settings, resolved runtime not introspectable. No implementation edits
were made by this reviewer.

First round found nine static fixtures whose disclosure strings occupied
`rig.expected_bones`. Implementer cleared expected bones for every static case
and introduced independently authored `requirements.expected_disclosures`, with
interpretation, example phrasing, semantic keywords and a conditional on ID 22.
Fixture revision `v1-premeasurement-r2` is explicitly recorded before any live
run. No scored failures were omitted and release thresholds were not changed.

ID 01's incidental flat-base wording and ID 02's incidental tilted-shade wording
were removed before measurement because the original master-plan scope requires
mug body/handle and lamp base/stem/head, and no independent geometric check for
these extra attributes had been frozen. Other required parts, appearance and
dimensions remain in the full briefs. This is a disclosed fixture revision.

A refinement risk was fixed: `build_candidate` now checks known unsupported
refinement requests before any provider call. Animated GLB and physical-glass
refinement regressions assert that no call occurs. The orchestrator will also
reinterpret refinements to preserve the broader normalized-intent boundary.

Implementer reported 19 focused prompt tests and 66 combined prompt/contracts/
provider tests passed. The reviewer inspected the fixes and hash identities in
one focused verification round; they did not rerun the reported suite. Verdict:
**local implementation and fixture review passed**, after the final documentation
sentence was added by the orchestrator.

Release fixture SHA-256:
`0ef3291a7cb5818091a1a22ebdbfe75dc9cb4118274f32fe6395c478e119e560`.
Live prop/shelter/rig baseline, endpoint/model release configuration, artistic
human scoring and two frozen benchmark runs remain pending. This review does
not mark the complete live Phase 2 gate passed.
