"""Undo/operator layer: QUndoCommand wrappers for every UI mutation.

Each command mutates the model through the same Session / panel code
paths the UI used before Phase 4, so behaviour is identical — the only
difference is that the mutation becomes undoable.  Commands store
absolute before/after values, which makes ``redo()`` idempotent: when a
widget already applied a change live (e.g. a viewport gizmo drag),
pushing the command re-applies the same value harmlessly.

The :class:`PySide6.QtGui.QUndoStack` lives on the MainWindow; panels
push through ``MainWindow.push_command`` (falling back to a direct
``redo()`` when no undo stack is present, e.g. in isolated panel tests).
"""

from __future__ import annotations

import copy

import numpy as np

from PySide6.QtGui import QUndoCommand, QUndoStack

__all__ = [
    "QUndoStack",
    "RenameObjectCommand", "DeleteObjectCommand", "AddObjectCommand",
    "SetObjectVisibleCommand", "SetObjectTransformCommand",
    "AddMaterialCommand", "DeleteMaterialCommand",
    "SetMaterialColorCommand", "SetMaterialMapsCommand",
    "SetBoneEndpointsCommand", "PoseBoneCommand",
    "MoveCPCommand", "InsertCPCommand", "RemoveCPCommand",
    "CreateActionCommand", "DeleteActionCommand", "RenameActionCommand",
    "AssignActionCommand", "InsertKeyCommand", "MoveKeyCommand",
    "DeleteKeyCommand", "SetAnimationSettingsCommand",
]


class _SessionCommand(QUndoCommand):
    """Base: a command bound to a Session."""

    def __init__(self, session, text):
        super().__init__(text)
        self.session = session


# -- objects ---------------------------------------------------------------
class RenameObjectCommand(_SessionCommand):
    def __init__(self, session, old_name, new_name):
        super().__init__(session, f"Rename {old_name} -> {new_name}")
        self.old = old_name
        self.new = new_name

    def redo(self):
        self.session.rename_object(self.old, self.new)

    def undo(self):
        self.session.rename_object(self.new, self.old)


class DeleteObjectCommand(_SessionCommand):
    """Delete an object (deep snapshot restores it, incl. its skeleton)."""

    def __init__(self, session, name):
        super().__init__(session, f"Delete object {name}")
        self.name = name
        self._obj = copy.deepcopy(session.project.objects[name])
        self._skeleton = copy.deepcopy(
            session.project.skeletons.get(name))
        self._index = list(session.project.objects).index(name)

    def redo(self):
        self.session.delete_object(self.name)

    def undo(self):
        proj = self.session.project
        items = list(proj.objects.items())
        items.insert(min(self._index, len(items)),
                     (self.name, copy.deepcopy(self._obj)))
        proj.objects = dict(items)
        if self._skeleton is not None:
            proj.skeletons[self.name] = copy.deepcopy(self._skeleton)


class AddObjectCommand(_SessionCommand):
    def __init__(self, session, name):
        super().__init__(session, f"Add object {name}")
        self.name = name

    def redo(self):
        self.session.create_object(self.name)

    def undo(self):
        self.session.delete_object(self.name)


class SetObjectVisibleCommand(_SessionCommand):
    def __init__(self, session, name, visible):
        super().__init__(session,
                         f"{'Show' if visible else 'Hide'} {name}")
        self.name = name
        self.new = bool(visible)
        self.old = bool(session.get_object(name).visible)

    def redo(self):
        self.session.set_object_visible(self.name, self.new)

    def undo(self):
        self.session.set_object_visible(self.name, self.old)


class SetObjectTransformCommand(_SessionCommand):
    def __init__(self, session, name, before, after):
        super().__init__(session, f"Transform {name}")
        self.name = name
        self.before = np.array(before, dtype=np.float64).reshape(4, 4)
        self.after = np.array(after, dtype=np.float64).reshape(4, 4)

    def redo(self):
        self.session.get_object(self.name).transform = self.after.copy()

    def undo(self):
        self.session.get_object(self.name).transform = self.before.copy()


# -- materials -------------------------------------------------------------
class AddMaterialCommand(_SessionCommand):
    def __init__(self, session, name):
        super().__init__(session, f"Add material {name}")
        self.name = name

    def redo(self):
        self.session.create_material(self.name)

    def undo(self):
        self.session.project.materials.pop(self.name, None)


class DeleteMaterialCommand(_SessionCommand):
    def __init__(self, session, name):
        super().__init__(session, f"Delete material {name}")
        self.name = name
        self._mat = copy.deepcopy(session.project.materials[name])
        self._index = list(session.project.materials).index(name)

    def redo(self):
        self.session.project.materials.pop(self.name, None)

    def undo(self):
        items = list(self.session.project.materials.items())
        items.insert(min(self._index, len(items)),
                     (self.name, copy.deepcopy(self._mat)))
        self.session.project.materials = dict(items)


class SetMaterialColorCommand(_SessionCommand):
    def __init__(self, session, name, color):
        super().__init__(session, f"Material {name} colour")
        self.name = name
        self.new = tuple(color)
        self.old = tuple(session.project.materials[name].color)

    def redo(self):
        self.session.project.materials[self.name].color = self.new

    def undo(self):
        self.session.project.materials[self.name].color = self.old


class SetMaterialMapsCommand(_SessionCommand):
    """One undo step for all three map path fields of a material."""

    _FIELDS = ("bump_map", "transparency_map", "specular_map")

    def __init__(self, session, name, bump, transparency, specular):
        super().__init__(session, f"Material {name} maps")
        self.name = name
        self.new = (bump, transparency, specular)
        mat = session.project.materials[name]
        self.old = tuple(getattr(mat, f) for f in self._FIELDS)

    def _apply(self, values):
        mat = self.session.project.materials[self.name]
        for f, v in zip(self._FIELDS, values):
            setattr(mat, f, v)

    def redo(self):
        self._apply(self.new)

    def undo(self):
        self._apply(self.old)


# -- bones -------------------------------------------------------------------
class SetBoneEndpointsCommand(_SessionCommand):
    def __init__(self, session, object_name, bone_name, before, after):
        super().__init__(session, f"Bone {bone_name} endpoints")
        self.object_name = object_name
        self.bone_name = bone_name
        self.before = (np.asarray(before[0], dtype=np.float64),
                       np.asarray(before[1], dtype=np.float64))
        self.after = (np.asarray(after[0], dtype=np.float64),
                      np.asarray(after[1], dtype=np.float64))

    def _bone(self):
        return self.session.project.skeletons[self.object_name][
            self.bone_name]

    def _apply(self, ht):
        bone = self._bone()
        bone.head = ht[0].copy()
        bone.tail = ht[1].copy()

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


class PoseBoneCommand(_SessionCommand):
    """A pose rotation for one bone (see Session.pose_bone)."""

    def __init__(self, session, object_name, bone_name, before, after):
        super().__init__(session, f"Pose {bone_name}")
        self.object_name = object_name
        self.bone_name = bone_name
        self.before = None if before is None else np.asarray(
            before, dtype=np.float64).reshape(3, 3)
        self.after = np.asarray(after, dtype=np.float64).reshape(3, 3)

    def redo(self):
        self.session.pose_bone(self.object_name, self.bone_name,
                               self.after)
        self.session.apply_pose(self.object_name)

    def undo(self):
        if self.before is None:
            self.session.clear_pose(self.object_name, self.bone_name)
        else:
            self.session.pose_bone(self.object_name, self.bone_name,
                                   self.before)
        self.session.apply_pose(self.object_name)


# -- spline control points ---------------------------------------------------
class _CPCommand(_SessionCommand):
    def __init__(self, session, object_name, spline_name, index, text):
        super().__init__(session, text)
        self.object_name = object_name
        self.spline_name = spline_name
        self.index = int(index)

    def _spline(self):
        return self.session.project.objects[self.object_name].splines[
            self.spline_name]


class MoveCPCommand(_CPCommand):
    def __init__(self, session, object_name, spline_name, index,
                 before, after):
        super().__init__(session, object_name, spline_name, index,
                         f"Move CP {spline_name}[{index}]")
        self.before = np.asarray(before, dtype=np.float64).reshape(3)
        self.after = np.asarray(after, dtype=np.float64).reshape(3)

    def redo(self):
        self._spline().cps[self.index].position = self.after.copy()

    def undo(self):
        self._spline().cps[self.index].position = self.before.copy()


class InsertCPCommand(_CPCommand):
    """Insert the stored control point at *index*."""

    def __init__(self, session, object_name, spline_name, index, cp):
        super().__init__(session, object_name, spline_name, index,
                         f"Add CP to {spline_name}")
        self._cp = copy.deepcopy(cp)

    def redo(self):
        self._spline().cps.insert(self.index, copy.deepcopy(self._cp))

    def undo(self):
        del self._spline().cps[self.index]


class RemoveCPCommand(_CPCommand):
    """Remove the control point at *index* (re-inserted on undo)."""

    def __init__(self, session, object_name, spline_name, index):
        super().__init__(session, object_name, spline_name, index,
                         f"Delete CP {spline_name}[{index}]")
        self._cp = None

    def redo(self):
        spline = self._spline()
        self._cp = copy.deepcopy(spline.cps[self.index])
        del spline.cps[self.index]

    def undo(self):
        self._spline().cps.insert(self.index, copy.deepcopy(self._cp))


# -- actions / keyframes -----------------------------------------------------
class CreateActionCommand(_SessionCommand):
    def __init__(self, session, name, duration=1.0):
        super().__init__(session, f"Add action {name}")
        self.name = name
        self.duration = float(duration)

    def redo(self):
        if self.name in self.session.actions:      # idempotent redo
            return
        self.session.create_action(self.name, self.duration)

    def undo(self):
        self.session.delete_action(self.name)


class DeleteActionCommand(_SessionCommand):
    """Delete an action (deep snapshot restores it)."""

    def __init__(self, session, name):
        super().__init__(session, f"Delete action {name}")
        self.name = name
        self._action = copy.deepcopy(session.actions[name])
        self._assignments = dict(session.action_assignments)

    def redo(self):
        self.session.delete_action(self.name)

    def undo(self):
        self.session.actions[self.name] = copy.deepcopy(self._action)
        self.session.action_assignments = dict(self._assignments)


class RenameActionCommand(_SessionCommand):
    def __init__(self, session, old_name, new_name):
        super().__init__(session, f"Rename action {old_name} -> {new_name}")
        self.old = old_name
        self.new = new_name

    def redo(self):
        self.session.rename_action(self.old, self.new)

    def undo(self):
        self.session.rename_action(self.new, self.old)


class AssignActionCommand(_SessionCommand):
    """Assign an action to an object (undo restores the old assignment)."""

    def __init__(self, session, action_name, object_name):
        super().__init__(session,
                         f"Assign {action_name} to {object_name}")
        self.action_name = action_name
        self.object_name = object_name
        self.old = session.action_assignments.get(object_name)

    def redo(self):
        self.session.assign_action(self.action_name, self.object_name)

    def undo(self):
        if self.old is None:
            self.session.unassign_action(self.object_name)
        else:
            self.session.assign_action(self.old, self.object_name)


def _channel(session, action_name, bone, prop):
    return session.actions[action_name].get_channel(bone, prop)


class InsertKeyCommand(_SessionCommand):
    """Insert one keyframe (undo removes it again)."""

    def __init__(self, session, action_name, bone, prop, time, value,
                 interp="smooth"):
        super().__init__(session, f"Key {bone}.{prop} @ {time:g}")
        self.action_name = action_name
        self.bone = bone
        self.prop = prop
        self.time = float(time)
        self.value = np.asarray(value, dtype=np.float64).reshape(-1)
        self.interp = interp

    def redo(self):
        self._replaced = None
        ch = _channel(self.session, self.action_name, self.bone, self.prop)
        if ch is not None:
            for k in ch.keys:
                if abs(k.time - self.time) < 1e-9:
                    self._replaced = copy.deepcopy(k)
        self.session.insert_keyframe(self.action_name, self.bone, self.prop,
                                     self.time, self.value, self.interp)

    def undo(self):
        ch = _channel(self.session, self.action_name, self.bone, self.prop)
        if ch is None:
            return
        for i, k in enumerate(ch.keys):
            if abs(k.time - self.time) < 1e-9:
                del ch.keys[i]
                break
        if self._replaced is not None:
            ch.keys.append(self._replaced)
            ch.keys.sort(key=lambda k: k.time)


class MoveKeyCommand(_SessionCommand):
    """Move one keyframe to a new time (found by object identity)."""

    def __init__(self, session, action_name, bone, prop, index, after_time):
        super().__init__(session, f"Move key {bone}.{prop}")
        self.action_name = action_name
        self.bone = bone
        self.prop = prop
        ch = _channel(session, action_name, bone, prop)
        self._key = ch.keys[index]
        self.before = self._key.time
        self.after = float(after_time)

    def _set(self, time):
        self._key.time = time
        ch = _channel(self.session, self.action_name, self.bone, self.prop)
        ch.keys.sort(key=lambda k: k.time)

    def redo(self):
        self._set(self.after)

    def undo(self):
        self._set(self.before)


class DeleteKeyCommand(_SessionCommand):
    """Delete the key at *index* (re-inserted on undo)."""

    def __init__(self, session, action_name, bone, prop, index):
        super().__init__(session, f"Delete key {bone}.{prop}")
        self.action_name = action_name
        self.bone = bone
        self.prop = prop
        self.index = int(index)
        self._key = None

    def redo(self):
        ch = _channel(self.session, self.action_name, self.bone, self.prop)
        self._key = ch.keys[self.index]
        del ch.keys[self.index]

    def undo(self):
        ch = _channel(self.session, self.action_name, self.bone, self.prop)
        ch.keys.append(self._key)
        ch.keys.sort(key=lambda k: k.time)


class SetAnimationSettingsCommand(_SessionCommand):
    """Frame range / FPS edits, applied to Project.animation_settings."""

    def __init__(self, session, before, after):
        super().__init__(session, "Animation settings")
        self.before = dict(before)
        self.after = dict(after)

    def _apply(self, settings):
        self.session.project.animation_settings.update(settings)

    def redo(self):
        self._apply(self.after)

    def undo(self):
        self._apply(self.before)


def push_or_apply(main, command, emit=None):
    """Push *command* onto the main window's undo stack if it has one.

    Without an undo stack (isolated panel tests) the command is applied
    directly.  ``emit`` is the panel's ``data_changed`` signal, fired on
    the direct path only — the stacked path refreshes via MainWindow.
    """
    push = getattr(main, "push_command", None)
    if push is not None:
        push(command)
    else:
        command.redo()
        if emit is not None:
            emit.emit()
