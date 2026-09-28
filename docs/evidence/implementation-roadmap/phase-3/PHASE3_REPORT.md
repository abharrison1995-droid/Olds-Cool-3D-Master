# Phase 3 — Linux Mint preview candidate

Date: 2026-09-28.

## Result

The final-scope source tree built successfully with the pinned Linux dependency
set on Linux Mint 22.3 (Zena), x86-64, kernel `6.8.0-139-generic`. The bundle
passed the full source suite, packaged GUI and CLI checks, payload hygiene,
and relocation acceptance. This is a **Mint-hosted preview candidate**.
GUI checks used Qt offscreen mode and software rendering; they do not qualify
native desktop interaction, physical GPU behavior, MX Linux, or general Linux
support.

## Candidate identity

- Archive: `release/3D-MASTER-2005-Beta-0.2.0b1-linux-x86_64.tar.gz`
- SHA-256: `4d41c0cf7cbf069edf907483cbf16ff4b0f8dcc54130aa791a16a049568d6433`
- Build inputs: `release/BUILD_INPUTS-linux.json`
- Build provenance: `release/BUILD_PROVENANCE-linux.txt`
- Captured build log: `build_linux.log`
- Source commit: `f35e4e5772f3be91fe48743686c323764421dc13`; the build includes
  uncommitted source and plan changes identified in the provenance.
- Build input digest: `6e62c8cdf6ecfb578885f852391b5d8b50d118a6405b9f4817cb36aa0fd60283`
- Input manifest: 141 files (140 tracked, one untracked digest tool).
- Repeated input-digest calculation: identical; see
  `digest_reproducibility.txt`.
- Dependencies: installed from `requirements-lock-linux.txt`; resolved
  versions are recorded in the provenance.

## Acceptance results

- Full source suite: **738 passed**, four Qt deprecation warnings.
- PyInstaller produced the GUI and recipe CLI executables.
- Qt plugin inventory includes Wayland, xcb, offscreen and Wayland shell
  integration.
- Packaged GUI smoke: **14 steps passed** in Qt offscreen mode.
- Packaged recipe CLI: the bundled example validated and generated output;
  malformed JSON returned exit code 1 with a structured `recipe_read_error`
  record.
- Payload hygiene: no build-root paths leaked into the bundle.
- Relocation: CLI validation and GUI smoke passed after extraction to a path
  containing spaces and non-ASCII characters.
- The build log records the input digest before and after the build; the
  source inputs did not change while it ran.
- The archive SHA-256 matches its sidecar.

## Archive reproducibility note

The source-input digest is stable for the recorded inputs, and the archive
normalizes ordering, ownership and timestamps. This acceptance identifies one
specific built archive by SHA-256; it does not claim that separately frozen
PyInstaller builds are byte-for-byte reproducible. Use the published checksum
to identify this candidate.

## Limits and next work

This candidate has not been interactively accepted through Mint's native
compositor. The xcb route requires `libxcb-cursor0`; native Wayland, DPI
scaling, and physical GPU checks have not been repeated on the current source.
Current-source MX qualification and Windows qualification remain follow-on
release work. The older MX evidence applies only to the historical artifact
identified in `docs/SUPPORTED_PLATFORMS.md`.

Two independent fresh Luna reviews of this candidate and the revised scope
passed after their findings were resolved. See
`docs/evidence/implementation-roadmap/CANDIDATE_REVIEW.md`.
