"""Tests for the serializer / Action-reuse asset format."""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.animation import Action, Interpolation
from am3d.core import serializer
from am3d.core.project import Material, Project, Spline, ControlPoint


def test_action_roundtrip_bytes():
    a = Action(name="walk", duration=2.0, signature=("hip->root", "upper->hip"))
    ch = a.add_channel("upper", "rotate")
    ch.add_key(0.0, [0, 0, 0], Interpolation.SMOOTH)
    ch.add_key(1.0, [0, 30, 0], Interpolation.SMOOTH)
    a.metadata["author"] = "agent"

    blob = serializer.dump_action(a)
    b = serializer.load_action(blob)
    assert b.name == "walk"
    assert b.duration == 2.0
    assert b.signature == ("hip->root", "upper->hip")
    assert b.metadata["author"] == "agent"
    ch2 = b.get_channel("upper", "rotate")
    assert np.allclose(ch2.sample(0.5), ch.sample(0.5), atol=1e-6)


def test_action_drop_onto_character(tmp_path):
    act = Action("cycle", duration=1.0)
    act.add_channel("root").add_key(0, [0, 0, 0])
    path = tmp_path / "cycle.am3a"
    serializer.save_action(act, str(path))
    loaded = serializer.load_action_file(str(path))
    assert loaded.name == "cycle"


def test_project_roundtrip():
    p = Project("scene")
    obj = p.create_object("vase")
    obj.add_spline(Spline(name="profile", cps=[
        ControlPoint([0.5, 0, 0]), ControlPoint([1, 1, 0]), ControlPoint([0.6, 2, 0]),
    ]))
    p.materials["red"] = Material("red", (1, 0, 0))

    blob = serializer.dump_project(p)
    q = serializer.load_project_bytes(blob)
    assert q.name == "scene"
    assert "vase" in q.objects
    assert "profile" in q.objects["vase"].splines
    assert q.materials["red"].color == (1, 0, 0)


# ---------------------------------------------------------------------------
# Project round-trip: patches / bones / hooks / transforms (Phase 3A fixes)
# ---------------------------------------------------------------------------
from am3d.core.project import Bone, Hook, Patch
from am3d.core.serializer import load_project, save_project
from am3d.spline.kernel import build_lathe_net


def _rich_project():
    p = Project("roundtrip")
    obj = p.create_object("vase")
    obj.transform = np.diag([2.0, 2.0, 2.0, 1.0])
    profile = np.array([[0.5, 0.0], [1.0, 1.0], [0.6, 2.0], [0.4, 2.5]])
    obj.patches.append(Patch(name="body", splines=["profile_a"],
                             interior=build_lathe_net(profile, sections=8)))
    p.skeletons["hero"] = {
        "hip": Bone(name="hip", head=[0, 0.9, 0], tail=[0, 1.0, 0],
                    cp_weights={0: 1.0}),
        "spine": Bone(name="spine", parent="hip", head=[0, 1.0, 0],
                      tail=[0, 1.4, 0], cp_weights={1: 0.7, 2: 0.3}),
    }
    obj.hooks.append(Hook(source=("profile_a", 0), target=("profile_b", 3),
                          strength=0.5))
    p.materials["gold"] = Material("gold", (0.85, 0.65, 0.2))
    return p


def test_patch_interior_survives_roundtrip(tmp_path):
    original = _rich_project()
    path = str(tmp_path / "r.am3d")
    save_project(original, path)
    loaded = load_project(path)

    assert loaded.name == "roundtrip"
    assert len(loaded.objects["vase"].patches) == 1
    restored = loaded.objects["vase"].patches[0]
    assert restored.name == "body"
    assert restored.interior is not None
    assert np.allclose(restored.interior,
                       original.objects["vase"].patches[0].interior)


def test_transform_and_hooks_survive():
    original = _rich_project()
    loaded = serializer.load_project_bytes(serializer.dump_project(original))
    assert np.allclose(loaded.objects["vase"].transform,
                       np.diag([2, 2, 2, 1]))
    hooks = loaded.objects["vase"].hooks
    assert len(hooks) == 1
    assert hooks[0].source == ("profile_a", 0)
    assert hooks[0].strength == 0.5


def test_skeletons_survive_with_weights():
    original = _rich_project()
    loaded = serializer.load_project_bytes(serializer.dump_project(original))
    rig = loaded.skeletons.get("hero", {})
    assert set(rig) == {"hip", "spine"}
    hip = rig["hip"]
    assert isinstance(hip, Bone)
    assert np.allclose(hip.head, [0, 0.9, 0])
    assert hip.cp_weights == {0: 1.0}
    spine = rig["spine"]
    assert spine.parent == "hip"
    assert spine.cp_weights == {1: 0.7, 2: 0.3}


def test_materials_still_survive():
    loaded = serializer.load_project_bytes(
        serializer.dump_project(_rich_project()))
    assert loaded.materials["gold"].color == (0.85, 0.65, 0.2)


def test_tessellation_works_after_reload(tmp_path):
    from am3d.renderer.tessellate import tessellate_object

    original = _rich_project()
    path = str(tmp_path / "r.am3d")
    save_project(original, path)
    reloaded = load_project(path)

    mesh = tessellate_object(reloaded.objects["vase"], nu=8, nv=6)
    assert mesh.vertices.shape[0] > 0
    assert mesh.indices.shape[0] > 0


def test_project_roundtrip_splines_only():
    p = Project("scene")
    obj = p.create_object("vase")
    obj.add_spline(Spline(name="profile", cps=[
        ControlPoint([0.5, 0, 0]), ControlPoint([1, 1, 0]),
        ControlPoint([0.6, 2, 0]),
    ]))
    p.materials["red"] = Material("red", (1, 0, 0))

    blob = serializer.dump_project(p)
    q = serializer.load_project_bytes(blob)
    assert q.name == "scene"
    assert "vase" in q.objects
    spl = q.objects["vase"].splines["profile"]
    assert len(spl.cps) == 3


def test_project_save_load(tmp_path):
    p = Project()
    p.create_object("box")
    path = tmp_path / "scene.am3d"
    serializer.save_project(p, str(path))
    q = serializer.load_project(str(path))
    assert "box" in q.objects


# ---------------------------------------------------------------------------
# Regression tests: keyframe tangents, material maps, actions section
# ---------------------------------------------------------------------------
def test_keyframe_tangents_survive_action_roundtrip():
    a = Action(name="curve", duration=1.0)
    ch = a.add_channel("root", "translate")
    k0 = ch.add_key(0.0, [0, 0, 0], Interpolation.SMOOTH)
    k1 = ch.add_key(1.0, [1, 0, 0], Interpolation.SMOOTH)
    k0.out_tangent = np.array([0.0, 2.0, 0.0])
    k1.in_tangent = np.array([0.0, -2.0, 0.0])

    b = serializer.load_action(serializer.dump_action(a))
    ch2 = b.get_channel("root", "translate")
    assert np.allclose(ch2.keys[0].out_tangent, [0, 2, 0])
    assert np.allclose(ch2.keys[1].in_tangent, [0, -2, 0])
    assert ch2.keys[0].in_tangent is None
    assert np.allclose(ch2.sample(0.5), ch.sample(0.5), atol=1e-9)


def test_walk_asset_still_loads():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "..",
                        "assets", "walk.am3a")
    act = serializer.load_action_file(os.path.abspath(path))
    assert act.channels, "walk.am3a should contain channels"
    for ch in act.channels:
        for k in ch.keys:
            assert k.in_tangent is None and k.out_tangent is None


def test_material_maps_survive_project_roundtrip():
    p = Project("mats")
    p.materials["wood"] = Material(
        "wood", (0.5, 0.3, 0.1), bump_map="wood_b.png",
        transparency_map="wood_t.png", specular_map="wood_s.png")
    p.materials["plain"] = Material("plain", (1, 0, 0))

    q = serializer.load_project_bytes(serializer.dump_project(p))
    wood = q.materials["wood"]
    assert wood.color == (0.5, 0.3, 0.1)
    assert wood.bump_map == "wood_b.png"
    assert wood.transparency_map == "wood_t.png"
    assert wood.specular_map == "wood_s.png"
    plain = q.materials["plain"]
    assert plain.bump_map is None
    assert plain.transparency_map is None
    assert plain.specular_map is None


def test_vase_demo_project_still_loads():
    import os
    path = os.path.join(os.path.dirname(__file__), "..", "..",
                        "assets", "vase_demo.am3d")
    p = serializer.load_project(os.path.abspath(path))
    assert p.objects, "vase_demo.am3d should contain objects"


def test_actions_section_survives_project_roundtrip(tmp_path):
    p = Project("with_actions")
    p.create_object("box")
    act = Action("wave", duration=2.0)
    ch = act.add_channel("arm")
    ch.add_key(0.0, [0, 0, 0])
    ch.add_key(2.0, [0, 1, 0])

    path = str(tmp_path / "a.am3d")
    serializer.save_project(p, path, actions={"wave": act})
    q = serializer.load_project(path)
    assert set(q.actions) == {"wave"}
    loaded = q.actions["wave"]
    assert loaded.name == "wave"
    assert loaded.duration == 2.0
    ch = loaded.get_channel("arm")
    assert np.allclose(ch.sample(2.0), [0, 1, 0], atol=1e-9)


def test_project_without_actions_section_loads(tmp_path):
    p = Project("plain")
    p.create_object("box")
    path = str(tmp_path / "plain.am3d")
    serializer.save_project(p, path)   # no actions -> no section
    q = serializer.load_project(path)
    assert q.actions == {}
    assert "box" in q.objects


def test_session_save_load_project_roundtrip(tmp_path):
    from am3d.core.script import Session

    s = Session(Project("sess"))
    s.create_object("hero")
    act = s.create_action("idle", duration=1.5)
    act.add_channel("root").add_key(0.0, [0, 0, 0])

    path = str(tmp_path / "sess.am3d")
    s.save_project(path)

    s2 = Session()
    s2.load_project(path)
    assert s2.project.name == "sess"
    assert "hero" in s2.project.objects
    assert "idle" in s2.actions
    assert s2.get_action("idle").duration == 1.5


# ---------------------------------------------------------------------------
# Phase 2 Persistence, Material State, Safety Limits, and Undo Tests
# ---------------------------------------------------------------------------
import pytest
from am3d.core.serializer import ProjectFormatError, resolve_resource_path


def test_material_full_properties_roundtrip(tmp_path):
    p = Project("mat_test")
    obj = p.create_object("mesh")
    obj.material = "copper"
    profile = np.array([[0.5, 0.0], [1.0, 1.0], [0.6, 2.0], [0.4, 2.5]])
    patch1 = Patch(name="patch1", splines=["s1"],
                   interior=build_lathe_net(profile, sections=4),
                   material="copper")
    patch2 = Patch(name="patch2", splines=["s2"],
                   interior=build_lathe_net(profile, sections=4),
                   material="graph_mat")
    obj.patches.extend([patch1, patch2])

    p.materials["copper"] = Material(
        name="copper",
        color=(0.95, 0.64, 0.54),
        roughness=0.25,
        metalness=0.9,
        texture="textures/copper_albedo.png",
        pattern="noise",
        params={"octaves": 3, "contrast": 0.3},
        objects=["mesh"],
        bump_map="textures/copper_bump.png",
        transparency_map=None,
        specular_map="textures/copper_spec.png",
    )
    p.materials["graph_mat"] = Material(
        name="graph_mat",
        color=(0.8, 0.8, 0.8),
        roughness=0.6,
        metalness=0.1,
        graph=[{"type": "checker", "params": {"cells": 4}}],
        objects=["mesh"],
    )

    path = str(tmp_path / "mats.am3d")
    serializer.save_project(p, path)
    q = serializer.load_project(path)

    # Object and patch material bindings
    assert q.objects["mesh"].material == "copper"
    assert q.objects["mesh"].patches[0].material == "copper"
    assert q.objects["mesh"].patches[1].material == "graph_mat"

    # Material properties
    cop = q.materials["copper"]
    assert cop.name == "copper"
    assert np.allclose(cop.color, (0.95, 0.64, 0.54))
    assert abs(cop.roughness - 0.25) < 1e-6
    assert abs(cop.metalness - 0.9) < 1e-6
    assert cop.texture == "textures/copper_albedo.png"
    assert cop.pattern == "noise"
    assert cop.params == {"octaves": 3, "contrast": 0.3}
    assert cop.objects == ["mesh"]
    assert cop.bump_map == "textures/copper_bump.png"
    assert cop.specular_map == "textures/copper_spec.png"
    assert cop.transparency_map is None

    gmat = q.materials["graph_mat"]
    assert gmat.graph == [{"type": "checker", "params": {"cells": 4}}]
    assert abs(gmat.roughness - 0.6) < 1e-6
    assert abs(gmat.metalness - 0.1) < 1e-6


def test_session_authored_poses_roundtrip(tmp_path):
    from am3d.core.script import Session

    s = Session(Project("rig_session"))
    s.create_object("hero")
    s.add_bone("hero", "hip", [0, 0, 0], [0, 1, 0])
    s.add_bone("hero", "spine", [0, 1, 0], [0, 2, 0], parent="hip")

    # Author pose rotations and translation offsets
    rot = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]], dtype=np.float64)
    s.pose_bone("hero", "hip", rot)
    s.pose_offsets.setdefault("hero", {})["hip"] = np.array([0.1, 0.2, 0.3])
    s.apply_pose("hero")

    path = str(tmp_path / "rig.am3d")
    s.save_project(path)

    # Fresh session load
    s2 = Session()
    s2.load_project(path)

    assert "hero" in s2.poses
    assert "hip" in s2.poses["hero"]
    assert np.allclose(s2.poses["hero"]["hip"], rot)
    assert np.allclose(s2.pose_offsets["hero"]["hip"], [0.1, 0.2, 0.3])
    assert "hero" in s2.posed_transforms
    assert "hip" in s2.posed_transforms["hero"]


def test_session_preserves_explicit_active_action_none(tmp_path):
    from am3d.core.script import Session

    s = Session(Project("act_none"))
    s.create_action("walk", duration=1.0)
    s.create_action("run", duration=0.8)
    s.set_active_action(None)
    assert s.active_action is None

    path = str(tmp_path / "act_none.am3d")
    s.save_project(path)

    s2 = Session()
    s2.load_project(path)
    assert s2.active_action is None
    assert set(s2.actions) == {"walk", "run"}


def test_spline_point_weight_mismatch_raises_project_format_error():
    p = Project("bad_spline")
    obj = p.create_object("box")
    # Mismatch: 3 points, 2 weights
    raw_cps = [
        serializer._pack_ndarray(np.array([[0, 0, 0], [1, 0, 0], [2, 0, 0]], dtype=np.float64)),
        [1.0, 1.0],
    ]
    blob = serializer.dump_project(p)
    import msgpack
    data = msgpack.unpackb(blob, raw=False)
    data["objects"]["box"]["splines"]["s"] = {
        "degree": 3,
        "closed": False,
        "cps": raw_cps,
    }
    corrupted_blob = msgpack.packb(data, use_bin_type=True)

    with pytest.raises(ProjectFormatError, match="control point count .* does not match weight count"):
        serializer.load_project_bytes(corrupted_blob)


def test_spline_non_finite_coordinates_raises_project_format_error():
    p = Project("nan_spline")
    p.create_object("box")
    raw_cps = [
        serializer._pack_ndarray(np.array([[0, 0, 0], [float("nan"), 0, 0]], dtype=np.float64)),
        [1.0, 1.0],
    ]
    blob = serializer.dump_project(p)
    import msgpack
    data = msgpack.unpackb(blob, raw=False)
    data["objects"]["box"]["splines"]["s"] = {
        "degree": 3,
        "closed": False,
        "cps": raw_cps,
    }
    corrupted_blob = msgpack.packb(data, use_bin_type=True)

    with pytest.raises(ProjectFormatError, match="non-finite"):
        serializer.load_project_bytes(corrupted_blob)


def test_disallowed_dtype_raises_project_format_error():
    p = Project("bad_dtype")
    blob = serializer.dump_project(p)
    import msgpack
    data = msgpack.unpackb(blob, raw=False)
    data["objects"]["box"] = {
        "visible": True,
        "transform": {
            "__nd__": True,
            "shape": [4, 4],
            "dtype": "complex128",
            "data": b"\x00" * 256,
        },
        "splines": {},
        "patches": [],
        "hooks": [],
    }
    corrupted_blob = msgpack.packb(data, use_bin_type=True)

    with pytest.raises(ProjectFormatError, match="Disallowed or unknown numpy dtype"):
        serializer.load_project_bytes(corrupted_blob)


def test_array_elements_exceed_limit_raises_project_format_error():
    p = Project("huge_array")
    blob = serializer.dump_project(p)
    import msgpack
    data = msgpack.unpackb(blob, raw=False)
    data["objects"]["box"] = {
        "visible": True,
        "transform": {
            "__nd__": True,
            "shape": [10000, 2000],
            "dtype": "float32",
            "data": b"\x00" * 4,
        },
        "splines": {},
        "patches": [],
        "hooks": [],
    }
    corrupted_blob = msgpack.packb(data, use_bin_type=True)

    with pytest.raises(ProjectFormatError, match="Array element count .* exceeds limit"):
        serializer.load_project_bytes(corrupted_blob)


def test_container_depth_exceeded_raises_project_format_error():
    nested = {"name": "deep"}
    curr = nested
    for _ in range(25):
        curr["sub"] = {}
        curr = curr["sub"]
    import msgpack
    blob = msgpack.packb(nested, use_bin_type=True)

    with pytest.raises(ProjectFormatError, match="Container nesting depth .* exceeds safety limit"):
        serializer.load_project_bytes(blob)


def test_atomic_save_preserves_existing_file_on_error(tmp_path):
    target = tmp_path / "document.am3d"
    target.write_text("original-content", encoding="utf-8")

    # Pass an object that causes serialization to raise an error
    class BadProject:
        name = "bad"
        mode = "object"
        frame = 0.0
        fps = 30.0
        objects = {"obj": None}  # will trigger AttributeError when accessing obj.visible

    with pytest.raises(AttributeError):
        serializer.save_project(BadProject(), str(target))

    # Existing file must be 100% intact
    assert target.read_text(encoding="utf-8") == "original-content"
    # No temporary files should be left behind
    tmp_files = [p for p in tmp_path.iterdir() if p.name.startswith(".am3d_tmp_")]
    assert len(tmp_files) == 0


def test_delete_action_undo_restores_exact_dict_order():
    from am3d.core.script import Session
    from am3d.ui.operators import DeleteActionCommand

    s = Session()
    s.create_action("first")
    s.create_action("second")
    s.create_action("third")
    assert list(s.actions.keys()) == ["first", "second", "third"]

    cmd = DeleteActionCommand(s, "second")
    cmd.redo()
    assert list(s.actions.keys()) == ["first", "third"]

    cmd.undo()
    assert list(s.actions.keys()) == ["first", "second", "third"]


def test_rename_action_preserves_dict_order():
    from am3d.core.script import Session
    from am3d.ui.operators import RenameActionCommand

    s = Session()
    s.create_action("a")
    s.create_action("b")
    s.create_action("c")
    assert list(s.actions.keys()) == ["a", "b", "c"]

    cmd = RenameActionCommand(s, "b", "beta")
    cmd.redo()
    assert list(s.actions.keys()) == ["a", "beta", "c"]

    cmd.undo()
    assert list(s.actions.keys()) == ["a", "b", "c"]


def test_delete_object_undo_restores_poses_and_assignments():
    from am3d.core.script import Session
    from am3d.ui.operators import DeleteObjectCommand

    s = Session()
    s.create_object("hero")
    s.add_bone("hero", "hip", [0, 0, 0], [0, 1, 0])
    s.create_action("walk", duration=1.0)
    s.assign_action("walk", "hero")
    s.pose_bone("hero", "hip", np.eye(3))
    s.pose_offsets.setdefault("hero", {})["hip"] = np.array([0, 0.5, 0])

    cmd = DeleteObjectCommand(s, "hero")
    cmd.redo()
    assert "hero" not in s.project.objects
    assert "hero" not in s.poses
    assert "hero" not in s.action_assignments

    cmd.undo()
    assert "hero" in s.project.objects
    assert "hero" in s.poses
    assert "hip" in s.poses["hero"]
    assert np.allclose(s.pose_offsets["hero"]["hip"], [0, 0.5, 0])
    assert s.action_assignments.get("hero") == "walk"


def test_save_action_file_missing_action_raises_scripting_error(tmp_path):
    from am3d.core.script import Session, ScriptingError

    s = Session()
    target = tmp_path / "action.am3a"
    with pytest.raises(ScriptingError, match="no such action: 'nonexistent'"):
        s.save_action_file("nonexistent", str(target))


def test_legacy_samples_migrate():
    import os
    assets_dir = os.path.join(os.path.dirname(__file__), "..", "..", "assets")
    vase_path = os.path.join(assets_dir, "vase_demo.am3d")
    knight_path = os.path.join(assets_dir, "demo", "knight_project.am3d")
    walk_path = os.path.join(assets_dir, "walk.am3a")

    vase = serializer.load_project(vase_path)
    assert vase.name == "Vase demo"
    assert len(vase.objects) >= 1

    knight = serializer.load_project(knight_path)
    assert knight.name == "knight_demo"
    assert "steel" in knight.materials
    assert knight.materials["steel"].roughness == 0.5

    walk = serializer.load_action_file(walk_path)
    assert walk.name == "walk"
    assert walk.duration == 1.0


def test_resolve_resource_path():
    assert resolve_resource_path("") == ""
    assert resolve_resource_path("C:/abs/path.png") == "C:/abs/path.png"
    rel = resolve_resource_path("tex.png", "C:/projects/demo")
    assert rel.replace("\\", "/").endswith("projects/demo/tex.png")
    # When base_dir is None, relative paths are preserved as relative
    assert resolve_resource_path("relative/tex.png") == "relative/tex.png"


def test_max_channels_enforced():
    import msgpack
    # Channels count exceeding _MAX_CHANNELS = 2000
    oversized = [{"bone": f"b_{i}", "property": "translate", "keys": []}
                 for i in range(2001)]
    act_dict = {
        "__action__": True,
        "name": "too_many_channels",
        "duration": 1.0,
        "channels": oversized,
    }
    payload = msgpack.packb(act_dict)
    with pytest.raises(ProjectFormatError, match="Action channel count"):
        serializer.load_action(payload)

    # In project validate_project_data
    proj_dict = {
        "name": "test_proj",
        "objects": {},
        "skeletons": {},
        "actions": {"items": {"oversized_act": {"channels": oversized}}},
    }
    with pytest.raises(ProjectFormatError, match="exceeds channel limit"):
        serializer.validate_project_data(proj_dict)


def test_spline_non_positive_weights_raises_project_format_error(tmp_path):
    # Zero weight
    p = Project("zero_weight")
    obj = p.create_object("s")
    obj.add_spline(Spline(name="bad", cps=[ControlPoint((0, 0, 0), weight=0.0)]))
    raw = serializer.dump_project(p)
    with pytest.raises(ProjectFormatError, match="weights must be positive"):
        serializer.load_project_bytes(raw)

    # Negative weight
    p2 = Project("neg_weight")
    obj2 = p2.create_object("s")
    obj2.add_spline(Spline(name="bad", cps=[ControlPoint((0, 0, 0), weight=-0.5)]))
    raw2 = serializer.dump_project(p2)
    with pytest.raises(ProjectFormatError, match="weights must be positive"):
        serializer.load_project_bytes(raw2)


def test_atomic_write_cleans_up_tempfile_on_replace_error(tmp_path, monkeypatch):
    import os
    target = tmp_path / "save_target.am3d"
    target.write_text("prior-good-content", encoding="utf-8")

    def mock_replace(src, dst):
        raise OSError("Simulated disk replacement error")

    monkeypatch.setattr(os, "replace", mock_replace)
    with pytest.raises(OSError, match="Simulated disk replacement error"):
        serializer._atomic_write(str(target), b"new-payload")

    # Original file must remain intact
    assert target.read_text(encoding="utf-8") == "prior-good-content"
    # Temp file must be cleanly unlinked
    tmp_files = [p for p in tmp_path.iterdir() if p.name.startswith(".am3d_tmp_")]
    assert len(tmp_files) == 0


def test_session_load_project_preserves_session_on_candidate_failure(tmp_path):
    from am3d.core.script import Session
    from am3d.core.project import Bone

    s = Session(Project("original"))
    s.create_object("hero")
    s.poses["hero"] = {"hip": np.eye(3)}

    # Create a project with invalid pose rotation shape (e.g. shape (5, 5))
    corrupt_proj = Project("corrupt")
    corrupt_proj.create_object("hero")
    corrupt_proj.skeletons["hero"] = {"hip": Bone("hip", (0, 0, 0), (0, 1, 0))}
    corrupt_proj.poses["hero"] = {"hip": np.ones((5, 5))}
    bad_path = str(tmp_path / "corrupt.am3d")
    # Save raw corrupt project
    serializer._atomic_write(bad_path, serializer.dump_project(corrupt_proj))

    # Loading corrupt project fails during candidate pose verification
    with pytest.raises(Exception):
        s.load_project(bad_path)

    # Session state must be completely preserved without partial clobbering
    assert s.project.name == "original"
    assert "hero" in s.project.objects
    assert "hip" in s.poses["hero"]
    assert s.poses["hero"]["hip"].shape == (3, 3)


def test_delete_object_undo_restores_posed_transforms_on_rest_rig():
    from am3d.core.script import Session
    from am3d.ui.operators import DeleteObjectCommand

    s = Session()
    s.create_object("knight")
    s.add_bone("knight", "root", (0, 0, 0), (0, 1, 0))
    # In rest pose, session.poses is empty, but apply_pose populates posed_transforms
    s.apply_pose("knight")
    assert "knight" in s.posed_transforms

    cmd = DeleteObjectCommand(s, "knight")
    cmd.redo()
    assert "knight" not in s.project.objects
    assert "knight" not in s.posed_transforms

    cmd.undo()
    assert "knight" in s.project.objects
    assert "knight" in s.posed_transforms
    assert "root" in s.posed_transforms["knight"]


def test_set_bone_endpoints_command_updates_posed_transforms():
    from am3d.core.script import Session
    from am3d.ui.operators import SetBoneEndpointsCommand

    s = Session()
    s.create_object("figure")
    s.add_bone("figure", "arm", (0, 0, 0), (1, 0, 0))
    s.apply_pose("figure")
    t0 = s.posed_transforms["figure"]["arm"][:3, 3].copy()

    cmd = SetBoneEndpointsCommand(s, "figure", "arm",
                                  before=((0, 0, 0), (1, 0, 0)),
                                  after=((0, 2, 0), (1, 2, 0)))
    cmd.redo()
    t1 = s.posed_transforms["figure"]["arm"][:3, 3].copy()
    assert not np.allclose(t0, t1)

    cmd.undo()
    t2 = s.posed_transforms["figure"]["arm"][:3, 3].copy()
    assert np.allclose(t0, t2)


def test_create_action_command_undo_restores_active_action_none():
    from am3d.core.script import Session
    from am3d.ui.operators import CreateActionCommand

    s = Session()
    assert s.active_action is None

    cmd = CreateActionCommand(s, "new_action")
    cmd.redo()
    assert s.active_action == "new_action"

    cmd.undo()
    assert "new_action" not in s.actions
    assert s.active_action is None


def test_project_remove_and_rename_object_maintains_order_and_assignments():
    from am3d.core.script import Session

    p = Project("ordering_test")
    p.create_object("first")
    p.create_object("second")
    p.create_object("third")
    p.action_assignments = {"first": "act1", "second": "act2", "third": "act3"}
    p.skeletons = {"first": {}, "second": {}, "third": {}}
    p.poses = {"first": {}, "second": {}, "third": {}}
    p.pose_offsets = {"first": {}, "second": {}, "third": {}}

    # Renaming 'second' to 'two' preserves dict order in objects, skeletons, poses, pose_offsets, action_assignments
    p.rename_object("second", "two")
    assert list(p.objects.keys()) == ["first", "two", "third"]
    assert list(p.skeletons.keys()) == ["first", "two", "third"]
    assert list(p.poses.keys()) == ["first", "two", "third"]
    assert list(p.pose_offsets.keys()) == ["first", "two", "third"]
    assert list(p.action_assignments.keys()) == ["first", "two", "third"]
    assert p.action_assignments["two"] == "act2"

    # Removing 'two' cleans up action_assignments
    p.remove_object("two")
    assert "two" not in p.action_assignments
    assert list(p.action_assignments.keys()) == ["first", "third"]

    # Session rename object with identical name is no-op and preserves order
    s = Session(p)
    s.rename_object("first", "first")
    assert list(s.project.objects.keys()) == ["first", "third"]


# -- malformed spline records are rejected, not silently truncated ------


def _spline_project():
    p = Project("corrupt")
    obj = p.create_object("o")
    cps = [ControlPoint(np.array([float(i), 0.0, 0.0])) for i in range(4)]
    obj.add_spline(Spline(name="s", cps=cps, degree=3))
    return p


def _corrupt(mutate):
    """Round-trip a project through msgpack, mutating the spline record."""
    import msgpack

    data = msgpack.unpackb(serializer.dump_project(_spline_project()),
                           raw=False)
    mutate(data["objects"]["o"]["splines"]["s"])
    return msgpack.packb(data, use_bin_type=True)


def test_spline_roundtrip_keeps_every_control_point():
    """Baseline: the honest path must not lose control points."""
    q = serializer.load_project_bytes(
        serializer.dump_project(_spline_project()))
    assert len(q.objects["o"].splines["s"].cps) == 4


def test_truncated_weights_are_rejected_not_silently_dropped():
    """zip() would have yielded 2 control points instead of 4."""
    payload = _corrupt(lambda s: s.__setitem__(
        "cps", [s["cps"][0], s["cps"][1][:2]]))
    with pytest.raises(serializer.ProjectFormatError) as excinfo:
        serializer.load_project_bytes(payload)
    msg = str(excinfo.value)
    assert "control point count (4) does not match weight count (2)" in msg
    assert "spline 's'" in msg      # field path, not a bare error


def test_surplus_weights_are_rejected():
    payload = _corrupt(lambda s: s.__setitem__(
        "cps", [s["cps"][0], list(s["cps"][1]) + [1.0, 1.0]]))
    with pytest.raises(serializer.ProjectFormatError):
        serializer.load_project_bytes(payload)


@pytest.mark.parametrize("field", ["cps", "degree", "closed"])
def test_missing_spline_field_raises_project_format_error(field):
    """Previously a bare KeyError escaped the loader."""
    payload = _corrupt(lambda s, f=field: s.pop(f))
    with pytest.raises(serializer.ProjectFormatError) as excinfo:
        serializer.load_project_bytes(payload)
    assert repr(field) in str(excinfo.value)


@pytest.mark.parametrize("bad", [None, "nope", [], [1, 2, 3], {}])
def test_malformed_cps_container_raises_project_format_error(bad):
    payload = _corrupt(lambda s, b=bad: s.__setitem__("cps", b))
    with pytest.raises(serializer.ProjectFormatError):
        serializer.load_project_bytes(payload)


@pytest.mark.parametrize("bad_degree", [0, -1, 1.5, "3", True])
def test_invalid_spline_degree_is_rejected(bad_degree):
    """degree must be an int >= 1 -- 0/negative/non-int previously loaded
    unchecked and only surfaced as a crash later, in tessellation."""
    payload = _corrupt(lambda s, d=bad_degree: s.__setitem__("degree", d))
    with pytest.raises(serializer.ProjectFormatError) as excinfo:
        serializer.load_project_bytes(payload)
    assert "degree" in str(excinfo.value)


@pytest.mark.parametrize("bad_closed", [0, 1, "yes", None])
def test_non_bool_closed_is_rejected(bad_closed):
    payload = _corrupt(lambda s, c=bad_closed: s.__setitem__("closed", c))
    with pytest.raises(serializer.ProjectFormatError) as excinfo:
        serializer.load_project_bytes(payload)
    assert "closed" in str(excinfo.value)


def test_corrupt_declared_shape_surfaces_as_project_format_error():
    """A points/weights count that agrees (so passes length validation)
    but whose declared array shape lies about the actual packed byte count
    must still fail structured, not as a raw numpy ValueError from
    reshape() escaping the loader."""
    def mutate(s):
        pts = s["cps"][0]
        pts["shape"] = [pts["shape"][0] + 1, *pts["shape"][1:]]
        s["cps"] = [pts, list(s["cps"][1]) + [1.0]]

    payload = _corrupt(mutate)
    with pytest.raises(serializer.ProjectFormatError) as excinfo:
        serializer.load_project_bytes(payload)
    assert "byte length mismatch" in str(excinfo.value)


def test_disallowed_dtype_is_rejected():
    """dtype was declared but unenforced; a lying dtype string previously
    reached np.frombuffer unchecked."""
    payload = _corrupt(lambda s: s["cps"][0].__setitem__("dtype", "complex128"))
    with pytest.raises(serializer.ProjectFormatError) as excinfo:
        serializer.load_project_bytes(payload)
    assert "dtype" in str(excinfo.value)


def test_deeply_nested_project_data_is_rejected():
    """_MAX_CONTAINER_DEPTH was declared but unenforced."""
    import msgpack

    nested = {}
    cur = nested
    for _ in range(serializer._MAX_CONTAINER_DEPTH + 5):
        cur["x"] = {}
        cur = cur["x"]
    payload = msgpack.packb(nested, use_bin_type=True)
    with pytest.raises(serializer.ProjectFormatError) as excinfo:
        serializer.load_project_bytes(payload)
    assert "exceeds safety limit" in str(excinfo.value)


def test_deeply_nested_action_data_is_rejected():
    """load_action gets the same depth guard as load_project_bytes."""
    import msgpack

    nested = {}
    cur = nested
    for _ in range(serializer._MAX_CONTAINER_DEPTH + 5):
        cur["x"] = {}
        cur = cur["x"]
    payload = msgpack.packb(nested, use_bin_type=True)
    with pytest.raises(serializer.ProjectFormatError):
        serializer.load_action(payload)


def test_oversized_array_is_rejected(monkeypatch):
    """_MAX_ARRAY_ELEMENTS was declared but unenforced; a claimed array
    length beyond the limit must fail structured, not as a raw msgpack
    ValueError escaping the loader."""
    monkeypatch.setattr(serializer, "_MAX_ARRAY_ELEMENTS", 3)
    payload = serializer.dump_project(_spline_project())    # 4 weights
    with pytest.raises(serializer.ProjectFormatError) as excinfo:
        serializer.load_project_bytes(payload)
    assert "Malformed msgpack data" in str(excinfo.value)


def test_future_format_version_is_rejected():
    """format_version was written but never read; a file from a newer,
    incompatible build must not be silently misinterpreted."""
    import msgpack

    data = msgpack.unpackb(serializer.dump_project(_spline_project()),
                           raw=False)
    data["format_version"] = serializer.FORMAT_VERSION + 1
    payload = msgpack.packb(data, use_bin_type=True)
    with pytest.raises(serializer.ProjectFormatError) as excinfo:
        serializer.load_project_bytes(payload)
    assert "format version" in str(excinfo.value).lower()


def test_missing_format_version_still_loads():
    """Files saved before this field existed (format 1) must still open."""
    import msgpack

    data = msgpack.unpackb(serializer.dump_project(_spline_project()),
                           raw=False)
    del data["format_version"]
    payload = msgpack.packb(data, use_bin_type=True)
    q = serializer.load_project_bytes(payload)
    assert "o" in q.objects


def test_rejected_file_does_not_partially_construct(tmp_path):
    """A malformed file must fail before it can replace a live session."""
    from am3d.core.script import Session

    good = tmp_path / "good.am3d"
    serializer.save_project(_spline_project(), str(good))
    s = Session()
    s.load_project(str(good))

    bad = tmp_path / "bad.am3d"
    bad.write_bytes(_corrupt(lambda sp: sp.__setitem__(
        "cps", [sp["cps"][0], sp["cps"][1][:1]])))
    with pytest.raises(serializer.ProjectFormatError):
        s.load_project(str(bad))
    # the previously loaded project is still intact
    assert len(s.project.objects["o"].splines["s"].cps) == 4
