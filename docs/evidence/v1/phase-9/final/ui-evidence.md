# Phase 9 UI evidence

This is a focused Windows offscreen UI run for the Phase 9 changes. The source and capture-script SHA-256 values, requested/actual client and frame sizes, screenshot paths, and the comparison with the earlier screenshot receipt are in [ui-capture-measurements.json](ui-capture-measurements.json). The screenshot checksums are in [checksums.sha256](checksums.sha256).

The implementation makes Home content scrollable, sizes the shared stack from its active page so inactive editor constraints do not block compact Home/AI, keeps AI Settings actions and their footer reachable, adds a Help guide, and renders diagnostics as PlainText from an allowlist. The compact Home test confirms the primary Create with AI action has focus and is visible, Quick Start is reachable by scrolling, and the real Home button switches into AI at the requested size. The AI test scrolls Generate into the viewport and checks that Home→AI→Editor→Home preserves the session, undo entries, dirty state, and the editor’s original size policy/minimum when Editor is active.

Focused verification passed on Windows 10 IoT Enterprise LTSC build 19044 x64, Python 3.12.14, PySide6/Qt 6.11.2, using `QT_QPA_PLATFORM=offscreen`:

```text
$env:QT_QPA_PLATFORM='offscreen'; .venv\Scripts\python.exe -m pytest am3d\ui\test_home.py am3d\ui\test_phase9_ui.py -q --maxfail=1 --tb=long
23 passed in 34.04s

.venv\Scripts\python.exe -m py_compile am3d\ui\app.py am3d\ui\home.py am3d\ui\ai_settings.py am3d\ui\ai_workspace.py am3d\ui\test_home.py am3d\ui\test_phase9_ui.py am3d\__init__.py
exit 0

git diff --check -- am3d/ui/app.py am3d/ui/home.py am3d/ui/ai_settings.py am3d/ui/ai_workspace.py am3d/ui/test_home.py am3d/ui/test_phase9_ui.py am3d/__init__.py pyproject.toml
exit 0
```

The capture used isolated temporary QSettings and app-data roots. It made zero provider/network calls and read zero credential values. Tahoma was loaded from the installed Windows font file for this capture because offscreen Qt initially exposed no font families. The product has no new font-file dependency. Requested dimensions are Qt logical-pixel proxies only; this run does not qualify physical DPI scaling, native Windows display behavior, Windows 11, Linux, GPU rendering, or live-provider behavior.

The corrected MainWindow Home and AI windows both reached 640×410 client size (644×414 frame). Home’s scroll viewport measured 626×383 with a 75-pixel vertical range; Create with AI was focused and visible. The AI scroll viewport measured 626×343 with a 1393-pixel vertical range at 640×410; the focused test verified Generate can be scrolled into view. At 853×546 and 1280×820, AI client size matched the request and its vertical scroll ranges were 1229 and 913 pixels. AI Settings measured 560×360 (540×304 content viewport, no current overflow, Save/Cancel footer visible) at all three parent sizes. Quick Start measured 620×380 with its OK footer visible. The diagnostics box measured 400×244 and used PlainText. Result/history/refinement/error captures use synthetic offline UI fixtures; the preview is drawn only to show layout and is not model output.

The initial compact-AI test run recorded a real window width of 1274 pixels because the hidden editor page constrained the stack. Ignoring only the editor reduced that to 792 pixels because Home had its own wide minimum. The completed active-page sizing change plus Home scroll wrapper resolves both constraints. Two intermediate assertions also failed for harness reasons: one compared content-local button geometry with the scroll viewport instead of mapping coordinates; the other used a test helper that starts in Editor while intending to measure Home. The final tests exercise mapped viewport geometry and explicitly start from Home. The capture helper first failed before opening the UI due to an invalid QSettings API call, then failed twice because the script directory—not the repository—was on `sys.path`; both harness issues were corrected. An early offscreen capture lacked fonts and rendered tofu; the final captures use the installed Tahoma described above. The first failure tracebacks are visible in this task’s tool output, but no separate stdout files were saved under `work/v1`, so no log path or hash is claimed.

## Historical capture receipt

Before the corrected captures were created, an intermediate run wrote to the original Phase 9 screenshot paths. I discovered afterward that [SOURCE_IDENTITY.json](../SOURCE_IDENTITY.json) already recorded different SHA-256 values for those paths. That identity file and its old hash claims remain unchanged. The original raw PNG bytes were not available to restore, so the original screenshot bindings are unverifiable and are not counted as passing evidence. The exact prior hashes and current intermediate hashes for every overwritten path are preserved in the `historical_capture_receipt.previous_receipt_comparison` section of the new capture manifest.

The intermediate write occurred on 13 October 2026 at approximately 23:56 local time, with `work/v1/phase9_capture_temp.py` and the command shown in the original capture manifest. It was after the active-stack minimum correction but before the Home scroll wrapper; the 640-pixel AI request was still enlarged by Home’s then-current minimum. Those intermediate files are retained at their original paths for audit and are not presented as final screenshots. Corrected evidence was written to the separate `final/screens/` directory and is bound to the exact final source hashes in the new manifest. No settings, credentials, history records, or project files outside isolated temporary roots were read or changed by these captures.

## Corrected captures

- [Home at 640×410](screens/home-640x410.png)
- [Diagnostics from Home at 640×410](screens/diagnostics-home-640x410.png)
- [Create with AI at 640×410](screens/main-idle-640x410.png)
- [AI Settings at 640×410](screens/settings-640x410.png)
- [Quick Start at 640×410](screens/quick-start-640x410.png)
- [Checked result, synthetic fixture](screens/main-result-synthetic-fixture.png)
- [History, synthetic fixture](screens/main-history-synthetic-fixture.png)
- [Refinement, synthetic fixture](screens/main-refinement-synthetic-fixture.png)
- [Timeout state, synthetic fixture](screens/main-error-synthetic-fixture.png)
