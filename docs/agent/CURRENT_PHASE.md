# Current handoff — M2 local generation

**Status:** M1 passed focused independent exit verification. Verified M1 source:
`81f9a979af6534d08f2c4803a2430fa24471451f`. The verified M1c source checkpoint
is `e7aa5ff22a5e34ff307d2b1213679451b5791bbb`; the final M1 branch tip adds
the verification evidence record.

**Active milestone:** M2, local generation without a model. Branch:
`v1/m2-local-generation`, based directly on the verified M1 SHA above.
**Checkpoint:** M2 implementation candidate ready on `v1/m2-local-generation`.

M2 exercises recipe-v1 through strict AI policy, a fixed terminable worker,
deterministic checks and preview, immutable app-data records, and guarded
opening of a writable copy. No provider, prompt, model, credential, or M3
functionality is in scope. M3 has not started.

**Implementation state:** local recipe policy, fixed worker lifecycle,
deterministic checks and preview, immutable records, Windows worker CI, and
guarded writable-copy editor adoption are implemented. Linux full and focused
tests pass. M2 remains blocked pending focused independent worker-boundary
verification. M3 has not started.

**M2 gate:** the Windows worker workflow must exercise worker launch,
cancellation, timeout, and stale-result handling independently of the
separate pre-existing ModernGL test-collection crash. Do not claim Windows
qualification. M2 is not complete until the local desktop path and independent
worker-boundary review pass.
