"""M2 generated-project adoption reuses the guarded normal document path."""

from __future__ import annotations

import hashlib
from pathlib import Path

from am3d.core.script import Session


def _window():
    from am3d.ui.test_operators import _make_main_window
    return _make_main_window()


def _write_generated_project(path: Path):
    from am3d.recipes.executor import RecipeExecutor
    source = Session()
    result = RecipeExecutor(session=source, ai_mode=True).execute({
        "version": 1, "name": "generated", "objects": [
            {"name": "generated", "primitive": "box"}]})
    assert result.ok
    source.project.objects["generated"].transform[:3, 3] = [10.0, 0.0, 0.0]
    source.save_project(str(path))


def test_clean_editor_opens_writable_copy_and_save_preserves_snapshot(
        tmp_path, monkeypatch):
    win = _window()
    try:
        snapshot = tmp_path / "snapshot.am3d"
        _write_generated_project(snapshot)
        original_hash = hashlib.sha256(snapshot.read_bytes()).hexdigest()
        working_copy = tmp_path / "generated-working-copy.am3d"
        working_copy.write_bytes(snapshot.read_bytes())
        monkeypatch.setattr(win._generation_runner, "is_current", lambda _run: True)
        monkeypatch.setattr(win._generation_runner, "create_writable_project_copy",
                            lambda _run: working_copy)
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: True)

        assert win._open_generated_generation("a" * 32)
        assert win.doc_ctrl.path == str(working_copy)
        assert "generated" in win.session.project.objects
        assert abs(float(win.viewport.camera.target[0]) - 10.0) < 1e-6
        win.session.project.name = "edited copy"
        assert win.doc_ctrl.do_save() == str(working_copy)
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == original_hash
        assert hashlib.sha256(working_copy.read_bytes()).hexdigest() != original_hash
    finally:
        win.viewport._timer.stop()
        win.close()


def test_dirty_document_cancel_keeps_current_session_and_removes_copy(
        tmp_path, monkeypatch):
    win = _window()
    try:
        snapshot = tmp_path / "snapshot.am3d"
        _write_generated_project(snapshot)
        working_copy = tmp_path / "generated-working-copy.am3d"
        working_copy.write_bytes(snapshot.read_bytes())
        win.session.create_object("unsaved")
        win.doc_ctrl.mark_dirty()
        original_session = win.session
        original_path = win.doc_ctrl.path
        monkeypatch.setattr(win._generation_runner, "is_current", lambda _run: True)
        monkeypatch.setattr(win._generation_runner, "create_writable_project_copy",
                            lambda _run: working_copy)
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: False)

        assert not win._open_generated_generation("b" * 32)
        assert win.session is original_session
        assert "unsaved" in win.session.project.objects
        assert win.doc_ctrl.path == original_path
        assert win.doc_ctrl.dirty
        assert not working_copy.exists()
        assert snapshot.is_file()
    finally:
        win.viewport._timer.stop()
        win.close()


def test_dirty_document_confirmation_opens_generated_copy(
        tmp_path, monkeypatch):
    win = _window()
    try:
        snapshot = tmp_path / "snapshot.am3d"
        _write_generated_project(snapshot)
        working_copy = tmp_path / "generated-working-copy.am3d"
        working_copy.write_bytes(snapshot.read_bytes())
        win.session.create_object("unsaved")
        win.doc_ctrl.mark_dirty()
        monkeypatch.setattr(win._generation_runner, "is_current", lambda _run: True)
        monkeypatch.setattr(win._generation_runner, "create_writable_project_copy",
                            lambda _run: working_copy)
        monkeypatch.setattr(win.doc_ctrl, "maybe_abandon_document", lambda: True)

        assert win._open_generated_generation("c" * 32)
        assert "generated" in win.session.project.objects
        assert "unsaved" not in win.session.project.objects
        assert win.doc_ctrl.path == str(working_copy)
        assert not win.doc_ctrl.dirty
    finally:
        win.viewport._timer.stop()
        win.close()


def test_regular_open_redirects_generation_snapshot_to_writable_copy(
        tmp_path, monkeypatch):
    import json
    from am3d.ai.storage import GenerationStore

    data_root = tmp_path / "local data"
    monkeypatch.setenv("AM3D_DATA_HOME", str(data_root))
    store = GenerationStore()
    run_id = "d" * 32
    run_dir = store.generations / run_id
    run_dir.mkdir(parents=True)
    snapshot = run_dir / "project.am3d"
    _write_generated_project(snapshot)
    record = {
        "run_id": run_id,
        "status": "complete",
            "artifacts": [{
                "path": "project.am3d",
                "size_bytes": snapshot.stat().st_size,
                "sha256": store._hash(snapshot),
            }],
    }
    (run_dir / "record.json").write_text(json.dumps(record), encoding="utf-8")

    win = _window()
    try:
        win.doc_ctrl.do_open(str(snapshot))
        assert Path(win.doc_ctrl.path) != snapshot
        assert Path(win.doc_ctrl.path).parent.name == "generated-working-copies"
        assert "generated" in win.session.project.objects
        assert win.doc_ctrl.path is not None
        assert Path(win.doc_ctrl.path).read_bytes() == snapshot.read_bytes()
    finally:
        win.viewport._timer.stop()
        win.close()
