# 3D MASTER:2005 — quick start

Version 0.2.0b1 (beta). Nothing here needs Python, pip, a terminal or a
checkout: the bundle carries its own runtime.

## Linux (MX 25.2 KDE / Debian 13, x86-64)

1. Unpack the archive anywhere you can write — your home folder is fine:

   ```
   tar -xzf 3D-MASTER-2005-Beta-0.2.0b1-linux-x86_64.tar.gz
   cd "3D MASTER 2005 Beta"
   ```

2. Start the application:

   ```
   ./3D-MASTER-2005.sh
   ```

   The launcher picks your session's normal graphics route. If the window
   does not appear, or drawing looks wrong, two fallbacks are built in:

   | Command | Route |
   | --- | --- |
   | `./3D-MASTER-2005.sh` | native session (Wayland, or X11 if that is what you run) |
   | `./3D-MASTER-2005.sh --xcb` | xcb / XWayland compatibility route |
   | `./3D-MASTER-2005.sh --software` | software rendering, no GPU used |

   The xcb route needs the system package `libxcb-cursor0`; the native
   Wayland route does not.

3. Run a recipe without opening the application:

   ```
   ./am3d-recipe --recipe examples/recipes/minimal.json --out ~/am3d-out
   ```

   It prints a JSON report, exits 0 on success and 1 on failure. Open the
   project it wrote with **File ▸ Open .am3d…**.

### Putting it in the application menu

Create `~/.local/share/applications/3d-master-2005.desktop`, replacing the
path with wherever you unpacked the folder:

```ini
[Desktop Entry]
Type=Application
Name=3D MASTER:2005
Exec=/home/YOU/3D MASTER 2005 Beta/3D-MASTER-2005.sh
Path=/home/YOU/3D MASTER 2005 Beta
Icon=/home/YOU/3D MASTER 2005 Beta/_internal/assets/icon.png
Categories=Graphics;3DGraphics;
Terminal=false
```

Then run `update-desktop-database ~/.local/share/applications` (or just log
out and back in).

## Windows (x86-64)

No Windows bundle is included in this release — see "Known limitations"
below. The build definition (`build_windows.ps1`) is in the source tree and
produces the same two executables (`3D MASTER 2005.exe` and
`am3d-recipe.exe`) when run on a Windows machine.

## Your first five minutes

1. **Home** appears first: start an empty project, or open one of the
   examples in `examples/`.
2. **Create ▸ Sphere** puts an object in the scene. Drag with the left or
   middle mouse button to orbit, **Shift + middle** to pan, and the wheel
   to zoom.
3. Click the object in the viewport or the outliner to select it. Its
   control points appear; drag one to change the shape. **Ctrl+Z** undoes
   anything.
4. **Rig ▸ Add Bone**, then **Rig ▸ Add Child Bone**, then **Rig ▸ Bind
   Geometry to Skeleton**. Pose a bone in the viewport and the surface
   follows.
5. In the **Animate** workspace, create an action, move a bone, press
   **I** to key it, move the playhead, key again, and press play.
6. **File ▸ Render Image / Sequence… (F12)** writes a finished PNG (or a
   numbered sequence) wherever you choose. **File ▸ Export OBJ / GLB**
   writes geometry for another program.

Full details of every menu, panel and shortcut: `docs/USER_GUIDE.md`.
What each surface can and cannot do: `docs/CAPABILITY_MATRIX.md`.

## Where your files go

| What | Where |
| --- | --- |
| Projects, renders, exports | wherever you save them |
| Preferences | `~/.config/3DMASTER2005/app.conf` (Linux) |
| Autosave / crash recovery | `~/.local/share/3DMASTER2005/3D MASTER 2005/` (Linux) |
| Logs and diagnostics | **Help ▸ Diagnostics…** prints the exact paths in use |

Nothing is written inside the unpacked application folder, so it can live
in a read-only location.

## If something goes wrong

- **The window never appears.** Try `./3D-MASTER-2005.sh --xcb`, then
  `--software`. If the xcb route reports "could not connect to display",
  your session did not pass `XAUTHORITY` through — launch it from a normal
  desktop terminal rather than from a service or `sudo`.
- **The viewport is blank or the render looks wrong.** Use
  `./3D-MASTER-2005.sh --software`; it uses no GPU at all. Please report
  the output of **Help ▸ Diagnostics…** with the problem.
- **The application was killed with unsaved work.** Start it again: Home
  lists the recovered documents by name, original location and time, and
  you pick which one to restore. Recovering one does not delete the others,
  and it does not overwrite your last saved file until you save.

## Known limitations in this beta

- **No Windows artifact in this release.** No Windows machine was
  available to build or test one, and an untested build is not shipped.
- OBJ and GLB exports are static, tessellated snapshots of one pose. They
  carry no skeleton, weights or keyframes; export animation as a rendered
  frame sequence.
- Open construction splines are curves, not surfaces: they draw and export
  no triangles by design.
- No video encoding, importing of third-party 3D formats, IK, or weight
  painting. See `docs/CAPABILITY_MATRIX.md` for the complete list.
