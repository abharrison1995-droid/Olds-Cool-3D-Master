# Phase 10 Packaging and Tooling Review

Review date: 2026-10-13. Review mode: independent source/tooling review; no implementation.

## Scope and identity

Reviewed the Phase 10 and release-ladder requirements in `docs/V1_MASTER_IMPLEMENTATION_PLAN.md` (SHA-256 `9490c687c240598317d7db74048961772e60034f6b8ebadde2565e2100ef16b1`) and `work/v1/phase10-task.md` (SHA-256 `12edbdbedd6503c397ff3fe3f5321d36e669f89f9aa72d5fb60975cb2df4c19e`), plus the tooling-preparation and strict-source-followup receipts (hashes below).

Checkout HEAD remains `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`, with the authorized V1 working-tree changes present. The complete input digest read `f781efc9f9435821a4026b6a88c4af7de89abaf9d5070d3a3067db39c53e2566` at the start of focused verification and `39b1a2b795d61d94d8d587d9b6d763098445e069c524fea3f00ed10b31ac843b` at close; the latter returned twice consecutively. The plan document also changed during the review. This is a moving-source review, not evidence for a frozen candidate or an exact test-time source digest.

The documented host is Windows 10 IoT Enterprise LTSC, build 19044 x64, not the Windows 11 target. The Windows lock is absent, the Linux lock is present, and the evidence directory contains no build/archive. No build, lock capture, archive, frozen acceptance, clean-machine, native Mint, Windows 11, live network, or physical-GPU qualification was run or claimed.

## Findings and dispositions

### [P1] Confirmed Phase 10 qualification blocker — no target candidate has been built or qualified

Phase 10 requires the exact frozen archive, source/input digest, a successful locked build, and qualification on Windows 11 and Mint 22.3 (`docs/V1_MASTER_IMPLEMENTATION_PLAN.md`, lines 365–372 and 421–426). The current evidence explicitly says no build/archive or lock capture was run; the Windows lock file is absent, and this workstation is Windows 10 IoT 19044. The successful source/offscreen checks below cannot satisfy the frozen, clean-host, native-desktop, or GPU rungs. Keep both target gates open. After source freeze, the Windows bootstrap proposal must be followed by a full build against the promoted Windows lock; the proposal pass alone is not a candidate identity.

### [P1] Source-reasoned risk — build-input digest silently degrades when Git enumeration fails

`scripts/build_input_digest.py:73–80` catches Git execution errors and returns an empty tracked-path set. The digest then cannot report a deleted tracked runtime/lock/script input at lines 129–138, although the build scripts can treat Git provenance calls as optional. This makes the advertised complete tracked/untracked inventory fail open on a checkout without a working Git command. Disposition: make tracked-path enumeration failure explicit and fail the digest/build, or define and test a complete non-Git inventory mode. This condition was source-inspected, not separately induced during this review.

### [P1] Confirmed credential-qualification blocker; fixed acceptance itself is not defective

`am3d/ai/frozen_acceptance.py:177–194` imports the explicit platform class, while lines 202–205 and 251–259 construct and use `SessionCredentialStore`. The output deliberately says `credential_backend_import` at line 422. Thus the fixed offline acceptance proves that the backend module imports in a frozen process; it does not prove OS credential-service availability or CRUD. This is honest labeling and appropriate for an offline MockTransport test. Treating the session store as a self-test bug would be a false positive.

The separate source-host probe performed store, read, overwrite/rotate, read, delete, and absence verification through `SystemCredentialStore` on this Windows 10 host; it passed and cleaned up its randomly named alias. That does not prove behavior in the frozen payload or on Windows 11. The fixed CLI currently has only `--internal-ai-worker` and `--ai-self-test` dispatch before Qt (`am3d/ui/__main__.py:17–31`); the self-test parser accepts only `--out` (`frozen_acceptance.py:433–439`). It exposes no bounded frozen credential-sentinel CRUD entry point. Disposition: keep the offline self-test unchanged and require a separate, explicitly invoked trusted frozen-host probe with a random owned alias, store/get/rotate/delete/absence checks, and cleanup; also exercise the locked/unavailable path without recording secrets. Do not report import success as secure-store acceptance.

### [P2] Suggestion — fail fast on the first source-test error during diagnostic builds

The full-suite commands in `build_windows.ps1:196` and `build_linux.sh:193` use quiet output and short tracebacks but no `--maxfail=1`. For the owner’s diagnostic follow-up to the unexplained prior test failure, adding `--maxfail=1` to both commands would surface the first traceback sooner. This is a diagnostic suggestion, not a finding about the cause and not a substitute for a complete passing suite on the final locked source.

### [P2] Source-reasoned evidence gap — runtime notices are not yet tied to a frozen payload inventory

`scripts/write_runtime_licenses.py:16–27` names the expected common/platform distributions and copies available upstream license texts; the preparation receipt records a successful helper probe with 18 notices and 37 license texts. The helper is driven by that fixed package list, not by an executed PyInstaller payload inventory. No frozen payload exists here to compare. Disposition: after a real build, retain the notice output and compare it with the actual runtime closure/TOC before treating payload license coverage as accepted. This is an unverified artifact gate, not a reproduced omission.

## Packaging/tooling review

- **Late lock capture:** `build_windows.ps1:58–67, 109–163` rejects `-CaptureLock` with `-SkipTests`, refuses replacement of an existing lock, installs the isolated development set only for bootstrap, verifies the exact source lock when present, and writes the proposal after candidate checks. `.github/workflows/windows.yml:27–47` promotes the proposal and runs the locked build again. The digest explicitly includes the Windows lock when present; the bootstrap provenance is marked non-final. No capture was run here.
- **Isolation and HTTPS/keyring payload:** Windows takes an explicit host Python path and creates `build/windows/venv`; Linux uses `build/linux/venv` and requires its lock. `am3d.spec:32–65, 77–112` requires and includes the certifi CA file, the identity file, and explicit Windows Vault/win32ctypes or Linux Secret Service/secretstorage/jeepney/cryptography imports. These are source checks only; no frozen dependency closure was inspected.
- **Qt-free entry paths:** `am3d/ui/__main__.py:17–33` dispatches the worker and fixed self-test before importing `am3d.ui.app`; `am3d/ui/__init__.py` lazily exposes app exports. `am3d_recipe.spec:42–65` excludes Qt, GPU, and UI imports. The focused tests passed these source contracts; only a frozen run can confirm PyInstaller's realized imports.
- **Fixed mock flow:** `frozen_acceptance.py` hard-codes its endpoint, responses, brief, recipe, and refinements; uses `httpx.MockTransport`; checks the native save/reopen, refinement history, exports, and a generated sentinel scan; and states that no live network qualification occurred. The source acceptance test passed. Its sentinel scan covers the fixed self-test output tree and does not turn this into a live provider or persistent-key test.
- **Digest, identity, path safety, and relocation:** The digest scope enumerates `am3d`, assets, benchmarks, recipe docs, scripts, build specs/scripts, locks, and active bundled docs; generated identity is excluded to avoid a self-hash cycle. The identity writer stores the full input digest in the approved compact envelope. The payload scanner streams all regular-file bytes and rejects links; a tooling test covers a 5 MiB file. Windows and Linux scripts stage into fixed release paths, exercise extracted paths containing spaces and Unicode, and make read-only checks explicit (including an `UNPASSED` outcome where the host cannot prove them). These checks were reviewed statically or through bounded helper tests; they do not establish archive relocation.

## Focused verification

- `.venv/Scripts/python.exe -m pytest scripts/test_phase10_tooling.py am3d/ai/test_credentials.py -q --tb=short` — **18 passed, 3 skipped in 57.90s**. The run did not print skip reasons; the existing Phase 10 receipts attribute these symlink-guard skips to unavailable symlink creation. The included source fixed-acceptance test passed.
- `bash -n build_linux.sh` — passed.
- PowerShell AST parsing of `build_windows.ps1` and `scripts/phase10_safety.ps1` — passed.
- Source Windows system credential probe — store/get/rotate/get/delete/absence passed with a random alias; cleanup completed. Host-only, unfrozen, Windows 10 evidence.
- Final input-digest check — `39b1a2b795d61d94d8d587d9b6d763098445e069c524fea3f00ed10b31ac843b` twice consecutively. No full source suite or packaging build was run.

## Hashes of inspected materials

| File | SHA-256 |
| --- | --- |
| `docs/V1_MASTER_IMPLEMENTATION_PLAN.md` | `9490c687c240598317d7db74048961772e60034f6b8ebadde2565e2100ef16b1` |
| `work/v1/phase10-task.md` | `12edbdbedd6503c397ff3fe3f5321d36e669f89f9aa72d5fb60975cb2df4c19e` |
| `docs/evidence/v1/phase-10/tooling-preparation.json` | `97841fbb1d6daa33e65af8b123fc47ffeafeb2f3b4339aa424951d4dcdcdb42a` |
| `docs/evidence/v1/phase-10/strict-source-followup.json` | `a68e245e1d6be435999c575514003cabf4a239398211854a2cd5f2a9461be4a9` |
| `am3d/ai/frozen_acceptance.py` | `add07ebdfad3f767978966652c85238aa297c3c1fd42448341f777e4fd877cec` |
| `am3d/ai/credentials.py` | `bcaee82e8db9f0bbcf6d01455477572c50cd890195e41badf5e5f9300d5d2141` |
| `am3d/ai/records.py` | `d11eb513b64a8c5a92f5271dc184be919ddab50390787336b2f5d085472ed2ae` |
| `am3d/ai/worker.py` | `184df9bf7555ee9496120e30ae4aab3bb1a9e3807326721e092b2313ced7fae7` |
| `am3d/ai/test_credentials.py` | `331f62ad879e4dafa33af46bd1e1592ec4a85e001876978f5d3f0499f56f7fae` |
| `am3d/ui/__main__.py` | `770ebefbdf164b916bf655548bac162e20c7debdf204905c5bce38dde4edb7e5` |
| `am3d/ui/__init__.py` | `f8870938899a2a89df8a73689481774243c9952e56c2a52c499b89a19d734b34` |
| `am3d.spec` | `e89fe51c06557df2367ca02f3ecdb79e6aa7df61d7fab455394d82addfcb4814` |
| `am3d_recipe.spec` | `e17a0e33771f8b245cf3f32a78df0c08749568121bcd28673cb1a8caa18feb14` |
| `build_windows.ps1` | `00dc5856ce4ed49a19c3fa73542401150aad0aadf7fa99b175fc80249e7aa385` |
| `build_linux.sh` | `13f77a18a19abbc9173ec5f663ddb981207a370cc12669a2497e62e0fb98ff7d` |
| `scripts/build_input_digest.py` | `708b0922d61db86830d640d9627fbb4d0b4e1902d4644ee707cb8c1af62ea602` |
| `scripts/write_build_identity.py` | `c667ee9d2367c3cabd6e0a7ce24a2fdc8651d611c8f700bd6f5d2f32f4664090` |
| `scripts/audit_build_payload.py` | `8dfc7ceb8b7d63c5e4670d4d48b8310a16564c84746d762a4c5a57102fb24a69` |
| `scripts/write_runtime_licenses.py` | `044592efbe51f83e6beff834d3069b8a142b14807f43a2f5620af1396b67fae` |
| `scripts/phase10_safety.ps1` | `96ffcd2aeb3a12a6303e6a2a7e59b537f82b980c8da665b2f4f41b5393ac2264` |
| `scripts/test_phase10_tooling.py` | `6df72ef30fc7ba6466e68b99fdabff7ad81570c9162aa304979c449e5a97c201` |
| `.github/workflows/windows.yml` | `d03523e2f37f9355aa14184c185d37c938932711662a8dd48cf78c98c7dc4f8a` |
| `requirements.txt` | `3c824deee0c74e483bccc442a52757e215ddcbbc96eec01a25d2bbb22f47092e` |
| `requirements-dev.txt` | `d2ab7cfaf2fadf6b24a3885a24b650c0c6d0b6feda93c10bd3a35f70efaf170f` |
| `requirements-lock-linux.txt` | `e54845b55de19f734b8177ca8f5c27c3c6a927ef7abd5106c3363ea1c1de84c3` |
| `requirements-lock-windows.txt` | missing at review close |
