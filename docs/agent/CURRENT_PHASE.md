# Current handoff — M0 / H1

**Status:** in progress on baseline `3f6f7f0` (6 Oct 2026).

M0 is repository/context setup. Branch inventory found only `master` at
`3f6f7f0`, equal to `origin/master`; no stash or local-only commits exist.
GitHub's Windows workflow has two runs (Oct 4 and Sep 28); both reach pytest
and then crash during collection with a `moderngl` access violation.
`checkout@v7`, `setup-python@v7`, and `upload-artifact@v7` match current
releases checked from GitHub. See `docs/evidence/v1/m0/repository-inventory.md`.
Checkpoint tags will use `v0.3.0-dev.N`; package metadata agrees at `0.2.0b1`.

**GitHub tracking:** [V1 milestone](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/milestone/1);
M1–M6 issues are #3, #8, #6, #5, #4, and #7. Duplicate M3 issue #9 is closed.

**Complete locally:** compact docs/archives and platform authority; version
and branch inventory; six GitHub issues; build-input manifest with digest
`2ecca41c98d723fd4f8f28c9928bc8542cd53250c4a5a5495d4be8eef0631980`; doc
limits/links and `git diff --check`; pinned offscreen suite: 738 passed, 4
deprecation warnings (77.87s).

**Still required:** push the runner runtime fix, get the Linux fast job green, then tag
`v0.3.0-dev.1`. First GitHub Linux run exposed missing runner `libEGL.so.1`
during Qt test collection; the workflow now installs `libegl1`. The Windows
failure is recorded for follow-up under M2/M6.

**Next:** commit/push the `libegl1` runner setup fix; tag only after a green
GitHub Linux run.
