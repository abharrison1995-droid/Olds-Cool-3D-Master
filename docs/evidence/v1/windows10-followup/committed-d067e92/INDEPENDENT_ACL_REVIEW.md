# Independent ACL preflight review

Reviewer: `/root/acl_reviewer`; read-only, no code edits and no ACL command run.

The Windows build script saves the relocated payload DACL, resolves the parent from the payload path, and attempts `/restore` before `/deny`. A failed preflight leaves both write-denial statuses unpassed and skips the denial branch. Source tests cover ordering and parent resolution, not live ACL restoration. The script records `UNPASSED: Windows ACL restore capability unavailable` and `UNPASSED: restore capability not proven; payload ACL was not changed` for the committed candidate. No mutation was attempted.

The reviewer notes that this no-op preflight treats `$LASTEXITCODE` as its success criterion; it does not compare before/after DACLs or inspect per-object output. The available logs do not contain raw `icacls` output or DACL captures, so the exact cause of preflight failure cannot be independently diagnosed. Keep the gate unpassed pending a restore-capable target and live evidence.
