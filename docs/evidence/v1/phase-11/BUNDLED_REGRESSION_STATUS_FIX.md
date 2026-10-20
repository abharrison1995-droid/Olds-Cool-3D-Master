# Bundled regression status correction

## Disposition

The Quick Start, User Guide, and Capability Matrix now describe the local
locked Windows development-candidate checks as passed: the full source
regression and the fixed offline frozen history/refinement checks. The text
points readers to the active [PROGRESS ledger](../../../../PROGRESS.md) and
[V1 acceptance ledger](../ACCEPTANCE_LEDGER.md) for the current independent
review disposition and exact candidate identity. It no longer hard-codes a
transient documentation/product-review state into the bundled text.

The documents continue to state that Windows 11 and Mint target
qualification, native/read-only/GPU gates, live-provider and human-quality
gates, and overall V1/RC acceptance remain open. This correction does not
claim cross-platform V1 acceptance or qualify a release. The prior locked
candidate record is in [Phase 10 acceptance](../phase-10/development-candidate-1/ROOT_LOCKED_ACCEPTANCE.md)
and its [identity binding](../phase-10/development-candidate-1/LOCKED_ROOT_BINDING.json);
those records remain tied to their recorded source and archive identities.

## Scope and checks

Only these bundled documents were edited:

- `docs/QUICK_START.md`
- `docs/USER_GUIDE.md`
- `docs/CAPABILITY_MATRIX.md`

Their hashes at the start of this correction and after editing are:

| File | Before SHA-256 | After SHA-256 |
| --- | --- | --- |
| `docs/QUICK_START.md` | `42d627ba2a5ec9253b2a3f6727784e137d0c6946beeab0e5defeb7ec5fd2db01` | `a7981b218694cf7525fe57c01d7d31b2fa2f10ec30c2434c7c7fdcd3288cc801` |
| `docs/USER_GUIDE.md` | `8ab92201f35fdb26e44a6e9eb6838d2dae678bb2ee8bc4b1c8e44a4abaf79f9e` | `f0ce86b546f982b7e49d8d14eaacf9a38d4e34d1eb03331b4c000785ba006f2b` |
| `docs/CAPABILITY_MATRIX.md` | `f3adc01471e027470c9af346550a28ca7629f322933bf1b34281ab643c76be54` | `d3f6d83690b9c83ed6ba479db5475a40b5c5e21efd2d85af20e17519c1222b40` |

The complete packaging-input digest was `31381e2e79747cc821f45e73e941cfae811ee7d02a829f6ffe364ddc539258e5`
before the wording change and is `c22f8e8d05df0d1d2a61477d8309e63ed6c385c141987cdbb050e5c3ec96e388`
after the first correction. Removing new relative links to repository-only
status files, because those files are not included in archives, produces the
final input digest `2be687b3249db162c9c04081ab77eea9f6c966210317da147d9ebcd34b79924d`.
The changes are expected because all three documents are explicit packaging
inputs. This new digest identifies pending inputs only; it does not identify
a rebuilt or accepted artifact.

Commands/results:

- `.venv\Scripts\python.exe scripts\build_input_digest.py --digest-only` —
  returned the before, intermediate, and final digests recorded above.
- `Get-FileHash docs/QUICK_START.md,docs/USER_GUIDE.md,docs/CAPABILITY_MATRIX.md -Algorithm SHA256` —
  matched the after hashes above.
- `rg -n -i "final independent (documentation|product)|documentation/product review|final reviews .* remain open|full integrated regression.*(pending|open|remain)|final regression.*(pending|open|remain)" docs/QUICK_START.md docs/USER_GUIDE.md docs/CAPABILITY_MATRIX.md` —
  no stale review-pending or integrated-regression-pending statements found.
- `git diff --check -- docs/QUICK_START.md docs/USER_GUIDE.md docs/CAPABILITY_MATRIX.md` —
  passed; only Git's existing LF-to-CRLF conversion notices were printed.
- `Test-Path ..\PROGRESS.md; Test-Path evidence\v1\ACCEPTANCE_LEDGER.md` —
  both linked status records exist relative to `docs/`.

No tests, build, lock capture, publication, or release action was performed.
