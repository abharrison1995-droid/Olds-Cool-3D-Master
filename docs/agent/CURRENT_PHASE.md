# Current handoff — M3.2f Codex recipe-only integration

**Baseline:** V1 plan rev. 3, 6 Oct 2026. M0–M2 are accepted; M3.1 passed independent verification at `88a9b85cfc30854fe8f3234eca44cfce2b30e4e9`.

**Active milestone:** M3.2 on `v1/m3.2-codex-cli`, PR #16. The owner reports that the pinned Codex recipe-only source gate passed independent review. That gate does not approve a compiled executable or accept M3.2.

**M3.2f state:** The offline prototype is preserved at `/tmp/codex-upstream-m32b.3Pz6KA/prototype`, based on Codex `740e5af33c71225640e0c1c1555c514c2c93ab74`. The approved recipe-only patch SHA-256 is `0481c3e9c2969871b2f2455dd52e6b9be6afe9f57cdec48175f0d6e0912a7e66`; the full current prototype diff SHA-256 is `c675a03d3051192bfce3b8e960cf7966b91c4eac24298fa4131d7b09a32a3ee1`. The earlier focused core test passed (8). The 13 Oct bounded continuation was stopped by the 23.5 GiB safety threshold while Cargo was still compiling dependencies; it produced no new test summary or Codex executable. No candidate binary or offline capability self-test exists. The 3D MASTER adapter integration has not begun.

**Resource gate:** The owner authorized 24 GiB (`25769803776` bytes) while preserving the shared Cargo target. The one cached continuation stopped at `25233514496` bytes (23.5 GiB safety threshold), leaving `536289280` bytes below the hard cap; filesystem free space was `9669091328` bytes. The second run ended during dependency compilation, without a compiler diagnostic or test result. No further build attempt is authorized by the completed bounded attempt; the amount needed to finish is unknown. Full measurements are recorded in the evidence file.

**M3.2 acceptance remains blocked:** The candidate binary identity and approval, production-path capability self-test, app integration, independent integration review, subscription compatibility, and platform qualification remain outstanding. A prior adapter review also identified process-boundary concerns that must be checked in the integration: fail-closed capability detection, response-file size enforcement during execution, and an effective subprocess memory limit.

**CI / PR:** PR #16 remains open and draft. Its remote tip is `edf352ab6960fb920303e6da9ece6dfe3f80721d`; this checkout has an unpushed local commit at `4bf2d7b1fde5204309a23541eb3e7572370e678f`. Latest remote CI: Linux fast tests and Windows worker tests passed; Windows candidate failed at the known ModernGL collection crash. No Windows qualification is claimed.

M2 worker/policy/check/publication code remains frozen. No live provider calls, credential access, modified-binary installation, merge, or M3.3 work occurred. Details and exact evidence are in [`docs/evidence/v1/m3/m3.2f-resumption.md`](../evidence/v1/m3/m3.2f-resumption.md); historical M3.2b evidence remains unchanged.
