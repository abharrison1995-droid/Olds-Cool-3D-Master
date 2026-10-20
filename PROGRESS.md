# 3D MASTER:2005 — current progress

Updated: 2026-10-20 (Europe/London).

## Active V1 direction and status

The approved implementation authority is [docs/V1_MASTER_IMPLEMENTATION_PLAN.md](docs/V1_MASTER_IMPLEMENTATION_PLAN.md). The V1 workflow implementation and Windows lock are committed locally. Current Windows development candidate source: `d067e921cb8f6b767c6faa526553ae28d20fd71c`; input digest `a109c4a8c50365ea155b0356282b1b1745d2758b18af751492e59ae9a4af9b7d`; ZIP SHA-256 `229ccb5292b74823ee1d274f3170a175ac40716821e87da938507174af7c04ce`. The build was made from a clean committed-source worktree. This candidate ZIP was not published or released; source integration does not qualify V1.

The local Windows V1 source is being converged with the existing GitHub master milestones. The integrated tree keeps V1 at am3d.ai and preserves the incompatible earlier M2/M3.1 API under am3d.ai.m3. The combined Windows 10 source suite passed 1,182 tests, skipped 3, with 4 deprecation warnings in 654.01 seconds (Qt offscreen; hardware GPU tests not run). This source result is not Windows 11, native-GPU, clean-machine, or release qualification. PR #16 for M3.2 remains a draft because its provider-process isolation review is blocked.


The exact host is Windows 10 IoT Enterprise LTSC `10.0.19044`, x64. The locked Windows build passed 1,049 tests, 2 skips and 4 warnings in 744.71 seconds; a fresh tooling run passed 44 and skipped 4 symlink-capability checks. Exact frozen offline mock workflow, CLI, credential-store sentinel CRUD/cleanup, relocation, payload audits and independent parent/child OBJ/GLB parsing passed. GUI tests ran offscreen/software; current-candidate native manual interaction, DPI, physical GPU and read-only ACL acceptance are not claimed. Windows 11 remains the approved target and is unqualified; Mint 22.3 remains explicitly deferred.

The delivered ZIP, checksum, build-input manifest and provenance are in the requested output folder. The current concise report and complete phase receipts explain exact evidence and open gates: [docs/evidence/v1/phase-11/FINAL_ACCEPTANCE.md](docs/evidence/v1/phase-11/FINAL_ACCEPTANCE.md), [docs/evidence/v1/phase-10/ROOT_LOCKED_ACCEPTANCE.md](docs/evidence/v1/phase-10/ROOT_LOCKED_ACCEPTANCE.md), and `docs/evidence/v1/windows10-followup/committed-d067e92/`.

## Current phase ledger

| Phase | Current state |
| --- | --- |
| 0–9 — Plan, implementation, contracts, security, workflow and UX | Local implementation receipts remain in `docs/evidence/v1/phase-0/` through `phase-9/`. Their local findings do not qualify live-provider, human, or target-platform acceptance. Earlier unexplained wait/interrupted-run and overwritten preliminary-capture limits remain preserved. |
| 10 — Windows build and qualification | Committed Windows 10 development candidate built and locally verified. The corrected locked suite passed 1,049/2/4. Frozen GUI smoke was 14/14 offscreen; CLI, offline mock AI, credential sentinel CRUD/cleanup, relocation and package audits passed. Native manual, ACL restore/read-only, GPU, live, clean-machine and Windows 11 gates remain open. Exact bindings are in `docs/evidence/v1/phase-10/`. |
| 11 — Final acceptance | Development-candidate disposition only. Windows V1/RC are not accepted. Needs native desktop and target checks, an elevated restore-capable ACL target, approved live provider/model and spend limits with private local credentials, two live benchmark runs and independent human scores, Windows 11 clean-host qualification, and release signoffs. Mint 22.3 is deferred for this task. |

The superseded pre-commit candidate and its logs, archives, manifests, provenance and bindings are preserved under `docs/evidence/v1/precommit-final-candidate-2be687b/`. The unrelated `.agents/artifacts/review-loops/v3-phase0-20260908-plan.md` remains outside the candidate commits.
## Preserved preview evidence

The accepted Linux Mint 22.3 x86-64 preview candidate is a historical, artifact-specific result: archive SHA-256 `4d41c0cf7cbf069edf907483cbf16ff4b0f8dcc54130aa791a16a049568d6433`, build-input digest `6e62c8cdf6ecfb578885f852391b5d8b50d118a6405b9f4817cb36aa0fd60283`. Its recorded scope includes 738 source tests, 14 packaged GUI smoke steps, CLI validation/export and structured-failure checks, relocation and payload checks. GUI checks used Qt offscreen mode and software rendering. This does not qualify V1, native desktop interaction, physical GPU rendering, MX, or general Linux support. Full evidence remains in `docs/evidence/implementation-roadmap/phase-3/` and `docs/evidence/implementation-roadmap/CANDIDATE_REVIEW.md`.

The older MX 25.2 acceptance is a different historical artifact: source commit `b96c922a3c9d6461f0e4888ce47dbc28b3449067`, archive SHA-256 `ad36d7ef798d3fd3bd7dc68bd15a8540a8c535655b2e8ec1e7fe6e86eefc4cdf`. It does not qualify the Mint preview candidate or current V1. Its evidence remains in `docs/evidence/desktop-release/phase-e/`.

| Historical preview milestone | Preserved result |
| --- | --- |
| Preview Phase 0 — documentation/authority | Complete; two independent Luna reviews; `docs/evidence/implementation-roadmap/phase-0-review.md` |
| Preview Phase 1 — external-agent recipe trial | Complete; a fresh same-family substitute agent corrected a structured recipe rejection and generated project/exports; independent evaluation confirmed leg motion; a separate model vendor was not tested |
| Preview Phase 2 — editor handoff | Complete in Qt offscreen mode; edit, undo, redo, save/reopen and two workspace captures passed; native compositor and physical GPU remained outside that gate |
| Preview Phase 3 — Mint candidate | Complete for the identified archive above; 738 tests, 14 GUI smoke steps and package/CLI checks; two independent Luna reviews passed |
| Preview Phase 4 — MX qualification | Deferred; the older MX artifact does not qualify current source |
| Preview Phase 5 — Windows CI preparation | Reviewed; `.github/workflows/windows.yml` was not executed in the recorded evidence; clean-machine, interactive, DPI and real-GPU gates remain open |

Windows candidate artifacts may be produced for testing. A supported publication claim requires the actual Windows acceptance gates. See [supported platforms](docs/SUPPORTED_PLATFORMS.md), [Windows acceptance](docs/WINDOWS_ACCEPTANCE_PLAN.md), and the historical [preview roadmap](docs/IMPLEMENTATION_ROADMAP.md).

Final local acceptance and exact independent-review receipt hashes: docs/evidence/v1/phase-11/FINAL_ACCEPTANCE.md and FINAL_ACCEPTANCE_BINDING.json. Required cross-platform V1/RC gates remain open; no publication.
