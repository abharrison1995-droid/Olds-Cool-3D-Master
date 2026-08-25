"""Smoke tests for the UI (requires a display / PySide6).

The tests create a QApplication and MainWindow, exercise the mode switches,
and verify docks are visible/hidden correctly — then exit.
"""

from __future__ import annotations

import importlib
import sys


def test_ui_import():
    """The UI modules import cleanly."""
    import am3d.ui.app
    import am3d.ui.viewport
    import am3d.ui.timeline
    import am3d.ui.object_panel
    import am3d.ui.properties


def test_main_window_smoke():
    """Create a QApplication and MainWindow, verify mode switching.

    This test runs only if a display is available (PySide6 can create
    a QApplication).  On headless CI it is skipped.
    """
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
    except Exception:
        import pytest
        pytest.skip("PySide6 not available or no display")

    from am3d.ui.app import MainWindow
    win = MainWindow()
    win.show_editor()
    win.show()
    # Outliner + properties are visible in every editing mode.
    for mode in ("object", "segment", "material"):
        win.set_mode(mode)
        assert win.current_mode == mode
        assert win.object_dock.isVisible()
        assert win.properties_dock.isVisible()
        assert not win.timeline_dock.isVisible()

    win.set_mode("choreography")
    assert win.current_mode == "choreography"
    # Animate keeps the outliner (bone selection) plus the dope sheet.
    assert win.object_dock.isVisible()
    assert win.timeline_dock.isVisible()

    win.close()


def _make_main_window():
    """Create a MainWindow (skip when no display is available)."""
    import pytest
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
    except Exception:
        pytest.skip("PySide6 not available or no display")

    from am3d.ui.app import MainWindow
    win = MainWindow()
    _add_test_sphere(win)
    win.show_editor()
    win.set_mode("object")
    return win


def _add_test_sphere(win):
    """Add a test sphere to a MainWindow for tests that need it."""
    from am3d.recipes.primitives import build_primitive
    from am3d.core.project import Patch
    s = win.session
    s.create_object("sphere")
    for pname, net, du, dv in build_primitive(
            "sphere", dict(radius=0.8, sections=12, rings=8))["patches"]:
        s.get_object("sphere").patches.append(
            Patch(name=pname, splines=[], interior=net))
    s.create_material("base", color=(0.72, 0.75, 0.85))


def test_outliner_selection_sync():
    """Viewport selection highlights the outliner row and vice versa."""
    win = _make_main_window()
    try:
        win.object_dock.refresh()
        item = win.object_dock._find("object", "sphere", "")
        assert item is not None
        win.object_dock.tree.setCurrentItem(item)
        assert win.viewport.selected == ("sphere", 0)
        ctx = win.properties_dock._context
        assert ctx == ("object", "sphere", "")

        win.viewport.set_selected(None)
        assert win.object_dock.tree.currentItem() is None
    finally:
        win.viewport._timer.stop()
        win.close()


def test_outliner_visibility_checkbox():
    """Toggling the row checkbox flips Object3D.visible and re-renders."""
    from PySide6.QtCore import Qt
    win = _make_main_window()
    try:
        win.object_dock.refresh()
        find = lambda: win.object_dock._find("object", "sphere", "")
        find().setCheckState(0, Qt.Unchecked)
        assert not win.session.get_object("sphere").visible
        # data_changed rebuilt the tree; re-find the fresh row.
        find().setCheckState(0, Qt.Checked)
        assert win.session.get_object("sphere").visible
    finally:
        win.viewport._timer.stop()
        win.close()


def test_properties_object_transform_edit():
    """Editing a location spinbox rewrites Object3D.transform."""
    win = _make_main_window()
    try:
        win.properties_dock.set_context("object", "sphere", "")
        win.properties_dock.obj_loc.spins[0].setValue(2.5)
        import numpy as np
        m = win.session.get_object("sphere").transform
        assert np.isclose(m[0, 3], 2.5)
    finally:
        win.viewport._timer.stop()
        win.close()



def _make_viewport():
    """Create a Viewport with a minimal fake main window (skip headless)."""
    import pytest
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
    except Exception:
        pytest.skip("PySide6 not available or no display")

    from am3d.core.project import Project
    from am3d.ui.viewport import Viewport

    class _Session:
        project = Project()

    class _Main:
        session = _Session()

    return Viewport(_Main())


def test_viewport_merge_meshes_combines_all():
    """Viewport renders all meshes: merge keeps every vertex, offsets indices."""
    import numpy as np
    from am3d.renderer.tessellate import MeshData
    from am3d.ui.viewport import Viewport

    m1 = MeshData(np.zeros((3, 3)), np.array([[0, 1, 2]]), np.zeros((3, 3)))
    m2 = MeshData(np.ones((4, 3)), np.array([[0, 1, 2]]), np.zeros((4, 3)))
    merged = Viewport._merge_meshes([m1, m2])
    assert len(merged.vertices) == 7
    assert merged.indices[1].min() == 3  # second mesh indices offset
    single = Viewport._merge_meshes([m1])
    assert single is m1


def test_viewport_pan_translates_target():
    """Regression: panning must translate eye and target, not rotate."""
    import numpy as np
    vp = _make_viewport()
    try:
        m0 = vp.camera.view_matrix()
        vp.camera.pan(50, -25, viewport_height=480)
        m1 = vp.camera.view_matrix()
        # same orientation (no rotation from panning)...
        assert np.allclose(m0[:3, :3], m1[:3, :3])
        # ...but a different translation
        assert not np.allclose(m0[:3, 3], m1[:3, 3])
    finally:
        vp._timer.stop()
        vp.close()


def test_viewport_orbit_schedules_render():
    """Regression: orbit drag must schedule a re-render, not just set _dirty."""
    vp = _make_viewport()
    try:
        vp._timer.stop()
        vp._dirty = False
        vp._orbit_drag(10, 0)
        assert vp._dirty
        assert vp._timer.isActive()
    finally:
        vp._timer.stop()
        vp.close()


def test_viewport_tessellation_cache():
    """Tessellation is cached across camera moves; refresh() invalidates it."""
    vp = _make_viewport()
    try:
        vp._timer.stop()
        first = vp._scene_meshes()
        assert vp._scene_meshes() is first          # cache hit
        vp._schedule_render()                        # camera-only change
        assert vp._scene_meshes() is first          # still cached
        vp.refresh()                                 # data changed
        assert vp._scene_meshes() is not first      # cache dropped
    finally:
        vp._timer.stop()
        vp.close()


def test_viewport_selection_signal():
    """set_selected emits selection_changed with (name, index)."""
    vp = _make_viewport()
    try:
        vp.main.session.project.create_object("hero")
        seen = []
        vp.selection_changed.connect(lambda n, i: seen.append((n, i)))
        vp.set_selected("hero")
        assert vp.selected == ("hero", 0)
        assert seen == [("hero", 0)]
        vp.set_selected(None)
        assert vp.selected is None
        assert seen[-1] == ("", -1)
    finally:
        vp._timer.stop()
        vp.close()


def test_viewport_pick_selects_object():
    """Clicking the center of the view selects the object under the ray."""
    import numpy as np
    from am3d.renderer.tessellate import MeshData
    vp = _make_viewport()
    try:
        vp.resize(640, 480)
        vp.camera.set_view("front")
        c = np.array([[x, y, z] for x in (-.5, .5) for y in (-.5, .5)
                      for z in (-.5, .5)], dtype=np.float64)
        tris = np.array([
            [0, 2, 1], [1, 2, 3], [4, 5, 6], [5, 7, 6],
            [0, 1, 4], [1, 5, 4], [2, 6, 3], [3, 6, 7],
            [0, 4, 2], [2, 4, 6], [1, 3, 5], [3, 7, 5],
        ], dtype=np.int64)
        vp._meshes = {"hero": MeshData(c, tris, name="hero")}
        vp.main.session.project.create_object("hero")
        seen = []
        vp.selection_changed.connect(lambda n, i: seen.append((n, i)))
        vp._pick(320, 240)          # center of the view: hits the cube
        assert seen == [("hero", 0)]
        vp._pick(2, 2)              # corner: misses, clears selection
        assert seen[-1] == ("", -1)
        assert vp.selected is None
    finally:
        vp._timer.stop()
        vp.close()

# ---------------------------------------------------------------------------
# Phase 3: workspaces, tiled layout, theme, status bar.
# ---------------------------------------------------------------------------

def test_workspace_definitions_headless():
    """Workspace defs are Qt-free data covering all classic modes."""
    from am3d.ui.workspaces import (
        MODES, MODE_TO_WORKSPACE, WORKSPACE_NAMES, WORKSPACES,
        workspace_for_mode,
    )
    assert WORKSPACE_NAMES == ("Layout", "Model", "Rig", "Animate", "Render")
    # Every classic mode maps to exactly one workspace and back.
    assert set(MODE_TO_WORKSPACE) == set(MODES)
    assert workspace_for_mode("object").name == "Model"
    assert workspace_for_mode("segment").name == "Rig"
    assert workspace_for_mode("choreography").name == "Animate"
    assert workspace_for_mode("material").name == "Render"
    for ws in WORKSPACES.values():
        assert ws.mode in MODES
        assert ws.tool_hint


def test_workspace_layout_state_serialization():
    """Layout state dicts round-trip through JSON; bad input is safe."""
    from am3d.ui.workspaces import (
        deserialize_layout_state, serialize_layout_state,
    )
    states = {"Model": {"main": [700, 300], "right": [250, 400]},
              "Bogus": {"main": [1, 2]}}      # unknown name is dropped
    text = serialize_layout_state(states)
    out = deserialize_layout_state(text)
    assert out == {"Model": {"main": [700, 300], "right": [250, 400]}}
    assert deserialize_layout_state("not json") == {}
    assert deserialize_layout_state(None) == {}


def test_theme_file_loads():
    """The retro theme file exists, parses as text, and applies."""
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
    except Exception:
        import pytest
        pytest.skip("PySide6 not available or no display")
    from am3d.ui.app import DEFAULT_THEME, apply_theme, load_theme
    qss = load_theme()
    assert "#D4D0C8" in qss
    assert "QTabBar::tab" in qss
    assert apply_theme(app, DEFAULT_THEME)
    assert "#D4D0C8" in app.styleSheet()
    assert not apply_theme(app, "no_such_theme")


def test_workspace_switch_changes_visible_areas():
    """Switching workspaces shows/hides the tiled areas per definition."""
    win = _make_main_window()
    try:
        win.show()
        from am3d.ui.workspaces import WORKSPACES
        for name, ws in WORKSPACES.items():
            win.set_workspace(name)
            assert win.current_workspace == name
            assert win.current_mode == ws.mode
            panels = win.tiled._panels
            assert panels["outliner"].isVisible() == \
                ("outliner" in ws.panels)
            assert panels["properties"].isVisible() == \
                ("properties" in ws.panels)
            assert panels["timeline"].isVisible() == \
                ("timeline" in ws.panels)
            assert win.tool_strip.workspace_label.text() == name
            assert name in win.status_workspace.text()
    finally:
        win.viewport._timer.stop()
        win.close()


def test_workspace_layout_state_restored():
    """Splitter sizes are saved on switch-away and restored on return."""
    win = _make_main_window()
    try:
        win.show()
        win.resize(1280, 820)
        win.set_workspace("Model")
        win.tiled.main_splitter.setSizes([600, 400])
        win.tiled.right_splitter.setSizes([200, 500])
        saved_main = win.tiled.main_splitter.sizes()
        saved_right = win.tiled.right_splitter.sizes()
        win.set_workspace("Render")     # same panels, different state
        win.tiled.main_splitter.setSizes([900, 100])
        render_main = win.tiled.main_splitter.sizes()
        win.set_workspace("Model")
        assert win.tiled.main_splitter.sizes() == saved_main
        assert win.tiled.right_splitter.sizes() == saved_right
        # ...and "Render" kept its own sizes too.
        win.set_workspace("Render")
        assert win.tiled.main_splitter.sizes() == render_main
    finally:
        win.viewport._timer.stop()
        win.close()


def test_status_bar_updates_on_selection():
    """Selecting in the viewport updates the status bar selection label."""
    win = _make_main_window()
    try:
        win.show()
        win.viewport.set_selected("sphere")
        assert "sphere" in win.status_selection.text()
        win.viewport.set_selected(None)
        assert win.status_selection.text() == "No selection"
        # Frame label follows the dope-sheet clock.
        win.timeline_dock.set_frame(60)
        assert "2.0" in win.status_frame.text()
        # Backend label is one of the two known renderers.
        assert win.status_backend.text() in ("GPU (moderngl)",
                                             "software (toon)")
    finally:
        win.viewport._timer.stop()
        win.close()


def test_area_panel_collapse():
    """Area headers collapse/expand their content."""
    win = _make_main_window()
    try:
        win.show()
        panel = win.tiled.properties_panel
        assert not panel._collapsed
        panel.toggle_collapsed()
        assert panel._collapsed
        assert not win.properties_dock.isVisible()
        panel.toggle_collapsed()
        assert not panel._collapsed
        assert win.properties_dock.isVisible()
    finally:
        win.viewport._timer.stop()
        win.close()


# ---------------------------------------------------------------------------
# Headless tests: model-level logic behind the outliner / properties dock.
# ---------------------------------------------------------------------------

def test_session_rename_object():
    """rename_object rekeys the object, keeps order, moves its skeleton."""
    from am3d.core.script import Session, ScriptingError
    s = Session()
    s.create_object("a")
    s.create_object("b")
    s.add_bone("b", "root", (0, 0, 0), (0, 1, 0))
    s.rename_object("b", "hero")
    assert list(s.project.objects) == ["a", "hero"]
    assert s.project.objects["hero"].name == "hero"
    assert "hero" in s.project.skeletons
    assert "b" not in s.project.skeletons
    import pytest
    with pytest.raises(ScriptingError):
        s.rename_object("hero", "a")          # duplicate
    with pytest.raises(ScriptingError):
        s.rename_object("missing", "x")       # unknown
    with pytest.raises(ScriptingError):
        s.rename_object("hero", "  ")         # empty


def test_session_delete_object_drops_skeleton():
    from am3d.core.script import Session
    s = Session()
    s.create_object("a")
    s.add_bone("a", "root", (0, 0, 0), (0, 1, 0))
    s.delete_object("a")
    assert "a" not in s.project.objects
    assert "a" not in s.project.skeletons


def test_object_visibility_default_and_setter():
    from am3d.core.script import Session
    s = Session()
    obj = s.create_object("a")
    assert obj.visible is True
    s.set_object_visible("a", False)
    assert obj.visible is False


def test_trs_roundtrip():
    """compose_trs/decompose_trs round-trip loc/rot/scale."""
    import numpy as np
    from am3d.core.mathutil import compose_trs, decompose_trs
    loc = (1.0, -2.0, 3.5)
    rot = (15.0, -30.0, 45.0)
    scl = (2.0, 0.5, 1.5)
    loc2, rot2, scl2 = decompose_trs(compose_trs(loc, rot, scl))
    assert np.allclose(loc2, loc)
    assert np.allclose(rot2, rot)
    assert np.allclose(scl2, scl)
    # Identity stays identity.
    loc2, rot2, scl2 = decompose_trs(np.eye(4))
    assert np.allclose(loc2, 0) and np.allclose(rot2, 0)
    assert np.allclose(scl2, 1)


def test_visibility_serialization_roundtrip(tmp_path):
    """visible flag and render_settings survive save/load."""
    from am3d.core.script import Session
    s = Session()
    s.create_object("a")
    s.set_object_visible("a", False)
    s.project.render_settings["supersample"] = 4
    s.project.render_settings["toon"] = False
    path = str(tmp_path / "p.am3d")
    s.save_project(path)
    s2 = Session()
    s2.load_project(path)
    assert s2.project.objects["a"].visible is False
    assert s2.project.render_settings["supersample"] == 4
    assert s2.project.render_settings["toon"] is False
