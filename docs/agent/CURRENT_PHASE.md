# Current handoff — M3.2 Codex CLI adapter

**Status:** M2 was independently accepted at `0f3413adebe1b07c582c4617aa0c18053fda1e1a` and remains frozen. M3.1 passed focused independent verification at `88a9b85cfc30854fe8f3234eca44cfce2b30e4e9`.

**Active milestone:** M3.2 — one subscription-backed Codex CLI adapter. Branch `v1/m3.2-codex-cli`, implementation commit `98854a65ba94103b52c138ae6ddac31b03840a85`, based directly on accepted M3.1. The offline fake, Linux tests, host-owned argv, and M2 runner path are implemented. See [`docs/evidence/v1/m3/m3.2-codex-cli.md`](../evidence/v1/m3/m3.2-codex-cli.md).

**Gate:** M3.2 remains blocked. Two permitted live calls each reached `turn.started` then failed with an unclassified CLI error before a structured response; neither reached recipe parsing or `GenerationRunner`. Synthetic outside sentinels were unchanged, but effective model-tool confinement was not established by those failed turns. Do not begin M3.3 or another adapter until the live failure is diagnosed and the confinement probes are completed.

**CI:** Linux fast tests and Windows worker/fake-Codex lifecycle passed on the implementation commit. The Windows candidate failed at the known ModernGL access-violation path; this is separate and not Windows qualification.

**Scope:** no Claude/OpenCode/local/API adapter, credential storage, retry/fallback/repair, bake-off, selection UI, or M4+ work. No M2 worker, policy, check, or publication implementation changed. No Windows qualification is claimed.
