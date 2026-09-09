# Phase 7 — manual scaling / keyboard / GPU / missing-resource / read-only / recovery checks

Evidence for: "Execute manual scaling (100/150/200%), keyboard, GPU/software,
missing-resource, read-only output, and multiple-recovery checks. Record any
environment exclusions." (`docs/V3_FUNCTIONAL_IMPLEMENTATION_PLAN.md` Phase 7.)

This machine has no interactively-controllable window for the built,
unregistered `3D MASTER 2005.exe` (computer-use's `request_access` only
resolves Start-Menu-registered applications — see
`docs/evidence/v3/phase-7/trial/gui_inspection.md` for the same limitation
hit during the trial). Each check below was therefore done as a genuine,
non-mocked exercise of the real code path that is reachable without an
interactive display, and the parts that require an actual human-operated
window are recorded as an explicit exclusion rather than inferred as passing.

## 1. Manual scaling (100/150/200%)

Ran the full 8-step packaged smoke workflow
(`am3d.ui.smoke.run_smoke_test`, the same real `MainWindow` workflow used
for build-time smoke testing) three times under `QT_QPA_PLATFORM=offscreen`
with `QT_SCALE_FACTOR` set to `1.0`, `1.5`, and `2.0`. All three runs: `"ok":
true`, all 8 steps `"ok"` — the application does not crash or fail any
create/save/render/export workflow step at any of the three scale factors.

**Excluded:** visual layout correctness at each scale (no clipped text,
no overlapping widgets, correct icon crispness) requires actually looking
at a rendered window, which this session cannot do for this executable.
Recorded as pending a human check, not claimed as verified.

## 2. Keyboard

Drove the real `MainWindow`'s own `QAction` objects — the same objects the
keyboard shortcuts (`Ctrl+Z` / `Ctrl+Shift+Z`) are bound to via
`setShortcut`/`setShortcuts` in `am3d/ui/app.py` — by locating them via
`findChildren(QAction)` and matching their bound shortcut, then `.trigger()`-
ing them exactly as Qt's own shortcut dispatch would: created a `Box`,
triggered the action bound to `Ctrl+Z`, confirmed the object list emptied;
triggered the action bound to `Ctrl+Shift+Z` (redo), confirmed `Box`
reappeared. This exercises the real undo/redo command stack through the
same `QAction` the keyboard would hit, not a direct method call.

**Excluded:** physical key-press-through a live window (`QTest.keyClick`
against a real, focused, on-screen widget) was not run — no live window is
controllable in this session. The existing source suite
(`am3d/ui/test_operators.py`) already covers additional shortcut-adjacent
behavior at the unit level and passed in the full 484-test run.

## 3. GPU / software rendering

Software path: already covered by the smoke test's own
`multi_object_software_rendering` step (`win.viewport.force_software = True`),
which passed at all three scale factors above and in the packaged build
(Phase 6 evidence). Hardware GPU path: this build machine's `moderngl`
hardware-context path is exercised by `am3d/gpu/test_gpu.py` in the source
suite (484 passed) but a real on-screen hardware-accelerated frame requires
an actual display surface.

**Excluded:** a genuine on-screen hardware-accelerated (non-offscreen)
render was not captured in this session for the same reason as above — no
controllable live window. Not claimed as verified beyond what the source
suite and offscreen software path already demonstrate.

## 4. Missing-resource

Ran a recipe referencing a nonexistent texture file
(`"texture": "does_not_exist.png"`) through the real CLI:
```json
{"ok": false, "error_records": [{"code": "missing_resource", "stage": "resource",
  "path": "recipe.materials", "message": "resource file not found: does_not_exist.png",
  "hint": "Check that all texture or image resource paths exist relative to base_dir or project root."}]}
```
Exit code 1, structured error with a hint, no crash, no partial manifest.
Matches the existing regression `test_missing_texture_resource_reports_structured_error`
in `am3d/recipes/test_executor.py`.

## 5. Read-only output

Unix-style `chmod` under Git Bash does not reliably enforce a real
write-deny on this Windows/NTFS machine (confirmed: `chmod 555` left the
directory showing `drwxr-xr-x` and the CLI wrote to it successfully). Used
a genuine Windows ACL instead — a PowerShell `FileSystemAccessRule` `Deny`
on `Write,CreateFiles,AppendData` for the current user — verified the deny
actually blocks a raw `File.WriteAllText` first, then ran the real recipe
CLI against that directory:
```json
{"ok": false, "error_records": [{"code": "publish_error", "stage": "write",
  "path": "recipe.exports",
  "message": "failed to publish artifact to '...\\cube.obj': [Errno 13] Permission denied: '...\\cube.obj'"}]}
```
Exit code 1, clean structured error, no crash, no partial manifest. ACL
removed and the test directory deleted afterward.

## 6. Multiple-recovery

Created two independent documents in one process (`doc0`, `doc1`), saved
each, made each dirty again post-save, and called the real
`doc_ctrl.do_autosave()` on each. `list_autosave_files()` found both
per-document autosave slots simultaneously
(`doc0-f9b0e966b7.autosave.am3d`, `doc1-...`, names hashed from each
document's own path). Recovered `doc0`'s autosave into a fresh `MainWindow`
via the real `recover_from()`: succeeded, and the recovered project
contained exactly `doc0`'s objects (`Obj0`, `Obj0b`) with no trace of
`doc1`'s — confirming per-document identity holds and recoveries don't
cross-contaminate. This exercises the same `recover_from`/`autosave_path`/
`list_autosave_files` API covered at the unit level by
`am3d/ui/test_document_controller.py` (already in the 484-test suite), but
as a live integration exercise across two real documents in one process
rather than isolated unit calls.

**Excluded:** interrupted-write and corrupt-recovery-file scenarios are
already covered as source-level regressions
(`test_recover_from_corrupt_file_returns_false_without_mutating_state`) and
were not independently re-exercised live in this pass.
