# V1 Phase 9 — independent UX, product and documentation review

## Initial receipt

**Disposition: changes requested for two current-document mismatches.** I found no implementation blocker in the bounded Home, settings, AI workspace, privacy and editor-handoff review. This is an independent local source/UI review on the authorized dirty V1 tree, not a release acceptance or a claim about native display, platform, GPU or live-provider behavior.

Reviewed against Phase 9/12/13 of `docs/V1_MASTER_IMPLEMENTATION_PLAN.md` and `DESIGN.md`. The reviewed repository baseline is `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`; the V1 implementation is dirty and uncommitted. Review scope included the current Home, AI Settings, AI workspace, MainWindow and diagnostics source, the named product and user documents, final Phase 9 capture evidence, and the manual-divergence source path.

## Findings

### P2 — Quick Start and User Guide send readers to diagnostics for paths that diagnostics omit

**Category: confirmed documentation defect.** `docs/QUICK_START.md:105-106` and `docs/USER_GUIDE.md:153-155` say Help → Diagnostics reports application paths. The current `MainWindow._diagnostics_text` at `am3d/ui/app.py:1277-1340` emits an allowlist of version/build, renderer, AI job stage/count, saved/modified state, object/action/undo counts, and bounded autosave interval; it emits no filename, local data root, or other path. `am3d/ui/test_phase9_ui.py::test_diagnostics_omit_private_inputs_and_paths_and_force_plain_text` checks that the filename sentinel, prompt sentinel, credential sentinel, malformed preference text and app-data path are absent, and that the credential getter is never called. Describe the request-confirmation dialog as the surface that shows the local run-record location; say diagnostics omits paths.

Exact check: `rg -n -C 2 "Diagnostics.*path|paths used|App data directory" docs/QUICK_START.md docs/USER_GUIDE.md am3d/ui/app.py am3d/ui/test_phase9_ui.py`.

### P2 — Release Notes show a superseded Phase 9 test and capture status

**Category: confirmed documentation defect.** The current-status note in `docs/RELEASE_NOTES.md:6-7` says 21 Home/Phase 9 checks passed and visual captures remain open. The final owner evidence now records 23 checks and completed captures in `docs/evidence/v1/phase-9/final/ui-evidence.md`; the independent command below also passed 23 checks. At this review, independent UX/docs review and final integrated regression are still open. Update the status note to the 23-check result and completed capture state while keeping the unpassed integration and target gates explicit.

Exact check: `rg -n -C 2 "21 focused|visual captures|capture completion" docs/RELEASE_NOTES.md docs/evidence/v1/phase-9/IMPLEMENTATION.md docs/evidence/v1/phase-9/SOURCE_IDENTITY.json`.

The older `SOURCE_IDENTITY.json` and Phase 9 `IMPLEMENTATION.md` retain a prior documentation-time snapshot. Their historical screenshot hashes do **not** bind the final screenshots: the original PNG bytes were unavailable to restore. The current evidence is separately bound under `docs/evidence/v1/phase-9/final/`; do not treat the old PNG paths as recovered or passing evidence.

### P3 — Home contains a possible duplicate keyboard mnemonic

**Category: source-reasoned suggestion / low-priority keyboard risk.** `am3d/ui/home.py:109` marks the primary **Create with AI...** button with `&AI`, and `am3d/ui/home.py:119` marks **About** with `&About`; both encode Alt+A. The source comment at `am3d/ui/home.py:105-107` says the button mnemonics are distinct. The offscreen host did not establish native Alt+A dispatch, so I do not claim either action is unreachable. Default focus on Create with AI and Tab/Enter navigation were exercised by the focused tests. If desired, give About a unique mnemonic and add a native keyboard check on a supported desktop; this is not a release blocker for the compact layout.

Exact source check: `rg -n "Create with &AI|&About|Mnemonics" am3d/ui/home.py`.

### No confirmed UI blocker; compact Home reachability false positive ruled out

The 640×410 Home capture has the focused primary AI action visible; Home content scrolls to the remaining actions, and the test enters AI through that real Home button at the requested client size. AI brief entry is plain text with no JSON step. The AI page scrolls to Generate and the result/history/refinement controls; Settings scrolls its fields while Save/Cancel remain in the footer. New runs and refinements require a separate **Send request** confirmation that shows the endpoint/model, disclosed content, local run-record location, bounded calls/times, static export limit and unavailable cost. Result and history states distinguish the checked result and limitations from the lower recipe/check report. The preview in the result/history/refinement/error captures is synthetic layout evidence, not an AI-generated asset.

Source inspection of `MainWindow._prepare_ai_refinement` at `am3d/ui/app.py:873-940` confirms it compares the saved generation with the live session including `Session.actions`, restores provenance state after the read-only digest, offers Save manual copy / Refine original generation / Cancel when content diverges, and starts refinement from the immutable saved recipe. The accepted Phase 7 review remains the separate test evidence for the preservation workflow; it was not rerun as part of this bounded Phase 9 check.

The version declaration and About/package copy consistently identify `1.0.0.dev1` as a development test candidate. The checked docs distinguish current source from the older Mint preview artifact and do not claim a current shipped AI release. Modeling claims accurately describe a spline-patch editor with internal tessellation, retained editable lathe/extrude profiles, no general patch control-net editor, and static OBJ/GLB exports. Windows 11, Mint 22.3, physical DPI/native display, physical GPU, live provider quality, human scoring, and full integration remain unpassed.

## Bounded verification

Independent focused command, run with isolated temporary QSettings via the test fixtures and Qt offscreen:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d\ui\test_home.py am3d\ui\test_phase9_ui.py -q --maxfail=1 --tb=short
```

Result: `23 passed in 20.44s`. No provider request or credential getter was invoked by this review run. The tests cover compact Home scroll/focus and entry, Settings tab/scroll reachability, AI workspace focus/scroll, session/undo/dirty-state preservation across Home/AI/Editor, diagnostics secrecy/PlainText/corrupt-autosave fallback, and About/Quick Start/version text.

Capture-integrity check: a read-only Python verification compared each of the 16 entries in `final/checksums.sha256` with the corresponding file and compared all eight `source_sha256` entries in `final/ui-capture-measurements.json` with the current source. Result: **16 entries, 0 mismatches; 8 source hashes match**. The manifest contains **13 screenshot rows**. Its size requests are Qt logical-pixel proxies; `physical_dpi_qualification` is false. Tahoma was registered from the installed Windows font for offscreen capture, with no product font-file dependency.

The capture check was run as:

```powershell
@'
from pathlib import Path
import hashlib, json
root=Path('docs/evidence/v1/phase-9/final')
for line in (root/'checksums.sha256').read_text().splitlines():
    expected, rel=line.split('  ',1)
    assert hashlib.sha256(Path(rel).read_bytes()).hexdigest() == expected, rel
data=json.loads((root/'ui-capture-measurements.json').read_text())
for rel, expected in data['source_sha256'].items():
    assert hashlib.sha256(Path(rel).read_bytes()).hexdigest() == expected, rel
print('16 checksums and 8 source hashes verified; screenshots:', len(data['screenshots']))
'@ | .venv\Scripts\python.exe -
```

## Initial source and document identity

The final capture manifest SHA-256 is `2403f4d3d76d681135d7f50b864ecc2e26fd3793e393498d1b4edfc920c2affc`; final capture evidence SHA-256 is `8d1b217cd1c19151a47e100c2a88dce3a0743a4287732a6f94bea5f56346cd1b`; final checksum-list SHA-256 is `3e423128c72f54c60acf8fcd18b96d97fd224a4e012b5017339e36fbcd8032f9`.

| Reviewed source or document | SHA-256 at initial review |
| --- | --- |
| `am3d/__init__.py` | `2f39d9fd40de9c28772d8ecda78a9734a0842f0dd042e7d364431f44482637ef` |
| `pyproject.toml` | `c051f027adbd8904592e297eb96c2a28afa0be212a482d4109b59bcb096f64ac` |
| `am3d/ui/app.py` | `42e5c011955cbee9cd5d31f2007e88506e0e0dc4c450171db69c4c3810369729` |
| `am3d/ui/home.py` | `8af6c00d1ea19e795364a66205db8c8b399ea478330c3508df7656f3b84a56d1` |
| `am3d/ui/ai_settings.py` | `41b1b9f7cfdbf299ae6fd999f9dfc7a23d238a8be04d20918339b089fd350aea` |
| `am3d/ui/ai_workspace.py` | `097397c217abcadd7307a3583cb8cbd0c706b9bb900cc2a5e717c3099adc10da` |
| `am3d/ui/test_home.py` | `e73d233e3fa06aa6c9f62352b042e38303cc8c2daa84ad104d428d2a99d42e57` |
| `am3d/ui/test_phase9_ui.py` | `f945286674f76b49bb0dc24aed1067e74aa24d31d47bf3ade220b73412fcd3e2` |
| `docs/QUICK_START.md` | `9959f97d5a8606d956fb674a9671a08b96e9602f13a2b3e50b75222037f8ec27` |
| `docs/USER_GUIDE.md` | `e2bd2a186ed0313ed6dc681e2c999a5ec320affca0ab00a0e47daa16c231e683` |
| `docs/RELEASE_NOTES.md` | `3b34fa534a58e1e56f230b6e6caa3bb0d15b9b60f8ca09ab62e483a0dd5da133` |

This hash set is the initial review snapshot. After the two confirmed document corrections, the one focused follow-up should verify those exact statements, record the new hashes, and leave UI source/capture hashes unchanged.

## Focused follow-up and final local disposition

**The two P2 documentation findings are closed. Local Phase 9 UX/product/docs review passes.** The focused follow-up verified the corrected Quick Start and User Guide now point to request confirmation for the local run-record location and say Diagnostics omits filenames, local paths, prompts and credentials. The obsolete path claims and obsolete `21 tests` / captures-pending claims had zero matches. The current Release Notes records the owner’s 23-check run, the final 13-screenshot capture set, its checksum/source-hash counts, and the completed two-finding verification while preserving the still-open DPI/native-display and integrated-regression gates.

The application test suite was not rerun after these documentation-only edits. The initial independent run remains `23 passed in 20.44s`; the fixes do not change application source. In the single focused evidence check, the post-edit capture manifest still had 13 screenshot rows, all 16 entries in its checksum list matched, and all eight current UI-source hashes matched the manifest. The later owner status-only update changed Release Notes and the fix receipt only; it did not change the UI source or final captures.

Focused text checks:

```powershell
rg -n "Help.*Diagnostics.*path|Diagnostics.*paths used|reports the paths used|21 focused Home/Phase 9 tests|visual captures.*open|visual capture completion remains open" docs/QUICK_START.md docs/USER_GUIDE.md docs/RELEASE_NOTES.md
# No matches (exit 1, expected)

rg -n "local run-record location|allowlisted support summary|omits filenames" docs/QUICK_START.md docs/USER_GUIDE.md
rg -n "23 focused|13 screenshots|16-entry|eight source hashes|physical DPI/native display" docs/RELEASE_NOTES.md
```

The focused post-edit hash check first matched the three corrected documents against the doc-owner receipt: `docs/QUICK_START.md` `d8d3eeb9cd6adde6274fedcd9abdd5758f1f949154d622aa339b61b2024f619a`; `docs/USER_GUIDE.md` `c0d632d45187518b075e6de3bdc818bd08e71bb6b3645ec3e195fc6192f77f45`; and `docs/RELEASE_NOTES.md` `54a3502a5405c919deac7606053d1429bc19dc8d593f337e2ba14e777ecbe030`. The doc-owner receipt has hash `b61cdf46318e2b9e4e6fb35f9d1b82a4232d347d02d04bf4a8c868bf1969fecc` at that check.

After the owner’s status-only update, the two current status hashes were checked directly with:

```powershell
Get-FileHash docs/RELEASE_NOTES.md,docs/evidence/v1/phase-9/DOC_REVIEW_FIX.md -Algorithm SHA256
```

The verified hashes are `docs/RELEASE_NOTES.md` `1ac64393648a65d72c15c62a7f85f8d27acf85e4bfbc5d1081427d09e8be864c` and `docs/evidence/v1/phase-9/DOC_REVIEW_FIX.md` `85c8791f4fc16a5e33c34ac8ec056a1ad85112cad7df4bc695c4ec7e1413b053`. Release Notes now points to this final disposition; `DOC_REVIEW_FIX.md` preserves its original owner-fix snapshot and pre/post hash table, and links this closure.

The duplicate Alt+A mnemonic is **deferred as a low-priority suggestion**. Offscreen checks verified default focus and Tab/Enter reachability but did not establish native Alt+A behavior; I make no claim of a native keyboard failure. Physical native DPI/display, native keyboard inspection, Windows 11, Mint 22.3, physical GPU, live provider/model quality, human quality scoring, and full integrated V1 regression remain unpassed. Synthetic result/history/refinement/error captures remain layout fixtures, not generated-asset evidence.
