"""Tests for the authoritative scene evaluation boundary (Phase 3)."""

from __future__ import annotations

import numpy as np
import pytest

from am3d.core.mathutil import transform_mesh_geometry
from am3d.core.naming import allocate_unique_name
from am3d.core.project import Bone, ControlPoint, Object3D, Patch, Spline
from am3d.core.rigging import auto_weight_object, deform_object, fk_pose
from am3d.core.scene import EvaluatedScene, evaluate_scene, scene_material_colors
from am3d.core.script import Session
from am3d.recipes.animation import generate_action, generate_idle, generate_walk_cycle
from am3d.renderer.tessellate import MeshData, tessellate_object


def _make_two_bone_arm():
    """Two-bone arm along +Y: lower [0, 0, 0] -> [0, 1, 0], upper [0, 1, 0] -> [0, 2, 0]."""
    b1 = Bone(name="lower", head=[0.0, 0.0, 0.0], tail=[0.0, 1.0, 0.0])
    b2 = Bone(name="upper", parent="lower", head=[0.0, 1.0, 0.0], tail=[0.0, 2.0, 0.0])
    return [b1, b2]


def _make_test_cylinder(name="arm", radius=0.3, height=2.0, sections=8, rings=6):
    """Build an Object3D cylinder with spline rings along +Y."""
    obj = Object3D(name=name)
    # Build 2-sided patch interior net (rings along Y)
    net = np.zeros((rings, sections + 1, 3), dtype=np.float64)
    for r in range(rings):
        y = height * r / (rings - 1)
        for s in range(sections + 1):
            theta = 2.0 * np.pi * s / sections
            net[r, s] = [radius * np.cos(theta), y, radius * np.sin(theta)]
    obj.patches.append(Patch(name="cyl_patch", splines=[], interior=net))
    return obj


# ---------------------------------------------------------------------------
# 1. Transform Mesh Geometry & Normal Integrity
# ---------------------------------------------------------------------------

def test_transform_mesh_geometry_identity():
    verts = np.array([[1.0, 2.0, 3.0]], dtype=np.float64)
    normals = np.array([[0.0, 1.0, 0.0]], dtype=np.float64)
    indices = np.array([[0, 1, 2]], dtype=np.int64)
    v, n, idx = transform_mesh_geometry(verts, normals, indices, np.eye(4))
    assert np.allclose(v, verts)
    assert np.allclose(n, normals)
    assert np.array_equal(idx, indices)


def test_transform_mesh_geometry_non_uniform_scale_normals():
    """Non-uniform scale transforms normals using inverse transpose (A^-1)^T."""
    # A triangle on the XY plane with normal facing +Z
    verts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)
    normals = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    indices = np.array([[0, 1, 2]], dtype=np.int64)

    # Scale non-uniformly: X by 4, Y by 1, Z by 2
    S = np.diag([4.0, 1.0, 2.0, 1.0])
    v, n, idx = transform_mesh_geometry(verts, normals, indices, S)

    # Normals should still point purely along +Z because the triangle remains in the XY plane
    for normal in n:
        assert np.isclose(normal[0], 0.0)
        assert np.isclose(normal[1], 0.0)
        assert np.isclose(normal[2], 1.0)
        assert np.isclose(np.linalg.norm(normal), 1.0)


def test_transform_mesh_geometry_reflection_flips_winding():
    """Mirrored transforms (det < 0) flip triangle winding so faces don't invert."""
    verts = np.array([[0.0, 0.0, 0.0], [1.0, 0.0, 0.0], [0.0, 1.0, 0.0]], dtype=np.float64)
    normals = np.array([[0.0, 0.0, 1.0], [0.0, 0.0, 1.0], [0.0, 0.0, 1.0]], dtype=np.float64)
    indices = np.array([[0, 1, 2]], dtype=np.int64)

    # Mirror along X (det = -1)
    M = np.diag([-1.0, 1.0, 1.0, 1.0])
    v, n, idx = transform_mesh_geometry(verts, normals, indices, M)

    # Column 1 and 2 must be swapped: [0, 1, 2] -> [0, 2, 1]
    assert np.array_equal(idx, np.array([[0, 2, 1]], dtype=np.int64))


def test_transform_mesh_geometry_singular_matrix_raises():
    """Singular transform matrix (|det| < 1e-12) raises ValueError."""
    verts = np.array([[1.0, 2.0, 3.0]], dtype=np.float64)
    normals = np.array([[0.0, 1.0, 0.0]], dtype=np.float64)
    indices = np.array([[0, 1, 2]], dtype=np.int64)
    singular = np.diag([1.0, 0.0, 1.0, 1.0])  # zero Y scale -> det = 0
    with pytest.raises(ValueError, match="Singular transform matrix"):
        transform_mesh_geometry(verts, normals, indices, singular)


# ---------------------------------------------------------------------------
# 2. Centralized Naming Allocation
# ---------------------------------------------------------------------------

def test_allocate_unique_name_free():
    names = {"box", "sphere"}
    assert allocate_unique_name(names, "cylinder") == "cylinder"


def test_allocate_unique_name_collision():
    names = {"cylinder", "cylinder_001", "cylinder_002"}
    assert allocate_unique_name(names, "cylinder") == "cylinder_003"


def test_allocate_unique_name_exhaustion_raises():
    names = {f"item_{i:03d}" for i in range(1, 11)}  # block item_001..item_010
    names.add("item")
    with pytest.raises(RuntimeError, match="Naming collision limit reached"):
        allocate_unique_name(names, "item", max_attempts=10)


# ---------------------------------------------------------------------------
# 3. Deterministic Proximity Weighting
# ---------------------------------------------------------------------------

def test_auto_weight_object_two_bone_arm():
    """auto_weight_object assigns proximity weights summing to 1.0."""
    obj = _make_test_cylinder("arm", radius=0.2, height=2.0, sections=4, rings=5)
    bones = _make_two_bone_arm()

    weights = auto_weight_object(obj, bones, max_influences=2, assign=True)
    assert set(weights.keys()) == {"lower", "upper"}

    # Lower CPs (near Y=0) should have dominant weight on "lower" bone
    # Upper CPs (near Y=2) should have dominant weight on "upper" bone
    assert weights["lower"][0] > 0.8
    total_cp_count = sum(len(w) for w in weights.values())
    assert total_cp_count > 0

    # Ensure bones have cp_weights populated
    assert bones[0].cp_weights == weights["lower"]
    assert bones[1].cp_weights == weights["upper"]

    # Ensure weights for every control point sum strictly to 1.0
    all_cp_indices = set(weights["lower"].keys()) | set(weights["upper"].keys())
    for cp_idx in all_cp_indices:
        cp_sum = weights["lower"].get(cp_idx, 0.0) + weights["upper"].get(cp_idx, 0.0)
        assert cp_sum == pytest.approx(1.0, abs=1e-5)


# ---------------------------------------------------------------------------
# 4. Shared Scene Evaluation Boundary & Rigged Deformation
# ---------------------------------------------------------------------------

def test_evaluate_scene_purity_no_cumulative_mutation():
    """evaluate_scene does not alter bind control points or cached meshes."""
    s = Session()
    s.create_object("arm")
    obj = _make_test_cylinder("arm", radius=0.2, height=2.0, sections=4, rings=4)
    s.project.objects["arm"] = obj
    orig_interior = obj.patches[0].interior.copy()

    bones = _make_two_bone_arm()
    for b in bones:
        s.add_bone("arm", b.name, b.head, b.tail, parent=b.parent)
    auto_weight_object(obj, s.get_bones("arm"), assign=True)

    # Pose bone by 90 degrees
    s.pose_bone("arm", "upper", [0, 0, 90])
    s.apply_pose("arm")

    # Evaluate multiple times
    scene1 = s.evaluate_scene(apply_transforms=True)
    scene2 = s.evaluate_scene(apply_transforms=True)

    # Control points in canonical object must be completely untouched
    assert np.allclose(obj.patches[0].interior, orig_interior)

    # Evaluated meshes must be equivalent across runs
    assert np.allclose(scene1.meshes["arm"].vertices, scene2.meshes["arm"].vertices)


def test_evaluate_scene_visible_deformation_between_frames():
    """An animated weighted character visibly changes shape across action frames."""
    s = Session()
    s.create_object("hero")
    obj = _make_test_cylinder("hero", radius=0.2, height=2.0, sections=6, rings=6)
    s.project.objects["hero"] = obj
    bones = _make_two_bone_arm()
    for b in bones:
        s.add_bone("hero", b.name, b.head, b.tail, parent=b.parent)
    auto_weight_object(obj, s.get_bones("hero"), assign=True)

    # Create walk action and assign to hero
    act = generate_walk_cycle(bones, duration=1.0)
    s.actions[act.name] = act
    s.assign_action(act.name, "hero")
    s.set_active_action(act.name)

    # Sample at t=0.0 and t=0.25 (quarter-cycle swing)
    frame0 = s.evaluate_scene(time=0.0)
    frame1 = s.evaluate_scene(time=0.25)

    v0 = frame0.meshes["hero"].vertices
    v1 = frame1.meshes["hero"].vertices

    # Geometry must have deformed visibly between frames
    delta = np.linalg.norm(v1 - v0, axis=1)
    assert np.max(delta) > 0.05, "Character must visibly change shape across animation frames"


def test_evaluate_scene_honors_visibility():
    """Objects with visible=False are excluded when visible_only=True."""
    s = Session()
    s.create_object("visible_obj")
    s.create_object("hidden_obj")
    s.project.objects["visible_obj"] = _make_test_cylinder("visible_obj", height=1.0)
    s.project.objects["hidden_obj"] = _make_test_cylinder("hidden_obj", height=1.0)
    s.project.objects["hidden_obj"].visible = False

    scene_vis = s.evaluate_scene(visible_only=True)
    assert "visible_obj" in scene_vis.meshes
    assert "hidden_obj" not in scene_vis.meshes

    scene_all = s.evaluate_scene(visible_only=False)
    assert "visible_obj" in scene_all.meshes
    assert "hidden_obj" in scene_all.meshes


def test_evaluate_scene_multi_object_bounds():
    """Overall scene bounds encompass transformed world bounds of all visible meshes."""
    s = Session()
    s.create_object("obj1")
    s.create_object("obj2")
    s.project.objects["obj1"] = _make_test_cylinder("obj1", radius=0.5, height=1.0)
    s.project.objects["obj2"] = _make_test_cylinder("obj2", radius=0.5, height=1.0)

    # Translate obj2 by +10 along X
    m2 = np.eye(4, dtype=np.float64)
    m2[0, 3] = 10.0
    s.project.objects["obj2"].transform = m2

    scene = s.evaluate_scene(apply_transforms=True)
    min_b, max_b = scene.bounds
    assert max_b[0] > 9.5
    assert min_b[0] < 0.5


def test_scene_material_colors_reads_bound_objects_only():
    """scene_material_colors is the single source of truth OBJ/GLB export
    and the GUI export path both draw from — it must reflect exactly the
    object -> material -> colour bindings on the evaluated scene, skipping
    unbound objects and materials with no colour."""
    s = Session()
    s.project.objects["colored"] = _make_test_cylinder("colored", radius=0.5, height=1.0)
    s.project.objects["plain"] = _make_test_cylinder("plain", radius=0.5, height=1.0)
    mat = s.create_material("blue", color=(0.1, 0.2, 0.9))
    s.project.objects["colored"].material = "blue"

    scene = s.evaluate_scene()
    colors = scene_material_colors(scene)

    assert colors == {"colored": (0.1, 0.2, 0.9, 1.0)}
    assert "plain" not in colors


# ---------------------------------------------------------------------------
# 5. Animation Keyframe Hygiene & Loop Continuity
# ---------------------------------------------------------------------------

def test_channel_add_key_replaces_duplicate_timestamp():
    """add_key at an existing timestamp replaces value in place without duplicates."""
    from am3d.core.animation import Channel, Interpolation
    ch = Channel(bone="hip", property="translate")
    ch.add_key(0.0, [0.0, 0.0, 0.0])
    ch.add_key(0.5, [0.0, 0.5, 0.0])
    ch.add_key(1.0, [0.0, 1.0, 0.0])

    # Re-key at 0.5 with a new value
    ch.add_key(0.5, [0.0, 0.9, 0.0])

    assert len(ch.keys) == 3
    assert np.isclose(ch.keys[1].time, 0.5)
    assert np.allclose(ch.keys[1].value, [0.0, 0.9, 0.0])
    assert ch.sample(0.5)[1] == pytest.approx(0.9)


def test_idle_loop_continuity_zero_seam():
    """generate_idle rotation at t=0 and t=duration match identically."""
    bones = _make_two_bone_arm()
    act = generate_idle(bones, duration=2.0)

    for ch in act.channels:
        if ch.property == "rotate":
            first_val = ch.sample(0.0)
            last_val = ch.sample(act.duration)
            assert np.allclose(first_val, last_val, atol=1e-7), (
                f"Idle loop seam detected on {ch.bone}: {first_val} != {last_val}"
            )


# ---------------------------------------------------------------------------
# 6. Retargeting with Distinct Skeletons & Persisted Provenance
# ---------------------------------------------------------------------------

def test_retarget_with_distinct_skeletons_and_lengths():
    """Retargeting between differing skeleton lengths scales translation proportionally."""
    from am3d.core.retarget import retarget_action
    from am3d.core.animation import Action

    # Source skeleton: bone length = 1.0
    src_bones = [Bone(name="leg", head=[0, 1, 0], tail=[0, 0, 0])]
    # Target skeleton: bone length = 2.0
    tgt_bones = [Bone(name="leg", head=[0, 2, 0], tail=[0, 0, 0])]

    src_act = Action(name="kick", duration=1.0)
    ch = src_act.add_channel("leg", "translate")
    ch.add_key(0.0, [0.0, 0.0, 0.0])
    ch.add_key(0.5, [0.0, 0.5, 0.0])
    ch.add_key(1.0, [0.0, 0.0, 0.0])

    retargeted = retarget_action(src_act, src_bones, tgt_bones)

    assert retargeted.metadata["retargeted_from"] == "kick"
    # Target bone length is 2x source; translation amplitude at t=0.5 should be scaled by 2.0 -> 1.0
    tgt_ch = retargeted.get_channel("leg", "translate")
    assert tgt_ch.sample(0.5)[1] == pytest.approx(1.0)


def test_multi_skeleton_scene_evaluation():
    """Scenes with multiple distinct skeletons and action assignments evaluate each independently."""
    s = Session()
    s.new_project("duel")

    # Character 1: Hero
    s.create_object("hero")
    cyl_hero = _make_test_cylinder("hero_body", radius=0.2, height=2.0)
    s.project.objects["hero"].patches = cyl_hero.patches
    s.add_bone("hero", "hip", [0, 0, 0], [0, 1, 0])
    s.add_bone("hero", "spine", [0, 1, 0], [0, 2, 0], parent="hip")
    auto_weight_object(s.project.objects["hero"], s.get_bones("hero"))

    # Character 2: Villain
    s.create_object("villain")
    cyl_villain = _make_test_cylinder("villain_body", radius=0.2, height=2.0)
    s.project.objects["villain"].patches = cyl_villain.patches
    s.add_bone("villain", "hip", [0, 0, 0], [0, 1, 0])
    s.add_bone("villain", "spine", [0, 1, 0], [0, 2, 0], parent="hip")
    auto_weight_object(s.project.objects["villain"], s.get_bones("villain"))

    # Assign distinct actions
    hero_act = generate_walk_cycle(s.get_bones("hero"), name="hero_walk", duration=1.0)
    villain_act = generate_idle(s.get_bones("villain"), name="villain_idle", duration=1.0)
    s.actions["hero_walk"] = hero_act
    s.actions["villain_idle"] = villain_act

    s.assign_action("hero_walk", "hero")
    s.assign_action("villain_idle", "villain")

    # Evaluate at t=0.25
    eval_scene = s.evaluate_scene(time=0.25)
    rest_scene = s.evaluate_scene(time=None)

    v_hero_rest = rest_scene.meshes["hero"].vertices
    v_hero_eval = eval_scene.meshes["hero"].vertices
    v_villain_rest = rest_scene.meshes["villain"].vertices
    v_villain_eval = eval_scene.meshes["villain"].vertices

    # Both characters must visibly deform from rest pose
    assert np.max(np.linalg.norm(v_hero_eval - v_hero_rest, axis=1)) > 0.01
    assert np.max(np.linalg.norm(v_villain_eval - v_villain_rest, axis=1)) > 0.01


def test_evaluate_scene_save_reload_equivalence(tmp_path):
    """Evaluating a scene, saving to .am3d, and reloading yields equivalent sampled geometry."""
    s1 = Session()
    s1.new_project("knight_run")
    s1.create_object("knight")
    cyl = _make_test_cylinder("body", radius=0.3, height=2.0, sections=6, rings=4)
    s1.project.objects["knight"].patches = cyl.patches
    s1.add_bone("knight", "b1", [0, 0, 0], [0, 1, 0])
    s1.add_bone("knight", "b2", [0, 1, 0], [0, 2, 0], parent="b1")
    auto_weight_object(s1.project.objects["knight"], s1.get_bones("knight"))

    act = generate_walk_cycle(s1.get_bones("knight"), name="walk", duration=1.0)
    s1.actions["walk"] = act
    s1.assign_action("walk", "knight")

    # Evaluate original session at t=0.25
    eval1 = s1.evaluate_scene(time=0.25)

    save_file = tmp_path / "knight_run.am3d"
    s1.save_project(str(save_file))

    # Reload into fresh session
    s2 = Session()
    s2.load_project(str(save_file))
    eval2 = s2.evaluate_scene(time=0.25)

    assert set(eval1.meshes.keys()) == set(eval2.meshes.keys())
    m1 = eval1.meshes["knight"]
    m2 = eval2.meshes["knight"]
    assert np.allclose(m1.vertices, m2.vertices, atol=1e-6)
    assert np.allclose(m1.normals, m2.normals, atol=1e-5)


def test_evaluate_scene_explicit_euler_degrees_pose():
    """Explicit pose dict in degrees poses bone accurately without radian corruption."""
    s = Session()
    s.new_project("pose_test")
    s.create_object("arm")
    cyl = _make_test_cylinder("arm_body", radius=0.2, height=2.0)
    s.project.objects["arm"].patches = cyl.patches
    s.add_bone("arm", "b1", [0, 0, 0], [0, 1, 0])
    s.add_bone("arm", "b2", [0, 1, 0], [0, 2, 0], parent="b1")
    auto_weight_object(s.project.objects["arm"], s.get_bones("arm"))

    # 90 degrees around Z axis on bone b2
    pose = {"arm": {"b2": [0.0, 0.0, 90.0]}}
    scene = s.evaluate_scene(pose=pose)
    rest_scene = s.evaluate_scene(time=None)

    v_rest = rest_scene.meshes["arm"].vertices
    v_posed = scene.meshes["arm"].vertices

    # Must visibly deform
    diff = np.linalg.norm(v_posed - v_rest, axis=1)
    assert np.max(diff) > 0.1
    # Check that rotation did not explode into thousands of degrees
    assert np.max(diff) < 5.0


def test_evaluate_scene_spline_control_point_purity():
    """Repeated scene evaluations preserve pristine spline control points on project objects."""
    s = Session()
    s.new_project("spline_test")
    s.create_object("curve_obj")
    cps = [
        np.array([0.0, 0.0, 0.0]),
        np.array([1.0, 1.0, 0.0]),
        np.array([2.0, 0.0, 0.0]),
    ]
    s.add_spline("curve_obj", cps, name="curve")

    orig_pts = s.project.objects["curve_obj"].splines["curve"].point_array().copy()

    for t in [0.0, 0.5, 1.0]:
        s.evaluate_scene(time=t)

    after_pts = s.project.objects["curve_obj"].splines["curve"].point_array()
    assert np.allclose(orig_pts, after_pts)


def test_session_insert_keyframe_resets_tangents_and_updates_interp():
    """Session.insert_keyframe cleanly replaces key, updates interp, and clears tangents."""
    from am3d.core.animation import Interpolation
    s = Session()
    s.new_project("key_test")
    s.create_object("char")
    s.add_bone("char", "root", [0, 0, 0], [0, 1, 0])
    act = s.create_action("test_act", duration=2.0)

    # Insert initial key with LINEAR
    k1 = s.insert_keyframe("test_act", "root", "translate", 0.5, [1.0, 0.0, 0.0], interp=Interpolation.LINEAR)
    k1.in_tangent = np.array([0.1, 0.0, 0.0])
    k1.out_tangent = np.array([0.1, 0.0, 0.0])

    # Overwrite at the exact same timestamp with STEP (hold-constant interpolation)
    k2 = s.insert_keyframe("test_act", "root", "translate", 0.5, [2.0, 0.0, 0.0], interp=Interpolation.STEP)

    ch = act.get_channel("root", "translate")
    assert len(ch.keys) == 1
    assert ch.keys[0].interp == Interpolation.STEP
    assert np.allclose(ch.keys[0].value, [2.0, 0.0, 0.0])
    assert ch.keys[0].in_tangent is None
    assert ch.keys[0].out_tangent is None
