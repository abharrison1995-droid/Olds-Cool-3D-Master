"""Headless preservation foundations for recipe-based refinement."""

from __future__ import annotations

import copy
import hashlib
import math
from pathlib import Path

import pytest

from am3d.ai import orchestrator as orch
from am3d.ai.contracts import AssetBrief
from am3d.ai.records import GenerationRecordStore

from .test_orchestrator import FakeProvider, MemoryStore, _fake_worker, _recipe


@pytest.mark.parametrize("refinement", [
    "Make the roof flatter",
    "Make the character's arms longer",
    "Change the body to dark green",
    "Make the wheels larger",
])
def test_refinement_reinterprets_parent_brief_and_keeps_parent_immutable(
        tmp_path, monkeypatch, refinement):
    parent_id = "11111111-1111-4111-8111-111111111111"
    parent = {
        "run_id": parent_id,
        "status": "complete",
        "accepted_brief": {"brief": "Create a stylized vehicle with a roof, arms, green body, and wheels."},
        "accepted_recipe": _recipe("parent-vehicle"),
        "check_report": {"ok": True, "status": "passed", "artifacts": []},
        "artifact_manifest": [{"path": "project.am3d", "sha256": "a" * 64, "bytes": 10}],
        "native_bytes_sha256": hashlib.sha256(b"unchanged parent").hexdigest(),
    }
    parent_before = copy.deepcopy(parent)
    store = MemoryStore(tmp_path / "records")
    store.parents[parent_id] = parent
    interpreted = []
    build_calls = []

    def interpret(provider, raw_request, deadline, cancellation):
        provider.generate(None, deadline, cancellation)
        interpreted.append(raw_request)
        return AssetBrief(brief=raw_request)

    def build(provider, brief, deadline, cancellation, previous_recipe=None,
              repair_errors=None, refinement_request=None):
        provider.generate(None, deadline, cancellation)
        build_calls.append({"previous": copy.deepcopy(previous_recipe),
                            "refinement": refinement_request})
        return _recipe("child-vehicle")

    monkeypatch.setattr(orch, "interpret_brief", interpret)
    monkeypatch.setattr(orch, "build_candidate", build)
    worker = _fake_worker(["checked_ok"])
    subject = orch.GenerationOrchestrator(FakeProvider(), store,
                                          worker_runner=worker)

    outcome = subject.generate("ignored caller text", parent_generation_id=parent_id,
                               refinement_request=refinement)

    assert outcome.status == "completed"
    assert outcome.run_id != parent_id
    assert outcome.record["parent_generation_id"] == parent_id
    assert interpreted == [parent["accepted_brief"]["brief"]
                           + "\n\nRequested refinement: " + refinement]
    assert build_calls[0]["previous"] == parent_before["accepted_recipe"]
    assert build_calls[0]["refinement"] == refinement
    assert parent == parent_before


@pytest.mark.parametrize("status,check_report", [
    ("complete", {"ok": False, "status": "failed"}),
    ("failed", {"ok": True, "status": "passed"}),
])
def test_refinement_without_a_verified_successful_parent_stops_before_provider(
        tmp_path, monkeypatch, status, check_report):
    parent_id = "22222222-2222-4222-8222-222222222222"
    store = MemoryStore(tmp_path / "records")
    store.parents[parent_id] = {
        "run_id": parent_id,
        "status": status,
        "accepted_brief": {"brief": "Create a vehicle."},
        "accepted_recipe": _recipe("vehicle"),
        "check_report": check_report,
    }
    provider = FakeProvider()
    subject = orch.GenerationOrchestrator(provider, store,
                                          worker_runner=_fake_worker([]))

    outcome = subject.generate("unused", parent_generation_id=parent_id,
                               refinement_request="make it wider")

    assert outcome.status == "failed"
    assert outcome.error["code"] == "parent_not_successful"
    assert provider.calls == 0


def test_refinement_candidate_and_publication_failures_leave_parent_available(
        tmp_path, monkeypatch):
    parent_id = "33333333-3333-4333-8333-333333333333"
    parent = {
        "run_id": parent_id,
        "status": "complete",
        "accepted_brief": {"brief": "Create a vehicle."},
        "accepted_recipe": _recipe("vehicle"),
        "check_report": {"ok": True, "status": "passed"},
        "native_bytes_sha256": hashlib.sha256(b"original").hexdigest(),
    }
    before = copy.deepcopy(parent)
    store = MemoryStore(tmp_path / "records", fail_publish=True)
    store.parents[parent_id] = parent
    monkeypatch.setattr(orch, "interpret_brief",
                        lambda _p, raw, _d, _c: AssetBrief(brief=raw))
    monkeypatch.setattr(orch, "build_candidate",
                        lambda *_a, **_kw: _recipe("child"))
    subject = orch.GenerationOrchestrator(
        FakeProvider(), store, worker_runner=_fake_worker(["checked_ok"]))

    outcome = subject.generate("unused", parent_generation_id=parent_id,
                               refinement_request="make it wider")

    assert outcome.status == "publication_failed"
    assert parent == before
    assert parent_id in store.parents


def _vehicle_recipe(*, roof_angle=0.0, arm_width=0.5, body_color=(0.04, 0.16, 0.92),
                    wheel_radius=0.25):
    def transform(x, y, z, angle=0.0):
        c, s = math.cos(angle), math.sin(angle)
        return [[c, -s, 0.0, x], [s, c, 0.0, y],
                [0.0, 0.0, 1.0, z], [0.0, 0.0, 0.0, 1.0]]

    return {
        "version": 1,
        "name": "measured refinement vehicle",
        "objects": [
            {"name": "body", "primitive": "box",
             "params": {"width": 1.5, "height": 1.0, "depth": 0.8}},
            {"name": "roof", "primitive": "box",
             "params": {"width": 2.0, "height": 0.2, "depth": 1.0},
             "transform": transform(0.0, 0.7, 0.0, roof_angle)},
            {"name": "left_arm", "primitive": "box",
             "params": {"width": arm_width, "height": 0.15, "depth": 0.15},
             "transform": transform(-1.2, 0.0, 0.0)},
            {"name": "right_arm", "primitive": "box",
             "params": {"width": arm_width, "height": 0.15, "depth": 0.15},
             "transform": transform(1.2, 0.0, 0.0)},
            {"name": "wheel", "primitive": "cylinder",
             "params": {"radius": wheel_radius, "height": 0.4, "sections": 16},
             "transform": transform(1.2, -0.2, 0.0)},
        ],
        "materials": [{"name": "body_paint", "color": list(body_color),
                       "objects": ["body"]}],
        "exports": [],
    }


def _reopened_component_extents(native_path, names):
    """Measure named meshes after reopening the published native project."""
    import numpy as np
    from am3d.core.script import Session

    session = Session()
    session.load_project(str(native_path))
    scene = session.evaluate_scene(visible_only=True, apply_transforms=True,
                                   nu=16, nv=16)
    result = {}
    for name in names:
        mesh = scene.meshes[name]
        vertices = np.asarray(mesh.vertices, dtype=np.float64)
        result[name] = vertices.max(axis=0) - vertices.min(axis=0)
    return result


def test_four_refinements_change_measured_reopened_native_geometry_and_material(
        tmp_path, monkeypatch):
    """Offline fake prompts still pass through the real worker and checker."""
    parent_brief = "A vehicle with a roof, long arms, a green body, and wheels."
    refinements = {
        "Make the roof flatter": (_vehicle_recipe(roof_angle=0.0), "roof_flatter"),
        "Make both arms longer": (_vehicle_recipe(arm_width=0.9), "arms"),
        "Change the body to dark green": (
            _vehicle_recipe(body_color=(0.05, 0.28, 0.08)), "green"),
        "Increase the wheel radius": (_vehicle_recipe(wheel_radius=0.45), "wheel"),
    }
    def interpret(provider, raw_request, deadline, cancellation):
        provider.generate(None, deadline, cancellation)
        return AssetBrief(brief=raw_request)

    def build(provider, brief, deadline, cancellation, *, refinement_request=None,
              **_kwargs):
        provider.generate(None, deadline, cancellation)
        if refinement_request is None:
            return _vehicle_recipe(roof_angle=0.35)
        return refinements[refinement_request][0]

    monkeypatch.setattr(orch, "interpret_brief", interpret)
    monkeypatch.setattr(orch, "build_candidate", build)
    store = GenerationRecordStore(tmp_path / "measured-refinement-records")
    worker_results = []

    def real_worker(*args, **kwargs):
        result = orch.run_worker(*args, **kwargs)
        worker_results.append(result)
        return result

    subject = orch.GenerationOrchestrator(FakeProvider(), store,
                                          worker_runner=real_worker)
    common_requirements = {"required_components": [
        "body", "roof", "left_arm", "right_arm", "wheel"]}

    parent = subject.generate(parent_brief, requirements=common_requirements)
    assert parent.status == "completed", parent.error
    parent_record = store.get_record(parent.run_id)
    parent_native = Path(parent_record["project_path"])
    parent_native_hash = hashlib.sha256(parent_native.read_bytes()).hexdigest()
    parent_extents = _reopened_component_extents(
        parent_native, ("roof", "left_arm", "right_arm", "wheel"))

    for instruction, (_recipe_value, expected_change) in refinements.items():
        requirements = dict(common_requirements)
        if expected_change == "green":
            requirements["materials"] = [{
                "component": "body", "color_srgb": [0.05, 0.28, 0.08],
                "tolerance_per_channel": 0.01,
            }]
        child = subject.generate("ignored", parent_generation_id=parent.run_id,
                                 refinement_request=instruction,
                                 requirements=requirements)
        assert child.status == "completed", (
            instruction, child.error,
            [(result.get("status"), result.get("error_records"),
              result.get("checks_status")) for result in worker_results],
        )
        assert child.run_id != parent.run_id
        assert child.record["parent_generation_id"] == parent.run_id
        checks = {item["id"]: item["status"]
                  for item in child.check_report["checks"]}
        assert checks["native_roundtrip"] == "passed"
        assert checks["surface_geometry"] == "passed"
        assert checks["required_components"] == "passed"
        child_native = Path(store.get_record(child.run_id)["project_path"])
        child_extents = _reopened_component_extents(
            child_native, ("roof", "left_arm", "right_arm", "wheel"))
        if expected_change == "roof_flatter":
            assert child_extents["roof"][1] < parent_extents["roof"][1] - 0.15
        elif expected_change == "arms":
            for arm in ("left_arm", "right_arm"):
                assert child_extents[arm][0] > parent_extents[arm][0] + 0.15
        elif expected_change == "wheel":
            radius_before = max(parent_extents["wheel"][0],
                                parent_extents["wheel"][2]) / 2
            radius_after = max(child_extents["wheel"][0],
                               child_extents["wheel"][2]) / 2
            assert radius_after > radius_before + 0.15
        else:
            assert checks["material_assignments_and_color"] == "passed"
            saved_child = store.get_record(child.run_id)
            assert saved_child["accepted_recipe"]["materials"][0]["color"] == [
                0.05, 0.28, 0.08]
        assert child.record["accepted_brief"]["brief"].endswith(
            "Requested refinement: " + instruction)

    assert hashlib.sha256(parent_native.read_bytes()).hexdigest() == parent_native_hash
    assert store.get_record(parent.run_id)["accepted_recipe"] == parent_record["accepted_recipe"]
