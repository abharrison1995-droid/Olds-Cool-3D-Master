# Current regression follow-up ledger

2026-10-13: the benchmark tooling implementer started a broad `pytest am3d/ai`
compatibility run while other authorized profile, UI and packaging source edits
were still in progress. Streaming output showed one `F` around 33%; the run
was interrupted before a node name, traceback or complete summary was produced.
The pytest lastfailed cache was `{}` afterward. Root could not access the
implementer's scoped terminal session. The failed node and cause are unknown;
there is no evidence attributing the failure to contention or a specific edit.

This run is incomplete diagnostic evidence, not a regression PASS. Root will
run the full stable-source suite with `--maxfail=1`, preserve exact input
identity and stdout, and resolve any reproduced failure before packaging or
local acceptance. A later passing suite applies only to its recorded source
and environment; it does not supply the missing historical traceback.

The Phase 6 reviewer later observed a separate named timing failure in the
first focused 58-test run:
`test_close_cancel_restores_generation_failure_or_cancel_state[cancelled]`
timed out waiting eight seconds for `not busy and not closing` at test line
658 (57 passed, one failed, 56.39 seconds). The exact case passed alone in
9.53 seconds total, then a complete 58-test run passed in 52.00 seconds.
The original reproduced close-cancel defect and its four new branches were
independently verified fixed. The timing failure's cause remains unknown;
there is no evidence attributing it to contention. The reviewer retained its
trace and scope in `phase-6/INDEPENDENT_REVIEW.md`. Root's final stable-source
build suite will run with immediate first-failure reporting and preserve this
qualification limit rather than silently replacing the first result.

The first isolated Windows bootstrap full suite against input6c570bdd18102fb51f76e3e74626e8ecfd78c05e6d043c3ac47972089579aa9b stopped after27 passes with a named KeyError in test_native_failure_report_does_not_persist_untrusted_exception_text. The resource preflight now occupies checks[0]; a bounded test-only fix selects native_roundtrip by ID and retains privacy assertions. See phase-10/BOOTSTRAP_FAILURE_1.md and phase-4/TEST_SELECTION_REGRESSION_FIX.md. Runtime checker bytes were unchanged; independent verification and another complete suite remain required. This identified failure does not retroactively identify the unknown earlier broad-run F.

## Bootstrap retry1 and reopened packaging (2026-10-14)

The new native-privacy test-selection issue was independently verified fixed (two-node pair), and integrated source regression passed1048/2symlink privilege skips/4existing warnings in672.57s against input840c4e12518e9d279cf713c4e5f0fba3701c3bf9b4ffb29a85d31ee5eedfe41f. This includes the source lifecycle tests; it does not determine the cause of the earlier unknown eight-second close-cancel observation or the interrupted broad AI run.

The later frozen GUI60-second smoke timeout is a separate diagnosed packaging failure: hidden import exception caused by ambient Poppler ICU shadowing Windows ICU. Root captured the QtCore DLL import exception and bounded controlled removal/restoration gave14/14 smoke steps. It is not an explanation for the earlier source close-cancel wait. See phase-10/BOOTSTRAP_RETRY1_FAILURE.md. Reopened packaging source fixes passed root43 checks/4capability skips and independent19 focused checks. Retry2 is running against source2aab9e3b80626ea5020b67cc7bebf01e6488179ab64e2156c38bfa9a645309bc; full final locked regression/artifact qualification remain pending.
