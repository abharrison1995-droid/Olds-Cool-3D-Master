# Phase E acceptance matrix

Every row is either **PASS** with the command and output that produced it,
or **BLOCKED** with the reason it could not be executed here. No row is
marked PASS on the strength of a source reading, a historical result, or an
offscreen test standing in for a real one.

Artifacts under test: `release/3D MASTER 2005 Beta` and the archive beside
it, built by `./build_linux.sh` from a **clean** tree at commit
`b96c922` — SHA-256
`ad36d7ef798d3fd3bd7dc68bd15a8540a8c535655b2e8ec1e7fe6e86eefc4cdf`. The
pinned build set is in `BUILD_PROVENANCE-linux.txt`, copied into this
directory. The acceptance run reported **14 passed, 0 failed**; only the
evidence files in this directory changed after that build.

Executable evidence in this directory:

| Script | What it runs |
| --- | --- |
| `frozen_acceptance.sh` | the frozen bundle, launched under `env -i` (no Python, no venv on `PATH`) |
| `interactive_session_check.py` | the real KDE/Wayland session: visible window, injected mouse events, screenshots |
| `export_check.sh` | the frozen recipe CLI writes OBJ/GLB; `verify_exports.py` reads them back with no shared code |
| `gpu05_render01_check.py` | the GPU-vs-software framing and ink measurements behind GPU-05 / RENDER-01 |

Raw output: `frozen-acceptance.txt`, `interactive-session.txt`,
`independent-export-verification.txt`, `gpu05-render01-reproduction.txt`,
`frozen-launch-routes.txt`, and the `session-*.png` screenshots.

---

## Row 1 — MX 25.2 KDE x86-64 / Debian 13, reference hardware

| Required check | Result | Evidence |
| --- | --- | --- |
| Desktop launch without Python | **PASS** | `frozen_acceptance.sh` §1–2. Every launch goes through `env -i` with only `HOME`, `USER`, `PATH=/usr/local/bin:/usr/bin:/bin`, the session variables and `LANG`; nothing Python-related is passed and no virtualenv is on `PATH` |
| All six workflows | **PASS** | the packaged smoke run drives the real `MainWindow` through 14 steps — blank start, new project, primitives and a lathed profile, materials, rig + weighted action playback, GUI rig build and bind, multi-object software render, still render to PNG, save and reopen, transformed export, recipe output opened in the GUI, autosave and recovery, corrupt/missing project handling, posed export. `frozen-acceptance.txt` §1 (`not ok: none`) |
| Native Wayland | **PASS** | `frozen_acceptance.sh` §2 `native-session`; `interactive-session.txt` first block: platform plugin `wayland`, 10/10 interactive checks |
| xcb / XWayland compatibility route | **PASS** | §2 `xcb-xwayland`; `interactive-session.txt` xcb block, 10/10 |
| AMD radeonsi GPU rendering | **PASS** | `session-wayland-100.png` shows the shaded sphere with the status bar reporting `GPU (moderngl)`; the smoke run's GL-probe parity block compares the GPU frame against the software frame on this hardware |
| Software rendering | **PASS** | §2 `forced-software` (`LIBGL_ALWAYS_SOFTWARE=1`); `interactive-session.txt` software block, 10/10; parity ratio **0.969**, silhouette IoU **0.806** |
| Save / recovery locations | **PASS** | smoke step `autosave_snapshot_and_recovery`, executed inside the frozen executable: snapshot written to `~/.local/share/3DMASTER2005/3D MASTER 2005/` (the PATH-01 fix), listed with a display name, recovered after the document was lost, and recovered pathless so Save cannot overwrite the snapshot |
| 100 / 150 / 200% scaling | **PASS** | `interactive-session.txt` at `QT_SCALE_FACTOR` 1, 1.5, 2 — 10/10 each — with `session-wayland-100/150/200.png`. 200% is what exposed **UI-05**; the screenshot in this directory is the post-fix one, with the Properties panel scrolling instead of clipping |
| Unicode paths | **PASS** | §4 (`prosjekt æøå 走 test`, `oppskrift æøå.json`) and §6 (relocation to `flyttet æøå/…`) |

## Row 2 — Oldest declared Linux baseline

| Required check | Result | Evidence |
| --- | --- | --- |
| Frozen library compatibility on an older baseline | **BLOCKED** | Only one Linux userspace is available here (Debian 13 / MX 25.2). The bundle carries its own Qt and Python but links the host `glibc`, `libGL` and `libwayland-client`, so an older baseline is a genuinely different test and is not claimed. `docs/SUPPORTED_PLATFORMS.md` declares Debian 13 / MX 25.2 as the supported baseline rather than an older one |
| Software-only launch / render | **PASS** *(on the supported baseline, not an older one)* | `frozen_acceptance.sh` §2 `forced-software` |
| CLI success and failure | **PASS** | §3: the bundled recipe builds (`rc=0`, files written); a missing recipe exits non-zero and the report carries `recipe_read_error` |
| Relocation | **PASS** | §6, plus `build_linux.sh` step 9, which relocates the bundle during every build |

## Row 3 — Clean supported Windows machine / VM, no Python

| Required check | Result | Evidence |
| --- | --- | --- |
| Desktop `.exe` and CLI | **BLOCKED** | No Windows machine, VM or wine is available in this environment |
| All six workflows | **BLOCKED** | as above |
| Read-only installation | **BLOCKED** | as above |
| Relocation | **BLOCKED** | as above |
| Scaling | **BLOCKED** | as above |
| Save / recovery | **BLOCKED** | as above |

`build_windows.ps1` is kept step-for-step with `build_linux.sh` (isolated
venv, full suite, both executables, staged examples and docs, packaged
smoke, real bundled-recipe build, relocation check, ZIP + checksum +
provenance), but a pipeline that has never been executed is not a release
artifact. **No Windows artifact is produced or claimed by this release.**

## Row 4 — Real graphics environment on each OS

| Required check | Result | Evidence |
| --- | --- | --- |
| Actual GPU frame (Linux) | **PASS** | `session-wayland-100.png` — a shaded sphere with its selection cage, drawn through ModernGL on radeonsi and reported as such in the status bar; `interactive-session.txt` counts 91 051 lit pixels in the live viewport frame |
| Material / geometry correctness | **PASS** | `independent-export-verification.txt`: a parser sharing no code with the exporters reads 1 792 vertices / 3 150 faces, unit-length normals with full spread, the two materials distinct in the `.mtl` (`mat_body` 0.8/0.2/0.2, `mat_base` 0.2/0.4/0.9), per-object transforms baked (`base` centred at y = −1.2), and a GLB whose accessors stay inside its BIN chunk and whose geometry count matches the OBJ |
| Selected pose | **PASS** | smoke step `posed_export_carries_the_pose` exports the same rigged object at both ends of an action; `frozen_acceptance.sh` §8 re-reads both OBJs independently and requires the same vertex count with a non-trivial displacement (measured max shift ≈ 0.78) — i.e. the export writes the pose on screen, not the bind pose |
| Forced software | **PASS** | as Row 1; GPU-05 and RENDER-01 were both found by comparing the two paths on this hardware rather than by asserting a context could be created |
| Unavailable-GPU fallback and diagnostics | **PASS** | the smoke run probes for a GL context and records `skipped: no GL context` instead of inventing a parity number when none exists; **Help ▸ Diagnostics…** prints the active backend and the user-data paths, and the status bar names the backend in use |
| Real graphics environment on Windows | **BLOCKED** | no Windows machine available |

## Row 5 — Both packaged platforms: failure handling

| Required check | Result (Linux) | Evidence |
| --- | --- | --- |
| Payload hygiene | **PASS** | `frozen_acceptance.sh` §7 — no file in the shipped folder mentions the build root. This check found **PKG-05**: the build used to write its smoke manifest, stdout and stderr straight into the release folder |
| Corrupt / missing project resources | **PASS** | smoke step `damaged_project_is_reported_not_swallowed`: a corrupt file raises `ProjectFormatError: Malformed msgpack data…` and the document that was open survives intact; a missing file also fails rather than reporting success |
| Failed save / export | **PASS** | §5 runs the whole bundle from a `chmod -R a-w` install: the CLI and the full GUI workflow run, writing outside the install; the recipe engine reports per-export `error_records` rather than a bare traceback |
| Cancellation | **PASS** (suite) | the render dialog's cancel path keeps the frames already written — covered by the suite, not separately re-run inside the bundle |
| Restart / crash recovery | **PASS** | smoke step `autosave_snapshot_and_recovery`, executed in the frozen executable |
| Output validation | **PASS** | the recipe report's `manifest` records each export's status, size and version; §3 checks both the success and the failure shape; §8 validates exported geometry independently |
| Logs | **PASS** | the CLI writes a machine-readable JSON report with `warnings`, `errors` and `error_records`; the GUI's **Help ▸ Diagnostics…** prints backend and path diagnostics |
| All of the above on Windows | **BLOCKED** | no Windows machine available |

---

## Summary

| Gate | State |
| --- | --- |
| Linux x86-64 (Debian 13 / MX 25.2 KDE), reference hardware | complete — every required check executed and passing |
| Oldest declared Linux baseline | partially blocked: only the supported baseline exists here |
| Windows x86-64 | **BLOCKED — mandatory gate not met** |

Per the plan, the product is **not** labelled shippable while a mandatory
platform gate is pending. The Linux artifact is a complete, accepted beta
release; the Windows gate is outstanding and openly recorded as such in
`docs/RELEASE_NOTES.md`, `docs/SUPPORTED_PLATFORMS.md`,
`docs/CAPABILITY_MATRIX.md` and `docs/QUICK_START.md`.
