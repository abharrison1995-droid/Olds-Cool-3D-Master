# Phase 8 independent benchmark methodology review

**Verdict: not ready for methodology acceptance.** The fixed denominator, offline qualification label, budget disclosure, and reviewer-import paths are generally implemented as described, and the focused suite passes. One reproduced integrity gap lets a locally edited generation record turn arbitrary artifact bytes and self-asserted provider/check results into a valid deterministic success. No live-provider, network, or human-review evidence was created; this review does not qualify capability or release.

## Authority, input identity, and scope

Authority reviewed: `docs/V1_MASTER_IMPLEMENTATION_PLAN.md` section 10 and Phase 8; `work/v1/phase8-task.md`; `benchmarks/v1/rubric.md`; the frozen release/discovery fixtures; `scripts/run_ai_benchmark.py`; `am3d/ai/benchmark.py`; `am3d/ai/records.py`; `am3d/ai/test_benchmark.py`; and the implementation evidence/hash index. The interrupted broad diagnostic remains unidentified as described in `docs/evidence/v1/REGRESSION_FOLLOWUP.md`; I do not attribute it to this tooling.

Checkout HEAD was `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`. The environment reported Python 3.12.14 on Windows 10 build 19044. Frozen release prompts were unchanged at SHA-256 `0ef3291a7cb5818091a1a22ebdbfe75dc9cb4118274f32fe6395c478e119e560` (r2); discovery was `6483ccc038853cc50e7c9edc7c50e56cfef717151482aa84f1dcbf055177875b`; rubric was `b7c84a93d638bf46a0ac3223702abba7870997a89793b6b33b39a19d8b92026b`. The implementation-owned hashes matched `OWNED_FILE_HASHES.json` at review time:

| File | SHA-256 |
| --- | --- |
| `scripts/run_ai_benchmark.py` | `7578f40241493529d96547b73f35832b26250faa412cfeb9e6c822ac7fac4dbe` |
| `am3d/ai/benchmark.py` | `32baa0c0599786e498f06b615886f48bcc5c1fc978918688e832403950fb00f9` |
| `am3d/ai/test_benchmark.py` | `85829f3bcab5e1ee0eae2168b88d4a765357aa3ffaec8027295e85172c08a1c8` |
| `docs/evidence/v1/phase-8/IMPLEMENTATION.md` | `45c180ae4f44f4507bf02b996853752fe6f7f05e7796097fb3ff01dc9ea98d19` |

The requested Luna / xhigh / none settings are recorded as request metadata only; this review did not introspect runtime model settings. No source, test, fixture, runner, or implementation-evidence files were changed. This report is the sole file added by the review.

## Finding

**P1 — the success verifier trusts editable provider and check claims in `record.json`.** `am3d/ai/records.py` excludes `record.json` from `_artifact_manifest` because it cannot contain its own hash (lines 279–280). `GenerationRecordStore.get_record()` validates the artifact list against the files, but does not authenticate the record metadata itself (lines 607–616). `am3d/ai/benchmark.py` then trusts `record["check_report"]` for native-roundtrip and whole-scene-preview success and trusts `record["provider"]` for provider/model binding (lines 616–638); it sets `record_manifest_verified` to true at line 645. The benchmark journal does not hold an independent digest or receipt for those record fields.

This is reproducible with one post-run edit to the per-user store. A temporary store containing arbitrary non-PNG preview bytes and arbitrary non-project native bytes was given a self-consistent artifact manifest. With `record.json` reporting `offline-fake` and failed checks, the verifier rejected it. Editing only `record.json` to say `openai-compatible` / `live-model` and to report passed checks made `verify_success_artifacts()` return `valid: true`, `provider_matches_manifest: true`, and `native_roundtrip: true`. The stored artifact hashes still matched because the modified record supplied the hash list used for comparison; no PNG decode or native reopen/save/reopen was performed at report time. Thus an editable record can inflate deterministic success counts or bind artifacts to the wrong provider/model. The focused provider-binding unit test stubs `_record_for_item`, so it does not exercise this store-metadata trust boundary.

Relevant source locations: `am3d/ai/records.py:279` and `:602`; `am3d/ai/benchmark.py:593`, `:616`, `:628`, `:634`, and `:645`.

The verifier needs an independent anchor for the complete generation receipt, including provider/model and check report, and must validate that receipt before using it. The review does not implement that correction. The per-user LocalAppData ACL limits access by other accounts, but it does not make the current user's own generation record immutable or tamper-evident.

### Independent reproduction

Run from the repository root. This creates and removes a temporary store and uses no network or provider:

```powershell
@'
import json, shutil, tempfile, uuid
from pathlib import Path
from am3d.ai import benchmark, records

root = Path(tempfile.mkdtemp(prefix="v1-review-record-"))
try:
    run_root = root / "run"
    generation_id = str(uuid.uuid4())
    generation = run_root / "store" / "generations" / generation_id
    generation.mkdir(parents=True)
    (generation / "project.am3d").write_bytes(b"not a native project")
    (generation / "preview.png").write_bytes(b"not a PNG")
    artifact_manifest, _ = records._artifact_manifest(generation)
    record_path = generation / "record.json"
    record = {
        "run_id": generation_id, "status": "complete",
        "artifact_manifest": artifact_manifest,
        "provider": {"provider": "offline-fake", "model": "fake-model"},
        "check_report": {"ok": False, "status": "failed", "checks": []},
    }
    record_path.write_text(json.dumps(record), encoding="utf-8")
    item = {"generation_id": generation_id}
    manifest = {"provider": {"provider_id": "openai-compatible", "model": "live-model"}}
    before = benchmark.verify_success_artifacts(run_root, item, manifest)
    record["provider"] = {"provider": "openai-compatible", "model": "live-model"}
    record["check_report"] = {"ok": True, "status": "passed", "checks": [
        {"id": "native_roundtrip", "status": "passed"},
        {"id": "whole_scene_preview", "status": "passed"},
    ]}
    record_path.write_text(json.dumps(record), encoding="utf-8")
    after = benchmark.verify_success_artifacts(run_root, item, manifest)
    print(json.dumps({"before_valid": before["valid"],
        "after_record_json_edit_valid": after["valid"],
        "fake_project_bytes_accepted": after["native_project"] is not None,
        "fake_png_bytes_accepted": after["preview"] is not None,
        "after_provider_matches": after["provider_matches_manifest"],
        "after_roundtrip_claim": after["native_roundtrip"]}, sort_keys=True))
finally:
    shutil.rmtree(root, ignore_errors=True)
'@ | .venv\Scripts\python.exe -
```

Observed stdout:

```json
{"after_provider_matches": true, "after_record_json_edit_valid": true, "after_roundtrip_claim": true, "before_valid": false, "fake_png_bytes_accepted": true, "fake_project_bytes_accepted": true}
```

## Checks and limits

Commands run from the repository root:

```text
.venv\Scripts\python.exe -m pytest am3d/ai/test_benchmark.py -q --tb=short
.............                                                            [100%]
13 passed in 14.90s

.venv\Scripts\python.exe -m py_compile am3d/ai/benchmark.py am3d/ai/test_benchmark.py scripts/run_ai_benchmark.py
exit 0

.venv\Scripts\python.exe scripts/run_ai_benchmark.py --help
exit 0; displayed the eight expected subcommands and described offline fake as default.
```

The reviewed code and focused tests support fixed release IDs/tier floors, separate eight-item discovery, failure/interruption retention, source/fixture drift checks, offline `NONQUALIFYING`, bounded semantic calls and completion-output reservations, null unknown costs/actual HTTP attempts, secure credential sourcing, original human-score archival, and separately derived disagreement resolution. No live provider/model or human scores exist. The configured completion reservation does not cap prompt-input tokens or dollar cost; actual cost and transport-attempt counts remain unavailable as disclosed. Two full live 30-item ledgers, two independent reviewer imports per run, Phase 7, target-host qualification, and the root's stable full-suite run remain pending. The implementation evidence's interrupted broad compatibility run is incomplete and is not a pass.

No network request, live provider call, credential access, asset-generation run, commit, push, or release action occurred. The methodology verdict applies only to this local tooling review and leaves all live capability and human gates unqualified.

## Focused verification of the P1 correction

**Disposition: the original P1 finding is closed for record-only edits and the tested self-consistent artifact/receipt/journal rewrites.** This is a focused verification of the correction described in `P1_FIX.md`, not a broader methodology pass, live qualification, proof of provider origin, or protection against the same account rewriting the source, manifest, journal, receipt, and generated evidence together.

The original temporary-store reproduction was repeated against the corrected verifier. With a missing receipt anchor, editing `record.json` from offline/failing to live/passed left the result invalid; provider binding and native-roundtrip status stayed false. Exact stdout:

```json
{"after_record_json_edit_valid": false, "before_valid": false, "native_roundtrip_after_edit": false, "provider_matches_after_edit": false, "receipt_anchor": null}
```

The corrected real-pipeline test exercised the actual orchestrator, worker/checker subprocess, `GenerationRecordStore`, return-value binding, append-once receipt creation and report verification. It also changed provider/check claims with unchanged artifacts, then replaced artifact, record, receipt and journal-anchor hashes around invalid PNG/native bytes, removed and edited receipts, and checked that report generation did not mint a missing receipt. Those mutations failed integrity verification. The separate two-ledger fake-mode test kept both offline reports and the release gate `NONQUALIFYING`.

Verification commands and observed results:

```text
.venv\Scripts\python.exe -m pytest am3d/ai/test_benchmark.py -q --tb=short
13 passed in 37.12s

.venv\Scripts\python.exe -m pytest am3d/ai/test_benchmark.py -q --tb=short -k "real_offline_worker_store_receipt_is_anchored_once_and_rechecked or offline_gate_is_always_nonqualifying_even_with_two_ledgers"
2 passed, 11 deselected in 25.88s
```

Current hashes match every entry in `OWNED_FILE_HASHES.json`:

| File | SHA-256 |
| --- | --- |
| `scripts/run_ai_benchmark.py` | `dffa2dd2886ff6298303c8aee1691c6d7ef83735fb95b0488763b1016f13f13b` |
| `am3d/ai/benchmark.py` | `9b1940cb95975337edc63e569128bd1717b5c70ddc03918442cae8080941c1df` |
| `am3d/ai/test_benchmark.py` | `2cda61885af700cd9347ea9847bf6db5d9a36e3a70320665e7682f8aa213e1b1` |
| `docs/evidence/v1/phase-8/IMPLEMENTATION.md` | `4c5a79b9d209d16e61c2421d74e91cf351c4f10f9359aaeeb172b1126a4265e2` |
| `docs/evidence/v1/phase-8/P1_FIX.md` | `532c4bf04fba0e4a52694d1721f3c2c24fdfd9e1514958e0b31218d8fa087a6f` |

No source, test, fixture, runner, or implementation evidence was changed during this verification; only this independent review file was appended. No live calls, credentials, network requests, commits, pushes, or release actions were used. The exact self-consistency/tamper behavior is verified for these changes. It does not establish authenticity against a user who rewrites all local code and evidence, actual provider snapshot identity, the two-run live gate, human review, Phase 7, target-host qualification, or the unidentified interrupted broad-suite failure.
