# Phase 11 release-document source-delta clarification

Disposition: documentation clarification only. The Phase 9 checksum and source
hash results were accurate at their original gate. This follow-up makes clear
that those source hashes are historical after the Phase 11 Settings privacy
change. The independent reviewer classified the concern as an ambiguity or
clarification suggestion, not as a false historical result.

The Phase 9 final capture manifest recorded eight UI-source hashes and its
16-entry checksum list had zero mismatches at the recorded gate. The later
percent-encoded credential/privacy fixes changed `am3d/ui/ai_settings.py`; the
Settings hash no longer matches, while the other seven hashes still match.
Per [SOURCE_DELTA_REUSE.md](SOURCE_DELTA_REUSE.md), the unchanged screenshots
remain reusable for layout evidence only. Current Settings privacy behavior
has a separate independent 11-check result in
[ARCHITECTURE_REVIEW.md](ARCHITECTURE_REVIEW.md). The overwritten preliminary
captures remain unverifiable and were not recreated or recovered.

The progress note now distinguishes the present in-app AI/history/refinement
development source and its local verification from the historical Linux Mint
`0.2.0b1` desktop/recipe preview artifact. Neither the old preview's recorded
acceptance nor the current local source checks establish V1 acceptance.

This follow-up edited only `docs/RELEASE_NOTES.md`, `PROGRESS.md`, and this
receipt. No source, bundled document, test, lock, phase-ledger entry,
screenshot, or prior evidence record was changed.

## Verification

The complete build-input digest before the edits was
`2aab9e3b80626ea5020b67cc7bebf01e6488179ab64e2156c38bfa9a645309bc`. It was
checked after the documentation edits with:

```powershell
.venv\Scripts\python.exe scripts\build_input_digest.py --root . --digest-only
```

The result remained
`2aab9e3b80626ea5020b67cc7bebf01e6488179ab64e2156c38bfa9a645309bc`.

An inline `.venv` Python audit checked all 22 relative Markdown links in the
three changed documents; every local target exists. The scoped whitespace
check was:

```powershell
git diff --check -- docs/RELEASE_NOTES.md PROGRESS.md docs/evidence/v1/phase-11/RELEASE_DOC_DELTA_FIX.md
```

It passed. No tests or build commands were run; the edits affect documents
excluded from the source-input digest and packaged payload.
