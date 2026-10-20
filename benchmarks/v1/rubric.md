# V1 prompt benchmark rubric

Status: frozen fixture and scoring policy for Phase 2 implementation; release measurement is pending. The eight discovery probes are diagnostic and are never added to the 30-item release denominator.

## Frozen inputs and run identity

Before a scored release run, record the exact source commit and dirty-diff digest, fixture SHA-256 values, prompt-template version and SHA-256, capability-context version and SHA-256, provider and configured model identifier, date, and run ID. Preserve the original 30 release briefs, this rubric, and discovery set unchanged for that run. A change to fixture text, template, capability context, or scoring policy creates a new benchmark revision and requires rerunning all 30 release items. Never add, remove, or rewrite an item after seeing its outcome.

The user request and independently authored fixture checks are authoritative. Model interpretation, recipe assertions, and generated names cannot remove a required component, material, color, dimension, relation, rig check, action, or export. Record any unsupported requirement as a limitation requiring a user decision; keep it visible in the item result.

## Release protocol and denominator

Run all 30 frozen release prompts twice with one declared provider/model configuration. The static tier is IDs 01–25 (25 items); the rig/animation tier is IDs 26–30 (5 items). Every ID remains in both run denominators, including refusals, schema failures, policy denials, provider failures, timeouts, cancellation, malformed output, and failed checks. Report infrastructure/provider failures in a separate field as well as in end-to-end success.

Per prompt, record raw schema pass, normalized-brief preservation, semantic/preflight pass, direct executable candidate, repair outcome and counts, checked-candidate outcome, visible preview, fresh reopen/save/reopen, independently checked components/materials/colors/relations/dimensions, rig binding and sampled deformation where requested, export parsing and requested-file presence, policy/security findings, wall time, token usage, and cost when available. Keep a failed candidate and its diagnostics in the evidence directory. Do not count a refused or unsupported request as a successful completion.

Use these exact run ceilings: at most four recipe candidates, five semantic provider calls, and ten HTTP attempts. A run that hits a ceiling remains a failed item with the stopping reason recorded. Host code selects output directories and final export destinations. Retain raw model-supplied export paths for the later policy stage to inspect; never silently sanitize away a path-policy violation.

## Deterministic release gate

A checked candidate must pass recipe schema validation, policy preflight and configured resource bounds; reopen correctly as a native project; satisfy independently authored required components, material/color, spatial-relation and dimension checks within the fixture tolerance; produce the requested readable preview and exports; and pass applicable rig/action/deformation checks. Unsupported scope or a policy denial is not a completed candidate.

The proposed target is at least 27 of 30 checked candidates in each of two complete runs, with at least 20 of 25 static items and four of five rig/animation items passing in each run. Report raw counts and per-item failures; do not round a failed tier up to the threshold.

## Disclosure criteria

A fixture may declare `requirements.expected_disclosures`. Its `interpretation` states the independently authored criterion; `expected_phrasing` gives non-exhaustive examples, not exact-match strings; and `semantic_keywords` are concept anchors rather than a mandatory literal word list. If `applies_if` is present, score the disclosure only when that condition holds. Count a criterion only when the captured user-facing interpretation or completion disclosure clearly communicates the same limitation or approximation. Silence, a contradictory capability claim, or visual appearance alone does not pass it. Preserve the exact fixture field in the per-item record.

## Human review

Two evaluators independently inspect the saved preview and native project for each scored run. Each evaluator scores four attributes from 0 to 2:

- Recognizable silhouette: 0 = not recognizable, 1 = partly recognizable, 2 = clear at a useful view.
- Essential components: 0 = a required component is absent, 1 = most are present but one is materially weak, 2 = all essential components are represented.
- Proportions and appearance: 0 = unusable, 1 = rough but serviceable, 2 = coherent and useful for the stated stylised purpose.
- Editability: 0 = project cannot be meaningfully edited, 1 = some parts/materials are awkward to edit, 2 = major parts and materials are inspectable and editable.

An item is human-acceptable only when each evaluator's total is at least 6/8 and neither evaluator scores essential components as 0. Record evaluator scores independently before discussion. Preserve both original score sets, document any disagreement and resolution, and report agreement separately. The target is at least 24 of 30 human-acceptable items in each run. Human scores never replace deterministic checks.

## Discovery probes

Run the eight prompts in discovery.json separately from release scoring. Record whether each is supported, approximated with explicit disclosure, refused, blocked by policy, or requires a user choice. The intended result may be an honest limitation or refusal. Do not quietly translate an unsupported request into a different deliverable and call it complete.

## Live baseline status

The prop, shelter, and rig live-baseline calls have not been run as part of fixture authoring. Record them as pending until a credential, exact provider/model configuration, and explicit spend limit are available. Offline fake-provider tests do not count as live baseline evidence. Do not infer live capability from another checkout, historical report, or a different model version.

Premeasurement revision r2 removed the incidental flat-base wording from ID 01 and tilted-shade wording from ID 02 because these attributes exceeded the master-plan case scope and had no independent geometric assertions; no live runs or scored failures preceded this disclosed revision.
