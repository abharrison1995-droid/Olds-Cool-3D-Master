"""Viewport widget: camera-driven render of every object in the project.

Replaces the original orbit-only viewport internals.  A QWidget composites
the software-rendered toon frame with QPainter overlays (grid floor,
wireframe, selection highlight) — no forced OpenGL, so it stays headless-
testable.  Navigation is Blender-style: MMB orbit, Shift+MMB pan, wheel
zoom (LMB drag also orbits for A:M familiarity); LMB click ray-casts into
the tessellated meshes to select an object.

Phase 4 tool overlays (see :mod:`am3d.ui.gizmos`,
:mod:`am3d.ui.tools_spline`, :mod:`am3d.ui.tools_bone`):

* Transform gizmo on the selected object (W translate, E rotate,
  R modal rotate-grab, X off; toolbar buttons switch mode too).
* Blender-style modal grab: G translate / R rotate / S scale in the view
  plane, LMB or Enter confirms, Esc cancels.
* Model workspace: spline CP handles — click selects, drag moves,
  A / double-click inserts, X / Delete removes (degree-guarded).
* Rig workspace: bones drawn from the FK pose; dragging the rotate ring
  on the selected bone sets its pose rotation.

Grid / wireframe toggles moved to Shift+G / Shift+W.
"""

from __future__ import annotations

import numpy as np

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QImage, QMouseEvent, QPainter, QPen
from PySide6.QtWidgets import QWidget

from am3d.core.mathutil import rot_matrix
from . import gizmos, tools_bone, tools_spline
from .camera import Camera
from .picking import pick_object

# Cached GPU renderer (lazy import; tried once, cached for all future calls).
_gpu_render_frame = None
def _get_gpu_render():
    global _gpu_render_frame
    if _gpu_render_frame is None:
        try:
            from am3d.gpu import render_frame
            _gpu_render_frame = render_frame
        except Exception:
            _gpu_render_frame = False
    return _gpu_render_frame if _gpu_render_frame is not False else None

# View-preset hotkeys (numpad style) mapped in keyPressEvent.
_PRESET_KEYS = {
    Qt.Key_1: "front",
    Qt.Key_3: "side",
    Qt.Key_7: "top",
    Qt.Key_0: "perspective",
}


class Viewport(QWidget):
    """QWidget displaying the current project's rendered scene.

    Uses the software toon renderer by default; picks up the GPU renderer
    when available.  Emits :attr:`selection_changed` when click-picking
    selects (or deselects) an object.
    """

    selection_changed = Signal(str, int)

    def __init__(self, main_window):
        super().__init__()
        self.main = main_window
        self.setMinimumSize(320, 240)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        self.camera = Camera(yaw=0.0, pitch=15.0, distance=3.5)
        self.show_grid = True
        self.show_wireframe = False
        self._selected = None          # (name, index) or None

        # Phase 4 tool state
        self.gizmo_mode = None         # None | "translate"|"rotate"|"scale"
        self._selected_cp = None       # (spline_name, index) or None
        self._drag = None              # active gizmo/CP/bone drag dict
        self._modal = None             # G/R/S modal grab dict

        self._last_mouse = None
        self._press_pos = None
        self._meshes = None            # tessellation cache (name -> MeshData)
        self._dirty = True
        self._frame = None

        # Throttle re-renders to ~30 fps
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._render)
        self._timer.start(33)

    # -- selection --------------------------------------------------------
    @property
    def selected(self):
        """Currently selected ``(object_name, index)`` or None."""
        return self._selected

    def set_selected(self, name):
        """Select an object by name (None clears); emits selection_changed."""
        if name is None:
            sel = None
        else:
            names = list(self.main.session.project.objects)
            if name not in names:
                raise KeyError(f"no such object: {name!r}")
            sel = (name, names.index(name))
        if sel != self._selected:
            self._selected = sel
            n, i = sel if sel is not None else ("", -1)
            self.selection_changed.emit(n, i)
            self.update()

    # -- scheduling ---------------------------------------------------------
    def refresh(self):
        """Project data changed: drop the tessellation cache, re-render."""
        self._meshes = None
        self._dirty = True
        if not self._timer.isActive():
            self._timer.start(10)

    def _schedule_render(self):
        """Camera-only change: re-render but keep the tessellation cache."""
        self._dirty = True
        if not self._timer.isActive():
            self._timer.start(10)

    def _orbit_drag(self, dx, dy):
        self.camera.orbit(dx * 0.5, dy * 0.5)
        self._schedule_render()

    # -- tessellation ---------------------------------------------------------
    def _scene_meshes(self):
        """Tessellated world-space meshes, cached until refresh().

        Object transforms are baked here (per object) so both rendering and
        picking see the same world-space geometry.  Objects whose skeleton
        has CP weights and a current pose are skinned (smartskin) before
        tessellation; the cache is dropped on every refresh(), i.e. on any
        frame/pose change, so deform only recomputes then.
        """
        if self._meshes is None:
            from am3d.core.rigging import deform_object, fk_pose
            from am3d.renderer.tessellate import MeshData, tessellate_object
            session = self.main.session
            proj = session.project
            posed = getattr(session, "posed_transforms", {}) or {}
            out = {}
            for name, obj in proj.objects.items():
                if not getattr(obj, "visible", True):
                    continue                # hidden in the outliner
                source = obj
                rig = getattr(proj, "skeletons", {}).get(name)
                if rig and name in posed and any(
                        b.cp_weights for b in rig.values()):
                    bones = list(rig.values())
                    rest = fk_pose(bones)
                    source = deform_object(obj, bones, posed[name], rest)
                mesh = tessellate_object(source)
                m = np.asarray(getattr(obj, "transform", np.eye(4)),
                               dtype=np.float64).reshape(4, 4)
                if len(mesh.vertices) and not np.allclose(m, np.eye(4)):
                    rot = m[:3, :3]
                    verts = mesh.vertices @ rot.T + m[:3, 3]
                    normals = mesh.normals @ rot.T
                    n_len = np.linalg.norm(normals, axis=1, keepdims=True)
                    normals = normals / np.maximum(n_len, 1e-12)
                    mesh = MeshData(verts, mesh.indices, normals=normals,
                                    uvs=mesh.uvs, name=mesh.name)
                out[name] = mesh
            self._meshes = out
        return self._meshes

    # -- painting ---------------------------------------------------------
    def paintEvent(self, event):
        if self._frame is None:
            self._schedule_render()
        painter = QPainter(self)
        if self._frame is not None:
            h, w = self._frame.shape[:2]
            # Frames are float RGBA 0..1; convert to uint8 once, here at
            # the QImage edge.  Keep the bytes buffer alive on self so the
            # QImage does not dangle past this call.
            data = (np.clip(self._frame, 0.0, 1.0) * 255).astype(np.uint8)
            self._frame_bytes = data.tobytes()
            img = QImage(self._frame_bytes, w, h, QImage.Format_RGBA8888)
            painter.drawImage(self.rect(), img)
        else:
            painter.fillRect(self.rect(), Qt.darkGray)
            painter.setPen(Qt.white)
            painter.drawText(self.rect(), Qt.AlignCenter, "3D MASTER:2005")
        self._draw_overlays(painter)

    def _project(self, points):
        """World points -> widget pixels; None when the widget is empty."""
        w, h = self.width(), self.height()
        if w < 2 or h < 2:
            return None
        return self.camera.world_to_screen(points, w, h)

    def _draw_overlays(self, painter):
        if self.show_grid:
            self._draw_grid(painter)
        if self.show_wireframe:
            self._draw_wireframe(painter)
        if self._selected is not None:
            self._draw_selection(painter)
        self._draw_tool_overlays(painter)

    # -- tool overlays (Phase 4) ---------------------------------------------
    def _workspace(self):
        return getattr(self.main, "current_workspace", "Layout")

    def _context(self):
        return getattr(self.main, "current_context", ("", "", ""))

    def _selected_object(self):
        if self._selected is None:
            return None
        return self.main.session.project.objects.get(self._selected[0])

    def _draw_tool_overlays(self, painter):
        ws = self._workspace()
        if ws in ("Rig", "Animate"):
            self._draw_bones(painter)
        if ws == "Rig":
            return
        if ws == "Model":
            self._draw_cps(painter)
        if self.gizmo_mode and self._selected is not None:
            obj = self._selected_object()
            if obj is not None:
                origin = obj.transform[:3, 3]
                self._draw_handles(painter, gizmos.handle_geometry(
                    self.camera, self.width(), self.height(),
                    origin, self.gizmo_mode))

    _AXIS_COLORS = {"x": QColor(230, 70, 70), "y": QColor(90, 200, 90),
                    "z": QColor(80, 120, 235), "xyz": QColor(240, 210, 90)}

    def _draw_handles(self, painter, handles, active=None):
        for handle_id, kind, polylines in handles:
            axis = handle_id[-1] if handle_id[-1] in "xyz" else "xyz"
            color = self._AXIS_COLORS.get(axis, QColor(255, 255, 255))
            pen = QPen(QColor(255, 255, 255)
                       if handle_id == active else color)
            pen.setWidth(3 if handle_id == active else 2)
            painter.setPen(pen)
            for pts in polylines:
                if kind == "center":
                    painter.drawRect(int(pts[0][0]) - 5, int(pts[0][1]) - 5,
                                     10, 10)
                else:
                    for i in range(len(pts) - 1):
                        painter.drawLine(int(pts[i][0]), int(pts[i][1]),
                                         int(pts[i + 1][0]),
                                         int(pts[i + 1][1]))

    def _draw_cps(self, painter):
        obj = self._selected_object()
        if obj is None:
            return
        positions = tools_spline.cp_screen_positions(
            obj, self.camera, self.width(), self.height())
        painter.setPen(QPen(QColor(200, 200, 200, 160)))
        for sname, spline in obj.splines.items():
            pts = [positions.get((sname, i)) for i in range(len(spline.cps))]
            seq = list(range(len(pts)))
            if spline.closed and len(pts) > 1:
                seq.append(0)
            for a, b in zip(seq, seq[1:]):
                if pts[a] and pts[b] and pts[a][2] and pts[b][2]:
                    painter.drawLine(int(pts[a][0]), int(pts[a][1]),
                                     int(pts[b][0]), int(pts[b][1]))
        for key, (x, y, valid) in positions.items():
            if not valid:
                continue
            if key == self._selected_cp:
                painter.setPen(QPen(QColor(255, 150, 40)))
            else:
                painter.setPen(QPen(QColor(255, 255, 255)))
            painter.drawRect(int(x) - 3, int(y) - 3, 6, 6)

    def _draw_bones(self, painter):
        proj = self.main.session.project
        pen = QPen(QColor(90, 200, 255, 220))
        pen.setWidth(2)
        sel_pen = QPen(QColor(255, 150, 40, 240))
        sel_pen.setWidth(3)
        kind, oname, iname = self._context()
        for name in proj.skeletons:
            for bname, (head, tail) in tools_bone.bone_endpoints(
                    self.main.session, name).items():
                self._draw_polyline(
                    painter, [head, tail],
                    sel_pen if (kind == "bone" and name == oname
                                and bname == iname) else pen)
        if kind == "bone" and oname in proj.skeletons:
            heads = tools_bone.bone_endpoints(self.main.session, oname)
            if iname in heads:
                self._draw_handles(painter, gizmos.handle_geometry(
                    self.camera, self.width(), self.height(),
                    heads[iname][0], "rotate",
                    size=gizmos.gizmo_size_world(
                        self.camera, heads[iname][0], self.height(),
                        size_px=50.0)))

    def _draw_polyline(self, painter, pts, pen):
        proj = self._project(pts)
        if proj is None:
            return
        xs, ys, valid = proj
        painter.setPen(pen)
        for i in range(len(pts) - 1):
            if valid[i] and valid[i + 1]:
                painter.drawLine(xs[i], ys[i], xs[i + 1], ys[i + 1])

    def _draw_grid(self, painter):
        g = 5
        minor = QPen(QColor(255, 255, 255, 40))
        axis = QPen(QColor(255, 255, 255, 90))
        for i in range(-g, g + 1):
            pen = axis if i == 0 else minor
            self._draw_polyline(
                painter, [(i, 0, -g), (i, 0, g)], pen)
            self._draw_polyline(
                painter, [(-g, 0, i), (g, 0, i)], pen)

    def _draw_wireframe(self, painter):
        mesh = self._merged
        if mesh is None or len(mesh.indices) == 0:
            return
        proj = self._project(mesh.vertices)
        if proj is None:
            return
        xs, ys, valid = proj
        painter.setPen(QPen(QColor(30, 30, 30, 120)))
        w, h = self.width(), self.height()
        on = valid & (xs >= -w) & (xs <= 2 * w) & (ys >= -h) & (ys <= 2 * h)
        edges = mesh.indices[:, [0, 1, 1, 2, 2, 0]].reshape(-1, 2)
        for a, b in edges:
            if on[a] and on[b]:
                painter.drawLine(xs[a], ys[a], xs[b], ys[b])

    def _draw_selection(self, painter):
        name, _ = self._selected
        mesh = self._scene_meshes().get(name)
        if mesh is None or len(mesh.vertices) == 0:
            return
        lo = mesh.vertices.min(axis=0)
        hi = mesh.vertices.max(axis=0)
        corners = np.array([[x, y, z]
                            for x in (lo[0], hi[0])
                            for y in (lo[1], hi[1])
                            for z in (lo[2], hi[2])])
        edges = [(0, 1), (0, 2), (0, 4), (1, 3), (1, 5), (2, 3),
                 (2, 6), (3, 7), (4, 5), (4, 6), (5, 7), (6, 7)]
        pen = QPen(QColor(255, 150, 40, 220))
        pen.setWidth(2)
        for a, b in edges:
            self._draw_polyline(painter, [corners[a], corners[b]], pen)

    # -- rendering ---------------------------------------------------------
    def resizeEvent(self, event):
        self._dirty = True
        super().resizeEvent(event)

    @property
    def _merged(self):
        meshes = [m for m in self._scene_meshes().values()
                  if len(m.vertices) and len(m.indices)]
        if not meshes:
            return None
        return self._merge_meshes(meshes)

    def _render(self):
        if not self._dirty:
            return
        W = max(self.width(), 32)
        H = max(self.height(), 32)

        try:
            mesh = self._merged
            if mesh is None:
                self._frame = None
                return

            view = self.camera.view_matrix()
            gpu_render = _get_gpu_render()
            rgba = None
            if gpu_render is not None:
                try:
                    rgba = gpu_render(mesh, camera=view, size=(W, H))
                except Exception:
                    rgba = None

            if rgba is None:
                rgba = self._render_toon(mesh, W, H)

            if rgba is not None:
                if rgba.shape[0] != H or rgba.shape[1] != W:
                    from am3d.renderer.materials import _resize
                    rgba = _resize(rgba, H, W)
                # Renderers return float RGBA 0..1; keep float here and
                # convert to uint8 once, in paintEvent.
                self._frame = np.asarray(rgba, dtype=np.float32)
        except Exception:
            self._frame = None
        self._dirty = False
        self.update()

    def _render_toon(self, mesh, W, H):
        """Toon-render *mesh* through the orbit camera.

        The software rasterizer is orthographic and auto-fits the mesh, so
        the world mesh is first transformed into camera space, then two
        anchor vertices pin the view volume to the camera frustum — this
        makes zoom (distance) and pan actually visible.
        """
        from am3d.renderer.tessellate import MeshData
        from am3d.renderer.toon import toon_render_view

        view = self.camera.view_matrix()
        rot = view[:3, :3]
        v = mesh.vertices @ rot.T + view[:3, 3]
        n = mesh.normals @ rot.T
        v[:, 2] *= -1.0                     # rasterizer: nearer = smaller z
        n[:, 2] *= -1.0
        v[:, 0] *= H / W                    # correct for the square canvas

        d = self.camera.distance * 1.2
        z_mid = float(v[:, 2].mean()) if len(v) else 0.0
        anchors = np.array([[-d, -d, z_mid], [d, d, z_mid]])
        pinned = MeshData(np.vstack([v, anchors]), mesh.indices,
                          normals=np.vstack([n, np.zeros((2, 3))]))
        settings = getattr(self.main.session.project, "render_settings",
                           {}) or {}
        toon = bool(settings.get("toon", True))
        return toon_render_view(pinned, size=max(W, H),
                                supersample=int(settings.get("supersample", 2)),
                                bands=4 if toon else 64,
                                ink=toon)

    @staticmethod
    def _merge_meshes(meshes):
        """Combine multiple MeshData into one so all meshes are rendered."""
        if len(meshes) == 1:
            return meshes[0]
        from am3d.renderer.tessellate import MeshData
        verts, normals, indices = [], [], []
        offset = 0
        for m in meshes:
            v = np.asarray(m.vertices, dtype=np.float64)
            idx = np.asarray(m.indices, dtype=np.int64)
            if len(v) == 0 or len(idx) == 0:
                continue
            n = np.asarray(m.normals, dtype=np.float64)
            if len(n) != len(v):
                n = np.zeros_like(v)
            verts.append(v)
            normals.append(n)
            indices.append(idx + offset)
            offset += len(v)
        if not verts:
            return None
        return MeshData(np.vstack(verts), np.vstack(indices),
                        np.vstack(normals))

    # -- interaction ---------------------------------------------------------
    def _push(self, command):
        """Commit a command through the main window's undo stack."""
        push = getattr(self.main, "push_command", None)
        if push is not None:
            push(command)
        else:
            command.redo()
            self.refresh()

    def mousePressEvent(self, event: QMouseEvent):
        self._last_mouse = (event.position().x(), event.position().y())
        if event.button() == Qt.LeftButton:
            if self._modal is not None:
                self._confirm_modal()
                return
            if self._begin_tool_drag(*self._last_mouse):
                return
            self._press_pos = self._last_mouse
        self.setCursor(Qt.ClosedHandCursor)

    def mouseReleaseEvent(self, event):
        pos = (event.position().x(), event.position().y())
        if self._drag is not None and event.button() == Qt.LeftButton:
            self._end_tool_drag()
        elif (event.button() == Qt.LeftButton and self._press_pos is not None
                and abs(pos[0] - self._press_pos[0]) < 4
                and abs(pos[1] - self._press_pos[1]) < 4):
            self._pick(*pos)
        self._press_pos = None
        self._last_mouse = None
        self.setCursor(Qt.ArrowCursor)

    def mouseDoubleClickEvent(self, event):
        if (event.button() == Qt.LeftButton
                and self._workspace() == "Model"):
            self._add_cp()
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._modal is not None:
            self._update_modal(event.position().x(), event.position().y())
            return
        if self._drag is not None:
            self._update_tool_drag(event.position().x(),
                                   event.position().y())
            return
        if self._last_mouse is None:
            return
        dx = event.position().x() - self._last_mouse[0]
        dy = event.position().y() - self._last_mouse[1]
        self._last_mouse = (event.position().x(), event.position().y())
        buttons = event.buttons()
        if buttons & Qt.MiddleButton:
            if event.modifiers() & Qt.ShiftModifier:
                self.camera.pan(dx, dy, viewport_height=self.height())
            else:
                self._orbit_drag(dx, dy)
        elif buttons & Qt.LeftButton:
            self._orbit_drag(dx, dy)
        else:
            return
        self._schedule_render()

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        self.camera.zoom(1.0 - delta * 0.001)
        self._schedule_render()

    def keyPressEvent(self, event):
        key = event.key()
        shift = bool(event.modifiers() & Qt.ShiftModifier)
        if self._modal is not None:
            if key in (Qt.Key_Escape,):
                self._cancel_modal()
            elif key in (Qt.Key_Return, Qt.Key_Enter):
                self._confirm_modal()
            else:
                super().keyPressEvent(event)
            return
        if key in _PRESET_KEYS:
            self.camera.set_view(_PRESET_KEYS[key])
            self._schedule_render()
        elif key == Qt.Key_G and shift:
            self.show_grid = not self.show_grid
            self.update()
        elif key == Qt.Key_W and shift:
            self.show_wireframe = not self.show_wireframe
            self.update()
        elif key == Qt.Key_W:
            self.set_gizmo_mode("translate")
        elif key == Qt.Key_E:
            self.set_gizmo_mode("rotate")
        elif key == Qt.Key_X or key == Qt.Key_Delete:
            if not self._delete_selected_cp() and key == Qt.Key_X:
                self.set_gizmo_mode(None)
        elif key == Qt.Key_A and self._workspace() == "Model":
            self._add_cp()
        elif key in (Qt.Key_G, Qt.Key_R, Qt.Key_S) and \
                self._selected is not None:
            self._begin_modal({Qt.Key_G: "translate", Qt.Key_R: "rotate",
                               Qt.Key_S: "scale"}[key])
        else:
            super().keyPressEvent(event)

    # -- picking ---------------------------------------------------------
    def _pick(self, px, py):
        meshes = {n: m for n, m in self._scene_meshes().items()
                  if len(m.vertices) and len(m.indices)}
        origin, direction = self.camera.view_ray(
            px, py, self.width(), self.height())
        name = pick_object(meshes, origin, direction)
        if name is None:
            if self._selected is not None:
                self._selected = None
                self.selection_changed.emit("", -1)
                self.update()
        else:
            self.set_selected(name)

    # -- gizmo / tool drags (Phase 4) -----------------------------------------
    def set_gizmo_mode(self, mode):
        """Set the gizmo mode (None / translate / rotate / scale)."""
        if mode not in gizmos.MODES:
            mode = None
        if mode != self.gizmo_mode:
            self.gizmo_mode = mode
            hook = getattr(self.main, "_gizmo_mode_changed", None)
            if hook is not None:
                hook(mode)
            self.update()

    def _gizmo_hit(self, px, py):
        """Handle id under the cursor for the current gizmo, or None."""
        obj = self._selected_object()
        if obj is None or not self.gizmo_mode:
            return None
        return gizmos.hit_test(self.camera, self.width(), self.height(),
                               obj.transform[:3, 3], self.gizmo_mode,
                               px, py)

    def _bone_context(self):
        """(object_name, bone_name) when a bone is selected in Rig."""
        if self._workspace() != "Rig":
            return None, None
        kind, oname, iname = self._context()
        if kind != "bone":
            return None, None
        return oname, iname

    def _begin_tool_drag(self, px, py):
        """Try to start a CP / bone / gizmo drag; True when one started."""
        from .operators import (
            MoveCPCommand, PoseBoneCommand, SetObjectTransformCommand,
        )
        obj = self._selected_object()
        # Model workspace: spline CP handles win over the object gizmo.
        if self._workspace() == "Model" and obj is not None:
            hit = tools_spline.hit_cp(obj, self.camera, self.width(),
                                      self.height(), px, py)
            if hit is not None:
                self._selected_cp = hit
                spline = obj.splines[hit[0]]
                self._drag = {
                    "command": MoveCPCommand,
                    "obj": obj, "hit": hit,
                    "before": spline.cps[hit[1]].position.copy(),
                }
                self.update()
                return True
            self._selected_cp = None
        # Rig workspace: rotate ring on the selected bone.
        oname, bname = self._bone_context()
        if oname is not None:
            heads = tools_bone.bone_endpoints(self.main.session, oname)
            if bname in heads:
                head = heads[bname][0]
                size = gizmos.gizmo_size_world(
                    self.camera, head, self.height(), size_px=50.0)
                handle = gizmos.hit_test(
                    self.camera, self.width(), self.height(),
                    head, "rotate", px, py, size=size)
                if handle is not None:
                    pose = self.main.session.poses.get(oname, {})
                    self._drag = {
                        "command": PoseBoneCommand,
                        "bone": (oname, bname), "handle": handle,
                        "origin": head.copy(), "start": (px, py),
                        "before": (None if pose.get(bname) is None
                                   else pose[bname].copy()),
                    }
                    return True
        # Object transform gizmo.
        handle = self._gizmo_hit(px, py)
        if handle is not None:
            self._drag = {
                "command": SetObjectTransformCommand,
                "obj": obj, "handle": handle,
                "origin": obj.transform[:3, 3].copy(),
                "start": (px, py),
                "before": obj.transform.copy(),
            }
            return True
        return False

    def _update_tool_drag(self, px, py):
        d = self._drag
        w, h = self.width(), self.height()
        if d["command"] is not None and "hit" in d:
            obj, (sname, index) = d["obj"], d["hit"]
            world = tools_spline.spline_world_points(
                obj, obj.splines[sname])[index]
            hit_world = tools_spline.cp_ray_plane(
                self.camera, w, h, px, py, world)
            d["hit_pos"] = tools_spline.world_to_object(obj, hit_world)
            obj.splines[sname].cps[index].position = d["hit_pos"]
        elif "bone" in d:
            axis = gizmos.AXES[d["handle"][-1]]
            angle = gizmos.rotate_drag_angle(
                self.camera, w, h, d["origin"], axis, d["start"], (px, py))
            base = np.eye(3) if d["before"] is None else d["before"]
            rot = rot_matrix(axis, angle) @ base
            self.main.session.pose_bone(d["bone"][0], d["bone"][1], rot)
            self.main.session.apply_pose(d["bone"][0])
        else:
            obj, handle = d["obj"], d["handle"]
            dx = px - d["start"][0]
            dy = py - d["start"][1]
            axis = gizmos.AXES[handle[-1]]
            t = d["before"].copy()
            o = d["origin"]
            to_origin = np.eye(4)
            to_origin[:3, 3] = o
            back = np.eye(4)
            back[:3, 3] = -o
            if handle.startswith("t"):
                t[:3, 3] = d["before"][:3, 3] + gizmos.axis_drag_delta(
                    self.camera, w, h, o, axis, dx, dy)
            elif handle.startswith("r"):
                angle = gizmos.rotate_drag_angle(
                    self.camera, w, h, o, axis, d["start"], (px, py))
                rot = np.eye(4)
                rot[:3, :3] = rot_matrix(axis, angle)
                t = to_origin @ rot @ back @ d["before"]
            else:                                    # scale
                factor = gizmos.scale_drag_factor(
                    self.camera, w, h, o, axis, dx, dy,
                    uniform=(handle == "sxyz"))
                scl = np.diag([factor[0], factor[1], factor[2], 1.0])
                t = to_origin @ scl @ back @ d["before"]
            obj.transform = t
        self.refresh()

    def _end_tool_drag(self):
        d = self._drag
        self._drag = None
        session = self.main.session
        if "hit" in d:
            obj, (sname, index) = d["obj"], d["hit"]
            after = obj.splines[sname].cps[index].position
            if np.allclose(after, d["before"]):
                self.refresh()
                return
            self._push(d["command"](session, obj.name, sname, index,
                                    d["before"], after))
        elif "bone" in d:
            oname, bname = d["bone"]
            after = session.poses.get(oname, {}).get(bname)
            if after is None:
                return
            if d["before"] is not None and np.allclose(after, d["before"]):
                self.update()
                return
            self._push(d["command"](session, oname, bname,
                                    d["before"], after))
            hook = getattr(self.main, "_auto_key", None)
            if hook is not None:
                hook(oname, bname)
        else:
            obj = d["obj"]
            if np.allclose(obj.transform, d["before"]):
                self.refresh()
                return
            self._push(d["command"](session, obj.name,
                                    d["before"], obj.transform))

    # -- modal grab (G/R/S) -----------------------------------------------------
    def _begin_modal(self, kind):
        obj = self._selected_object()
        if obj is None:
            return
        self._modal = {"kind": kind, "obj": obj,
                       "before": obj.transform.copy()}
        self.setCursor(Qt.BlankCursor)
        self.update()

    def _update_modal(self, px, py):
        m = self._modal
        dx, dy = 0.0, 0.0
        if self._last_mouse is not None:
            dx = px - self._last_mouse[0]
            dy = py - self._last_mouse[1]
        self._last_mouse = (px, py)
        obj = m["obj"]
        origin = obj.transform[:3, 3].copy()
        to_origin = np.eye(4)
        to_origin[:3, 3] = origin
        back = np.eye(4)
        back[:3, 3] = -origin
        if m["kind"] == "translate":
            obj.transform[:3, 3] += gizmos.view_plane_delta(
                self.camera, self.height(), origin, dx, dy)
        elif m["kind"] == "rotate":
            rot = np.eye(4)
            rot[:3, :3] = rot_matrix(self.camera.forward, -dx * 0.01)
            obj.transform = to_origin @ rot @ back @ obj.transform
        else:
            f = 1.0 + dx * 0.005
            scl = np.diag([f, f, f, 1.0])
            obj.transform = to_origin @ scl @ back @ obj.transform
        self.refresh()

    def _confirm_modal(self):
        from .operators import SetObjectTransformCommand
        m = self._modal
        self._modal = None
        self._last_mouse = None
        self.setCursor(Qt.ArrowCursor)
        if not np.allclose(m["obj"].transform, m["before"]):
            self._push(SetObjectTransformCommand(
                self.main.session, m["obj"].name,
                m["before"], m["obj"].transform))
        self.refresh()

    def _cancel_modal(self):
        m = self._modal
        self._modal = None
        self._last_mouse = None
        self.setCursor(Qt.ArrowCursor)
        m["obj"].transform = m["before"]
        self.refresh()

    # -- spline CP tools (Model workspace) -------------------------------------
    def _add_cp(self):
        """Insert a CP after the selected one (or the nearest), undoable."""
        from .operators import InsertCPCommand
        obj = self._selected_object()
        if obj is None or self._workspace() != "Model" or not obj.splines:
            return
        if self._selected_cp is not None:
            sname, index = self._selected_cp
        else:
            sname = next(iter(obj.splines))
            index = len(obj.splines[sname].cps) - 1
        spline = obj.splines[sname]
        new_index = tools_spline.insert_cp_after(spline, index)
        cp = spline.cps[new_index]
        spline.cps.pop(new_index)                # command re-inserts it
        self._push(InsertCPCommand(self.main.session, obj.name, sname,
                                   new_index, cp))
        self._selected_cp = (sname, new_index)

    def _delete_selected_cp(self):
        """Remove the selected CP (degree-guarded); True when handled."""
        from .operators import RemoveCPCommand
        obj = self._selected_object()
        if (self._workspace() != "Model" or obj is None
                or self._selected_cp is None):
            return False
        sname, index = self._selected_cp
        spline = obj.splines.get(sname)
        if spline is None or not tools_spline.can_remove_cp(spline, index):
            self._selected_cp = None
            return False
        self._push(RemoveCPCommand(self.main.session, obj.name,
                                   sname, index))
        self._selected_cp = None
        return True
