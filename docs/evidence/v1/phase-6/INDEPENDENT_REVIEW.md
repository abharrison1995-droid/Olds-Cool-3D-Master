# Phase 6 independent Qt lifecycle and user-journey review

Review date: 2026-10-13  
Repository HEAD: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`  
Review mode: requested GPT-6 Luna/xhigh, accepted as requested; runtime model/effort was not independently introspected.  
Environment: Windows 10 IoT Enterprise LTSC build 19044 x64, Python 3.12.14, PySide6/Qt 6.11.2, `QT_QPA_PLATFORM=offscreen`.

This was a read-only review of the approved V1 plan sections 4–8 and review policy in section 12, `work/v1/phase6-task.md`, `DESIGN.md`, `docs/evidence/v1/phase-6/ui-implementation-evidence.md`, the generated-profile correction evidence, and the actual controller, workspace, settings, Home and `MainWindow` integration. I reviewed the focused Qt/document tests and generated-profile executor/edit tests. I changed no source or test files; this report is the only review-owned file.

## Verdict

**The local Phase 6 lifecycle review is blocked by one reproduced P2 defect.** If the user starts closing the application during an AI run and then cancels the deferred document-close prompt, the worker stops as requested but the run's terminal outcome is permanently suppressed. The window stays open with the workspace saying it is closing, and a completed result that raced with close cannot be recovered from the current workspace. The close-cancel path must restore or present the terminal state before this local lifecycle gate can pass.

The independently inspected generated-profile correction is present and its focused tests pass. Its supported scope is recipe-generated lathe/extrude source-profile editing through existing spline commands; this review found no basis for claiming a general patch control-net editor. Live provider, native display, frozen and target-platform gates remain unpassed.

## Reproduced defect

### P2 — Cancelling deferred application close discards the run's terminal outcome

**Classification: reproduced defect.** `MainWindow.closeEvent()` asks the controller to shut down an active job, ignores the first close, and later retries closing after `lifecycle_quiescent` (`am3d/ui/app.py:896–918`). The controller sets `_suppress_results=True` in `request_shutdown()` and, when the worker finishes, clears `_pending_outcome` without emitting `outcome_ready` (`am3d/ui/ai_controller.py:346–358, 364–395`). If the document guard then returns Cancel, `closeEvent()` calls `resume_after_close_cancelled()` (`am3d/ui/app.py:903–910`), which only clears the flags and cannot restore that outcome (`am3d/ui/ai_controller.py:360–362`). The workspace has already changed its status to “Closing after the owned AI operation stopped.” (`am3d/ui/ai_workspace.py`, `_on_busy_changed`).

I reproduced this with the existing offline fake orchestrator, without editing repository files. The fixture started a run, waited until the worker entered, set `maybe_abandon_document` to return `False` (the document-close Cancel choice), called `MainWindow.close()`, and pumped Qt events until the deferred close was cancelled. Observed: one outcome was recorded by the fake orchestrator, zero outcomes reached `outcome_ready`, `controller.closing` returned to `False`, and the visible workspace status remained “Closing after the owned AI operation stopped.” This confirms that cancelling the close does not resume the in-progress UI state. The same suppression boundary applies to copy-result signals; in particular, closing during a copy suppresses the explicit copy-cancel completion that normally restores the Open action.

The outcome should remain available until the close decision is final. If close is cancelled, present the actual worker terminal state (including a committed success if one won the cancel/commit race) or a clear cancelled state that leaves a successful checked result actionable. Do not resume with a permanently stale “Closing…” view.

## Checks that passed

The focused lifecycle, Home and document-controller suite passed independently:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py am3d/ui/test_home.py am3d/ui/test_document_controller.py -q --tb=short
```

```text
54 passed in 41.99s
```

That suite covers offline Home entry without credential-backend lookup; stale run IDs and non-increasing event sequences; cancel acknowledgement and retry UUID; copied resources and missing-sidecar refusal; copy cancel/close; dirty-guard cancel and failed-open preservation of Session/undo state; secret sentinels and explicit session-only storage; deferred close; and a real source worker/check/store generation fixture with guarded copy/adoption, manual edits, undo/redo, save/reopen and immutable-record checks. The fake provider keeps the pipeline offline. Existing close tests cover suppression when the application actually continues closing, but not a later Cancel at the deferred document prompt; that missing branch is the reproduction above.

I separately ran the profile correction with its executor and native edit regressions:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/recipes/test_executor.py::test_profile_recipes_keep_generator_degrees_and_append_collision_safe_source am3d/recipes/test_executor.py::test_legacy_recipe_primitives_retain_builder_nets_and_effective_degrees am3d/ui/test_generated_profile_edit.py am3d/ui/test_edit_surface.py -q --tb=short
```

```text
24 passed in 9.27s
```

The exercised cases check lathe/extrude source conventions and generator parameters, degree/net parity with existing primitive builders, appending a collision-safe helper after authored splines without changing explicit-weight indices, edited vertices referenced by rendered triangles, exact undo/redo, native save/reopen, working-copy provenance divergence, and unchanged immutable history hash/manifest. The reported separate owner run of all `test_executor.py` cases (101) and profile/surface cases (16) is recorded in `profile-edit-gap.stdout.txt`; I did not rerun all executor cases.

## Source identity and limits

HEAD remains `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`. All seven UI-file hashes in `ui-implementation-evidence.md` match the current files. The profile-fix identity also matches current files: executor `cc902232491f570dd8975cc44047b53e20106f685e1ca57d765bad91c4742a2b`, executor tests `2bb0e127c4ebe2142d690ef511db7ba07fd93c7e2432b04adcf5c016faf38cb6`, and generated-profile UI test `1ef27d090ce27fa739c1b056ad41b09404bc20bda33853bd21db677a8fcb51cd`. The seven UI identities are recorded in `ui-implementation-evidence.md` and were independently recomputed during this review.

Qt validation was offscreen on Windows 10 IoT LTSC 19044; it does not establish native display, DPI/scaling, GPU, Windows 11, Linux Mint, frozen executable, live provider, secure-backend availability, or artistic acceptance. No credentials, live network call, model spend, commit, push or release occurred. This is one bounded independent review round; after the close-cancel state fix, only a focused verification of that branch and the existing lifecycle suite is needed for this finding.

## Focused verification round — deferred-close cancellation fix

Review date: 2026-10-13. The owner correction is documented in `docs/evidence/v1/phase-6/close-cancel-fix.md`. The original P2 finding above is superseded for the exercised local cases by this focused follow-up; the other live/native/frozen and target-platform gates remain open.

The controller now retains the generation terminal result while deferred close is pending and publishes it only if the document-close prompt is cancelled. The success-race path returns a checked result and Open action without opening the editor. On copy shutdown, the controller reports cancellation after close-cancel resume instead of replaying `copy_ready`, which would invoke adoption. The previous checked result remains available and its Open action is restored. Source inspection found no new editor-adoption path in these resume branches.

I reran my original offline close-cancel reproduction against the fix. It started the existing fake orchestrator, called `MainWindow.close()` while the worker was active, forced the deferred document guard to return Cancel, and waited for quiescence. The new assertions passed: one terminal `cancelled` outcome was delivered, the visible AI workspace showed its terminal message and stage, the same Session remained active, and the controller left closing state. Observed fields:

```text
outcome_delivered=1
terminal_status=cancelled
workspace_status=Fixed test result.
current_session_preserved=True
closing_resumed=True
window_visible=True
```

The four new focused regressions also passed independently:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py::test_close_cancel_restores_generation_failure_or_cancel_state am3d/ui/test_ai_workspace.py::test_close_cancel_restores_late_committed_success_without_auto_adoption am3d/ui/test_ai_workspace.py::test_close_cancel_restores_copy_cancelled_state_without_late_adoption -q -vv --tb=long
```

```text
failed generation: PASSED
cancelled generation: PASSED
late committed success without auto-adoption: PASSED
copy cancellation without late adoption: PASSED
4 passed in 14.61s
```

The complete focused lifecycle/Home/document suite was run twice after the fix. The first run had one failure; the other 57 cases passed. The exact failing node and traceback were:

```text
FAILED am3d/ui/test_ai_workspace.py::test_close_cancel_restores_generation_failure_or_cancel_state[cancelled]
am3d/ui/test_ai_workspace.py:658: in test_close_cancel_restores_generation_failure_or_cancel_state
    assert _wait(app, lambda: not controller.busy and not controller.closing,
                 timeout=8.0)
E   assert False
1 failed, 57 passed in 56.39s
```

The exact parameter passed in isolation (1 passed in 9.53s total). An immediate full rerun passed:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py am3d/ui/test_home.py am3d/ui/test_document_controller.py -q --tb=long
```

```text
58 passed in 52.00s
```

The cause of the first-run wait failure is unknown. The isolated and full-suite reruns passed, but a successful rerun does not explain the first failure or by itself establish that its cause is fixed. I record it as an explicit lifecycle regression/qualification limit; this review did not make further attempts or attribute the timeout to load, contention, or a specific source defect.

The reviewed fix identities independently match the owner evidence:

| File | SHA-256 |
|---|---|
| `am3d/ui/ai_controller.py` | `4083EB07F7C818B7B14CE6CF82BA09D62ECEF851DC01AA207128D618403B213D` |
| `am3d/ui/ai_workspace.py` | `5065A3005C03DD0ECAE2A8D85512BB1C0F9A5BF81805B03DE71D8951CF2D546B` |
| `am3d/ui/app.py` | `81754CA352821BD45A82EBB2D87797E980302C213C62C55A5FFE5E5568792505` |
| `am3d/ui/test_ai_workspace.py` | `18376373AE5455B76218D2EFF5EBF1C61F45887BA0C833A9177D0962FF91E6DC` |

HEAD remains `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`. The fix only changes the controller and its focused tests; the existing `MainWindow.closeEvent()` continues to use the normal document guard. No automatic editor adoption was observed for the committed-success or copy-cancel paths. The generated-profile correction source and tests were unchanged from the identities and passing results above.

**Focused local finding disposition: verified fixed for deferred close-cancel failure, cancellation, committed-success, and copy scenarios.** This does not close the full Phase 6 gate. No live provider/key/network, native display or DPI/GPU, frozen package, Windows 11, Linux Mint, or artistic acceptance was performed. The requested Luna/xhigh configuration remains recorded as accepted from task metadata, not independently introspected.
The exact bounded Python reproduction body (passed through the same PowerShell here-string to `.venv\Scripts\python.exe -`) was:

```python
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from am3d.ui.test_ai_workspace import _app, _settings, _FakeOrchestrator, _Provider, _wait
from am3d.ui.test_operators import _make_main_window
from am3d.ai.credentials import SessionCredentialStore
app = _app()
with TemporaryDirectory() as tmp:
    _settings(Path(tmp) / 'settings')
    _FakeOrchestrator.outcomes = []
    _FakeOrchestrator.entered = threading.Event()
    _FakeOrchestrator.wait_for_cancel = True
    win = _make_main_window()
    win.ai_controller.data_root = Path(tmp) / 'app-data'
    win.ai_controller.orchestrator_factory = _FakeOrchestrator
    win.ai_controller.provider_factory = _Provider
    win.ai_controller.store_factory = lambda _root: object()
    win.ai_controller.session_credentials = SessionCredentialStore()
    outcomes = []
    win.ai_controller.outcome_ready.connect(outcomes.append)
    win.show()
    win.show_ai_workspace()
    win.ai_workspace.brief_edit.setPlainText('offline close cancellation fixture')
    original_session = win.session
    run_id = win.ai_controller.start_generation('offline close cancellation fixture')
    assert _FakeOrchestrator.entered.wait(5)
    win.doc_ctrl.maybe_abandon_document = lambda: False
    win.close()
    assert _wait(app, lambda: not win.ai_controller.busy and not win._close_after_ai, 5)
    app.processEvents()
    assert len(_FakeOrchestrator.outcomes) == 1
    assert len(outcomes) == 1 and outcomes[0].run_id == run_id
    assert outcomes[0].status == 'cancelled'
    assert win.ai_workspace.stage_label.text() == 'Stage: cancelled'
    assert win.ai_workspace.status_label.text() == 'Fixed test result.'
    assert win.session is original_session
    assert win.ai_controller.closing is False
    assert win.isVisible()
    print({'run_id': run_id, 'outcome_delivered': len(outcomes),
           'terminal_status': outcomes[0].status,
           'workspace_status': win.ai_workspace.status_label.text(),
           'current_session_preserved': win.session is original_session,
           'closing_resumed': not win.ai_controller.closing,
           'window_visible': win.isVisible()})
    win.viewport._timer.stop()
    _FakeOrchestrator.wait_for_cancel = False
    win.destroy()
```

The observed run ID was `a8bd6f0e-cf9f-4d86-9ba7-719a340d8aeb`; the assertions passed with one delivered cancelled outcome and the workspace/window/session fields listed above.

The unchanged UI product files were also rehashed after the focused run and still match the implementation snapshot: `am3d/ui/ai_workspace.py` `5065A3005C03DD0ECAE2A8D85512BB1C0F9A5BF81805B03DE71D8951CF2D546B`, `am3d/ui/ai_settings.py` `D909D131A857AB4AC0D22DE2F40D10E4EF9697EFD6F372EF58EA7D09BDFE4A5B`, `am3d/ui/app.py` `81754CA352821BD45A82EBB2D87797E980302C213C62C55A5FFE5E5568792505`, and `am3d/ui/home.py` `D3C89D1B08F1FFCE26A459539CFEBEC393280ADAAE8DE7E3AC5A09FEBCCB9F21`. `am3d/ui/test_home.py` is unchanged at `F1FADA2D5B1ED62E2E54C5C8A26D3F64A6262D758381EB60E043F14BBA6D0CE6`.
