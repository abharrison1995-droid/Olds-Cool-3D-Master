# Desktop release finding ledger

Source: `docs/DESKTOP_RELEASE_PLAN.md`. Baseline commit `d01187c`.

Status vocabulary — **REPRODUCED**: failure demonstrated by an executed run
before any change. **SOURCE-REASONED**: defect established by reading the code
and its callers, without a pre-fix executed failure. **DISPROVEN**: claimed
defect not present. **BLOCKED**: cannot be checked in this environment.
A historical PASS label from the V3 plan is *not* evidence for this release.

## Evidence index

| File | What it shows |
| --- | --- |
| `phase-a/baseline-suite.txt` | Reproduced baseline: 529 passed, 2 failed |
| `phase-a/environment.md` | OS/Python/resolved transitive versions |
| `phase-a/reference-machine.md` | The MX 25.2 acceptance machine, verified present |
| `phase-b/view-01-reproduction.txt` | VIEW-01 before the fix (4.1x mismatch) |
| `phase-b/view-01-after-fix.txt` | VIEW-01 after the fix (<=2.7px, picking works) |
| `phase-b/view01_check.py` | Re-runnable VIEW-01 probe |

## Findings

| ID | Prio | Status | Evidence | Fix | Tests |
| --- | --- | --- | --- | --- | --- |
| ENV-03a | high | REPRODUCED | `test_path_escape_drive_is_rejected` failed on POSIX: `os.path.splitdrive("D:outside_file")` -> `("", ...)`, so a Windows drive-relative export path passed the escape check on Linux | New host-independent policy `am3d/core/paths.py`; `RecipeExecutor._resolve_output_path` and `resolve_resource_path` use it; `\` normalised as a separator | `am3d/core/test_paths.py` (33), `test_executor.py` policy block (19) |
| ENV-03b | high | REPRODUCED | `test_schema_json_conformance` errored: `jsonschema` undeclared | Split `requirements.txt` (runtime) / `requirements-dev.txt` (test+build, adds `jsonschema==4.26.0`); `requirements-lock-linux.txt` captures the transitive set | Full suite green in a clean pinned venv |
| ENV-01 | high | CONFIRMED (metadata) | numpy 2.4.6 requires Python >=3.11 vs `requires-python = ">=3.10"` | Documented split between the flexible source install and the pinned frozen-build interpreter | `docs/SUPPORTED_PLATFORMS.md` |
| DATA-01 | blocker | REPRODUCED | `clear_autosave()` unlinked every `*.autosave.am3d`; quitting document A destroyed document B's recovery | `clear_autosave(path=None)` removes only the named/current slot; `clear_all_autosaves()` is the explicit opt-in sweep | `test_document_controller.py::test_clear_autosave_removes_only_the_current_documents_snapshot`, `::test_main_window_exit_preserves_another_documents_recovery` |
| DATA-02 | high | REPRODUCED | Home emitted `list_autosave_files()[0]` — filename order, no identity | `autosave_entries()` + `.meta.json` sidecar (name, original path, time, size); `RecoveryDialog` chooser; unselected snapshots preserved; corrupt sidecars listed, not hidden | 8 tests in `test_document_controller.py` |
| LIFE-01 | high | REPRODUCED | `_file_close_project()` omitted `_reset_document_ui_state()`; play timer kept running, Play stayed checked, stale selection/context survived | Reset + refresh on successful close; cancelled close changes nothing | `test_operators.py::test_close_project_stops_playback_and_clears_document_state`, `::test_cancelled_close_project_preserves_the_active_document` |
| LIFE-02 | medium | REPRODUCED | Empty `_render()` returned before clearing `_dirty`; every paint re-armed the render timer | Empty render is settled state; `paintEvent` re-arms only a genuinely pending render; real empty-state text | `test_operators.py::test_empty_scene_render_settles_and_stops_rescheduling`, `::test_content_after_an_empty_render_still_renders` |
| VIEW-01 | high | REPRODUCED | Measured: software render drew the box 4.11x smaller than `world_to_screen` placed it — clicking the visible object selected nothing | `toon_render_camera()` + `_rasterize_screen()` render through the camera's own perspective projection, the same call picking/overlays use | `am3d/ui/test_view_parity.py` (13) |
