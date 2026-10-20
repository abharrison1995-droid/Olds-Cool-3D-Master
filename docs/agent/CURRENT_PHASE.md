# Current handoff — Windows V1/master convergence

**Authority:** docs/V1_MASTER_IMPLEMENTATION_PLAN.md is the approved active
plan. User direction for this task is to make the local Windows V1 source
authoritative on GitHub master, while preserving compatible prior milestones.

**Integration:** local V1 source remains at am3d.ai.*. Incompatible M2/M3.1
provider and worker modules are preserved at am3d.ai.m3.*; their standalone
worker entry point and Windows CI path are namespaced accordingly. The
combined Windows 10 source suite passed 1,182 tests, skipped 3, with 4
warnings in 654.01 seconds under Qt offscreen. This is source evidence only;
Windows 11, native GPU, clean-machine, live-provider, and secure-credential
gates remain open. GitHub CI, final review, and the master merge are pending.

**Acceptance limits:** Windows 10 is the development workstation, not the
Windows 11 target. Approved live provider/model, secure credentials and spend
authorization, Windows 11, clean-machine, admin ACL, and physical-GPU targets
were unavailable. Native UI qualification and human-scored live benchmark
runs remain open. This branch is not a release or V1 acceptance claim.

**M3.2:** PR #16 remains a draft. Independent review found unresolved
provider-process isolation risks; it does not merge into master with this
convergence.

**Next gate:** complete combined regression tests and GitHub CI, review the
final merge diff, merge the V1 convergence to master, then verify the remote
default branch, local refs and stale branch cleanup. Preserve artifact- and
source-specific acceptance evidence.
