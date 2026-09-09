"""Acceptance tests for finding UI-01: building and binding a rig in the GUI.

Before this, the GUI could edit an existing bone's endpoints but had no way
to create, re-parent or delete a bone, and no way to bind geometry to a
skeleton -- so a model made in the GUI could only be rigged by writing a
script. These tests drive the same entry points the menu and the Bone tab
use, and check the whole journey through to geometry that actually follows
a posed bone.
"""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.script import ScriptingError, Session
from am3d.ui.operators import (
    AddBoneCommand, BindGeometryCommand, DeleteBoneCommand,
    SetBoneParentCommand, QUndoStack,
)


def _rigged_session():
    s = Session()
    s.create_object("hero")
    s.add_spline("hero", [(0, 0, 0), (0.4, 0.5, 0), (0.4, 1.5, 0),
                          (0, 2.0, 0)], name="profile")
    return s


# -- session-level validation (the GUI relies on it for its error text) ------

def test_add_bone_rejects_the_mistakes_the_gui_can_make():
    s = _rigged_session()
    with pytest.raises(ScriptingError):
        s.add_bone("nope", "b", (0, 0, 0), (0, 1, 0))      # unknown object
    with pytest.raises(ScriptingError):
        s.add_bone("hero", "  ", (0, 0, 0), (0, 1, 0))     # empty name
    s.add_bone("hero", "root", (0, 0, 0), (0, 1, 0))
    with pytest.raises(ScriptingError):
        s.add_bone("hero", "root", (0, 0, 0), (0, 1, 0))   # duplicate
    with pytest.raises(ScriptingError):
        s.add_bone("hero", "tip", (0, 0, 0), (0, 1, 0), parent="ghost")
    # the failures left exactly one bone behind
    assert [b.name for b in s.get_bones("hero")] == ["root"]


def test_a_duplicate_bone_name_no_longer_orphans_the_original():
    """Regression: add_bone used to overwrite the entry in place, so a
    repeated name silently destroyed the first bone and left its children
    pointing at a parent with different endpoints."""
    s = _rigged_session()
    s.add_bone("hero", "root", (0, 0, 0), (0, 1, 0))
    s.add_bone("hero", "child", (0, 1, 0), (0, 2, 0), parent="root")
    with pytest.raises(ScriptingError):
        s.add_bone("hero", "root", (9, 9, 9), (9, 9, 10))
    assert np.allclose(s.project.skeletons["hero"]["root"].tail, (0, 1, 0))
    assert s.project.skeletons["hero"]["child"].parent == "root"


def test_reparenting_rejects_self_and_cycles():
    s = _rigged_session()
    s.add_bone("hero", "a", (0, 0, 0), (0, 1, 0))
    s.add_bone("hero", "b", (0, 1, 0), (0, 2, 0), parent="a")
    s.add_bone("hero", "c", (0, 2, 0), (0, 3, 0), parent="b")
    with pytest.raises(ScriptingError):
        s.set_bone_parent("hero", "a", "a")
    with pytest.raises(ScriptingError):
        s.set_bone_parent("hero", "a", "c")     # c is a's descendant
    assert s.project.skeletons["hero"]["a"].parent is None
    s.set_bone_parent("hero", "c", "a")         # legal: shorten the chain
    assert s.bone_ancestors("hero", "c") == ["a"]


def test_deleting_a_bone_moves_its_children_up():
    s = _rigged_session()
    s.add_bone("hero", "a", (0, 0, 0), (0, 1, 0))
    s.add_bone("hero", "b", (0, 1, 0), (0, 2, 0), parent="a")
    s.add_bone("hero", "c", (0, 2, 0), (0, 3, 0), parent="b")
    s.remove_bone("hero", "b")
    assert [b.name for b in s.get_bones("hero")] == ["a", "c"]
    assert s.project.skeletons["hero"]["c"].parent == "a"


def test_deleting_the_last_bone_drops_the_empty_skeleton():
    s = _rigged_session()
    s.add_bone("hero", "only", (0, 0, 0), (0, 1, 0))
    s.remove_bone("hero", "only")
    assert "hero" not in s.project.skeletons


def test_binding_needs_bones_and_an_object():
    s = _rigged_session()
    with pytest.raises(ScriptingError):
        s.bind_geometry("hero")            # no bones yet
    with pytest.raises(ScriptingError):
        s.bind_geometry("nope")


# -- undo commands ----------------------------------------------------------

def test_add_bone_command_round_trips():
    s = _rigged_session()
    stack = QUndoStack()
    stack.push(AddBoneCommand(s, "hero", "root", (0, 0, 0), (0, 1, 0)))
    assert [b.name for b in s.get_bones("hero")] == ["root"]
    stack.undo()
    assert s.get_bones("hero") == []
    stack.redo()
    assert [b.name for b in s.get_bones("hero")] == ["root"]


def test_set_bone_parent_command_round_trips():
    s = _rigged_session()
    s.add_bone("hero", "a", (0, 0, 0), (0, 1, 0))
    s.add_bone("hero", "b", (0, 1, 0), (0, 2, 0))
    stack = QUndoStack()
    stack.push(SetBoneParentCommand(s, "hero", "b", "a"))
    assert s.project.skeletons["hero"]["b"].parent == "a"
    stack.undo()
    assert s.project.skeletons["hero"]["b"].parent is None


def test_deleting_a_bone_is_undoable_including_its_keyframes():
    """A delete that quietly threw away the bone's animation would be a
    data-loss bug that undo could not repair."""
    s = _rigged_session()
    s.add_bone("hero", "a", (0, 0, 0), (0, 1, 0))
    s.add_bone("hero", "b", (0, 1, 0), (0, 2, 0), parent="a")
    action = s.create_action("walk", duration=1.0)
    channel = action.add_channel("b", "rotate")
    channel.add_key(0.0, [0.0, 0.0, 0.0])
    channel.add_key(1.0, [0.5, 0.0, 0.0])

    stack = QUndoStack()
    stack.push(DeleteBoneCommand(s, "hero", "b"))
    assert [b.name for b in s.get_bones("hero")] == ["a"]
    assert [ch.bone for ch in s.actions["walk"].channels] == []

    stack.undo()
    assert [b.name for b in s.get_bones("hero")] == ["a", "b"]
    assert s.project.skeletons["hero"]["b"].parent == "a"
    restored = s.actions["walk"].get_channel("b", "rotate")
    assert restored is not None and len(restored.keys) == 2


def test_bind_geometry_command_round_trips():
    s = _rigged_session()
    s.add_bone("hero", "lower", (0, 0, 0), (0, 1, 0))
    s.add_bone("hero", "upper", (0, 1, 0), (0, 2, 0), parent="lower")
    stack = QUndoStack()
    stack.push(BindGeometryCommand(s, "hero"))
    assert any(b.cp_weights for b in s.get_bones("hero"))
    stack.undo()
    assert all(not b.cp_weights for b in s.get_bones("hero"))
    stack.redo()
    assert any(b.cp_weights for b in s.get_bones("hero"))


def test_binding_puts_every_control_point_under_some_bone():
    s = _rigged_session()
    s.add_bone("hero", "lower", (0, 0, 0), (0, 1, 0))
    s.add_bone("hero", "upper", (0, 1, 0), (0, 2, 0), parent="lower")
    s.bind_geometry("hero")
    from am3d.core.rigging import object_cp_positions
    positions, _ = object_cp_positions(s.project.objects["hero"])
    covered = set()
    for bone in s.get_bones("hero"):
        covered.update(bone.cp_weights)
    assert covered == set(range(len(positions)))


# -- the journey the finding is actually about ------------------------------

def test_bound_geometry_follows_a_posed_bone():
    """Rig, bind, pose -- the geometry must move. Without the bind step the
    weights are empty and posing moves the bone only."""
    from am3d.core.scene import evaluate_scene

    s = _rigged_session()
    s.lathe_spline("hero", "profile", sections=8)
    s.add_bone("hero", "lower", (0, 0, 0), (0, 1, 0))
    s.add_bone("hero", "upper", (0, 1, 0), (0, 2, 0), parent="lower")

    rest = evaluate_scene(s).meshes["hero"].vertices.copy()

    s.pose_bone("hero", "upper", (0.0, 0.0, 40.0))
    unbound = evaluate_scene(s).meshes["hero"].vertices
    assert np.allclose(rest, unbound), \
        "geometry moved before it was bound to anything"

    s.clear_pose("hero")
    assert np.allclose(rest, evaluate_scene(s).meshes["hero"].vertices), \
        "clearing the pose left the geometry deformed (finding RIG-01)"
    s.bind_geometry("hero")
    s.pose_bone("hero", "upper", (0.0, 0.0, 40.0))
    posed = evaluate_scene(s).meshes["hero"].vertices
    assert not np.allclose(rest, posed), \
        "bound geometry did not follow the posed bone"


# -- MainWindow entry points (what the menu and Bone tab actually call) -----

def _main_window():
    import sys
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication(sys.argv)
    except Exception:
        pytest.skip("PySide6 not available or no display")
    from am3d.ui.app import MainWindow
    win = MainWindow()
    win.session.create_object("hero")
    win.session.add_spline("hero", [(0, 0, 0), (0.4, 0.5, 0), (0.4, 1.5, 0),
                                    (0, 2.0, 0)], name="profile")
    win.show_editor()
    win.current_context = ("object", "hero", "")
    return win


def test_main_window_can_build_and_bind_a_rig():
    win = _main_window()
    try:
        root = win._rig_add_bone()
        assert root and [b.name for b in win.session.get_bones("hero")] == [root]
        # the new bone becomes the selection, so Add Child chains from it
        child = win._rig_add_child_bone()
        assert win.session.project.skeletons["hero"][child].parent == root
        assert np.allclose(
            win.session.project.skeletons["hero"][child].head,
            win.session.project.skeletons["hero"][root].tail)

        assert win._rig_bind_geometry() is True
        assert any(b.cp_weights for b in win.session.get_bones("hero"))

        win.undo_stack.undo()          # unbind
        assert all(not b.cp_weights for b in win.session.get_bones("hero"))
        win.undo_stack.undo()          # remove child
        assert [b.name for b in win.session.get_bones("hero")] == [root]
    finally:
        win.close()


def test_rig_menu_verbs_explain_themselves_instead_of_doing_nothing():
    win = _main_window()
    try:
        win.current_context = ("", "", "")
        win.viewport._selected = []
        assert win._rig_add_bone() is None
        assert "object" in win.statusBar().currentMessage().lower()

        win.current_context = ("object", "hero", "")
        assert win._rig_bind_geometry() is False
        assert "no bones" in win.statusBar().currentMessage().lower()

        assert win._rig_delete_bone() is False
        assert "bone" in win.statusBar().currentMessage().lower()
    finally:
        win.close()


def test_deleting_a_bone_from_the_main_window_is_undoable():
    win = _main_window()
    try:
        root = win._rig_add_bone()
        child = win._rig_add_child_bone()
        win.current_context = ("bone", "hero", root)
        assert win._rig_delete_bone() is True
        names = [b.name for b in win.session.get_bones("hero")]
        assert names == [child]
        assert win.session.project.skeletons["hero"][child].parent is None
        win.undo_stack.undo()
        assert [b.name for b in win.session.get_bones("hero")] == [root, child]
    finally:
        win.close()


def test_bone_tab_parent_combo_offers_no_cycle_and_reparents():
    win = _main_window()
    try:
        root = win._rig_add_bone()
        child = win._rig_add_child_bone()
        dock = win.properties_dock
        dock.set_context("bone", "hero", root)
        choices = [dock.bone_parent.itemData(i)
                   for i in range(dock.bone_parent.count())]
        # neither itself nor its own descendant may be offered as a parent
        assert choices == [None]

        dock.set_context("bone", "hero", child)
        assert dock.bone_parent.currentData() == root
        dock.bone_parent.setCurrentIndex(dock.bone_parent.findData(None))
        assert win.session.project.skeletons["hero"][child].parent is None
        win.undo_stack.undo()
        assert win.session.project.skeletons["hero"][child].parent == root
    finally:
        win.close()


# -- review round 4 findings (both reproduced before fixing) ----------------

def test_a_stale_bone_selection_does_not_crash_the_rig_verbs():
    """Regression: deleting the last bone drops the object's whole skeleton
    entry, and a Bone tab still pointing at it made Add Child raise
    KeyError instead of saying the bone is gone."""
    win = _main_window()
    try:
        root = win._rig_add_bone()
        win.current_context = ("bone", "hero", root)
        assert win._rig_delete_bone() is True
        win.current_context = ("bone", "hero", root)   # selection went stale

        assert win._rig_add_child_bone() is None
        assert win._rig_delete_bone() is False
        assert win._rig_bind_geometry() is False
        # and the object is still usable afterwards
        assert win._rig_add_bone()
    finally:
        win.close()


def test_a_recipe_may_list_a_child_bone_before_its_parent():
    """Regression: a recipe is declarative and may name a parent defined
    further down the list. The new add_bone validation is right for the
    imperative API but turned that legal recipe into a hard failure, so the
    executor now inserts bones parent-first."""
    import json
    import tempfile
    from pathlib import Path
    from am3d.recipes.cli import main

    recipe = {
        "version": 1, "name": "fwd",
        "objects": [{
            "name": "hero", "primitive": "box", "params": {},
            "bones": [
                {"name": "child", "parent": "root",
                 "head": [0, 1, 0], "tail": [0, 2, 0]},
                {"name": "root", "head": [0, 0, 0], "tail": [0, 1, 0]},
            ],
        }],
    }
    out = Path(tempfile.mkdtemp())
    path = out / "recipe.json"
    path.write_text(json.dumps(recipe))
    assert main(["--recipe", str(path), "--out", str(out)]) == 0


def test_bones_in_parent_order_keeps_the_written_order_otherwise():
    from am3d.recipes.executor import _bones_in_parent_order

    class B:
        def __init__(self, name, parent=None):
            self.name, self.parent = name, parent

    already = [B("a"), B("b", "a"), B("c", "b")]
    ordered, bad = _bones_in_parent_order(already)
    assert [b.name for b in ordered] == ["a", "b", "c"] and bad == []

    shuffled = [B("c", "b"), B("a"), B("b", "a")]
    ordered, bad = _bones_in_parent_order(shuffled)
    assert [b.name for b in ordered] == ["a", "b", "c"] and bad == []

    broken = [B("x", "ghost"), B("y")]
    ordered, bad = _bones_in_parent_order(broken)
    assert [b.name for b in ordered] == ["y"]
    assert [b.name for b in bad] == ["x"]

    cyclic = [B("p", "q"), B("q", "p")]
    ordered, bad = _bones_in_parent_order(cyclic)
    assert ordered == [] and {b.name for b in bad} == {"p", "q"}
