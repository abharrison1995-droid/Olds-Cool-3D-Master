# Current handoff — M3.2 Codex CLI adapter

**Status:** M2 was independently accepted at `0f3413adebe1b07c582c4617aa0c18053fda1e1a` and remains frozen. M3.1 passed focused independent verification at `88a9b85cfc30854fe8f3234eca44cfce2b30e4e9`.

**Active milestone:** M3.2 — one subscription-backed Codex CLI adapter on `v1/m3.2-codex-cli`. Adapter commit: `98854a65ba94103b52c138ae6ddac31b03840a85`. M3.2a schema/diagnostic work is in `140445a03d3db9aed9a8fed6ed68ffe2b65f4c7b`; focused-review remediation is `e0712461762828ca5485d0c6697b668896b2d6df`.

**Gate:** M3.2 remains blocked after focused independent review. The remediation rejects unreviewed enabled features, disables current API-key/browser/search/daemon/proxy/retry features, requires shell-tool-off when `unified_exec` is present, monitors the response file while running, and applies a 1 GiB process-tree memory cap. The first newly authorized tiny-schema live control failed with signal `SIGXFSZ` because the initial Linux memory wrapper also imposed a process-wide file-size cap; that cap has been removed. Per instruction, no second live call was made. Effective confinement remains unverified; the original two raw failure messages also remain unavailable.

**CI:** On remediation source `e0712461762828ca5485d0c6697b668896b2d6df`, Linux fast tests and Windows worker/fake-Codex lifecycle passed on push and PR events. Windows candidate still fails at the known ModernGL collection-time access violation in `am3d/gpu/test_scene_render.py::_has_gl`. No Windows qualification is claimed.

**Scope:** PR #16 is draft and unmerged. One of the two newly authorized live calls was used and failed; live testing stopped and call 2 was not made. No Claude/OpenCode/local/API adapter, credential storage, retries, fallback, repair, bake-off, selection UI, or M4+ work. No M2 worker, policy, check, or publication implementation changed. M3.3 has not started. See [`docs/evidence/v1/m3/m3.2-codex-cli.md`](../evidence/v1/m3/m3.2-codex-cli.md).
