# Phase 5 — Windows CI preparation

Date: 2026-09-27.

## Prepared locally

- Added `.github/workflows/windows.yml` for push, pull request, and manual
  runs on `windows-latest`.
- The job builds the application and packaged recipe CLI, runs the full suite,
  executes the Phase F frozen acceptance with the documented interactive
  checks reported as skipped, and runs the independent OBJ/GLB verifier.
- The first native run captures `requirements-lock-windows.txt` as an artifact.
  `build_windows.ps1` now consumes that file on later runs; without it, the
  script bootstraps from pinned direct requirements and can capture the
  platform-specific resolution.
- A successful run uploads the staged application, ZIP, SHA-256 sidecar,
  provenance, captured dependency lock, and build/frozen-acceptance/export
  logs for inspection. If a step fails, a diagnostics artifact preserves the
  logs and any lock generated before the failure.
- The workflow passes `actionlint` v1.7.12 (the downloaded release checksum
  was verified), YAML parsing, and `git diff --check`. The Linux candidate
  digest and SHA sidecar still match, and two independent Luna reviewers
  passed the preparation. Luna `max` was used because `xhigh` is unavailable.
- PowerShell 7.6.6 parsed the Windows build script, both Phase F acceptance
  scripts, and every inline PowerShell workflow step without syntax errors.
  The downloaded PowerShell archive checksum was verified. This validates
  syntax only; it does not exercise Windows APIs, packaging, or a native
  Windows run.

## Not yet accepted

The workflow has not run on GitHub Actions from this workspace. No Windows
artifact or Windows support claim is produced by adding the workflow. A green
native run is still required for Stage 1, and the clean Windows VM and real
GPU stages remain separate gates. The first generated lock should be reviewed
and committed before later builds rely on it.

The scripts and inline workflow steps have been parsed, but not executed.
PowerShell 7.6.6 ran on this Linux Mint host; it does not exercise Windows
APIs, Windows packaging, or native Windows acceptance. No Windows runner is
available in this workspace.
