# Locked Windows build — committed final development candidate

Build input identity: `a109c4a8c50365ea155b0356282b1b1745d2758b18af751492e59ae9a4af9b7d` (`LOCKED_SOURCE_INPUTS.json`); version `1.0.0.dev1`; source/Windows lock committed in `d067e921cb8f6b767c6faa526553ae28d20fd71c`. The build ran in a clean detached worktree on Microsoft Windows 10 IoT Enterprise LTSC `10.0.19044`, x64, using explicit host Python `3.12.14`. Windows 11 is not claimed. The locked Windows dependency set contained 38 packages and its source lock SHA-256 is `0a9a1b4086add4515dab3eed56cb585331b6526ef4de72e9fa83e4c38024d4d6`.

Exact command: `& .\build_windows.ps1` (default explicit host Python).

Final result: exit 0; full suite **1,049 passed, 2 skipped, 4 warnings in 744.71s**. The retained build log records the skip count but no reasons. GUI smoke passed 14/14 in Qt offscreen mode; recipe CLI validation/build/structured-error and relocation checks passed; frozen fixed MockTransport offline workflow passed; payload path scan passed. Exact candidate credential-store sentinel CRUD/cleanup and independent external-reader checks are separately bound in this directory. The read-only ACL workflow is **UNPASSED**: restore capability unavailable; payload ACL was not changed.

The first committed candidate attempt at `a671188` failed because frozen fixture text hashes differed on Windows CRLF checkouts. Its log is preserved at `windows10-followup/committed-d067e92/failed-a671188-build.log`. The narrow `d067e92` correction normalizes CRLF for the four frozen text inputs; raw generated-artifact and receipt hashes remain byte-exact. The full corrected committed candidate was rebuilt from a clean checkout and is the only current artifact binding.

No provider credentials or spending authorization were available. No live provider request, ACL denial, push, publication or release was made. Windows 11 and Mint 22.3 remain unqualified/deferred.
