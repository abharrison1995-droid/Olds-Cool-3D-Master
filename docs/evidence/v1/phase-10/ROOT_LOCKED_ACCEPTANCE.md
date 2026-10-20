# Locked Windows local acceptance — committed development candidate

**Disposition:** exact local Windows 10 development candidate accepted for the executed local gates listed here. This is **not accepted Windows V1**, a release candidate, or a Windows 11 qualification.

## Identity and host

The committed candidate is source commit `d067e921cb8f6b767c6faa526553ae28d20fd71c`; Windows lock SHA-256 `0a9a1b4086add4515dab3eed56cb585331b6526ef4de72e9fa83e4c38024d4d6`; build-input digest `a109c4a8c50365ea155b0356282b1b1745d2758b18af751492e59ae9a4af9b7d`; 189 tracked build inputs, zero untracked. Archive SHA-256 `229ccb5292b74823ee1d274f3170a175ac40716821e87da938507174af7c04ce`. These are bound by `LOCKED_ROOT_BINDING.json` and `windows10-followup/committed-d067e92/DELIVERY_VERIFY.json`.

The host was Microsoft Windows 10 IoT Enterprise LTSC `10.0.19044`, build `19044`, x64. Python `3.12.14`, PyInstaller `6.22.2`, locked dependency set 38 packages. Video-controller inventory reports Intel HD Graphics 4000; this is inventory, not rendering qualification. Windows 11 remains the approved Windows target and was not available. Mint 22.3 is explicitly deferred for this Windows-focused task.

## Exact build and local checks

A fresh locked build ran from a clean detached checkout at the committed source identity using `& .\build_windows.ps1`. Exit code 0; **1,049 passed, 2 skipped, 4 warnings in 744.71 seconds**. The build log records skip count but not the reasons. Existing warnings are QMouseEvent deprecations. A post-build isolated tooling run used `python -m pytest scripts/test_phase10_tooling.py -q -rs`: **44 passed, 4 symlink-capability skips in 40.47 seconds**; skips state file/directory symlink creation is unavailable.

Verified on the exact candidate:

- Qt offscreen GUI smoke 14/14; results use offscreen/software rendering.
- Shipped recipe CLI validation, valid build/export, structured malformed-input failure, and relocation checks.
- Frozen AI workflow using a fixed local `httpx.MockTransport`: 4 mocked requests; no live network; worker and checks; parent/child history and refinement; preview, spritesheet, OBJ and GLB outputs.
- Windows system credential-store explicit sentinel CRUD and cleanup; report confirms no sentinel remained and no live provider request occurred.
- Independent Trimesh 5.1.1 parse of generated parent and refined child OBJ/GLB: one mesh, 2,700 faces, finite bounds; parent 1×1×1 and child 1×1.5×1.
- ZIP structure, CRC, one top-level folder, zero duplicate/unsafe paths, and byte-for-byte equality of all 314 packaged files to the staged release folder.
- Recomputed input manifest exactly matches the delivered 189-input manifest; output-folder copies of ZIP, checksum, manifest, and provenance byte-match the repository release files. Embedded build identity matches the input digest.
- Complete staged-payload forbidden-build-root scan passed. Heuristic scan found zero common API token patterns or complete PEM private-key blocks; see its stated limits and Qt marker-only strings in `PAYLOAD_SECRET_PATTERN_SCAN.json`.

The candidate originally failed a Windows frozen-fixture hash regression because CRLF text bytes differed from LF golden inputs. That failure is preserved. Commit `d067e92` restricts CRLF normalization to four frozen text inputs; receipt/output hashes remain byte-exact. The corrected source and lock were committed, then rebuilt from clean committed source.

## Mandatory gates still unpassed

| Gate | Evidence and exact input needed |
| --- | --- |
| Native Windows workflow | UI window existed on a prior pre-commit build, but two screenshot captures timed out before interaction. No current-candidate manual workflow is claimed. Needs interactive capture/automation access to exercise editing, generation/result handoff, history/refinement, cancellation, dirty handling, undo/redo, save/reopen and recovery. |
| Keyboard, DPI and rendering | Needs native desktop checks at 100/150/200%, keyboard navigation, physical GPU and forced software rendering on a usable target. Offscreen smoke and adapter inventory do not satisfy these. |
| ACL/read-only installation | Build reports restore capability unavailable and states the payload ACL was not changed. Independent review confirms denial is skipped when preflight fails; no raw DACL capture is available. Needs an elevated restore-capable target and before/after ACL proof before any denial attempt. |
| Live provider/security | User supplied no approved provider/model, spend or call limits, or secure local credential configuration. Needs those inputs configured privately; no key should be sent in chat. No billable request has been made. |
| Benchmark and human scoring | Needs two full live 30-case frozen runs under the approved model/budget, style-family refinements, and separate original scores from the two independent human reviewers. Reviewers being available is not scoring. |
| Windows 11 clean target | Needs Windows 11 x64 target/VM and clean no-Python host access for the complete target ladder. Windows 10 results do not qualify Windows 11. |
| RC/release | Remains open until required target, live/provider, human, native, ACL, security and sign-off gates pass. No push, publication, or release occurred. |

No other target platform was tested; Mint 22.3 is deferred. The user confirmed none of the requested live-provider, credential, Windows 11/clean-machine or admin ACL inputs are available. This committed Windows 10 package is a development candidate, not accepted Windows V1.

## Review and runtime disclosure

Independent packaging review rechecked this exact committed ZIP, manifest, lock, provenance, embedded identity and archive structure; it found stale pre-commit acceptance bindings, which this evidence set replaces. Independent scope review found no blocker in the CRLF hash fix (one nonblocking docstring precision note). Independent ACL review found safe preflight ordering but no live restoration proof. The prior product/platform review is reused only for shipped text whose normalized content is verified identical; it is not used for runtime or platform acceptance. The fresh committed-source review found no source blocker in its scope and identified that the main checkout `release/` copy still held the pre-commit ZIP. That copy was refreshed from the clean committed build worktree; the follow-up byte audit matched all 314 staged files and all four release metadata/artifact files across the main checkout, clean build worktree, and output folder. The review and post-review reconciliation are recorded at `windows10-followup/committed-d067e92/INDEPENDENT_SOURCE_REVIEW.md` and `DELIVERY_VERIFY.json`.

Reviewer dispatch accepted GPT-6 Luna at xhigh with fresh contexts and no substitution. The requested root GPT-6.1 Sol/medium setting cannot be independently inspected by available tools. The user explicitly authorized continuation on the currently configured root runtime; no root runtime verification is claimed.
