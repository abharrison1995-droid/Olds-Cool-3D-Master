# Windows 10 V1 follow-up - 2026-10-20

## Scope and identity

This follow-up records checks made after the exact local Windows development candidate was independently reverified. It does not qualify Windows 11 or Mint and does not accept Windows V1.

- Repository HEAD before the follow-up commit: `3f6f7f03d32b4d1a3af06af4fdc0724bf0436945`; the V1 candidate source and lock were uncommitted at this check.
- Recomputed build-input digest: `2be687b3249db162c9c04081ab77eea9f6c966210317da147d9ebcd34b79924d`.
- Windows lock SHA-256: `0a9a1b4086add4515dab3eed56cb585331b6526ef4de72e9fa83e4c38024d4d6`.
- Frozen ZIP: `36970e05116bd691ee1b80e3431e82987c0dc2547fbcdfc485d4b5b743340afe`.
- Input manifest SHA-256: `278f2dd244c925f122cf9f49132a21ad91698de895d9ffbae59a0cf1341beefb`.

The archive, checksum sidecar, input manifest, provenance and reviewer bindings were independently compared with the repository release files and the requested output-directory copies. The artifact reviewer found exact matches and a valid 384-entry ZIP CRC check. The source digest and archive hash are unchanged from the previously reviewed development candidate.

## Host facts

Observed using `Get-CimInstance Win32_OperatingSystem`, `Win32_Processor`, and `Win32_VideoController`: Microsoft Windows 10 IoT Enterprise LTSC, version `10.0.19044`, build `19044`, 64-bit OS, Intel Core i3-3110M, Intel HD Graphics 4000, driver `10.18.10.4252`, desktop `1366x768` at 49 Hz. This is Windows 10, not the approved Windows 11 target.

The current process token is not in the local Administrators role (`ElevatedAdminRole=False`); `whoami /priv` showed no `SeRestorePrivilege` entry. No security settings were changed.

## Native frozen-app launch attempt

The exact frozen executable at `release/3D MASTER 2005 Beta/3D MASTER 2005.exe` was launched through the Computer Use helper on the native Windows 10 desktop. `list_apps` returned one window titled `3D MASTER:2005`, so process/window creation succeeded for this pre-commit archive.

The first `get_window_state` call failed with `FrameArrived timed out: timed out waiting on channel`. The skill-required one-time reselect/retry failed with `window capture timed out: timed out waiting on channel`. No click, key, or text action followed. No assertion is made about the visible UI or any native editing workflow.

Consequently, native manual editing, generation/result/editor handoff, history/refinement interaction, cancellation, dirty-document handling, undo/redo, save/reopen/recovery, keyboard navigation, scaling at 100/150/200%, and physical-GPU rendering remain unpassed. The 1366x768 and GPU/driver observations identify the host only; they are not rendering acceptance.

## Exact-candidate gates reused

The input digest, source lock, source files, tests, packaging scripts and archive matched the previously accepted local development snapshot, so unchanged results are reused with that exact binding:

- Locked source suite: 1,048 passed, 2 privilege-related skips, 4 warnings in 596.54 seconds.
- Packaging tooling: 44 passed, 4 symlink-capability skips in 44.66 seconds. Skips were file or directory symlink creation unavailable.
- Frozen GUI smoke: 14 steps passed in Qt offscreen/software mode; CLI validation/export/structured-error, worker startup, fixed offline MockTransport workflow, relocation and payload-path scan passed.
- Frozen sentinel credential-store CRUD/cleanup and independent Trimesh OBJ/GLB parsing passed for the bound archive. No real key or provider request was used.

The local agent focused run for the ACL code path also passed 2 tests with 46 deselected. It tested PowerShell parent-path resolution and source-order guards, not actual ACL restoration.

## Read-only installation gate

The exact locked build log records `UNPASSED: Windows ACL restore capability unavailable` and `UNPASSED: restore capability not proven; payload ACL was not changed`. The follow-up verified that the current token is not elevated and lacks `SeRestorePrivilege`; no denial or ACL mutation was attempted. The gate remains unpassed.

Independent ACL review confirmed that `build_windows.ps1` saves the relocated payload DACL, calls `/restore` from the payload's parent before `/deny`, and skips denial when preflight fails. The source tests verify ordering but do not execute `icacls`. Raw `icacls` output and before/after DACL captures are not retained, so the exact operating-system cause of the failed preflight cannot be independently determined from the logs.

## Delegation and reviewer disposition

The requested agent settings were dispatched as `model=gpt-6-luna`, `reasoning_effort=xhigh`, `fork_turns=none`; tool dispatch succeeded without substitution. The ACL implementer found no confirmed source defect, made no changes, and ran the focused 2-test check. Independent ACL, artifact and scope reviewers did not implement the code they reviewed.

- Artifact review: exact ZIP/output/checksum/manifest/provenance/source-lock hashes; ZIP integrity passed. Disposition: retain candidate; no packaging change required.
- ACL review: preflight ordering is correct and failure safely skips deny. Disposition: keep the read-only gate unpassed on this token; no ACL change required.
- Scope review: candidate changes are V1-related; `.agents/artifacts/review-loops/v3-phase0-20260908-plan.md` is separate archival housekeeping and must stay out of the candidate commit. Linux packaging inputs are part of the shared V1 build-input digest and remain explicitly unqualified for Mint.

The root model and reasoning effort are not exposed by available tools. After being asked whether to continue with that uninspectable configuration, the user authorized continuing on the current runtime. No unsupported root model metadata is claimed.

## External inputs and disposition

The user replied `None available` to the request for an approved live provider/model and spending limit, secure local credential configuration, and Windows 11/clean-machine/admin-capable test targets. No live call was made and no key was requested. Two independent human reviewers are available once live assets exist, but there are no live benchmark assets or scores.

This is a Windows 10 local development candidate. Mandatory live-provider/benchmark/human-scoring, read-only ACL, native desktop interaction/scaling/GPU, Windows 11 and Mint gates remain unpassed. No push, publication or release occurred.