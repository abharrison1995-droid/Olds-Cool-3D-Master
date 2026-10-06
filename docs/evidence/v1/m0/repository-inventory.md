# M0 repository inventory

Checked 2026-10-06 against baseline `3f6f7f0`.

- Local branch: `master`, equal to `origin/master`; `git log --branches --not --remotes --oneline` returned no commits. `git stash list` was empty. No branches, commits, or stashes were deleted.
- GitHub Windows workflow runs: [37189546555](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/actions/runs/37189546555) (2026-10-04) and [36364860487](https://github.com/abharrison1995-droid/Olds-Cool-3D-Master/actions/runs/36364860487) (2026-09-28). Both fail during “Build the frozen Windows candidate”, in pytest collection. Both diagnostic logs report `Windows fatal exception: access violation`; the stack enters `moderngl.init_context` / `create_context`. Frozen acceptance and independent export verification were skipped. This is a real open CI defect, not Windows acceptance.
- Action release checks through GitHub API: `actions/checkout@v7` → latest `v7.0.1`; `actions/setup-python@v7` → latest `v7.0.0`; `actions/upload-artifact@v7` → latest `v7.0.1`.
- Package version metadata matches: `pyproject.toml` and `am3d.__version__` both declare `0.2.0b1`. Adopted V1 checkpoint tags: `v0.3.0-dev.N`; first checkpoint will be `.1` after M0 CI is green.

This file records repository/workflow inventory only. It does not certify a
frozen artifact or source changes after baseline `3f6f7f0`.
