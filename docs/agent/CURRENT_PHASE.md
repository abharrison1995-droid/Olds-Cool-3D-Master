# Current handoff — M3.2 Codex CLI adapter

**Status:** M2 was independently accepted at `0f3413adebe1b07c582c4617aa0c18053fda1e1a` and remains frozen. M3.1 passed focused independent verification at `88a9b85cfc30854fe8f3234eca44cfce2b30e4e9`.

**Active milestone:** M3.2 — one subscription-backed Codex CLI adapter on `v1/m3.2-codex-cli`. Adapter commit: `98854a65ba94103b52c138ae6ddac31b03840a85`. M3.2a diagnostic/schema source candidate: `140445a03d3db9aed9a8fed6ed68ffe2b65f4c7b`, based on previous blocked tip `153133edc443720256ba20e3dbebc5a0e7dedd8b`.

**Gate:** M3.2 implementation gate is satisfied and ready for focused independent Codex CLI sandbox review; M3.2 is not accepted yet. A strict Codex-only schema projection resolved the production-schema compatibility differential while the M3.1 parser and policy remained unchanged. One production live turn completed through parsing, `authorize_recipe`, and the M2 runner; all deterministic checks passed. Synthetic confinement probes found no workspace writes, outside writes, sentinel disclosure, or tool-call event. The two original raw failure messages were not retained, so their exact text is unavailable; schema incompatibility is strongly supported, but not retrospectively proven from those messages.

**CI:** The prior implementation commit passed Linux fast tests and Windows worker/fake-Codex lifecycle; its Windows candidate failed at the known ModernGL access-violation path. CI for the M3.2a push is pending. No Windows qualification is claimed.

**Scope:** PR #16 remains draft and unmerged. No Claude/OpenCode/local/API adapter, credential storage, retries, fallback, repair, bake-off, selection UI, or M4+ work. No M2 worker, policy, check, or publication implementation changed. M3.3 has not started. See [`docs/evidence/v1/m3/m3.2-codex-cli.md`](../evidence/v1/m3/m3.2-codex-cli.md).
