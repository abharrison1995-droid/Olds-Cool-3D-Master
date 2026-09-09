# Desktop release assessment and implementation handoff

Date: 2026-09-09. Assessed commit: `d01187ccbc48803add2cf7ebd3e750f68883362b`.
This task is assessment and planning only. No application, test, dependency, or build changes are authorized by this document itself. A subsequent agent implements it when instructed by the user.

## Assessment

The project is an established Python/PySide6 desktop beta with substantial spline, recipe, animation, persistence, rendering, export, and editor code. Preserve this foundation; a rewrite or a web-app conversion is unnecessary. Windows packaging scripts and historical packaged smoke evidence exist. The project is not yet demonstrated shippable on both MX Linux and Windows.

The previous V3 plan is useful implementation history, not current cross-platform release acceptance. Its PASS labels coexist with explicitly unpassed clean-Windows-machine, interactive display, scaling, and GPU checks. Phase 7 also refers to clean-VM validation as completed in Phase 6, whereas Phase 6 explicitly says it was unavailable. Keep historical records, but correct their interpretation in the release ledger. Do not replay already-completed V3 work blindly.

Current verification on Debian 13, Python 3.13.5:

```text
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest am3d/ -q
Exit 1: 529 passed, 2 failed, 4 warnings in 46.30s
```

Failures:

1. `am3d/recipes/test_executor.py:779`, `test_path_escape_drive_is_rejected`: `D:outside_file` succeeds on POSIX despite the test requiring rejection. The observed output remains inside the output root; this is a cross-platform contract failure, not evidence of an actual Linux directory escape.
2. `am3d/recipes/test_schema.py:157`, `test_schema_json_conformance`: `jsonschema` is missing. Fix the declared test environment before claiming reproducible suite success.

The existing environment is not the pinned release environment: NumPy 2.5.2 and msgpack 1.2.2 are installed versus requirements pins 2.4.6 and 1.2.1. PySide6 6.11.2, Pillow 12.3.0, ModernGL 5.12.0, and pytest 9.1.1 are installed. These results are a current development baseline, not packaged-platform certification. No live desktop session, new frozen executable, or actual MX machine was tested during this assessment.

## Release scope and platform contract

Deliver a desktop editor that an ordinary user can launch without Python, a checkout, pip, or a terminal. Retain the standalone recipe CLI as a companion. Keep spline patches authoritative; tessellated exports are output representations.

Required outputs:

- Linux x86-64: portable archive containing a native executable and its runtime, plus an executable launcher and desktop entry/icon instructions. Prefer a reliable PyInstaller directory bundle first; an AppImage is useful only after the same payload passes compatibility testing. Do not make AppImage extraction/FUSE behavior the only launch route.
- Windows x86-64: portable ZIP containing the desktop `.exe`, recipe `.exe`, bundled runtime, examples, and quick start. An installer/Start-menu registration can follow the portable build; it is not necessary to prove the executable works.
- Both: version, platform/architecture, dependency inventory, checksums, release notes, limitations, and an identifiable source commit. User documents, preferences, logs, and recovery files must live in writable user locations.

The user supplied their system report on 2026-09-09. The mandatory Linux target is **MX-25.2 KDE x86-64 (Infinity), based on Debian 13 trixie**, running **KDE Plasma 6.3.6 on Wayland (KWin)**. Use MX 25.2 / Debian 13 userspace as the initial release baseline; older MX releases are outside the initial compatibility claim unless separately tested. A Debian build environment alone does not establish acceptance on the user's MX desktop.

Reference hardware and graphics from the supplied report:

- AMD Ryzen 7 5700U, 8 cores / 16 threads; 32 GiB RAM.
- Integrated AMD Radeon/Vega graphics, kernel `amdgpu`, Mesa `26.1.4-1~mx25ahs` / radeonsi; reported OpenGL 4.6 and EGL 1.5.
- Kernel `6.12.90+deb13-amd64`; Xwayland 24.1.6 available within the Wayland session.
- Built-in display 1920×1080 at 60 Hz, currently 100% scaling.

These identify the reference acceptance machine, not mandatory exact kernel/driver pins or proven application compatibility. Verify the frozen app on this graphics stack, including actual GPU rendering and forced software fallback. Test native Qt Wayland startup and interaction as the primary desktop route, and the Qt xcb/XWayland route as a documented compatibility alternative. Do not treat an X11-only/offscreen check as Wayland acceptance. Include pointer capture during drags, focus/shortcuts, file dialogs, and fractional scaling in these checks.

Select and document a Windows minimum version and test that version plus the current supported target; do not claim untested versions or ARM/32-bit compatibility.

Build each platform natively. Linux builds must target a compatible oldest supported userspace: PyInstaller does not bundle glibc, and bundled third-party binaries can impose further OS requirements. Qt also requires Linux platform-plugin dependencies. Validate actual bundled libraries rather than assuming an archive or AppImage solves compatibility. Sources: [PyInstaller platform notes](https://pyinstaller.org/en/stable/usage.html), [Qt Linux requirements](https://doc.qt.io/qt-6/linux-requirements.html).

Minimum usable workflows:

1. Launch from the desktop into Home; start an empty project or open an example.
2. Create and edit a spline-based object, navigate/select reliably, assign supported appearance, undo/redo, save, close, and reopen.
3. Create a simple skeleton and bind/weight geometry from a blank project, then pose/key/play it. Also open a supplied bound character; scrub/play, edit, save/reopen, and observe deformation.
4. Render the visible scene and export the documented static OBJ/GLB pose and image/animation outputs.
5. Recover unsaved changes after forced termination without overwriting the last good save or another document's recovery.
6. Execute/correct a recipe using the bundled CLI, then open its output in the GUI.

Publish a capability matrix distinguishing engine/API, recipe, and GUI availability. Static OBJ/GLB export must not be advertised as skeletal-animation interchange. For the first usable release, prioritize completing these journeys over graph editors, pie menus, GPU skinning, new shaders, embedded AI chat, or additional interchange formats.

## Implementation sequence

### A — Reproducible baseline and truthful scope

Create fresh platform-specific development/build environments. Declare all required test/build dependencies and capture resolved versions, Python version, OS, architecture, backend, and source identity. Reproduce the two current failures and repair the root cause; preserve a common cross-platform recipe-path policy with regression cases for Windows drive-relative/absolute paths, POSIX paths, UNC paths, traversal, and legitimate Unicode names. Do not weaken a test merely to get a green run.

Create `docs/evidence/desktop-release/` and a finding ledger with IDs, evidence, priority, owner, phase, status, and test links. Reconcile old PASS claims and stale README counts with actual tests and supported workflows. Reuse earlier successful work after verification.

Gate: clean environment installation succeeds; full suite passes on Linux and Windows, with skips and warnings explained; every advertised first-release workflow has explicit expected behavior and an owning phase.

### B — Correctness and data durability

Implement the confirmed review findings recorded below, beginning with save/data integrity, scene evaluation, editing, and rendering correctness. Reproduce source-reasoned findings before changes and record disproven ones. Test the actual consumer path, not just the helper that creates data. Keep shared scene/session/command boundaries so GUI, recipes, saves, and exports agree.

Gate: regression tests demonstrate each fix; original/reopened scenes and selected poses agree; failed/cancelled operations preserve active state and prior output. The representative editable object and weighted character both survive save/reload and undo/redo.

### C — Complete the desktop journeys

Map every visible control to a working action and expected feedback. Finish required authoring routes and remove or explicitly disable unsupported optional controls with an explanation. Provide useful empty states, examples, error messages, progress/cancellation for long operations, and a short keyboard/navigation guide. Ensure normal modelling, playback, render/export, and large-project interaction remain responsive. Measure responsiveness with a named representative fixture and machine before choosing caching/threading changes.

Test actual pointer/keyboard events and focused widgets: outliner selection, control points, transforms, bones, keyframes, dialogs, and workspace transitions. Verify Save/Discard/Cancel on New/Open/Home/Quit; autosave timer scheduling and recovery discovery; writable locations; missing resources; invalid input; and failed writes. Include 100%, 150%, and 200% scaling screenshots on real desktop sessions. Offscreen action triggering does not close these checks.

Gate: a fresh user can complete the six workflows above with the shipped quick start; no unexplained dead control or silent failure on those routes. Required features must be reachable from the GUI; recipe-only support is not desktop-authoring completion.

### D — Native reproducible distribution

Add Linux build/staging/verification automation alongside the existing Windows pipeline. Resolve paths from the repository/spec location, work from arbitrary current directories, and use isolated builds. Include the required Qt Wayland and xcb platform plugins and their runtime dependencies, theme, icons, examples, recipe schema/docs, and all optional runtime dependencies needed by the selected release configuration. Make test/build tooling separate from runtime dependencies and capture transitive resolution rather than describing direct pins alone as fully reproducible.

Retain a working software renderer without ModernGL or a usable GPU. Make the selected backend and fallback reason observable. Test normal GUI startup separately from headless smoke startup; do not inject offscreen mode into the user launcher. Build smoke outputs outside the release payload. Verify relocation, paths with spaces/Unicode, read-only install directories, and absence of source-tree references.

Add native Linux and Windows CI jobs for unit/integration tests, frozen builds, packaged recipe execution, and packaged smoke. CI artifacts are candidates; interactive clean-system checks remain required. Verify source/wheel resource packaging if pip installation remains documented.

Gate: both downloadable native bundles build from a clean checkout and run without Python installed. Archive listings, dependency manifests, hashes, and packaged smoke reports identify the same candidate commit.

### E — Release candidate acceptance

Run the matrix below on the actual frozen artifacts. Record exact commands, environment, outputs, screenshots, and failures. Independently reopen OBJ/GLB exports in a reader/viewer outside this writer, checking geometry, materials, normals, and selected pose. Exercise GPU and forced-software scene parity with a fixed multi-object fixture and tolerant numeric/image comparisons; a context-creation test alone is insufficient.

Fix all confirmed release-scope defects before acceptance and rerun affected gates. Mark unavailable systems/backends as BLOCKED, never PASS. Publish only after the Linux and Windows mandatory matrix is complete.

| Environment | Required checks |
| --- | --- |
| MX 25.2 KDE x86-64 / Debian 13, clean standard user; user reference hardware for graphics | Desktop launch without Python; all six workflows; native Wayland and xcb/XWayland compatibility route; AMD radeonsi GPU and software rendering; save/recovery locations; 100/150/200% scaling; Unicode paths |
| Oldest declared Linux baseline | Frozen library compatibility; software-only launch/render; CLI success/failure; relocation |
| Clean supported Windows machine/VM, no Python | Desktop `.exe` and CLI; all six workflows; read-only installation; relocation; scaling; save/recovery |
| Real graphics environment on each OS | Actual GPU frame and material/geometry correctness; forced software; unavailable-GPU fallback and diagnostics |
| Both packaged platforms | Corrupt/missing project resources, failed save/export, cancellation, restart/crash recovery, output validation, logs |

## Review policy for the implementation agent

Use Luna agents for particular code reviews as requested by the user. Give each a bounded changed area, requirements, candidate identity, and relevant integration callers/tests. Require file/line evidence, impact, reproduction or reasoned proof, and missing coverage. Deduplicate results; do not implement speculative fixes solely because a reviewer suggested them. Re-review fixes and rerun affected tests. This assessment uses three targeted Luna reviewers; it is not a certification that the whole repository is defect-free.

Final handoff must include downloadable Linux/Windows artifacts, checksums, a quick start, verified platform versions, the completed finding ledger, test/review evidence, and explicit unsupported features. Do not label the product shippable while a mandatory platform gate is pending.

## Targeted Luna findings

These are targeted reviews by `gpt-5.6-luna` (UI, engine, packaging), not the historical substitute reviewers. Unless explicitly described as executed above, findings are source-reasoned and require focused reproduction before implementation. Line references identify the assessed commit.

| ID / priority | Evidence and effect | Work / acceptance |
| --- | --- | --- |
| PKG-01 / blocker | `build_windows.ps1:1`; no Linux build/release pipeline in the checkout | Phase D: native Linux executable bundle and mandatory actual-MX acceptance |
| PKG-02 / blocker | `docs/evidence/v3/phase-6/bullet5_release_zip.md:111`; clean Windows/no-Python test explicitly unpassed, contradicted by phase-7 gate text at line 73 | A/E: correct release status; verify frozen candidate on clean Windows |
| ENV-01 / high | `requirements.txt:8`, `pyproject.toml:10`, `build_windows.ps1:37`; pinned NumPy needs a newer Python than the advertised 3.10 build minimum | A: reconcile supported source Python and frozen-build Python; enforce selected interpreter before install; fresh install at every claimed minimum |
| ENV-02 / high | `build_windows.ps1:34-55` uses ambient Python; historical package listing includes unpinned Numba/llvmlite | A/D: isolate build environment and lock complete resolution; prove unrelated installed packages cannot affect payload |
| ENV-03 / high | Current suite missing `jsonschema`; POSIX drive-relative path test fails | A: complete test dependencies and cross-platform recipe policy; clean Linux/Windows suite |
| UI-01 / high | `am3d/ui/app.py:849-855,311-333`; skeleton creation is explicitly absent from GUI; Rig poses existing bones | C: bone creation/parenting/deletion, geometry binding and a usable initial weighting route; build and animate a small character without a recipe |
| UI-02 / high | `am3d/ui/app.py:274-287,754-776`, `workspaces.py:70-73`; file exports are OBJ/GLB, no final still/sequence render command | C: render dialog with destination, size, camera, frame/range, progress/cancel and actionable errors; open output and check pose/frame differences |
| MAT-01 / high | `am3d/recipes/executor.py:443-490,546-576`; baked atlases are detached from flat-color OBJ/GLB export material data | B: carry supported textures/UVs into GLB and OBJ/MTL and rendered images, or explicitly reject unsupported requests; checker/image fixture must visibly retain appearance in independent reader |
| MAT-02 / high | `am3d/renderer/tessellate.py:125-143`, `am3d/core/scene.py:185-200`; evaluated material colors use object material and lose patch identity | B: preserve per-patch assignment through rendering/export; two differently colored patches on one object remain distinct |
| API-01 / medium | `am3d/spline/kernel.py:174-199`; patch-grid input validation is incomplete | B: reject invalid grid resolutions, degree/control-point combinations and weight lengths clearly; test callers that expose these inputs |
| PKG-03 / medium | `pyproject.toml:28-30`, `am3d/ui/app.py:41-52`; wheel package-data coverage for theme/resources is not established | D: inspect/install a wheel outside checkout if source/pip install remains supported; otherwise state supported distribution route |
| UI-03 / medium | `am3d/ui/app.py:477-509`, `properties.py:148-155`; Render workspace does not select its properties tab | C: show relevant settings/output controls immediately on entering Render |
| UI-04 / medium | `am3d/ui/operators.py:486-500`; creating an action does not activate it and no-active-action keying can silently return | C: make next action explicit/active with undo semantics, or show actionable guidance; create action then insert first key via UI |

For ENV-01, the reviewer checked [NumPy 2.4.6 package metadata](https://pypi.org/project/numpy/2.4.6/), which declares Python >=3.11. A source installation with a flexible NumPy requirement and a pinned frozen-build environment may have different supported Python versions; document this deliberately rather than assuming they are identical.

### Standalone renderer defects: keep caller scope precise

The normal viewport already evaluates the Session and merges the scene into a single mesh (`am3d/ui/viewport3d.py:171-187,383-408`). The following defects affect the standalone `am3d.gpu.render_frame(Project)` API, not that normal merged viewport route:

- **GPU-01 / high, Phase B:** `am3d/gpu/__init__.py:44-46` directly tessellates a Project, bypassing shared evaluation of visibility/transforms and available pose/material state. Define a Session/evaluated-scene input for action-dependent rendering; route Project input through an appropriate static evaluator. A transformed/hidden scene must match the shared evaluator, and a Session-based animated scene must match its selected frame.
- **GPU-02 / high, Phase B:** `am3d/gpu/__init__.py:127-138` renders only the first mesh on GPU failure. Fallback must preserve all visible meshes and shared occlusion. Force context failure and verify a two-object image.
- **GPU-03 / high, Phase B:** `am3d/gpu/__init__.py:84-88` draws meshes separately while `am3d/gpu/shaders.py:176-184` fits projection separately for each mesh. Use one camera/projection derived from the whole scene. Unequally sized, offset objects must retain relative placement/depth in GPU and software outputs.

**SCOPE-01 / clarify, Phase A:** Open splines produce vertices without triangles (`am3d/renderer/tessellate.py:100-112`), while the viewport draws separate editing overlays (`viewport3d.py:323-331`). Treat them as construction curves unless curve rendering/export is explicitly adopted. Document surface-only exports and explain an empty surface export. This is not automatically a request to add curve interchange.

### Desktop integrity and editing rechecks

The UI reviewer initially used an interpreter without PySide6, then reran focused checks with the repository `.venv/bin/python` and PySide6 6.11.2. The findings below distinguish executed checks from source proofs.

| ID / priority | Evidence | Required repair and acceptance |
| --- | --- | --- |
| DATA-01 / blocker | Source proof: `am3d/ui/app.py:688-694` calls `clear_autosave()` on exit; `document_controller.py:313-319` enumerates and unlinks every autosave, without document identity | B: delete only the appropriate current-document snapshot after the relevant save/discard decision. Create recoveries for A and B, close A, restart, and prove B remains recoverable |
| DATA-02 / high | Source proof: `am3d/ui/home.py:213-223` emits only `autosaves[0]`; `document_controller.py:273-278` sorts by filename | B/C: recovery chooser with document identity, original path and time; preview/select recoveries; handle corrupt entries separately; preserve unselected snapshots |
| LIFE-01 / high | Executed: `MainWindow._file_close_project()` leaves playback timer active and play button checked while Home is shown; `am3d/ui/app.py:718-722` omits the existing document UI reset | B: stop playback, cancel pending drags, clear selection/context and derived caches on successful Close Project; cancelled close preserves state; verify timers stop |
| EDIT-01 / high | Executed: edit a lathed spline CP and generated patch `interior` stays unchanged. `am3d/ui/app.py:364-384`, `operators.py:130-157` snapshot the profile; `viewport3d.py:677-687`, `operators.py:438-450` edit only spline CPs | B/C: explicitly choose live profile regeneration with durable undo, or baked geometry with a usable surface-editing route and clear UI semantics. Merely hiding misleading controls does not satisfy the editable-surface journey. Edit the surface, observe image/geometry change, undo/redo, then save/reopen |
| LIFE-02 / medium | Executed state check: empty `_render()` leaves `_dirty=True`, `_frame=None`, timer active. `am3d/ui/viewport3d.py:391-401,190-205,160-164` can reschedule on subsequent paint events | B: represent a completed empty render and stable empty state; repeated paints must not continuously enqueue redundant rendering. This is potential repeated scheduling, not a measured unconditional CPU loop |
| VIEW-01 / investigate | Source risk: software fitting at `am3d/ui/viewport3d.py:427-457` differs from perspective picking/overlays in `camera.py:125-154` and `viewport3d.py:578-584` | B/C: reproduce orbit/pan/zoom selection of known screen targets in software mode. If mismatched, share camera/projection; accept only when visible surfaces, handles and pick rays agree |

Recommended first implementation batch: ENV-03 baseline, DATA-01/DATA-02 recovery preservation, LIFE-01/LIFE-02 lifecycle, then EDIT-01 and VIEW-01. Next finish material/renderer parity, GUI rig/render routes, and native packaging. Start platform build-environment preparation early, but do not mistake a successfully frozen broken workflow for release completion.

## Copyable handoff instruction

> Implement `docs/DESKTOP_RELEASE_PLAN.md` against the current checkout. Preserve unrelated work and existing functioning features. Start with Phase A and the prioritized defect ledger; reproduce findings before repairing them. Use Luna agents for bounded code reviews. Work through phases B–E, maintaining evidence and updating each gate honestly. Deliver usable standalone MX Linux and Windows desktop bundles plus the recipe CLI, with clean-machine and real-interaction validation. Do not substitute a web app, claim offscreen tests establish interactive usability, or mark unavailable platform checks as passed. Target the confirmed MX 25.2 KDE x86-64 / Debian 13 system, with native Wayland acceptance and xcb/XWayland compatibility testing; use the reference AMD hardware details in this plan. Report completed fixes, tests, artifacts, and remaining blockers.
