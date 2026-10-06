# Current handoff — M3.1 provider boundary

**Status:** M2 independently reviewed and accepted. Accepted source:
`0f3413adebe1b07c582c4617aa0c18053fda1e1a` on `v1/m2-local-generation`,
tagged `v0.3.0-dev.2`. PR #14 remains open and stacked on M1c, following the
repository's open milestone-PR chain. See
[`docs/evidence/v1/m2/m2-independent-acceptance.md`](../evidence/v1/m2/m2-independent-acceptance.md).

**Active milestone:** M3.1 — provider boundary, strict structured response,
offline fake provider, and one-call orchestration skeleton. Candidate source:
`fb73687` (`Implement M3.1 provider boundary and orchestration`), based on the
accepted M2 source above. Local Linux validation is green; focused independent
verification is pending. M2 worker/policy/publication behavior is frozen;
change it only for a specific reproducible defect needed by M3.

**M3.1 limits:** no real provider adapters, CLI flags, credential handling,
automatic repair/retry/fallback, analytics UI, benchmark, model selection, or
M4/M5 work. Provider data can only produce a recipe-v1 object; the existing
`authorize_recipe(...)` and `GenerationRunner` remain mandatory. No live
provider calls in validation.

**Gate:** strict 1 MiB provider response parsing, fake-provider tests, one-call
orchestration through M2, focused and full Linux suites, and Linux fast CI.
Windows worker CI is reported if triggered. M3.1 ends at this review
checkpoint; M3.2 has not started and requires explicit instruction.
