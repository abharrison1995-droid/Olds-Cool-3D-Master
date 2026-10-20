# Integrated bootstrap retry1 source regression

Source input digest840c4e12518e9d279cf713c4e5f0fba3701c3bf9b4ffb29a85d31ee5eedfe41f; baseline HEAD3f6f7f03d32b4d1a3af06af4fdc0724bf0436945 with authorized uncommitted changes. Windows10 IoT Enterprise LTSC19044 x64; isolated build/windows/venv, Python3.12.14,38 resolved build packages, Qt offscreen.

`python -m pytest am3d/ -q --maxfail=1 --tb=short` passed **1048 tests,2 skipped,4 warnings in672.57s**. Full command/output is bootstrap-build-retry1.log (still growing while packaging runs; final log hash belongs in build disposition). The four QMouseEvent deprecation warnings are from test_dopesheet.py lines97/152.

A separate bounded `-rs` probe identified the host capability for the two skipped worker symlink checks: test_output_root_symlink_is_rejected_without_following_it and test_final_tree_audit_rejects_symlink. Both skipped due Windows error1314, required privilege not held (1.59s). See retry1-skip-capability-corrected.log. The first probe used an incorrect second test node and collected no tests; its error remains separately preserved in retry1-skip-capability.log. It made no source change or successful-test claim.

This source regression does not qualify live provider, frozen artifacts, native display, physical GPU or target Windows11/Mint. Historical unknown close-wait and interrupted-run observations remain preserved; this pass does not establish their cause.
