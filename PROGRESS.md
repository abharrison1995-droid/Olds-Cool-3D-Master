# 3D MASTER:2005 — V1 progress

Updated: 2026-10-07 · Baseline: `3f6f7f0` · Plan: [docs/V1_PLAN.md](docs/V1_PLAN.md)

Historical evidence applies only to its recorded source. Platform caveats live
in [docs/SUPPORTED_PLATFORMS.md](docs/SUPPORTED_PLATFORMS.md).

| Milestone | Status | Next gate |
| --- | --- | --- |
| M0 Repository/context | Complete | H1 merged; Linux CI green. [Inventory](docs/evidence/v1/m0/repository-inventory.md). |
| M1 Contract | Complete | Independent exit verification passed at `81f9a979af6534d08f2c4803a2430fa24471451f`. |
| M2 Local generation | Complete | Independently reviewed and accepted at `0f3413adebe1b07c582c4617aa0c18053fda1e1a`; tagged `v0.3.0-dev.2`. |
| M3 AI loop | In progress | M3.1 passed at `88a9b85cfc30854fe8f3234eca44cfce2b30e4e9`. Owner reports the pinned recipe-only Codex source gate passed independent review. M3.2f remains incomplete: the earlier core test passed, but the 24 GiB-authorized cached build continuation stopped at its 23.5 GiB safety threshold during dependency compilation; no candidate binary, new test result, self-test or 3D MASTER integration exists. PR #16 remains draft; M3.3 has not started. See [M3.2f resumption evidence](docs/evidence/v1/m3/m3.2f-resumption.md). |
| M4 Baseline | Queued | Benchmark baseline and evidence-based contract. |
| M5 Product workflow | Queued | AI workspace, history/refinement, usability. |
| M6 Release | Queued | Exact RC qualification on Windows 11 and Mint 22.3. |

M2 acceptance and its CI/review record are in
[docs/evidence/v1/m2/m2-independent-acceptance.md](docs/evidence/v1/m2/m2-independent-acceptance.md).
Its worker boundary remains frozen. The separate Windows ModernGL collection
crash is a known limitation and is not Windows qualification. M3.2 evidence is
in [docs/evidence/v1/m3/m3.2-codex-cli.md](docs/evidence/v1/m3/m3.2-codex-cli.md);
it records the diagnosis, live control and production probe results, and the
independent-review gate. No M3.3 work has begun.
