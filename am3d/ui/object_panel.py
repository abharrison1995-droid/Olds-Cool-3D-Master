"""Outliner: one hierarchical tree of the whole scene.

Scene -> Objects -> (Patches, Splines, Bones) plus a Materials node.
Replaces both the old read-only Object panel and the Segment (skeleton)
panel.  Rows are selectable and checkable (visibility); object rows can be
renamed in place (F2 / double-click) and deleted via Del or the context
menu.  Selection is synced both ways with the viewport.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QInputDialog, QMenu, QMessageBox, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

# Item roles: (kind, object_name, item_name) stored in Qt.UserRole.
_KIND = Qt.UserRole


class ObjectDock(QWidget):
    """Blender-style outliner over the whole project.

    A plain widget so it can live inside the tiled area layout
    (:mod:`am3d.ui.area_layout`); the "Dock" name is kept for
    compatibility with earlier phases.
    """

    data_changed = Signal()
    # Emitted when the selected row changes: kind is "object", "bone",
    # "material" or "" (nothing context-relevant).
    context_changed = Signal(str, str, str)

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self.setWindowTitle("Outliner")
        self._syncing = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Scene")
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(self._on_current_changed)
        self.tree.customContextMenuRequested.connect(self._context_menu)
        layout.addWidget(self.tree)

    # -- construction ---------------------------------------------------
    def refresh(self):
        if self._syncing:
            return
        self._syncing = True
        try:
            current = self._current_context()
            self.tree.clear()
            proj = self.main.session.project

            scene = QTreeWidgetItem([proj.name or "Scene"])
            scene.setData(0, _KIND, ("scene", "", ""))
            self.tree.addTopLevelItem(scene)

            for name, obj in proj.objects.items():
                item = QTreeWidgetItem(scene, [name])
                item.setData(0, _KIND, ("object", name, ""))
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable
                              | Qt.ItemIsEditable)
                item.setCheckState(0, Qt.Checked
                                   if getattr(obj, "visible", True)
                                   else Qt.Unchecked)
                for p in obj.patches:
                    child = QTreeWidgetItem(item, [f"patch: {p.name}"])
                    child.setData(0, _KIND, ("patch", name, p.name))
                for sname in obj.splines:
                    child = QTreeWidgetItem(item, [f"spline: {sname}"])
                    child.setData(0, _KIND, ("spline", name, sname))
                for bone in self.main.session.get_bones(name):
                    child = QTreeWidgetItem(item, [f"bone: {bone.name}"])
                    child.setData(0, _KIND, ("bone", name, bone.name))

            mats = QTreeWidgetItem(["Materials"])
            mats.setData(0, _KIND, ("materials", "", ""))
            self.tree.addTopLevelItem(mats)
            for mname in proj.materials:
                child = QTreeWidgetItem(mats, [mname])
                child.setData(0, _KIND, ("material", "", mname))

            acts = QTreeWidgetItem(["Actions"])
            acts.setData(0, _KIND, ("actions", "", ""))
            self.tree.addTopLevelItem(acts)
            for aname, act in self.main.session.actions.items():
                marks = [obj for obj, a
                         in self.main.session.action_assignments.items()
                         if a == aname]
                label = aname + (f"  -> {', '.join(marks)}" if marks else "")
                child = QTreeWidgetItem(acts, [label])
                child.setData(0, _KIND, ("action", "", aname))

            self.tree.expandAll()
            self._restore_current(current)
        finally:
            self._syncing = False

    # -- selection sync ---------------------------------------------------
    def _current_context(self):
        item = self.tree.currentItem()
        return item.data(0, _KIND) if item is not None else ("", "", "")

    def _restore_current(self, ctx):
        kind, oname, iname = ctx
        if not kind:
            return
        item = self._find(kind, oname, iname)
        if item is not None:
            self.tree.setCurrentItem(item)

    def _find(self, kind, oname, iname):
        it = self._iter_items()
        for item in it:
            if item.data(0, _KIND) == (kind, oname, iname):
                return item
        return None

    def _iter_items(self, parent=None):
        count = (self.tree.topLevelItemCount() if parent is None
                 else parent.childCount())
        for i in range(count):
            item = (self.tree.topLevelItem(i) if parent is None
                    else parent.child(i))
            yield item
            yield from self._iter_items(item)

    def _on_current_changed(self, item, _prev):
        if self._syncing:
            return
        kind, oname, iname = (item.data(0, _KIND) if item is not None
                              else ("", "", ""))
        if kind == "object":
            vp = getattr(self.main, "viewport", None)
            if vp is not None and (vp.selected is None
                                   or vp.selected[0] != oname):
                self._syncing = True
                try:
                    vp.set_selected(oname)
                finally:
                    self._syncing = False
        elif kind == "action":
            self.main.session.set_active_action(iname or None)
            QTimer.singleShot(0, self.data_changed.emit)
        self.context_changed.emit(kind, oname, iname)

    def on_viewport_selection(self, name, _index):
        """Highlight the outliner row for a viewport selection."""
        if self._syncing:
            return
        self._syncing = True
        try:
            item = self._find("object", name, "") if name else None
            self.tree.setCurrentItem(item)
        finally:
            self._syncing = False

    # -- editing -----------------------------------------------------------
    def _push(self, command, applied=False):
        """Route a mutation through the main window's undo stack.

        Deferred with singleShot(0): callers run inside tree change
        notifications, where a synchronous refresh would clear the tree
        re-entrantly.  With ``applied=True`` the mutation already happened
        (command redo is idempotent, so the deferred push is safe).
        """
        push = getattr(self.main, "push_command", None)
        if push is not None:
            QTimer.singleShot(0, lambda: push(command))
        else:
            if not applied:
                command.redo()
            QTimer.singleShot(0, self.data_changed.emit)

    def _on_item_changed(self, item, _col):
        if self._syncing:
            return
        data = item.data(0, _KIND)
        if data is None:
            return
        kind, oname, _ = data
        if kind != "object":
            return
        from .operators import RenameObjectCommand, SetObjectVisibleCommand
        # Checkbox toggles visibility; a changed text is a rename.
        visible = item.checkState(0) == Qt.Checked
        obj = self.main.session.project.objects.get(oname)
        if obj is not None and obj.visible != visible:
            # Apply at once (undo command captures the old value first).
            cmd = SetObjectVisibleCommand(self.main.session, oname, visible)
            self.main.session.set_object_visible(oname, visible)
            self._push(cmd, applied=True)
            return
        new_name = item.text(0).strip()
        if new_name and new_name != oname:
            if new_name in self.main.session.project.objects:
                self._syncing = True
                try:
                    item.setText(0, oname)
                finally:
                    self._syncing = False
                QMessageBox.warning(self, "Rename failed",
                                    f"object {new_name!r} already exists")
                return
            cmd = RenameObjectCommand(self.main.session, oname, new_name)
            self.main.session.rename_object(oname, new_name)
            item.setData(0, _KIND, ("object", new_name, ""))
            self._push(cmd, applied=True)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete:
            self._delete_current()
        elif event.key() == Qt.Key_F2:
            self._rename_current()
        else:
            super().keyPressEvent(event)

    def _rename_current(self):
        kind, oname, _ = self._current_context()
        if kind != "object":
            return
        item = self.tree.currentItem()
        if item is not None:
            self.tree.editItem(item, 0)

    def _delete_current(self):
        from .operators import (
            DeleteActionCommand, DeleteMaterialCommand, DeleteObjectCommand,
        )
        kind, oname, iname = self._current_context()
        if kind == "object":
            if QMessageBox.question(
                    self, "Delete object",
                    f"Delete object {oname!r}?") != QMessageBox.Yes:
                return
            vp = getattr(self.main, "viewport", None)
            if vp is not None and vp.selected is not None \
                    and vp.selected[0] == oname:
                vp.set_selected(None)
            self._push(DeleteObjectCommand(self.main.session, oname))
        elif kind == "material":
            if QMessageBox.question(
                    self, "Delete material",
                    f"Delete material {iname!r}?") != QMessageBox.Yes:
                return
            self._push(DeleteMaterialCommand(self.main.session, iname))
        elif kind == "action":
            self._push(DeleteActionCommand(self.main.session, iname))

    def _context_menu(self, pos):
        menu = QMenu(self)
        kind, oname, iname = self._current_context()
        add_obj = menu.addAction("Add Object")
        add_mat = menu.addAction("Add Material")
        add_act = menu.addAction("Add Action")
        menu.addSeparator()
        rename = menu.addAction("Rename")
        rename.setEnabled(kind in ("object", "action"))
        assign = menu.addAction("Assign to Selected Object")
        vp = getattr(self.main, "viewport", None)
        assign.setEnabled(kind == "action" and vp is not None
                          and vp.selected is not None)
        delete = menu.addAction("Delete")
        delete.setEnabled(kind in ("object", "material", "action"))
        chosen = menu.exec(self.tree.viewport().mapToGlobal(pos))
        if chosen is add_obj:
            self._add_object()
        elif chosen is add_mat:
            self._add_material()
        elif chosen is add_act:
            self._add_action()
        elif chosen is rename:
            if kind == "action":
                self._rename_action(iname)
            else:
                self._rename_current()
        elif chosen is assign:
            self._assign_action(iname, vp.selected[0])
        elif chosen is delete:
            self._delete_current()

    def _add_action(self):
        from .operators import CreateActionCommand
        name, ok = QInputDialog.getText(self, "Add action", "Name:")
        name = name.strip()
        if not ok or not name:
            return
        if name in self.main.session.actions:
            QMessageBox.warning(self, "Add action",
                                f"action {name!r} already exists")
            return
        self._push(CreateActionCommand(self.main.session, name))

    def _rename_action(self, old_name):
        from .operators import RenameActionCommand
        name, ok = QInputDialog.getText(self, "Rename action", "Name:",
                                        text=old_name)
        name = name.strip()
        if not ok or not name or name == old_name:
            return
        if name in self.main.session.actions:
            QMessageBox.warning(self, "Rename action",
                                f"action {name!r} already exists")
            return
        self._push(RenameActionCommand(self.main.session, old_name, name))

    def _assign_action(self, action_name, object_name):
        from .operators import AssignActionCommand
        try:
            # Validate compatibility before the deferred undo push.
            self.main.session.apply_action_to_character(
                action_name, object_name)
        except Exception as exc:
            QMessageBox.warning(self, "Assign action", str(exc))
            return
        self._push(AssignActionCommand(self.main.session,
                                       action_name, object_name))

    def _add_object(self):
        from .operators import AddObjectCommand
        name, ok = QInputDialog.getText(self, "Add object", "Name:")
        name = name.strip()
        if not ok or not name:
            return
        if name in self.main.session.project.objects:
            QMessageBox.warning(self, "Add object",
                                f"object {name!r} already exists")
            return
        self._push(AddObjectCommand(self.main.session, name))

    def _add_material(self):
        from .operators import AddMaterialCommand
        name, ok = QInputDialog.getText(self, "Add material", "Name:")
        name = name.strip()
        if not ok or not name:
            return
        if name in self.main.session.project.materials:
            QMessageBox.warning(self, "Add material",
                                f"material {name!r} already exists")
            return
        self._push(AddMaterialCommand(self.main.session, name))
