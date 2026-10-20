# Phase 5 independent state-machine review

Review date: 2026-10-13  
Repository HEAD: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`  
Scope: read-only review of Phase 5 orchestration, repair counters, cancellation and the Phase 7 refinement foundation. No source or test files were changed.

The review followed sections 4–10 and 12 of `docs/V1_MASTER_IMPLEMENTATION_PLAN.md`, plus `docs/evidence/v1/phase-5/IMPLEMENTATION.md`. It reviewed `am3d/ai/orchestrator.py`, `contracts.py`, `providers.py`, `records.py`, `worker.py`, `prompts.py`, and the orchestrator/refinement tests. The configured Windows 10 IoT LTSC 19044 x64 offscreen environment was used. The requested Luna/xhigh model configuration cannot be verified from this review runtime.

## Findings

### P2 — Early terminal paths persist stale provider usage and repair counters

**Classification: reproduced defect.** The metered wrapper increments `semantic_calls` before calling the provider and collects usage after a response, but `record["usage"]` and provider metadata are only refreshed after brief interpretation succeeds or after later successful candidate/worker stages (`orchestrator.py:130-140`, `230-273`). A terminal brief interpretation error therefore records the initial all-zero usage snapshot even though the provider was called. Candidate-level early returns have the same gap. The protocol-repair branch increments `validation_repairs` but emits and continues without persisting that new count (`orchestrator.py:357-366`); cancellation from that repair event then finishes with the previous count.

I reproduced both cases with the existing fake provider and memory store, without editing repository files:

```powershell
@'
from pathlib import Path
from tempfile import TemporaryDirectory
from am3d.ai import orchestrator as orch
from am3d.ai.test_orchestrator import FakeProvider, MemoryStore
from am3d.ai.prompts import BriefRequiresUserChoiceError

def interpret(provider, request, deadline, cancellation):
    provider.generate(None, deadline, cancellation)
    raise BriefRequiresUserChoiceError(["USER_CHOICE_REQUIRED: unsupported request"])

original = orch.interpret_brief
orch.interpret_brief = interpret
try:
    with TemporaryDirectory() as root:
        result = orch.GenerationOrchestrator(
            FakeProvider(), MemoryStore(Path(root))
        ).generate("Make something unsupported")
        print(result.status, result.record["usage"], result.record["provider"])
finally:
    orch.interpret_brief = original
'@ | .venv\Scripts\python.exe -
```

Observed: `user_choice_required` with `semantic_calls=0`, `provider_responses=0`, null token totals, and null provider metadata, although `FakeProvider.generate` ran once and returned one response.

The repair-counter case used the same in-memory provider/store, with brief interpretation succeeding, `build_candidate` calling the provider and then raising `ProviderProtocolError`, and the event observer cancelling on `validation_repair`. It returned `cancelled`, `candidate_count=1`, `validation_repairs=0`, and usage showing only the earlier brief call (`semantic_calls=1`, `provider_responses=1`) although the candidate call also ran and one repair was consumed. The command used was:

```powershell
@'
from pathlib import Path
from tempfile import TemporaryDirectory
from am3d.ai import orchestrator as orch
from am3d.ai.test_orchestrator import FakeProvider, MemoryStore
from am3d.ai.contracts import AssetBrief, CancellationToken, ProviderProtocolError

original_interpret, original_build = orch.interpret_brief, orch.build_candidate
def interpret(provider, request, deadline, cancellation):
    provider.generate(None, deadline, cancellation)
    return AssetBrief(brief=request)
def build(provider, brief, deadline, cancellation, **_kwargs):
    provider.generate(None, deadline, cancellation)
    raise ProviderProtocolError("malformed candidate")
orch.interpret_brief, orch.build_candidate = interpret, build
try:
    with TemporaryDirectory() as root:
        token = CancellationToken()
        def cancel_after_repair(event):
            if event.stage == "validation_repair": token.cancel()
        result = orch.GenerationOrchestrator(
            FakeProvider(), MemoryStore(Path(root))
        ).generate("Make a cube", cancellation=token, on_event=cancel_after_repair)
        print(result.status, result.record.get("candidate_count"),
              result.record.get("validation_repairs"), result.record["usage"])
finally:
    orch.interpret_brief, orch.build_candidate = original_interpret, original_build
'@ | .venv\Scripts\python.exe -
```

This makes failed/cancelled run evidence understate actual semantic calls and consumed repair allowance, weakening audit of the stated ceilings and any available usage/cost reporting. Refresh the record snapshot before terminal exits and when consuming a protocol repair; this review does not apply that change.

## Cancel/commit assessment

No defect was reproduced in the final cancellation-versus-publication race. `CancellationToken.commit` validates deadlines and serializes the final atomic promotion against `cancel()`. Publication hashing, tree audits, and sidecar writes occur outside that lock; the protected action is the final rename. The orchestrator rechecks cancellation at stage boundaries, and post-commit cancellation cannot turn a completed result into a cancelled one.

One qualification limit remains: `GenerationAttempt.publish` performs artifact hashing and tree audits before its final `cancellation.commit(...)` call (`records.py:327-390`). Those operations do not poll cancellation. A cancellation request is still observed before promotion, so this does not create a false success, but the review did not measure worst-case cancel-to-terminal latency at the 256 MiB output limit or qualify the desktop acknowledgement target. This is a source-reasoned liveness risk, not a reproduced failure.

The exact candidate/semantic-call ceiling arithmetic is consistent in the inspected loop: one interpretation call plus at most four candidate calls gives five semantic calls; two validation/protocol repairs and one shared runtime/check repair fit that bound. Provider-internal HTTP attempts are unavailable through this adapter contract and should remain `null`, not be inferred as zero. Policy, provider authentication/refusal/configuration, resource, cancellation/deadline, and publication failures are terminal; only bounded schema/protocol and runtime/check paths request another candidate.

The refinement foundation reloads a checked parent, supplies its stored accepted recipe and brief to the child run, and publishes the child separately. The inspected flow does not mutate the parent snapshot. This review did not repeat the measured real-worker refinement integration or qualify editor adoption/manual-divergence UI behavior.

## Review boundary

This is one read-only independent review round. The only executed reproductions were the two bounded fake-provider snippets above; the full focused suite was not rerun. Live provider/credential behavior, Windows 11, Linux Mint, frozen spawning, desktop lifecycle, GPU/native qualification, cancellation latency at maximum output, and artistic quality remain unpassed or outside this review. No changes were made, so there is no fix-verification round.

## Focused verification round — accounting fix

Verification date: 2026-10-13. This was limited to the P2 accounting/counter finding above. The updated `am3d/ai/orchestrator.py` SHA-256 was `84f187777e1d338bba8738e74757a12fa3c595e213f98bbb590c5e8cd86591f5`.

I reran both original bounded fake-provider scenarios against the updated source and added assertions for the outcome plus persisted journal state. The brief user-choice case now records one semantic call and one returned response, with safe provider metadata (`request_id=req-1`). The protocol-error cancellation case now records two semantic calls/responses, the second safe request ID, one candidate, and one validation repair in both the outcome and terminal journal. Unknown HTTP attempts and absent cost remain `null`.

I also reran the fast orchestrator/refinement selection, including the exact call/repair ceiling case and cancellation checks at the starting, interpreting, candidate, checking, and publishing events:

```powershell
.venv\Scripts\python.exe -m pytest am3d/ai/test_orchestrator.py am3d/ai/test_refinement.py -k "terminal_user_choice_snapshots or protocol_repair_cancel_snapshots or provider_error_snapshots or cancellation_is_rechecked or not four_refinements_change_measured_reopened_native_geometry_and_material" -q
```

```text
........................................                                 [100%]
40 passed, 1 deselected in 9.18s
```

The unchanged source limits remain four candidate slots, five semantic calls, two shared validation/protocol repairs, and one shared runtime/check repair. The ceiling regression passed within this focused run. The accounting finding is **verified fixed for the exercised local state-machine cases**. This does not qualify the in-flight Phase 4 publication/checker changes, actual worker/check/publish integration, provider behavior, desktop cancel acknowledgement, or platform acceptance. The publication-stage cancellation-latency risk from the first review was not retested in this accounting-only round and remains an explicit qualification limit. No repository source or test files were modified in either review round, and the earlier initial review evidence was left intact.

This focused follow-up supersedes the earlier statement that fix verification was still pending; that statement recorded the status at the end of the first review round.
