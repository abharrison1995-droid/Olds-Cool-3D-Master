# Phase 10 reopened packaging review

Review date: 2026-10-14.
Review type: independent, read-only source review and bounded focused verification.
Baseline: HEAD 3f6f7f03d32b4d1a3af06af4fdc0724bf0436945, with authorized V1 working-tree changes.
Authority: docs/V1_MASTER_IMPLEMENTATION_PLAN.md, Phase 10 and Phase 11.
This receipt supplements PACKAGING_REVIEW.md and preserves its original findings and qualifications.

## Disposition

The retry1 packaging failure is explained by observed defects in the frozen payload and the Windows build environment. The current source changes address the singleton-array failure, development-only modules/notices in the GUI closure, pre-dispatch Qt initialization, and ambient DLL discovery. A bounded independent source selection passed. This supports proceeding to the next controlled build attempt; it does not qualify a built artifact, release candidate, or target platform.

The shared-tree build-input digest returned 2aab9e3b80626ea5020b67cc7bebf01e6488179ab64e2156c38bfa9a645309bc twice consecutively after source handoff. It binds this source snapshot only. The review host is Windows 10 IoT Enterprise LTSC build 19044 x64, not the Windows 11 target. Linux notice behavior was tested with fixtures on this Windows host; no native Mint result is claimed.

## Retry1 evidence and finding dispositions

The preserved integrated source regression reports 1048 passed, 2 privilege skips, and 4 warnings in 672.57 seconds. Both PyInstaller executables were produced, but the build script exited before its GUI, AI acceptance, archive, and lock stages. Under strict mode, a singleton FileInfo from Get-ChildItem had no Count property. Therefore retry1 did not complete the packaging gate.

The actual retry1 GUI Analysis closure contained three _pytest modules. Its notice manifest lacked pytest, pygments, packaging, and setuptools. A bounded frozen diagnostic showed PyInstaller's automatic pyi_rth_pyside6 hook importing Qt before the fixed pre-Qt dispatch. The startup investigation then recorded QtCore failing to load with a missing DLL procedure. The actual TOCs contained ICU DLLs originating from the ambient Codex Poppler directory.

A controlled diagnostic temporarily moved only the two generated-payload ICU files, ran the unchanged retry1 GUI executable, then restored and hash-checked both files. The executable completed 14 of 14 smoke steps during that altered-payload diagnostic. This supports ambient ICU shadowing as the loader failure mechanism; it is not acceptance of retry1 or a candidate. The exploratory Qt6Core import/export report is discarded because pefile's default 8192-export limit truncated the table and produced false positives. No real Qt ABI version mismatch was established.

The current source contains the reviewed corrections: specs exclude the observed optional test/console/build helpers; the GUI spec substitutes one PyInstaller PySide6 runtime hook; that hook returns before Qt initialization only for the fixed worker and self-test argv forms and retains the normal GUI setup; the Windows build scopes PATH to the isolated interpreter, selected host Python, and Windows directories around both PyInstaller calls, restoring it in finally; and singleton file results are materialized as arrays. Runtime notices list the expected runtime distributions and separately identify CPython/interpreter and PyInstaller bootloader/runtime-hook source files. Comparing that list with the exact frozen TOCs remains an artifact check.

The reopened review also found that requiring only sys.base_prefix/LICENSE.txt would fail for distro Python layouts used by Mint's Ubuntu base. The source now checks only the selected Python version's exact base/stdlib license path or version-specific distro copyright paths under share/doc, accepts only approved in-base symlink targets on Linux, and fails closed if no matching notice exists. Fixture tests cover Ubuntu Noble-style python3.12, python3.12-minimal, and libpython3.12-minimal paths, selected stdlib notice, missing/wrong-version notice, and symlink boundaries. Ubuntu package file lists show copyright files under /usr/share/doc/python3.12 and /usr/share/doc/libpython3.12-minimal ([python3.12](https://packages.ubuntu.com/noble/all/python3.12/filelist), [libpython3.12-minimal](https://packages.ubuntu.com/ca/noble/i386/libpython3.12-minimal/filelist)). This supports the path candidates but does not verify the installed notice layout on native Mint. The generated notice includes the selected source description; its language describes copied source text and makes no legal-compliance guarantee.

## Focused verification

Command, using the isolated Windows build interpreter with Qt offscreen:

    PowerShell: $env:QT_QPA_PLATFORM = 'offscreen'
    .\build\windows\venv\Scripts\python.exe -m pytest scripts/test_phase10_tooling.py -q --maxfail=1 --tb=short -k "runtime_license_writer_copies_exact_interpreter_and_pyinstaller_notices or runtime_license_names_cover_keyring_resolved_requirement_metadata or linux_interpreter_notice_uses_only_selected_versioned_distro_copyright or linux_interpreter_notice_accepts_selected_stdlib_license or linux_interpreter_notice_rejects_version_mismatch_and_missing_notice or linux_interpreter_notice_rejects_a_symlink_outside_the_selected_base or windows_interpreter_notice_does_not_use_linux_distribution_fallback or linux_interpreter_notice_allows_only_an_exact_in_base_distro_alias or recipe_spec_stays_free_of_qt_and_gpu_hidden_imports or frozen_specs_exclude_only_optional_test_and_command_helpers or guarded_pyside6_runtime_hook_skips_fixed_dispatch_without_qt or guarded_pyside6_runtime_hook_preserves_normal_gui_setup or gui_spec_substitutes_only_the_pyinstaller_pyside6_runtime_hook or windows_build_counts_singleton_recipe_artifacts_under_strict_mode or windows_pyinstaller_path_excludes_ambient_dlls_and_restores_after_failure"

Result: 19 passed, 28 deselected in 12.06 seconds. The count includes platform and fixed-dispatch parameter cases plus the singleton-array regression. The selection covers notice source/closure checks, Linux path fixtures, Qt-free fixed dispatch, normal GUI hook setup, recipe exclusions, Windows PATH scoping/restoration, and singleton-array handling. It did not run the full source suite, PyInstaller, the frozen self-test, or target-host qualification.

## Source identity

The six owned packaging files match the stable handoff hashes:

| File | SHA-256 |
| --- | --- |
| am3d.spec | 126a2a8e3ee939bdae1453710bcafc91a682dc332bbf34181473188a96254a0d |
| am3d_recipe.spec | c9eb9881913d57e8554aa02dbbf140087ef42ced6e51c965261c79931bd5af50 |
| build_windows.ps1 | 7414219de5e38e857e5784794060a8dc5dc9ef1740c5edda2b3f00e969b77c7b |
| scripts/pyi_rth_am3d_pyside6.py | 7de0d05b4abd1aa3024b0f17afa6666dc9522318ec1ebdeda8533bb2c531725d |
| scripts/test_phase10_tooling.py | 91d7a54c7ef4a250a404d0f650cb13f6d84d22814059b1248bf08d7dbd9d86c0 |
| scripts/write_runtime_licenses.py | 1f91c31d336a691bb13ba992233721d2aadaec7537db763fc86d71efa23a5f15 |

The authority plan hash was 63c011a48dfecf85613f43509d6714a39b50f2559df05c4955c7b469c6d19ef0. Retry1 failure receipt hash was 82a906bd61af2781c4d1b849a50bc6420dd6a4b670ab2de2c22e51d1dcc81a56; retry1 regression receipt hash was 7baeb9ddf729798ae70cf2cc7af3203c48cab0e5b6665755843a19c9c065c12f; retry1 payload inventory hash was 448efe9bbf16114b9d6e8fc308e35a5e10da3e2152755f232258524f02f7709b.

## Remaining gates

The exact bootstrap retry2 proposal must complete its build and packaging stages before the proposed Windows lock is considered. After the lock is promoted into the source inputs, a full locked build must bind the final source digest, archive, checksum, payload TOCs, notices, and acceptance outputs. The comparison between the actual payload closure and expected notice distributions, and one independent focused check of that exact final artifact, remain outstanding.

Windows 11, native Mint 22.3, live provider/TLS behavior, native keyboard and display-scale behavior, physical GPU paths, and any other target-platform acceptance not represented by executed evidence remain open. No source/runtime version change was justified by the retry1 diagnosis. The independent reviewer made no production-source or lock edits; this file is the only review output.

## Final exact-artifact verification (replacement candidate)

Review date: 2026-10-14. This section supersedes the earlier "Remaining gates" status for the final Windows development-candidate review only. The initial retry1/bootstrap diagnosis and retry2 failed invocation above remain historical failures.

**Disposition: no material packaging blocker found for the exact locked Windows development artifact reviewed below.** This is a focused artifact-integrity and payload-closure result. It is not Phase 10 target qualification, Phase 11 release acceptance, or approval of a committed RC.

Exact identity reviewed:

- Baseline HEAD: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`, with authorized uncommitted development inputs.
- Source/input digest: `2be687b3249db162c9c04081ab77eea9f6c966210317da147d9ebcd34b79924d`.
- Windows archive `release/3D-MASTER-2005-Beta-1.0.0.dev1-win64.zip`: SHA-256 `36970e05116bd691ee1b80e3431e82987c0dc2547fbcdfc485d4b5b743340afe`.
- Windows lock: SHA-256 `0a9a1b4086add4515dab3eed56cb585331b6526ef4de72e9fa83e4c38024d4d6`, 38 unique exact pins including `setuptools==84.0.0`.
- The preserved bootstrap retry2 proposal/capture is not reclassified as a successful invocation. This exact identity is the later complete locked build.

I independently recomputed the current source digest, checked every regular file entry in the 189-input manifest against its current SHA-256, and matched the 13 files recorded in `LOCKED_ROOT_BINDING.json` to disk. The ZIP SHA-256 matched both that binding and its `.sha256` sidecar. The standard provenance, locked start and root acceptance agree on the source digest, archive identity, host and development-only status.

I parsed the actual final GUI and CLI `Analysis-00.toc` files and matched their hashes and module counts to `LOCKED_PAYLOAD_INVENTORY.json` (GUI 916; CLI 685). No test or build-helper modules were in either module closure. The GUI contains its expected PySide6 and renderer dependencies; the CLI contains no PySide6/Qt or renderer/GPU modules. The GUI final `EXE-00.toc` names `scripts/pyi_rth_am3d_pyside6.py` as the substituted PySide6 runtime-hook source; the CLI has no PySide6 hook. The fresh exact-archive frozen acceptance is bound to this source/archive and reports `qt_loaded_before_dispatch=false`, four fixed MockTransport requests, no live network, and passed worker/check/history/refinement/export steps. These checks support the fixed dispatch and local frozen workflow claims; they do not qualify a live provider.

The actual ZIP has no Poppler/ICU-named members. Neither final TOC lists Poppler or ICU binaries. A full read-only member scan found no occurrence of the repository root path in payload bytes. `LOCKED_PAYLOAD_INVENTORY.json` binds the final TOC hashes and notice-manifest hash and reports no missing distribution-notice candidates or unexpected test modules. Every package license path in the archived `THIRD_PARTY_LICENSES.json` exists in the archive; the recorded CPython and PyInstaller notice hashes match their archived text. The notice describes the CPython interpreter/standard-library source and PyInstaller bootloader/runtime-hook source separately. Package license identifiers are the metadata labels represented by the notice; this review makes no legal-compliance conclusion.

The final locked build log records 1048 passed, 2 symlink-privilege skips, 4 existing warnings, both executables, CLI checks, 14 GUI smoke steps, fixed offline AI acceptance, relocation and the complete build-root scan. Fresh retained-QA receipts bind the final archive and record successful fixed workflow and Windows credential-store sentinel CRUD/rotation/deletion/cleanup. The independent Trimesh receipt also binds the final archive and reports successful parsing of the retained OBJ/GLB outputs. The 44-passed/4-skipped Phase10-tooling result is reused from the immediately preceding candidate because the test/script inputs are unchanged; it was not rerun for this documentation-only replacement. I did not run another suite or build during this review. The acceptance page's generic "All commands exited 0" follows a command list that includes pytest; read it with the explicit reuse qualification in the replacement note and binding, not as a fresh tooling execution on this digest.

The limited Linux notice-path handling remains source-reviewed and fixture-tested only; no native Mint result is inferred. The exact local host is Windows 10 IoT Enterprise LTSC 19044. Read-only ACL behavior remains unpassed and no ACL mutation occurred. Windows 11, native Mint, physical GPU/native UI, live TLS/provider behavior, human-quality benchmarks, and the committed-source/lock RC gate remain open. The root acceptance correctly keeps `target_qualification=false` and `release_accepted=false`.

Verification was read-only: source/manifest/archive/report hashing, current source-digest recomputation, JSON and TOC inspection, and in-memory ZIP member/license/path checks. No source, archive, lock or test was changed or executed by this focused review.
## Post-review evidence wording update

After the focused artifact review, the root reviewer removed the reused pytest command from the fresh-command block in `ROOT_LOCKED_ACCEPTANCE.md` and separated it into a note that the 44/4 tooling result is reused from the unchanged test/script set and was not rerun for the documentation-only digest. I verified the updated acceptance text and confirmed the archive SHA-256 still equals `36970e05116bd691ee1b80e3431e82987c0dc2547fbcdfc485d4b5b743340afe`; no artifact or source input changed. This closes the wording ambiguity noted above without changing the final artifact disposition.