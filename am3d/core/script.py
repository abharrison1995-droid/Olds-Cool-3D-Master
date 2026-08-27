"""Public, scriptable API for 3D MASTER:2005.

This is the automation surface an external agentic pipeline (e.g. an AI
assistant) drives.  Everything reachable here is safe to call headlessly —
no GUI or GPU context is required.  It mirrors what a user does through the
four UI modes:

    * Object Mode       : splines, patches, hooks, extrusion, lathe
    * Segment Mode      : skeletons, bones, CP weights
    * Material Mode     : materials
    * Choreography Mode : actions, keyframes, playback
"""

from __future__ import annotations

import threading

import numpy as np

from .project import (
    Bone,
    ControlPoint,
    Hook,
    Material,
    Object3D,
    Patch,
    Project,
    Spline,
)


class ScriptingError(RuntimeError):
    """Raised when a scripting call targets an invalid name."""


class Session:
    """Mutating facade bound to a single :class:`Project`."""

    def __init__(self, project: Project | None = None):
        self.project = project if project is not None else Project("Untitled")
        self.actions = {}
        # Pose rotations: object_name -> {bone_name -> 3x3 rotation}
        # applied on top of each bone's rest local transform by apply_pose.
        self.poses = {}
        # Pose translation offsets (bone-local), added to the rest local
        # translation before the pose rotation is applied.
        self.pose_offsets = {}
        self.posed_transforms = {}      # object_name -> {bone_name -> 4x4}
        # Choreography: which action the dope sheet edits and which action
        # is assigned to (drives) which object during playback.
        self.active_action = None
        self.action_assignments = {}    # object_name -> action_name

    # -- file ---------------------------------------------------------------
    def new_project(self, name: str = "Untitled") -> Project:
        self.project = Project(name)
        self.actions = {}
        self.poses = {}
        self.pose_offsets = {}
        self.posed_transforms = {}
        self.active_action = None
        self.action_assignments = {}
        return self.project

    def save_project(self, path: str):
        """Save the project (and session state) to a .am3d file."""
        from .serializer import save_project
        # Sync session state to project before serializing
        self.project.active_action = self.active_action
        self.project.action_assignments = dict(self.action_assignments)
        save_project(self.project, path, actions=self.actions)

    def load_project(self, path: str) -> Project:
        """Load a .am3d file, replacing project and session actions."""
        from .serializer import load_project
        self.project = load_project(path)
        self.actions = getattr(self.project, "actions", {})
        self.poses = {}
        self.pose_offsets = {}
        self.posed_transforms = {}
        self.active_action = getattr(self.project, "active_action", next(iter(self.actions), None))
        self.action_assignments = getattr(self.project, "action_assignments", {})
        if not isinstance(self.action_assignments, dict):
            self.action_assignments = {}
        return self.project

    # -- object mode --------------------------------------------------------
    def create_object(self, name: str) -> Object3D:
        return self.project.create_object(name)

    def delete_object(self, name: str) -> None:
        self.project.remove_object(name)
        self.project.skeletons.pop(name, None)
        self.poses.pop(name, None)
        self.pose_offsets.pop(name, None)
        self.posed_transforms.pop(name, None)
        self.action_assignments.pop(name, None)

    def rename_object(self, name: str, new_name: str) -> Object3D:
        if name not in self.project.objects:
            raise ScriptingError(f"no such object: {name!r}")
        new_name = (new_name or "").strip()
        if not new_name:
            raise ScriptingError("object name must not be empty")
        if new_name != name and new_name in self.project.objects:
            raise ScriptingError(f"object {new_name!r} already exists")
        for d in (self.poses, self.pose_offsets, self.posed_transforms,
                   self.action_assignments):
            if name in d:
                d[new_name] = d.pop(name)
        self.project.rename_object(name, new_name)
        return self.project.objects[new_name]

    def set_object_visible(self, name: str, visible: bool) -> None:
        self.get_object(name).visible = bool(visible)

    def get_object(self, name: str) -> Object3D:
        if name not in self.project.objects:
            raise ScriptingError(f"no such object: {name!r}")
        return self.project.objects[name]

    def add_spline(self, object_name, points, degree: int = 3,
                   name: str = "spline", closed: bool = False) -> Spline:
        if object_name not in self.project.objects:
            raise ScriptingError(f"no such object: {object_name!r}")
        cps = [ControlPoint(np.asarray(p, dtype=np.float64), 1.0) for p in points]
        spl = Spline(name=name, cps=cps, degree=degree, closed=closed)
        self.project.objects[object_name].add_spline(spl)
        return spl

    def extrude_spline(self, object_name, spline_name, height,
                       twist_deg: float = 0.0, rings: int = 4) -> Patch:
        from am3d.spline import kernel
        obj = self.project.objects.get(object_name)
        if obj is None:
            raise ScriptingError(f"no such object: {object_name!r}")
        if spline_name not in obj.splines:
            raise ScriptingError(f"no spline {spline_name!r}")
        profile = obj.splines[spline_name].point_array()
        net = kernel.build_extrude_net(profile, height, twist_deg, rings)
        patch = Patch(name=f"{spline_name}_extrude",
                      splines=[spline_name], interior=net)
        obj.patches.append(patch)
        return patch

    def lathe_spline(self, object_name, spline_name: str, axis: str = "y",
                     sections: int = 24) -> Patch:
        from am3d.spline import kernel
        obj = self.project.objects.get(object_name)
        if obj is None:
            raise ScriptingError(f"no such object: {object_name!r}")
        if spline_name not in obj.splines:
            raise ScriptingError(f"no spline {spline_name!r}")
        profile = obj.splines[spline_name].point_array()[:, [0, 1]]
        net = kernel.build_lathe_net(profile, axis=axis, sections=sections)
        patch = Patch(name=f"{spline_name}_lathe", splines=[spline_name],
                      interior=net)
        obj.patches.append(patch)
        return patch

    # -- segment mode -------------------------------------------------------
    def add_bone(self, object_name: str, name: str, head, tail,
                 parent: str | None = None) -> Bone:
        bones = self.project.skeletons.setdefault(object_name, {})
        bone = Bone(name=name, parent=parent,
                    head=np.asarray(head, dtype=np.float64),
                    tail=np.asarray(tail, dtype=np.float64))
        bones[name] = bone
        return bone

    def get_bones(self, object_name: str) -> list:
        """All bones of an object's rig, in insertion order."""
        return list(self.project.skeletons.get(object_name, {}).values())

    # -- posing (Rig workspace) ----------------------------------------------
    def pose_bone(self, object_name: str, bone_name: str, rotation) -> None:
        """Set a pose rotation for one bone.

        ``rotation`` is a 3x3 matrix or Euler XYZ degrees; it is applied
        on top of the bone's rest local transform by :meth:`apply_pose`.
        """
        bones = self.project.skeletons.get(object_name, {})
        if bone_name not in bones:
            raise ScriptingError(
                f"no bone {bone_name!r} on object {object_name!r}")
        r = np.asarray(rotation, dtype=np.float64)
        if r.shape == (3,):
            from .mathutil import compose_trs
            r = compose_trs((0, 0, 0), r, (1, 1, 1))[:3, :3]
        elif r.shape != (3, 3):
            raise ScriptingError("rotation must be 3x3 or Euler degrees")
        self.poses.setdefault(object_name, {})[bone_name] = r.copy()

    def clear_pose(self, object_name: str, bone_name: str | None = None):
        """Drop pose rotations: one bone, or the whole object."""
        if bone_name is None:
            self.poses.pop(object_name, None)
            self.pose_offsets.pop(object_name, None)
        else:
            self.poses.get(object_name, {}).pop(bone_name, None)
            self.pose_offsets.get(object_name, {}).pop(bone_name, None)

    def apply_pose(self, object_name: str | None = None) -> dict:
        """Run FK with the stored pose rotations.

        Returns ``{object_name: {bone_name: 4x4 world}}`` and caches it
        on :attr:`posed_transforms` for viewport/preview consumers.
        """
        from .rigging import fk_pose, rest_local_transform
        names = ([object_name] if object_name is not None
                 else list(self.project.skeletons))
        for name in names:
            bones = self.get_bones(name)
            if not bones:
                self.posed_transforms.pop(name, None)
                continue
            pose = self.poses.get(name, {})
            offsets = self.pose_offsets.get(name, {})
            locals_ = {}
            for b in bones:
                rest = rest_local_transform(b)
                if b.name in offsets:
                    rest = rest.copy()
                    rest[:3, 3] = rest[:3, 3] + np.asarray(
                        offsets[b.name], dtype=np.float64).reshape(3)
                if b.name in pose:
                    rot = np.eye(4)
                    rot[:3, :3] = pose[b.name]
                    locals_[b.name] = rest @ rot
                else:
                    locals_[b.name] = rest
            self.posed_transforms[name] = fk_pose(bones, locals_)
        return self.posed_transforms

    # -- material mode ------------------------------------------------------
    def create_material(self, name: str, color=(0.8, 0.8, 0.8)) -> Material:
        mat = Material(name=name, color=color)
        self.project.materials[name] = mat
        return mat

    # -- action reuse (choreography) ---------------------------------------
    def create_action(self, name: str, duration: float = 1.0) -> Action:
        from .animation import Action
        if name in self.actions:
            raise ScriptingError(f"action {name!r} already exists")
        act = Action(name=name, duration=duration)
        self.actions[name] = act
        if self.active_action is None:
            self.active_action = name
        self.project.active_action = self.active_action
        return act

    def get_action(self, name: str) -> Action:
        if name not in self.actions:
            raise ScriptingError(f"no such action: {name!r}")
        return self.actions[name]

    def delete_action(self, name: str) -> None:
        """Remove an action and any assignment pointing at it."""
        if name not in self.actions:
            raise ScriptingError(f"no such action: {name!r}")
        del self.actions[name]
        self.action_assignments = {
            obj: act for obj, act in self.action_assignments.items()
            if act != name}
        if self.active_action == name:
            self.active_action = next(iter(self.actions), None)
        self.project.active_action = self.active_action
        self.project.action_assignments = dict(self.action_assignments)

    def rename_action(self, name: str, new_name: str) -> Action:
        if name not in self.actions:
            raise ScriptingError(f"no such action: {name!r}")
        new_name = (new_name or "").strip()
        if not new_name:
            raise ScriptingError("action name must not be empty")
        if new_name != name and new_name in self.actions:
            raise ScriptingError(f"action {new_name!r} already exists")
        if new_name == name:
            return self.actions[name]
        act = self.actions.pop(name)
        act.name = new_name
        self.actions[new_name] = act
        if self.active_action == name:
            self.active_action = new_name
        self.action_assignments = {
            obj: (new_name if a == name else a)
            for obj, a in self.action_assignments.items()}
        self.project.active_action = self.active_action
        self.project.action_assignments = dict(self.action_assignments)
        return act

    def set_active_action(self, name: str | None) -> None:
        """Select the action shown/edited in the dope sheet."""
        if name is not None and name not in self.actions:
            raise ScriptingError(f"no such action: {name!r}")
        self.active_action = name
        self.project.active_action = name

    def assign_action(self, action_name: str, object_name: str) -> Action:
        """Assign an action to drive an object during playback."""
        act = self.apply_action_to_character(action_name, object_name)
        self.action_assignments[object_name] = action_name
        self.project.action_assignments = dict(self.action_assignments)
        return act

    def unassign_action(self, object_name: str) -> None:
        self.action_assignments.pop(object_name, None)
        self.project.action_assignments = dict(self.action_assignments)

    # -- keyframe editing ---------------------------------------------------
    def insert_keyframe(self, action_name: str, bone: str, prop: str,
                        time: float, value, interp: str | None = None):
        """Add (or replace at the same time) a key on a bone channel."""
        from .animation import Interpolation
        act = self.get_action(action_name)
        ch = act.get_channel(bone, prop)
        if ch is None:
            ch = act.add_channel(bone, prop)
        # Channel.add_key owns the replace-at-same-time invariant.
        return ch.add_key(float(time), value,
                          interp or Interpolation.SMOOTH)

    def remove_keyframe(self, action_name: str, bone: str, prop: str,
                        index: int):
        """Remove the key at *index* from a bone channel; returns it."""
        act = self.get_action(action_name)
        ch = act.get_channel(bone, prop)
        if ch is None or not (0 <= index < len(ch.keys)):
            raise ScriptingError(
                f"no key {index} on {action_name}:{bone}.{prop}")
        return ch.keys.pop(index)

    def key_bone_from_pose(self, action_name: str, object_name: str,
                           bone_name: str, time: float):
        """Key the stored pose of one bone into an action at *time*.

        Rotate channels store Euler XYZ *radians* (the same convention the
        procedural generators use); translate channels store bone-local
        offsets from the rest transform.
        """
        from .mathutil import decompose_trs
        keys = []
        rot = self.poses.get(object_name, {}).get(bone_name)
        if rot is not None:
            m = np.eye(4)
            m[:3, :3] = np.asarray(rot, dtype=np.float64).reshape(3, 3)
            _, euler_deg, _ = decompose_trs(m)
            keys.append(self.insert_keyframe(
                action_name, bone_name, "rotate", time,
                np.deg2rad(euler_deg)))
        offset = self.pose_offsets.get(object_name, {}).get(bone_name)
        if offset is not None:
            keys.append(self.insert_keyframe(
                action_name, bone_name, "translate", time, offset))
        return keys

    # -- playback ------------------------------------------------------------
    def apply_action_frame(self, object_name: str, time: float,
                           action_name: str | None = None) -> dict:
        """Sample an action at *time* (seconds) and pose the object.

        Channel values become pose rotations / translation offsets which
        run through :meth:`apply_pose`; the resulting world transforms are
        cached on :attr:`posed_transforms` for the viewport and skinning.
        """
        act = self.get_action(
            action_name or self.action_assignments.get(object_name)
            or self.active_action)
        frame = act.sample(float(time))
        pose = self.poses.setdefault(object_name, {})
        offsets = self.pose_offsets.setdefault(object_name, {})
        from .mathutil import compose_trs
        for bone_name, props in frame.items():
            if "rotate" in props:
                pose[bone_name] = compose_trs(
                    (0, 0, 0),
                    np.rad2deg(np.asarray(props["rotate"],
                                          dtype=np.float64).reshape(3)),
                    (1, 1, 1))[:3, :3]
            if "translate" in props:
                offsets[bone_name] = np.asarray(
                    props["translate"], dtype=np.float64).reshape(3)
        return self.apply_pose(object_name)

    def save_action_file(self, name: str, path: str):
        from .serializer import save_action
        save_action(self.actions[name], path)

    def load_action_file(self, path: str) -> Action:
        from .serializer import load_action_file
        act = load_action_file(path)
        self.actions[act.name] = act
        if self.active_action is None:
            self.active_action = act.name
        self.project.active_action = self.active_action
        return act

    def apply_action_to_character(self, action_name: str, object_name: str,
                                  skeleton=None):
        """Drop an Action onto a character if the skeleton is compatible."""
        act = self.get_action(action_name)
        if object_name not in self.project.objects:
            raise ScriptingError(f"no such object: {object_name!r}")
        bones = skeleton if skeleton is not None else self.get_bones(object_name)
        if not act.compatible_with(bones):
            missing = [ch.bone for ch in act.channels
                       if ch.bone not in {b.name for b in bones}]
            raise ScriptingError(
                f"action {action_name!r} not compatible; missing bones {missing}")
        return act


# A thread-local default session so `import am3d; am3d.create_object(...)`
# works, while concurrent agent threads never share one project's state.
Script = Session
_local = threading.local()


def _default() -> Session:
    """This thread's own Session (created on first use)."""
    session = getattr(_local, "session", None)
    if session is None:
        session = Session()
        _local.session = session
    return session


def reset_default() -> Session:
    """Force this thread's default Session to a fresh project."""
    session = Session()
    _local.session = session
    return session


def _propagate(name):
    def _fn(*a, **k):
        return getattr(_default(), name)(*a, **k)
    _fn.__name__ = name
    return _fn


new_project = _propagate("new_project")
save_project = _propagate("save_project")
load_project = _propagate("load_project")
create_object = _propagate("create_object")
delete_object = _propagate("delete_object")
rename_object = _propagate("rename_object")
set_object_visible = _propagate("set_object_visible")
get_object = _propagate("get_object")
add_spline = _propagate("add_spline")
extrude_spline = _propagate("extrude_spline")
lathe_spline = _propagate("lathe_spline")
add_bone = _propagate("add_bone")
get_bones = _propagate("get_bones")
pose_bone = _propagate("pose_bone")
clear_pose = _propagate("clear_pose")
apply_pose = _propagate("apply_pose")
create_material = _propagate("create_material")
create_action = _propagate("create_action")
get_action = _propagate("get_action")
delete_action = _propagate("delete_action")
rename_action = _propagate("rename_action")
set_active_action = _propagate("set_active_action")
assign_action = _propagate("assign_action")
unassign_action = _propagate("unassign_action")
insert_keyframe = _propagate("insert_keyframe")
remove_keyframe = _propagate("remove_keyframe")
key_bone_from_pose = _propagate("key_bone_from_pose")
apply_action_frame = _propagate("apply_action_frame")
save_action_file = _propagate("save_action_file")
load_action_file = _propagate("load_action_file")
apply_action_to_character = _propagate("apply_action_to_character")


__all__ = [
    "Session", "Script", "ScriptingError", "reset_default",
    "new_project", "save_project", "load_project",
    "create_object", "delete_object", "rename_object", "set_object_visible",
    "get_object",
    "add_spline", "extrude_spline", "lathe_spline", "add_bone", "get_bones",
    "pose_bone", "clear_pose", "apply_pose",
    "create_material",
    "create_action", "get_action", "delete_action", "rename_action",
    "set_active_action", "assign_action", "unassign_action",
    "insert_keyframe", "remove_keyframe", "key_bone_from_pose",
    "apply_action_frame",
    "save_action_file", "load_action_file", "apply_action_to_character",
]