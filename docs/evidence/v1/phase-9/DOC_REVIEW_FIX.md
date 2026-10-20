# Phase 9 focused documentation review fixes

Date: 2026-10-14. This receipt records only the two confirmed P2 documentation
corrections from the [initial independent UX/product/docs review](INDEPENDENT_REVIEW.md).
At this receipt's original fix snapshot, both corrections were applied but the
reviewer's focused follow-up was pending. That was the status at the fix
snapshot; the current follow-up disposition is recorded at the end of this
receipt. Neither status claims V1 is complete or physical-DPI, native-display,
GPU, live-provider, or target-platform gates have passed.

The initial reviewer reported no implementation blocker in the bounded Home,
settings, AI workspace, privacy, and editor-handoff review. The reviewed tree
was dirty at baseline `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`.

## P2 — diagnostics path disclosure wording

The [Quick Start](../../../QUICK_START.md) and [User Guide](../../../USER_GUIDE.md)
now identify the request-confirmation dialog as the surface that shows the
local run-record location. They describe **Help → Diagnostics...** as an
allowlisted summary of runtime/toolkit versions, a shortened validated
source/build identity when available, renderer route and preference, AI-job
stage and bounded attempt, saved/unsaved and modified/clean state,
object/action/undo counts, and autosave interval. The docs state that the
summary omits filenames, local paths, prompts, and credentials.

The finding was checked against `MainWindow._diagnostics_text` in
`am3d/ui/app.py` and the reviewer-cited
`test_diagnostics_omit_private_inputs_and_paths_and_force_plain_text` test.
That test checks that filename, prompt, credential, malformed preference, and
application-data-path sentinels are absent and that the credential getter is
not called. The independent reviewer ran the tests; this documentation fix
did not rerun application tests.

| Document | SHA-256 before | SHA-256 after |
| --- | --- | --- |
| `docs/QUICK_START.md` | `9959f97d5a8606d956fb674a9671a08b96e9602f13a2b3e50b75222037f8ec27` | `d8d3eeb9cd6adde6274fedcd9abdd5758f1f949154d622aa339b61b2024f619a` |
| `docs/USER_GUIDE.md` | `e2bd2a186ed0313ed6dc681e2c999a5ec320affca0ab00a0e47daa16c231e683` | `c0d632d45187518b075e6de3bdc818bd08e71bb6b3645ec3e195fc6192f77f45` |

## P2 — current Phase 9 results and captures

The current-status note in [Release Notes](../../../RELEASE_NOTES.md) now reports
the final owner run of 23 focused Home/UI tests in 34.04 seconds and the
independent run of the same 23 tests in 20.44 seconds. It records the
completed 13-image offscreen capture set at three requested Qt logical-size
proxies, the 16-entry checksum manifest with zero mismatches, and eight
matching source hashes. These measurements do not establish physical DPI or
native display behavior. The note says the initial independent UX/docs review
requested two corrections and that its focused verification of these fixes is
still pending; it does not imply completed UX/docs acceptance or final
integrated V1 regression.

| Document | SHA-256 before | SHA-256 after |
| --- | --- | --- |
| `docs/RELEASE_NOTES.md` | `3b34fa534a58e1e56f230b6e6caa3bb0d15b9b60f8ca09ab62e483a0dd5da133` | `54a3502a5405c919deac7606053d1429bc19dc8d593f337e2ba14e777ecbe030` |

The final capture evidence is separately bound and unchanged:

| Evidence | SHA-256 at this check |
| --- | --- |
| [Final UI evidence](final/ui-evidence.md) | `8d1b217cd1c19151a47e100c2a88dce3a0743a4287732a6f94bea5f56346cd1b` |
| [Capture measurements](final/ui-capture-measurements.json) | `2403f4d3d76d681135d7f50b864ecc2e26fd3793e393498d1b4edfc920c2affc` |
| [Capture checksums](final/checksums.sha256) | `3e423128c72f54c60acf8fcd18b96d97fd224a4e012b5017339e36fbcd8032f9` |
| Initial independent review receipt at this check | `947f8b18bbcf1e2f61fe4b266e3ceed2d825dde460f97a62a79c0ae44cad9857` |

The initial independent review reports 16 checksum entries and eight source
hashes matched, with 13 screenshot rows. The existing
[`SOURCE_IDENTITY.json`](SOURCE_IDENTITY.json) and
[`IMPLEMENTATION.md`](IMPLEMENTATION.md) retain their earlier documentation
snapshot and owner-only Phase 9 status. They were not rewritten by this fix;
their earlier PNG hashes do not bind the final captures. The final capture
manifest and checksum list above are the current evidence for those images.

## Commands and results

The pre-edit hashes above were collected with:

```powershell
Get-FileHash docs/QUICK_START.md,docs/USER_GUIDE.md,docs/RELEASE_NOTES.md -Algorithm SHA256
```

The diagnostics source labels were read with:

```powershell
rg -n -A 66 -B 5 "def _diagnostics_text|_diagnostics_text" am3d/ui/app.py
```

After editing, this obsolete-claim check returned no matches:

```powershell
rg -n -C 2 "Diagnostics.*path|paths used|App data directory" docs/QUICK_START.md docs/USER_GUIDE.md
```

The replacement-text check found the confirmation-location and allowlisted
summary wording in both documents:

```powershell
rg -n "local run-record location|allowlisted support summary|omits filenames" docs/QUICK_START.md docs/USER_GUIDE.md
```

The independent reviewer—not this docs-only follow-up—ran
`$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d\ui\test_home.py am3d\ui\test_phase9_ui.py -q --maxfail=1 --tb=short`
and reported `23 passed in 20.44s`. The independent capture check reported
`16 entries, 0 mismatches; 8 source hashes match`, with 13 screenshot rows.
No application tests or capture-generation command was run for this docs fix.

Scoped `git diff --check` passed for the three corrected documents; Git printed
only its LF-to-CRLF advisories. The scoped relative-link audit also passed.

## Focused verification update

The independent reviewer completed the single focused follow-up and passed
both confirmed P2 documentation findings. The final capture integrity result
remains 16 checksum entries with zero mismatches and eight matching UI source
hashes. The review and its current disposition are linked in
[`INDEPENDENT_REVIEW.md`](INDEPENDENT_REVIEW.md); the final capture evidence is
linked above. This closes the two documentation findings only. Physical DPI,
native display, target-platform qualification, and final integrated V1
regression remain outside this pass.

The prior table's `docs/RELEASE_NOTES.md` post-edit SHA-256 was
`54a3502a5405c919deac7606053d1429bc19dc8d593f337e2ba14e777ecbe030` at the
original fix snapshot. After this status-only update, its SHA-256 is
`1ac64393648a65d72c15c62a7f85f8d27acf85e4bfbc5d1081427d09e8be864c`. This
new hash records the closure status and does not rewrite the original pre/post
hash table above.
