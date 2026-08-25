"""Tests for the serializer / Action-reuse asset format."""

from __future__ import annotations

import numpy as np

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