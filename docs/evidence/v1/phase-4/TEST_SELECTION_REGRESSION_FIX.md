# Phase 4 test-selection regression fix

Date: 2026-10-14  
Baseline HEAD: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`  
Frozen Windows build-input digest in the bootstrap receipt: `6c570bdd18102fb51f76e3e74626e8ecfd78c05e6d043c3ac47972089579aa9b`

## Diagnosis and change

The Windows bootstrap stopped at the first failure in `test_native_failure_report_does_not_persist_untrusted_exception_text`. The test selected `report["checks"][0]` as the native check, then raised `KeyError: 'reason'`. `check_artifacts()` now appends a successful `output_tree_preflight` check before attempting native loading. In this fixture, that first check has byte-count details and no `reason`; the failing native check remains present under ID `native_roundtrip` with reason `native_project_or_provenance_verification_failed`.

The test now selects both checks by semantic ID and asserts that the preflight passed, the report is not a resource-limit failure, and the native roundtrip failed with the fixed reason. It retains the assertion that the serialized report contains no untrusted sentinel text. The existing pre-read Phase 4 resource review records the requirement that the tree budget be checked before native or exported file loading and its regression `test_output_tree_byte_preflight_stops_native_loading`; this test fix explicitly checks that preflight ordering remains visible in the native-failure case.

Other positional references in `test_checks.py` were reviewed. The `checks[0]` access in `test_export_preflight_stops_glb_parser_reads` inspects the sole check returned by the isolated `_verify_exports()` helper, so it does not rely on the `check_artifacts()` ordering that changed. The `[0]` accesses in the GLB image and resource-detail fixtures select the single expected array element and are unrelated to native check selection. No other same-cause assumption was found.

## Preserved bootstrap failure receipt

The actual Windows bootstrap used `build/windows/venv`, installed 38 packages from `requirements-dev.txt` because no Windows lock was present, and stopped during the full test suite with **1 failed, 27 passed in 96.01s**. No successful build or lock capture is claimed. Its first-failure trace is preserved unchanged in `docs/evidence/v1/phase-10/bootstrap-build.log` (SHA-256 `DB67006D79221DA3308F6E8A777ADA3175171FB74059B7F40D12BEDFF8BF9B20`):

```text
____ test_native_failure_report_does_not_persist_untrusted_exception_text _____
am3d\ai\test_checks.py:554: in test_native_failure_report_does_not_persist_untrusted_exception_text
    assert native_check["details"]["reason"] == "native_project_or_provenance_verification_failed"
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
E   KeyError: 'reason'
1 failed, 27 passed in 96.01s (0:01:36)
```

This failure was caused by a stale test-selection assumption. It did not indicate a regression in exception-text suppression: the sentinel-absence assertion remains in place and passes after selecting the native check by ID.

## Focused verification

Environment: existing `build/windows/venv`, `QT_QPA_PLATFORM=offscreen`.

```powershell
$env:QT_QPA_PLATFORM='offscreen'; & .\build\windows\venv\Scripts\python.exe -m pytest am3d/ai/test_checks.py::test_native_failure_report_does_not_persist_untrusted_exception_text am3d/ai/test_checks.py::test_output_tree_byte_preflight_stops_native_loading -q --maxfail=1 --tb=short
```

```text
2 passed in 0.80s
```

The complete focused checker module also passed:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; & .\build\windows\venv\Scripts\python.exe -m pytest am3d/ai/test_checks.py -q --maxfail=1 --tb=short
```

```text
16 passed in 78.99s (0:01:18)
```

## Identity

`am3d/ai/test_checks.py` SHA-256 before this edit: `7246329B5DD72373B9D3895B18F56BF2FDFB74886FB6E6318F68F7DF7638E17C`.  
`am3d/ai/test_checks.py` SHA-256 after this edit: `EB837EAED63FF3E1F18FF89FB70395CF36AB90023EE37E68A472F88902A5D687`.  
`am3d/ai/checks.py` SHA-256 after verification: `2C610C348E71D1311854EE9E3618DB2E62164067C87FEC2A84CA011708F27421` (unchanged from the frozen bootstrap input).

This regression fix changes only the Phase 4 test and this evidence record. It does not alter checker/runtime behavior or claim that the previously stopped full Windows bootstrap passed.
