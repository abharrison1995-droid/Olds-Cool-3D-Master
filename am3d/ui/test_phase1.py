"""Phase 1 regression tests: action persistence, rename/delete maps, assignment round-trip."""
from __future__ import annotations

import numpy as np
import pytest

from PySide6.QtGui import QUndoStack

from am3d.core.script import Session


@pytest.fixture
def session():
    return Session()


def test_assign_action_persists_through_save_reopen(tmp_path, session):
    session.create_object("hero")
    session.add_bone("hero", "root", (0,0,0), (0,1,0))
    act = session.create_action("walk", duration=1.0)
    act.add_channel("root").add_key(0, [0,0,0])
    session.assign_action("walk", "hero")
    session.set_active_action("walk")
    path = str(tmp_path / "test.am3d")
    session.save_project(path)
    s2 = Session()
    s2.load_project(path)
    assert "hero" in s2.project.objects
    assert "walk" in s2.actions
    assert s2.active_action == "walk"
    assert s2.action_assignments.get("hero") == "walk"


def test_rename_object_rekeys_assignments(session):
    session.create_object("hero")
    session.create_action("idle", duration=1.0)
    session.assign_action("idle", "hero")
    session.rename_object("hero", "knight")
    assert "knight" in session.action_assignments
    assert "hero" not in session.action_assignments
    assert session.action_assignments["knight"] == "idle"


def test_delete_object_clears_assignments(session):
    session.create_object("hero")
    session.create_action("idle", duration=1.0)
    session.assign_action("idle", "hero")
    session.delete_object("hero")
    assert "hero" not in session.action_assignments


def test_rename_object_rekeys_poses(session):
    session.create_object("hero")
    session.add_bone("hero", "root", (0,0,0), (0,1,0))
    session.pose_bone("hero", "root", np.eye(3))
    assert "hero" in session.poses
    session.rename_object("hero", "knight")
    assert "knight" in session.poses
    assert "hero" not in session.poses


def test_rename_action_updates_assignments(session):
    session.create_object("hero")
    session.create_action("walk", duration=1.0)
    session.assign_action("walk", "hero")
    session.set_active_action("walk")
    session.rename_action("walk", "run")
    assert "run" in session.actions
    assert "walk" not in session.actions
    assert session.active_action == "run"
    assert session.action_assignments["hero"] == "run"


def test_delete_action_clears_active_and_assignments(session):
    session.create_object("hero")
    session.create_action("walk", duration=1.0)
    session.create_action("run", duration=1.0)
    session.assign_action("walk", "hero")
    session.set_active_action("walk")
    session.delete_action("walk")
    assert "walk" not in session.actions
    assert session.active_action == "run"
    assert "hero" not in session.action_assignments


def test_session_state_full_roundtrip(tmp_path, session):
    session.create_object("hero")
    session.add_bone("hero", "root", (0,0,0), (0,1,0))
    session.create_object("prop")
    w = session.create_action("wave", duration=2.0)
    w.add_channel("root").add_key(0, [0,0,0])
    w.add_channel("root").add_key(2, [1,0,0])
    i = session.create_action("idle", duration=1.0)
    i.add_channel("root").add_key(0, [0,0,0])
    session.assign_action("wave", "hero")
    session.assign_action("idle", "prop")
    session.set_active_action("wave")
    path = str(tmp_path / "full.am3d")
    session.save_project(path)
    s2 = Session()
    s2.load_project(path)
    assert s2.active_action == "wave"
    assert s2.action_assignments == {"hero": "wave", "prop": "idle"}
    assert set(s2.actions) == {"wave", "idle"}


def test_delete_action_restores_active_action(session):
    session.create_object("hero")
    session.add_bone("hero", "root", (0,0,0), (0,1,0))
    session.create_action("walk", duration=1.0)
    session.create_action("run", duration=1.0)
    session.assign_action("walk", "hero")
    session.set_active_action("walk")

    from am3d.ui.operators import DeleteActionCommand
    stack = QUndoStack()
    cmd = DeleteActionCommand(session, "walk")
    stack.push(cmd)
    assert "walk" not in session.actions
    assert session.active_action == "run"

    stack.undo()
    assert "walk" in session.actions
    assert session.active_action == "walk"
    assert session.action_assignments["hero"] == "walk"


def test_create_primitive_command_redo_idempotent(session):
    """Redo of CreatePrimitiveCommand should not crash on name collision."""
    from am3d.ui.operators import CreatePrimitiveCommand
    stack = QUndoStack()
    cmd = CreatePrimitiveCommand(session, "sphere", "sphere",
                                 dict(radius=0.8, sections=12, rings=8))
    stack.push(cmd)
    assert "sphere" in session.project.objects
    assert len(session.project.objects["sphere"].patches) > 0

    # Redo should be idempotent
    stack.undo()
    assert "sphere" not in session.project.objects

    stack.redo()
    assert "sphere" in session.project.objects
    assert len(session.project.objects["sphere"].patches) > 0

    stack.redo()
    assert "sphere" in session.project.objects


def test_add_object_command_redo_idempotent(session):
    """Redo of AddObjectCommand should not crash on name collision."""
    from am3d.ui.operators import AddObjectCommand
    stack = QUndoStack()
    cmd = AddObjectCommand(session, "box")
    stack.push(cmd)
    assert "box" in session.project.objects

    stack.undo()
    assert "box" not in session.project.objects

    stack.redo()
    assert "box" in session.project.objects

    stack.redo()
    assert "box" in session.project.objects


def test_assign_action_command_roundtrip(session):
    import os
    from am3d.core.serializer import load_project
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    path = os.path.join(base, "assets", "vase_demo.am3d")
    if not os.path.exists(path):
        pytest.skip("vase_demo.am3d not found")
    p = load_project(path)
    assert p.objects
    assert p.action_assignments == {}


def test_legacy_walk_am3a_still_loads():
    import os
    from am3d.core.serializer import load_action_file
    base = os.path.join(os.path.dirname(__file__), "..", "..")
    path = os.path.join(base, "assets", "walk.am3a")
    if not os.path.exists(path):
        pytest.skip("walk.am3a not found")
    act = load_action_file(path)
    assert act.channels