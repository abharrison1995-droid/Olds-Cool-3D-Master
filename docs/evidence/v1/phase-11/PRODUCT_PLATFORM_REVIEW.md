# Phase 11 product and platform review

Review date: 2026-10-14 (Europe/London)  
Review type: independent, read-only product/platform and artifact-claim review  
Authority: `docs/V1_MASTER_IMPLEMENTATION_PLAN.md`, Phase 11  
Baseline: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945` with authorized uncommitted V1 source and Windows lock

## Initial candidate disposition (superseded)

The initial local Windows archive identity was bound consistently across the root acceptance receipt, build provenance, input manifest, checksum sidecar, and archive bytes. It was a `1.0.0.dev1` development candidate built on Windows 10 IoT Enterprise LTSC build 19044, not a release candidate or a qualified V1 platform.

The initial candidate did not pass the Phase 11 product/document agreement gate because bundled help said that the full integrated regression was pending despite the exact locked regression having passed. This was a reproduced documentation-status defect, severity P2. The replacement-candidate focused review below verifies the bounded correction and closes that finding for the replacement archive; the original candidate and its receipts remain superseded.

## Initial candidate identity and scope checked

- Baseline HEAD: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`; authorized working-tree source and lock remain uncommitted.
- Recomputed build-input digest: `7f90f1092eff741a399397f540a5cf3a38bb0902d249f7d3aaa0cfb7d4022a92`.
- Candidate version: `1.0.0.dev1`.
- Windows lock SHA-256: `0a9a1b4086add4515dab3eed56cb585331b6526ef4de72e9fa83e4c38024d4d6`.
- Archive: `release/3D-MASTER-2005-Beta-1.0.0.dev1-win64.zip`, SHA-256 `743eb4cbcf8b7e0e9920aa9ca9c26f7fa87fb266af40ec5254db730c3198bfe3`.
- Builder: Windows 10 IoT Enterprise LTSC build 19044 x64. The GUI route in the recorded acceptance is Qt offscreen/software mode.

I read `ROOT_LOCKED_ACCEPTANCE.md`, `LOCKED_ROOT_BINDING.json`, `BUILD_PROVENANCE-windows.txt`, `BUILD_INPUTS-windows.json`, `ACCEPTANCE_LEDGER.md`, the locked frozen acceptance, credential-store and external-reader receipts, current product/help/platform docs, and Phase 9 final capture/source-delta records. I did not run tests or a build, use the application, call a provider, read credentials, or perform native display/GPU inspection.

## Claims that match the evidence

The product docs describe the current development source as an in-app brief/provider workflow over bounded `recipe-v1`, with checked local artifacts, an editable project and guarded editor handoff. They distinguish that source workflow from the historical Mint `0.2.0b1` preview. The explicit model/request disclosure, one-host endpoint allowlist, unknown provider cost, static OBJ/GLB snapshots, profile-edit boundary, local-history behavior, and limitations are presented without promising artistic success.

The root locked receipt reports the full locked regression passed with 1,048 passed, 2 symlink-privilege skips and 4 existing warnings in 586.90 seconds. It also reports frozen GUI smoke 14/14, CLI validation/export/structured failure, relocation and path scans, fixed offline AI worker/check/publication/refinement, explicit Windows credential-store sentinel CRUD/cleanup, and independent Trimesh parsing of actual retained parent/child OBJ and GLB files. Those results support a local frozen development candidate and selected local workflows. The offline `MockTransport` run is not live generation or benchmark evidence; the export reader did not score human usefulness.

The qualifications remain explicit and material. Windows 11 and Mint 22.3 are the selected targets and neither is qualified. Read-only installation, clean no-Python target-host acceptance, native keyboard/manual recovery and scale checks, physical GPU and target software-fallback checks, live TLS/auth/network/cancellation, locked/unavailable credential service, two live 30-case benchmarks, live refinement families, and original independent human scores remain unpassed. Two reviewers being available is not a score. The prior unknown close-wait and interrupted AI trace remain unresolved historical diagnostics.

Phase 9 final-capture verification remains bounded as documented. I recomputed all 16 final capture checksums: zero mismatches. Of the eight source hashes in the capture manifest, seven match current source; `am3d/ui/ai_settings.py` is the only mismatch. The source-delta disposition limits screenshot reuse to unchanged layout and points to the separate 11-check privacy review. Result/history/refinement/error images are explicitly synthetic fixtures, and the 100/150/200 labels are logical-pixel proxies from offscreen Qt, not physical DPI inspection. The overwritten preliminary screenshot bindings remain unverifiable.

## Reproduced defect on initial candidate — P2: bundled help had stale regression status

The exact artifact's `BUILD_INPUTS-windows.json` binds the current `QUICK_START.md`, `USER_GUIDE.md`, and `CAPABILITY_MATRIX.md`; direct archive reads show the packaged copies have the same SHA-256 as those workspace files. They therefore carry these current statements:

- `docs/QUICK_START.md:84–86`: says the history/refinement flows passed a bounded local review, then says “full integrated regression” remains pending.
- `docs/USER_GUIDE.md:129–132`: repeats that full integrated regression is pending.
- `docs/CAPABILITY_MATRIX.md:32, 77, 164`: says the local gate does not complete integrated regression, and that full/final regression remains open.

Those overall-status statements are stale for this locked candidate. `ROOT_LOCKED_ACCEPTANCE.md` and the updated ledger bind a successful full locked regression to the exact source digest and archive above. The V1, external, target-host, live-provider, benchmark and human gates remain open; the correction should preserve those distinctions while stating that the exact local integrated regression and listed fixed offline frozen gates passed. Because these docs are build inputs and bundled files, correcting them requires a new source-input digest and locked archive. This is a documentation accuracy blocker for this candidate, not evidence that its source regression failed.

## Other classifications

- **Suggestion/clarification (resolved before this receipt):** the initial Phase 9 summary could be read as saying the capture source hashes still all matched. `RELEASE_NOTES.md` now anchors the 8/8 zero-mismatch result to the Phase 9 gate and states that the later Settings change leaves 7/8 current hashes; `SOURCE_DELTA_REUSE.md` limits reuse to layout. `PROGRESS.md` now separates the implemented development workflow from the historical Mint preview. These files are outside the package and build-input digest.
- **False positives:** the synthetic result/history/refinement/error screenshots do not claim AI-generated outputs, live-provider evidence, or human quality; their labels and manifests say they are fixtures. The historical Mint/MX acceptance statements are separately artifact-bound and do not claim current V1 support.

## Commands and exact results

Read-only commands/checks performed:

```text
.venv\Scripts\python.exe scripts\build_input_digest.py --root . --digest-only
7f90f1092eff741a399397f540a5cf3a38bb0902d249f7d3aaa0cfb7d4022a92

Get-FileHash -Algorithm SHA256 release/3D-MASTER-2005-Beta-1.0.0.dev1-win64.zip
743eb4cbcf8b7e0e9920aa9ca9c26f7fa87fb266af40ec5254db730c3198bfe3

Archive SHA-256 vs checksum sidecar
Match: true

Read ZIP entries and hash packaged QUICK_START.md, USER_GUIDE.md,
SUPPORTED_PLATFORMS.md and CAPABILITY_MATRIX.md against workspace files
All five document entries (including the internal Quick Start copy) match.

Recompute Phase 9 final capture manifest
16/16 capture checksums match; current source mismatch: am3d/ui/ai_settings.py only.
```

No test, provider, application, OS-key, commit, publication, or build command was run by this reviewer. The model/effort request recorded for this review is `gpt-6-luna` / `xhigh`; actual runtime model and reasoning effort are not independently introspectable in this session, so this records the request, not a runtime verification. No live or human acceptance score was produced.

## Focused replacement-candidate verification and disposition

I verified the replacement exact local candidate after the bounded bundled-doc correction. The recomputed build-input digest is `2be687b3249db162c9c04081ab77eea9f6c966210317da147d9ebcd34b79924d`. The archive is `release/3D-MASTER-2005-Beta-1.0.0.dev1-win64.zip`, SHA-256 `36970e05116bd691ee1b80e3431e82987c0dc2547fbcdfc485d4b5b743340afe`; the checksum sidecar contains the same digest. `LOCKED_ROOT_BINDING.json` binds that digest and archive to the successful locked run and records `target_qualification=false` and `release_accepted=false`. The source Windows lock SHA-256 remains `0a9a1b4086add4515dab3eed56cb585331b6526ef4de72e9fa83e4c38024d4d6`.

The root binding carries the same recomputed source/input digest and its recorded hash for `release/BUILD_INPUTS-windows.json` matches the file; its recorded Windows-lock hash also matches the lock file. `BUNDLED_DOC_INPUT_DELTA.json` records exactly three changed packaging inputs: `QUICK_START.md`, `USER_GUIDE.md`, and `CAPABILITY_MATRIX.md`; it records runtime, build scripts, locks, and tests unchanged. I read the corrected docs and independently compared every shipped copy in the ZIP with its source file. The three changed docs, `SUPPORTED_PLATFORMS.md`, and both packaged Quick Start copies match byte-for-byte and by SHA-256. The corrected wording says the exact local development candidate passed its full source regression and fixed offline frozen history/refinement checks, while keeping target-platform, native/read-only/GPU, live-provider, human-quality, and overall V1/RC gates open. No remaining bundled statement says that this candidate's full integrated regression is pending. The repository status pointers are plain text, not links to files omitted from the archive.

The root acceptance and current acceptance ledger bind the same replacement identity and continue to list the unpassed gates. I did not rerun source or tooling tests: the exact locked record reports 1,048 passed, 2 privilege skips, and 4 warnings for the full source suite, and 44 passed / 4 privilege skips for tooling. The tooling result is explicitly reused because its scripts and tests did not change. I did not run a build, use the application, call a provider, access OS keys, or perform native desktop/GPU inspection.

**Disposition:** the stale regression-status finding is closed for replacement source digest `2be687b3…` and archive SHA-256 `36970e05…`. The bundled docs now agree with the exact local locked development checks and retain accurate limits. This is a product/platform review of a Windows 10 local development candidate only; it does not accept a release candidate or V1. Windows 11 and Mint 22.3, read-only installation, native keyboard/manual recovery/scaling, physical GPU, live provider/network cases, the two live 30-case benchmarks, human scores, and the committed-source/lock gate remain unpassed. Two reviewer availability is not scoring. No live or human acceptance score was produced.

Focused read-only checks:

```text
.venv\Scripts\python.exe scripts\build_input_digest.py --root . --digest-only
2be687b3249db162c9c04081ab77eea9f6c966210317da147d9ebcd34b79924d

SHA-256 of ZIP: 36970e05116bd691ee1b80e3431e82987c0dc2547fbcdfc485d4b5b743340afe
ZIP checksum sidecar: exact match
Packaged QUICK_START.md, internal QUICK_START.md, USER_GUIDE.md,
SUPPORTED_PLATFORMS.md, CAPABILITY_MATRIX.md: all match workspace bytes
BUNDLED_DOC_INPUT_DELTA.json: exactly three bundled documentation inputs changed;
runtime/build scripts/locks/tests unchanged
```

No focused test/build/provider/OS-key command was run. The requested review model/effort was `gpt-6-luna` / `xhigh`; actual runtime model and reasoning effort remain uninspectable here.
