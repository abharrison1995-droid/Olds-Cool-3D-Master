"""Reopened rig bindings and sampled action deformation checks."""
from __future__ import annotations

import numpy as np
from ._check_report import _check
from ._scene_checks import _find_name

def _check_animation(report, recipe, requirements, brief, session, scene, diagonal):
    project = session.project
    rig = requirements.get("rig", {}) if isinstance(requirements, dict) else {}
    animation = brief.get("animation") if isinstance(brief, dict) else None
    rig = rig if isinstance(rig, dict) else {}
    missing_bones = []
    rig_requested = bool(rig.get("required"))
    if rig_requested:
        required_bones = rig.get("expected_bones", []) or []
        bone_names = {bone.name for bones in project.skeletons.values() for bone in bones.values()}
        missing_bones = [name for name in required_bones if name not in bone_names]
        binding_issues = []
        bound_components = rig.get("bound_components", []) or []
        if not bound_components and project.skeletons:
            bound_components = list(project.skeletons)
        for component in bound_components[:64]:
            object_name = _find_name(project.objects, component)
            if object_name is None:
                binding_issues.append(f"{component}: object missing")
                continue
            bones = project.skeletons.get(object_name, {})
            if not bones:
                binding_issues.append(f"{component}: skeleton missing")
            elif not any(any(float(weight) > 0 for weight in bone.cp_weights.values())
                         for bone in bones.values()):
                binding_issues.append(f"{component}: no positive control-point weights")
        _check(report, "rig_binding", not (missing_bones or binding_issues),
               "Checked required skeleton bones and positive weighted geometry bindings.",
               {"required_bones": required_bones[:64], "missing_bones": missing_bones[:32],
                "bound_components": bound_components[:64], "issues": binding_issues[:16]})

    animation_requested = bool((rig.get("action_kind") or rig.get("must_deform_components")) or animation)
    if animation_requested:
        action_specs = recipe.get("actions", []) or []
        action_name = next((a.get("name") for a in action_specs
                            if isinstance(a, dict) and a.get("name")), None)
        if rig.get("action_kind"):
            kind = str(rig["action_kind"]).casefold()
            action_name = next((a.get("name") for a in action_specs
                                if isinstance(a, dict) and str(a.get("kind", "")).casefold() == kind), action_name)
        action_ok = bool(action_name and action_name in session.actions)
        intended = rig.get("must_deform_components", []) or []
        if not intended:
            intended = rig.get("bound_components", []) or []
        if not intended:
            intended = [name for name in project.skeletons if name in scene.meshes]
        recipe_specs = {item.get("name"): item for item in recipe.get("objects", [])
                        if isinstance(item, dict) and isinstance(item.get("name"), str)}
        assignment_failures = []
        assigned_components = []
        for component in intended[:64]:
            object_name = _find_name(scene.meshes, component)
            target_rig_name = _find_name(project.skeletons, component)
            if object_name is None or target_rig_name is None:
                assignment_failures.append(f"{component}: intended component has no reopened rig")
                continue
            target_bones = project.skeletons.get(target_rig_name, {})
            target_weighted = any(
                any(float(weight) > 0 for weight in bone.cp_weights.values())
                for bone in target_bones.values())
            if not target_weighted:
                assignment_failures.append(f"{component}: intended component has no weighted rig binding")
                continue
            directly_assigned = bool(action_name and
                                     session.action_assignments.get(target_rig_name) == action_name)
            shared_assigned = False
            spec = recipe_specs.get(object_name) or recipe_specs.get(target_rig_name)
            params = spec.get("params", {}) if isinstance(spec, dict) else {}
            skeleton_ref = params.get("skeleton") if isinstance(params, dict) else None
            if action_name and isinstance(skeleton_ref, str):
                master_name = _find_name(project.skeletons, skeleton_ref)
                if master_name and master_name != target_rig_name:
                    master_bones = project.skeletons.get(master_name, {})
                    def _skeleton_signature(bones):
                        return tuple((bone.name, bone.parent) for bone in bones.values())
                    shared_assigned = bool(
                        session.action_assignments.get(master_name) == action_name
                        and _skeleton_signature(target_bones) == _skeleton_signature(master_bones)
                        and target_weighted)
            if directly_assigned or shared_assigned:
                assigned_components.append(component)
            else:
                assignment_failures.append(f"{component}: action is not assigned to its rig or explicit shared rig")
        assigned_ok = bool(intended) and not assignment_failures
        duration = None
        if action_name and action_name in session.actions:
            duration = float(getattr(session.actions[action_name], "duration", 0.0) or 0.0)
        if not duration and isinstance(animation, dict):
            duration = float(animation.get("duration_seconds") or 0.0)
        if not duration:
            duration = 1.0
        thresholds = []
        motion_issues = []
        rendered_samples = 0
        sample_times = [duration * fraction for fraction in (0.0, 0.25, 0.5, 0.75)]
        camera = None
        try:
            from am3d.gpu import scene_camera
            camera = scene_camera(list(scene.meshes.values()))
        except Exception:
            camera = None
        # Stream one evaluated scene at a time. Keep per-component evidence in
        # recipe order even though expensive work is shared by sample time.
        states = []
        for component in intended[:64]:
            object_name = _find_name(scene.meshes, component)
            states.append({"component": component, "name": object_name,
                           "maximum": 0.0, "stopped": False, "issues": []})
        for time_s in sample_times:
            active = [state for state in states
                      if state["name"] is not None and not state["stopped"]]
            if not active:
                break
            sampled = session.evaluate_scene(action_name=action_name, time=time_s,
                                             visible_only=True, apply_transforms=True,
                                             nu=16, nv=16)
            valid = []
            for state in active:
                component, object_name = state["component"], state["name"]
                initial = np.asarray(scene.meshes[object_name].vertices, dtype=np.float64)
                mesh = sampled.meshes.get(object_name)
                if mesh is None or np.asarray(mesh.vertices).shape != initial.shape:
                    state["issues"].append(f"{component}: sampled mesh changed shape or disappeared")
                    continue
                vertices = np.asarray(mesh.vertices, dtype=np.float64)
                if not np.isfinite(vertices).all():
                    state["issues"].append(f"{component}: sampled non-finite geometry")
                    continue
                displacement = float(np.max(np.linalg.norm(vertices - initial, axis=1))) if len(initial) else 0.0
                state["maximum"] = max(state["maximum"], displacement)
                valid.append(state)
            if camera is not None and valid:
                try:
                    from am3d.render_job import render_frame_image
                    image = render_frame_image(sampled, camera, 128, 128,
                                               time=time_s, action_name=action_name,
                                               force_software=True)
                    if image.shape != (128, 128, 4) or not np.isfinite(image).all():
                        raise ValueError("invalid frame")
                    # Preserve the report's logical component-sample count;
                    # there is only one physical render for this sample.
                    rendered_samples += len(valid)
                except Exception:
                    for state in valid:
                        state["issues"].append(f"{state['component']}: fixed-camera sample render failed")
                        state["stopped"] = True
            # Release this sample before allocating the next whole scene.
            del sampled
            mesh = vertices = None
        for state in states:
            component = state["component"]
            if state["name"] is None:
                motion_issues.append(f"{component}: intended object missing")
                continue
            motion_issues.extend(state["issues"])
            threshold = max(1e-6, 0.001 * diagonal)
            thresholds.append({"component": component, "max_displacement": state["maximum"],
                               "required_displacement": threshold})
            if state["maximum"] <= threshold:
                motion_issues.append(f"{component}: motion did not exceed threshold")
        animation_ok = action_ok and assigned_ok and not missing_bones and bool(intended) and not motion_issues
        _check(report, "animation_and_deformation", animation_ok,
               "Checked bound action samples at 0%, 25%, 50%, and 75% of duration with one fixed camera.",
               {"action": action_name, "action_present": action_ok,
                "assignment_present": assigned_ok,
                "assigned_components": assigned_components[:32],
                "assignment_issues": assignment_failures[:16],
                "missing_bones": missing_bones[:16],
                "samples": thresholds[:32], "rendered_sample_frames": rendered_samples,
                "issues": motion_issues[:16],
                "human_review": "useful visible motion remains a human acceptance question"})
