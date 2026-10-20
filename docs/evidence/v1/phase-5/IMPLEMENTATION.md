# V1 Phase 5 — bounded headless orchestration

## Implemented behavior

`am3d.ai.orchestrator.GenerationOrchestrator` coordinates one brief
interpretation, recipe candidates, safe validation repair, isolated worker
execution, deterministic checks, and immutable publication without importing
Qt. The shared wall-clock budget is capped at 600 seconds and each worker at
180 seconds. A run permits at most four candidates and five semantic provider
calls, with two validation/protocol repairs and one runtime/check repair shared
across those failure types. Provider adapters retain their two-HTTP-attempt
ceiling; the current adapter contract does not expose its internal attempt
count, so `usage.http_attempts` is recorded as `null`.

Only a worker result with `status == "checked_ok"` and a passing bounded check
report can be published. The orchestrator passes the worker's inner
`attempt-<id>` directory to `GenerationRecordStore.publish`, which rechecks
artifact hashes and paths. Cancellation and deadline are checked again at the
store's final atomic promotion boundary. The cancellation token serializes that
commit against cancel requests; a request after promotion cannot relabel a
completed run. Failed attempts retain their private state record and cannot
replace a prior generation.

Events have a per-run increasing sequence, run ID, stage, candidate attempt,
fixed bounded message, and no fabricated progress percentage. Observer
exceptions are ignored. Errors returned to callers and passed into repair are
allowlisted structured code/stage/path/hint records; raw provider exceptions,
response bodies, credential material, and arbitrary local paths are not
retained. Provider metadata is recorded only after a validated response.
Token and cost fields remain `null` when the provider does not report them.
Application provenance uses the records helper's declared source hash/build
identity and reports unavailable identities as such.

Refinement starts a new child run from a complete checked parent loaded through
the store. It sends the combined original brief and requested refinement for
interpretation, passes the prior accepted recipe to candidate generation,
links the child to the parent, and leaves the parent's immutable record and
native project unchanged. There is no parent recipe-diff helper; the native
refinement integration checks reopened per-component bounds for a flatter
roof, both longer arms, and a larger wheel, plus the body material requirement.
The roof starts at a positive angle and becomes flat; the assertions measure
named meshes rather than global scene bounds that unrelated parts could change.

## Evidence

Offline state-machine/refinement tests cover repair and call ceilings,
terminal provider/policy failures, sanitized repair input, publication
failure, cancellation boundaries and late cancellation, invalid deadline
configuration, verified-parent gating, and observer exceptions. A fake provider
is used; no live API credentials or network calls are involved.

The real-worker integration exercises a valid recipe through the subprocess
worker, native reopen, deterministic checks, artifact hash verification, and
immutable record publication. It was run five times using pytest's nested
Windows temporary root after the worker's fixed serializer-temporary live-audit
allowance was added. Each run passed. A separate offline refinement case sends
four fake refinements through the real worker/checker and compares reopened
native component bounds and material color after reopening each published
native project.

Commands:

```powershell
.venv\Scripts\python.exe -m pytest am3d/ai/test_orchestrator.py am3d/ai/test_refinement.py -q
.venv\Scripts\python.exe -m pytest am3d/ai/test_orchestrator.py::test_valid_recipe_runs_through_real_worker_checks_and_immutable_publish -q
```

Latest focused-suite output after the typed user-choice and per-component
measurement changes:

```text
.....................................                                    [100%]
37 passed in 128.54s (0:02:08)
```

The new fixed-copy limitation-choice regression also passed independently:

```powershell
.venv\Scripts\python.exe -m pytest am3d/ai/test_orchestrator.py::test_user_choice_error_surfaces_only_fixed_known_limitation_choices -q
```

```text
...                                                                      [100%]
3 passed in 0.87s
```

The measured four-refinement native round-trip case passed independently:

```powershell
.venv\Scripts\python.exe -m pytest am3d/ai/test_refinement.py::test_four_refinements_change_measured_reopened_native_geometry_and_material -q
```

```text
.                                                                        [100%]
1 passed in 103.77s (0:01:43)
```

The long-root checked worker/check/publish integration was repeated five times
with the command above; each invocation reported `1 passed`. Per-run elapsed
times were 19.91s, 18.53s, 13.05s, 22.54s, and 20.50s.

## Independent-review finding disposition

The first independent review reproduced a P2 evidence defect: terminal paths
could persist stale usage and repair counters. The orchestrator now has one
`_RunState.snapshot(record)` accounting path used before every run-state write
and terminal outcome. It derives semantic-call attempts from the metered
provider, aggregates usage and provider metadata only from returned validated
`ProviderResponse` objects, and uses `null` for unavailable token/cost/HTTP
attempt values. A provider exception counts the attempted semantic call but
does not invent response usage or provider metadata. Candidate and repair
counters are single-source run-state fields; candidate slots increment after
private candidate-directory creation, and validation/runtime repair counts are
persisted before observer callbacks can cancel the run.

Disposition: implementation fix applied; same-reviewer verification requested
and still pending. No self-review pass is claimed. This follow-up does not
change records/checks files. After Phase 4 checker/record changes stabilized,
the actual worker/check/publish integration was rerun and passed.

The fast accounting/state-machine suite was run with:

```powershell
.venv\Scripts\python.exe -m pytest am3d/ai/test_orchestrator.py am3d/ai/test_refinement.py -k "terminal_user_choice_snapshots or protocol_repair_cancel_snapshots or provider_error_snapshots or cancellation_is_rechecked or not four_refinements_change_measured_reopened_native_geometry_and_material" -q
```

```text
........................................                                 [100%]
40 passed, 1 deselected in 9.31s
```

The unchanged real-refinement test was deselected for this fix; it previously
passed after the component-local measurement correction. The latest source
SHA-256 after the resource-limit terminal seam is
`162c043dc2fc710ae5f7eab75088336e82415e692f0d46ef487d53699c5623d0`.

## Checker resource-limit terminal contract

The Phase 4 checker now supplies a trusted top-level boolean
`check_report.resource_limit`. The orchestrator treats only the literal boolean
`true` as a host resource-limit terminal, before the success-promotion or
ordinary check-repair branches. It records the fixed `resource_limit` error at
the `check` stage and preserves current usage/counters and the bounded report.
Absent/false fields and truthy non-booleans do not trigger this contract;
ordinary structural or material check failures retain their single bounded
repair opportunity.

The post-Phase 4 real worker/check/publish integration passed after the new
guard was applied:

```powershell
.venv\Scripts\python.exe -m pytest am3d/ai/test_orchestrator.py::test_valid_recipe_runs_through_real_worker_checks_and_immutable_publish -q --tb=short
```

```text
.                                                                        [100%]
1 passed in 7.13s
```

The focused terminal-seam and accounting regressions passed with:

```powershell
.venv\Scripts\python.exe -m pytest am3d/ai/test_orchestrator.py -k "host_resource_limit or truthy_nonboolean_resource_limit or check_failure_gets_one_shared_repair_then_publishes or protocol_repair_cancel_snapshots or terminal_user_choice_snapshots or provider_error_snapshots or cancellation_is_rechecked" -q --tb=short
```

```text
.............                                                            [100%]
13 passed, 23 deselected in 4.95s
```

## Qualification still required

This file records implementation evidence, not Phase 5 acceptance. Fresh
independent state-machine/security review and the approved live-provider
small-set gate remain pending. The focused tests do not qualify the desktop UI
lifecycle, guarded document adoption, frozen executable spawning, or Windows
11/Linux release acceptance.
