# Phase 6 deferred-close cancellation fix evidence

Status: bounded fix for the reproduced P2 in `INDEPENDENT_REVIEW.md`. This is
implementation evidence for the follow-up review, not a gate pass.

## Identity and scope

- Repository HEAD remains `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`.
- Changed source/test ownership is limited to `am3d/ui/ai_controller.py` and
  `am3d/ui/test_ai_workspace.py`. `MainWindow.closeEvent()` already calls
  `resume_after_close_cancelled()` after the document guard returns Cancel, so
  no `app.py` change was needed. No engine, profile, credential, privacy, or
  transport files were changed.
- No commit, push, release, live provider request, or network call was made.

| File | SHA-256 |
|---|---|
| `am3d/ui/ai_controller.py` | `4083EB07F7C818B7B14CE6CF82BA09D62ECEF851DC01AA207128D618403B213D` |
| `am3d/ui/test_ai_workspace.py` | `18376373AE5455B76218D2EFF5EBF1C61F45887BA0C833A9177D0962FF91E6DC` |

## Behavior change

The controller now retains a matching generation terminal outcome while
deferred close is pending. If the document guard accepts close, result signals
stay suppressed and the window closes only after the worker has quiesced. If
the user cancels close, the controller clears suppression and publishes the
terminal outcome to the workspace. Failed/cancelled runs show their terminal
state and Retry; a completed result that committed before cancellation shows
its checked preview and Open action. Neither path opens or adopts a project
automatically.

Copy shutdown is terminally treated as cancellation even when a `copy_ready`
signal raced just before shutdown. On close-cancel resume, the controller
publishes the fixed copy-cancelled state instead of replaying `copy_ready`, so
the previous checked result and Open action return without editor adoption.
Copy work that observes cancellation before completion still removes its
unadopted working copy.

## Reproductions and regression checks

Focused close-cancel reproductions, including failed and cancelled generation,
late committed success, and cancelled copy:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py::test_close_cancel_restores_generation_failure_or_cancel_state am3d/ui/test_ai_workspace.py::test_close_cancel_restores_late_committed_success_without_auto_adoption am3d/ui/test_ai_workspace.py::test_close_cancel_restores_copy_cancelled_state_without_late_adoption -q -vv --tb=long
```

```text
test_close_cancel_restores_generation_failure_or_cancel_state[failed] PASSED
test_close_cancel_restores_generation_failure_or_cancel_state[cancelled] PASSED
test_close_cancel_restores_late_committed_success_without_auto_adoption PASSED
test_close_cancel_restores_copy_cancelled_state_without_late_adoption PASSED
4 passed in 22.41s
```

Existing focused AI UI, Home, and document-controller lifecycle suite:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d/ui/test_ai_workspace.py am3d/ui/test_home.py am3d/ui/test_document_controller.py -q --tb=short
```

```text
58 passed in 52.52s
```

The existing close-accepted generation test confirms the app becomes hidden,
the worker is no longer busy, and no late outcome is delivered. The copy
quiescence test confirms shutdown suppresses adoption. The new copy close-cancel
case also checks that the original Session/path and checked preview/summary
survive, Open is restored, the late copy is not adopted, and cancellation is
shown. The generation success-race case uses an offline fake worker and checked
fixture preview; it confirms Open is enabled after close-cancel while the
original Session/path remain active.

Syntax compilation passed with exit code 0 and no stdout:

```powershell
.venv\Scripts\python.exe -m py_compile am3d/ui/ai_controller.py am3d/ui/ai_workspace.py am3d/ui/test_ai_workspace.py
```

All tests used Qt offscreen and fake/in-process provider behavior. No actual
provider, credential, or network access was used.

## Follow-up

The original independent UI lifecycle reviewer should verify this focused fix
and the close-cancel paths. Live provider, native display, frozen package, and
other V1 gates remain outside this fix; no Phase 6 acceptance status is claimed.
