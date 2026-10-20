"""Recipe-generated profile surfaces remain editable through the UI commands."""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path

import numpy as np
import pytest

from am3d.core.scene import evaluate_scene
from am3d.core.script import Session
from am3d.recipes.executor import RecipeExecutor
from am3d.recipes.primitives import build_primitive
from am3d.ui.operators import MoveCPCommand


LATHE_PROFILE = [[1.0, 0.0], [1.5, 1.0], [1.2, 2.0], [0.8, 3.0]]
EXTRUDE_PROFILE = [[0.0, 0.0, 0.0], [1.0, 0.0, 0.0],
                   [1.0, 0.0, 1.0], [0.0, 0.0, 1.0]]


def _rendered_geometry(session):
    mesh = evaluate_scene(session).meshes["body"]
    referenced = np.unique(mesh.indices)
    assert len(referenced), "generated profile surface has no referenced triangles"
    return mesh.vertices[referenced].copy(), mesh.indices.copy()


def _profile_case(kind):
    if kind == "lathe":
        return (LATHE_PROFILE,
                {"axis": "z", "sections": 9},
                1, [1.5, 1.0, 0.0], [4.5, 1.0, 0.0],
                {"axis": "z", "sections": 9})
    return (EXTRUDE_PROFILE,
            {"height": 1.75, "twist_deg": 33.0, "rings": 5},
            1, [1.0, 0.0, 0.0], [6.0, 0.0, 0.0],
            {"height": 1.75, "twist_deg": 33.0, "rings": 5})


@pytest.mark.parametrize("primitive", ["lathe", "extrude"])
def test_recipe_profile_edit_changes_referenced_surface_and_roundtrips(
        tmp_path, primitive):
    profile, params, cp_index, before_cp, after_cp, generator_params = \
        _profile_case(primitive)
    profile_name = f"__recipe_{primitive}_profile__"
    recipe = {
        "name": f"editable-{primitive}",
        "objects": [{
            "name": "body", "primitive": primitive,
            "params": {"profile": profile, **params},
            "splines": [{"name": "guide", "degree": 2,
                         "points": [[0, 0, 0], [0.2, 0.1, 0],
                                    [0.4, 0.2, 0], [0.6, 0.3, 0]]}],
        }],
        "exports": [{"format": "am3d", "path": str(tmp_path / "source")}],
    }
    session = Session()
    result = RecipeExecutor(session).execute(recipe)
    assert result.ok, result.error_records
    native_path = Path(next(path for fmt, path in result.exports
                            if fmt == "am3d"))
    assert native_path.is_file()

    obj = session.project.objects["body"]
    patch = obj.patches[0]
    expected_build = build_primitive(primitive,
                                     recipe["objects"][0]["params"])["patches"][0]
    assert list(obj.splines) == ["guide", profile_name]
    assert patch.generator == {"op": primitive, "spline": profile_name,
                               "params": generator_params}
    assert np.array_equal(obj.splines[profile_name].point_array(),
                          np.asarray(profile, dtype=np.float64) if primitive == "extrude"
                          else np.column_stack((np.asarray(profile)[:, 0],
                                                np.asarray(profile)[:, 1],
                                                np.zeros(len(profile)))))
    assert np.array_equal(patch.interior, expected_build[1])
    assert (patch.degree_u, patch.degree_v) == expected_build[2:]

    initial_vertices, initial_indices = _rendered_geometry(session)
    reopened = Session()
    from am3d.core.serializer import load_project
    reopened.project = load_project(str(native_path))
    reopened_obj = reopened.project.objects["body"]
    reopened_patch = reopened_obj.patches[0]
    assert reopened_patch.generator == patch.generator
    assert (reopened_patch.degree_u, reopened_patch.degree_v) == (
        patch.degree_u, patch.degree_v)
    assert list(reopened_obj.splines) == ["guide", profile_name]
    reopened_vertices, reopened_indices = _rendered_geometry(reopened)
    assert np.array_equal(reopened_vertices, initial_vertices)
    assert np.array_equal(reopened_indices, initial_indices)

    # Rebuilding from the stored source and parameters must retain the
    # original axis/twist geometry exactly.
    from am3d.core.generators import rebuild_patch
    rebuilt_before_edit = reopened_patch.interior.copy()
    assert rebuild_patch(reopened_obj, reopened_patch)
    assert np.array_equal(reopened_patch.interior, rebuilt_before_edit)

    command = MoveCPCommand(reopened, "body", profile_name, cp_index,
                            before_cp, after_cp)
    command.redo()
    edited_vertices, edited_indices = _rendered_geometry(reopened)
    assert not np.array_equal(initial_vertices, edited_vertices), (
        "moving the generated profile changed only its guide, not the rendered surface")
    assert len(edited_indices) == len(initial_indices)
    assert np.array_equal(edited_indices, initial_indices)

    command.undo()
    undo_vertices, undo_indices = _rendered_geometry(reopened)
    assert np.array_equal(undo_vertices, initial_vertices)
    assert np.array_equal(undo_indices, initial_indices)
    command.redo()
    redo_vertices, redo_indices = _rendered_geometry(reopened)
    assert np.array_equal(redo_vertices, edited_vertices)
    assert np.array_equal(redo_indices, edited_indices)

    edited_path = tmp_path / f"edited-{primitive}.am3d"
    from am3d.core.serializer import save_project
    save_project(reopened.project, str(edited_path))
    saved_again = Session()
    saved_again.project = load_project(str(edited_path))
    saved_obj = saved_again.project.objects["body"]
    assert saved_obj.patches[0].generator == patch.generator
    assert np.array_equal(saved_obj.splines[profile_name].point_array(),
                          reopened_obj.splines[profile_name].point_array())
    saved_vertices, saved_indices = _rendered_geometry(saved_again)
    assert np.array_equal(saved_vertices, edited_vertices)
    assert np.array_equal(saved_indices, edited_indices)


@pytest.mark.parametrize("primitive", ["lathe", "extrude"])
def test_recipe_profile_helpers_keep_auto_weights_finite_and_deformable(primitive):
    profile, params, _index, _before, _after, _generator_params = \
        _profile_case(primitive)
    session = Session()
    result = RecipeExecutor(session).execute({
        "name": "auto-weighted-profile",
        "objects": [{
            "name": "body", "primitive": primitive,
            "params": {"profile": profile, **params},
            "bones": [
                {"name": "root", "head": [0, 0, 0], "tail": [0, 1, 0]},
                {"name": "tip", "head": [0, 1, 0], "tail": [0, 2, 0],
                 "parent": "root"},
            ],
        }],
    })
    assert result.ok, result.error_records

    from am3d.core.rigging import object_cp_positions
    obj = session.project.objects["body"]
    positions, _writer = object_cp_positions(obj)
    bones = session.get_bones("body")
    assert bones and all(bone.cp_weights for bone in bones)
    for bone in bones:
        assert all(0 <= index < len(positions)
                   and np.isfinite(weight)
                   for index, weight in bone.cp_weights.items())

    rest = _rendered_geometry(session)[0]
    from am3d.core.scene import evaluate_scene as evaluate_with_pose
    posed_mesh = evaluate_with_pose(
        session, pose={"body": {"tip": [0.0, 0.0, 35.0]}}).meshes["body"]
    posed_vertices = posed_mesh.vertices[np.unique(posed_mesh.indices)]
    assert np.isfinite(rest).all() and np.isfinite(posed_vertices).all()
    assert not np.array_equal(rest, posed_vertices)


def _generation_envelope(recipe, run_id):
    encoded = json.dumps(recipe, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=False, allow_nan=False).encode("utf-8")
    return {
        "version": 1,
        "run_id": run_id,
        "parent_generation_id": None,
        "accepted_brief": {"brief": "editable profile fixture"},
        "recipe": recipe,
        "recipe_sha256": hashlib.sha256(encoded).hexdigest(),
        "application": {"version": "test", "build_id": "offline-fixture",
                        "capability_version": "fixture-v1"},
        "warnings": [],
        "artifact_refs": [],
    }


def test_generated_profile_edit_marks_working_copy_diverged_without_changing_history(
        tmp_path):
    from PIL import Image

    from am3d.ai.records import GenerationRecordStore
    from am3d.core.serializer import load_project, save_project

    recipe = {
        "version": 1,
        "name": "history-profile-fixture",
        "objects": [{"name": "body", "primitive": "lathe",
                     "params": {"profile": LATHE_PROFILE,
                                "axis": "z", "sections": 9}}],
    }
    session = Session()
    result = RecipeExecutor(session).execute(recipe)
    assert result.ok, result.error_records

    store = GenerationRecordStore(tmp_path / "history")
    attempt = store.begin()
    candidate = attempt.candidate_dir(1)
    session.project.generation = _generation_envelope(recipe, attempt.run_id)
    save_project(session.project, str(candidate / "project.am3d"))
    Image.new("RGBA", (8, 8), (0, 0, 0, 0)).save(candidate / "preview.png")
    artifacts = [
        {"path": path.name,
         "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
         "bytes": path.stat().st_size}
        for path in sorted(candidate.iterdir())
    ]
    check_report = {"ok": True, "status": "passed", "checks": [],
                    "artifacts": artifacts}
    record_data = {"accepted_recipe": recipe,
                   "accepted_brief": {"brief": "editable profile fixture"}}
    attempt.publish(candidate, record_data, check_report)
    record = store.get_record(attempt.run_id)
    immutable_path = Path(record["project_path"])
    immutable_hash = hashlib.sha256(immutable_path.read_bytes()).hexdigest()
    immutable_manifest = record["artifact_manifest"]

    working = store.create_working_copy(record, tmp_path / "working")
    working_path = Path(working["project_path"])
    editable = Session()
    editable.project = load_project(str(working_path))
    profile_name = editable.project.objects["body"].patches[0].generator["spline"]
    cp_before = editable.project.objects["body"].splines[profile_name].cps[1].position.copy()
    cp_after = np.array([4.5, cp_before[1], cp_before[2]])
    MoveCPCommand(editable, "body", profile_name, 1,
                  cp_before, cp_after).redo()
    save_project(editable.project, str(working_path))

    reopened = load_project(str(working_path))
    assert reopened.generation["diverged"] is True
    assert reopened.generation["run_id"] == record["run_id"]
    assert reopened.objects["body"].patches[0].generator["spline"] == profile_name
    assert np.array_equal(
        reopened.objects["body"].splines[profile_name].cps[1].position,
        cp_after)
    immutable_session = Session()
    immutable_session.project = load_project(str(immutable_path))
    edited_session = Session()
    edited_session.project = reopened
    initial_vertices, _ = _rendered_geometry(immutable_session)
    edited_vertices, _ = _rendered_geometry(edited_session)
    assert not np.array_equal(initial_vertices, edited_vertices)
    assert store.get_record(record["run_id"])["artifact_manifest"] == immutable_manifest
    assert hashlib.sha256(immutable_path.read_bytes()).hexdigest() == immutable_hash
