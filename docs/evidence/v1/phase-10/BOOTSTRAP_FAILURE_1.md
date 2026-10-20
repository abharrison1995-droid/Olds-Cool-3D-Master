# First bootstrap attempt — failed source regression, no package

Frozen input6c570bdd18102fb51f76e3e74626e8ecfd78c05e6d043c3ac47972089579aa9b; baselineHEAD3f6f7f03d32b4d1a3af06af4fdc0724bf0436945, version1.0.0.dev1. The command in BOOTSTRAP_START.md exited1 at the full-suite stage. Isolated dependency installation resolved38 packages; PyInstaller, archive creation and lock capture were not reached.

The exact first traceback is retained in bootstrap-build.log, SHA-256db67006d79221da3308f6e8a777ada3175171fb74059b7f40d12bedff8bf9b20. Result:1 failed,27 passed in96.01s. Named node: test_native_failure_report_does_not_persist_untrusted_exception_text in am3d/ai/test_checks.py, KeyError reason at line554.

Root source investigation identified a stale test assumption: checks[0] now identifies the successful output-tree byte preflight, not native_roundtrip. The runtime still emits the fixed native failure reason and omits untrusted exception text. A bounded Luna implementer changed only the test to select semantic check IDs, retained the whole-report sentinel privacy assertion, and asserted preflight success, native failure and resource_limit false. Two focused checks passed0.80s and the16-check module passed78.99s in the isolated build interpreter. Exact pre/post identities and commands are in phase-4/TEST_SELECTION_REGRESSION_FIX.md. Independent verification is pending; no runtime fix is claimed for this test change.

Separately, the fresh integrated architecture reviewer reproduced a percent-encoded credential endpoint guard bypass using a fake in-memory key and MockTransport, with no network or real credential. That material privacy fix and independent verification must finish before another source freeze/build. The original frozen manifest/log remain unchanged; a new attempt must use a distinct manifest/log and recomputed input digest.

These named current findings do not supply the unavailable traceback from the earlier interrupted broad AI diagnostic, and do not explain the earlier Phase6 eight-second close-cancel timeout. Preserve both limits in REGRESSION_FOLLOWUP.md. This attempt is a FAIL, not a packaging or lock-capture PASS.
