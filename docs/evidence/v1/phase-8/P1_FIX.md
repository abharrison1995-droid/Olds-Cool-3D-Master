# Phase 8 P1 correction evidence

**Disposition: the editable-record self-authentication path is closed for ordinary report/import verification. This correction is ready for fresh independent verification; it is not a methodology acceptance, live benchmark result, human-review pass, or release decision.**

The finding in `INDEPENDENT_REVIEW.md` was that `verify_success_artifacts()` trusted `record.json`'s editable provider/model, passed-check claims, and artifact hashes. A record-only edit could therefore turn arbitrary project/preview bytes into a claimed success.

`apply_outcome()` now captures an append-once receipt only while applying a returned successful `GenerationOutcome`. Before writing it, capture verifies the returned run identity, provider/model, accepted recipe/brief, and complete checker report against the committed record and sidecars; the store independently rechecks its artifact tree. The caller must supply the full frozen fixture object, which is hashed against the manifest item identity. The receipt records that fixture and its exact assertion envelope, run/manifest identity, provider/model, complete report and sidecar hashes, full record hash, recipe hash, artifact manifest, and every artifact byte hash. Its canonical JSON digest and fixed receipt path are anchored on the item in `run.json`. Create-only file semantics prevent a normal run from overwriting a receipt. Report, template, and import paths never mint or re-anchor missing receipts.

Every later success verification checks the journal anchor and canonical receipt digest, frozen fixture/run-manifest identity, record and sidecar bytes, provider/model binding, recipe, report, store manifest, and artifact hashes. It then decodes the bounded 512×512 PNG, checks nonblank occupancy/contrast, and copies the bounded native project to a private temporary directory for actual load, save, and reopen with the application serializer. The loaded and reopened project-content digests must match. Native checks use a 32 MiB maximum; preview PNGs use a 16 MiB maximum. Missing receipts and mismatched or legacy unreceipted records fail closed.

This is a consistency receipt created by trusted host execution, not a provider signature or a defense against the current account rewriting the program, journal, and receipt together. No cryptographic-origin claim is made. The user/provider can still control service behavior under a declared alias, and report status still cannot replace the two independent visual reviewers. Offline results remain `NONQUALIFYING`; item denominator and original human-score archive rules are unchanged.

## Verification performed

From `C:\Users\Alex\Desktop\Olds-Cool-3D-Master`:

```text
.venv\Scripts\python.exe -m py_compile am3d/ai/benchmark.py am3d/ai/test_benchmark.py scripts/run_ai_benchmark.py
.venv\Scripts\python.exe -m pytest am3d/ai/test_benchmark.py -q --tb=short
```

Results: compilation succeeded; **13 focused offline tests passed in 30.81 seconds**. The new receipt path uses the actual orchestrator, real `GenerationRecordStore`, and actual worker/checker subprocess with deterministic offline provider responses. The adversarial test rewrites both fake artifact bytes and a self-consistent record/receipt/journal anchor, then confirms physical PNG/native validation still rejects them. It also verifies that a changed returned in-memory provider identity prevents receipt creation, record provider/check changes fail with unchanged artifact bytes, missing/changed receipts fail, report generation does not recreate a missing receipt, and the offline report cannot qualify.

No live provider, network request, credential, or cost was used. No source runtime/store/checker/fixture/UI/packaging file was changed. The previously interrupted broad diagnostic remains unidentified and incomplete as documented in `IMPLEMENTATION.md` and `REGRESSION_FOLLOWUP.md`; it is not cleared by this focused run. A fresh independent methodology review is still required.
