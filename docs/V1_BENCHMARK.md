# V1 benchmark protocol

Authority: the approved [V1 master plan](V1_MASTER_IMPLEMENTATION_PLAN.md),
sections 10 and 13. This protocol describes the current V1 implementation;
the October 6 provider bake-off and M-stage schedule are historical in
[V1_PLAN.md](V1_PLAN.md), not prerequisites to resume.

## Inputs and implementation

- [Release fixtures](../benchmarks/v1/prompts.json): IDs 01–30, including
  25 static and five rig/animation items.
- [Discovery fixtures](../benchmarks/v1/discovery.json): eight diagnostic
  probes, excluded from the release denominator.
- [Scoring rubric](../benchmarks/v1/rubric.md): independent requirements,
  original human scores and disagreement handling.
- `am3d/ai/benchmark.py` and `scripts/run_ai_benchmark.py`: manifests,
  journals, offline/replay/live modes, score imports and gate reports.

Fixture and scoring policy are implemented and versioned. Actual live-provider
qualification and human scoring remain open. The rubric's historical
"proposed target" wording does not override the approved master release gates.
Do not edit frozen fixtures or scoring policy within an existing run. Changed
fixtures, prompt context, source or scoring policy require a new bound manifest
and the required complete reruns; prior evidence keeps its original identity.

## Release gates

Run all 30 release items twice using one declared provider/model configuration.
Each run requires at least 27/30 deterministic checked successes, with floors
of 20/25 static and 4/5 rig/animation items, and at least 24/30 human-acceptable
items. Two humans independently score silhouette, essential components,
proportions/appearance and editability from 0 to 2. Each evaluator must give
at least 6/8 and a nonzero essential-components score for an acceptable item.
Preserve original scores and document disagreements.

Failures, refusals, unsupported scope, cancellations, timeouts and provider
errors remain in the denominator. Infrastructure failures are also reported
separately. Integrity/security checks are mandatory for every successful item;
human scores cannot replace them. No extra local-model run or four-provider
bake-off is imposed by the active V1 contract.

## Reproducibility and bounds

Bind each run to source and dirty-input identity, exact fixtures, rubric,
prompt/capability context, provider/model, declared limits and run ID. Preserve
all failures and exact candidate/check/artifact receipts. Unknown token, usage
or cost data is null, not zero. Provider aliases may drift; record that limit.

Current orchestration permits at most four recipe candidates, five semantic
calls, two validation repairs and one execution/check repair. A semantic call
has at most two HTTP attempts under the shared deadline. See
[security limits](V1_SECURITY_LIMITS.md). The provider contract cannot enforce
a dollar ceiling or bound input tokens from an unknown tariff; cost remains
unavailable unless measured. Live runs require an explicitly approved provider,
model, private credentials and spending limits. Offline/mock and replay runs
exercise the machinery but cannot satisfy live or human release gates.
