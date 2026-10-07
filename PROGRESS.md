# 3D MASTER:2005 — V1 progress

Updated: 2026-10-07 · Baseline: `3f6f7f0` · Plan: [docs/V1_PLAN.md](docs/V1_PLAN.md)

Historical evidence applies only to its recorded source. Platform caveats live
in [docs/SUPPORTED_PLATFORMS.md](docs/SUPPORTED_PLATFORMS.md).

| Milestone | Status | Next gate |
| --- | --- | --- |
| M0 Repository/context | Complete | H1 merged; Linux CI green. [Inventory](docs/evidence/v1/m0/repository-inventory.md). |
| M1 Contract | Complete | Independent exit verification passed at `81f9a979af6534d08f2c4803a2430fa24471451f`. |
| M2 Local generation | Complete | Independently reviewed and accepted at `0f3413adebe1b07c582c4617aa0c18053fda1e1a`; tagged `v0.3.0-dev.2`. |
| M3 AI loop | In progress | M3.1 passed focused verification at `88a9b85cfc30854fe8f3234eca44cfce2b30e4e9`. M3.2a source candidate `140445a03d3db9aed9a8fed6ed68ffe2b65f4c7b` adds a generated Codex-compatible schema projection and bounded local diagnostics. A live production-path turn passed parsing, policy, M2 generation, and synthetic confinement probes. Implementation gate is ready for focused independent review; M3.2 is not accepted and M3.3 has not started. |
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
