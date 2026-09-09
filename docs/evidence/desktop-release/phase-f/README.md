# Phase F — Windows acceptance

**Nothing in this directory has been executed.** No Windows machine, VM or
wine was available on the machine these scripts were written on. They are
harness code awaiting a Windows host; until they have been run, every
Windows row in `../phase-e/acceptance-matrix.md` stays **BLOCKED**, and no
Windows artifact is produced or claimed.

| File | What it will run |
| --- | --- |
| `frozen_acceptance.ps1` | the frozen bundle under a scrubbed environment (no Python, no venv on `PATH`) — the twin of `../phase-e/frozen_acceptance.sh` |
| `export_check.ps1` | the frozen `am3d-recipe.exe` writes OBJ/GLB; `../phase-e/verify_exports.py` reads them back with no shared code |
| `../phase-e/interactive_session_check.py` | runs unmodified on Windows — it drives a real `MainWindow` and grabs the window with `QWidget.grab()`, neither of which is platform-specific |

`frozen_acceptance.ps1` sections 1–8 mirror the Linux script one for one.
Sections 9–11 have no Linux counterpart:

- **§9 long paths** — a `>260`-character output directory. Windows fails
  these with `ERROR_PATH_NOT_FOUND` unless the process is long-path aware,
  and a user reaches one just by nesting projects inside OneDrive.
- **§10 drive-relative paths** — `C:outside_file` resolves against the
  per-drive current directory, so it can land anywhere. The escape check was
  fixed for this (ENV-03a) but has only ever run on Linux, where the syntax
  is meaningless.
- **§11 user-data location** — the Windows counterpart of PATH-01: autosaves
  must live under `%LOCALAPPDATA%` in this application's own folder, not
  beside the executable (unwritable in a `Program Files` install) and not in
  the generic `PySideApp` directory Qt gives an unnamed application.

Two differences from the Linux harness are deliberate and are *not* silent
substitutions:

- `LIBGL_ALWAYS_SOFTWARE` is a Mesa variable and does nothing on Windows.
  §2 uses `QT_OPENGL=software` instead, which is a different thing — a
  machine with no usable GL driver — and is labelled as such. The
  application's own forced-software renderer has no environment variable; it
  is exercised by the packaged smoke run in §1.
- The Wayland/xcb route pair does not exist on Windows; `qwindows.dll` is the
  only platform plugin, and `build_windows.ps1` step 5 hard-checks that it
  and `qoffscreen.dll` are in the bundle.

`-SkipInteractive` exists for a CI runner with no desktop session. It reports
the skipped launches as **SKIP**, never as PASS.

See `../../../WINDOWS_ACCEPTANCE_PLAN.md` for which environment can certify
which matrix row.
