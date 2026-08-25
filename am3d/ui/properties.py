"""Properties editor: tabbed, context-sensitive dock.

Shows an Object, Bone, Material or Render tab depending on the current
outliner / viewport selection.  Every edit mutates the model and emits
``data_changed`` so the viewport and other panels refresh.
"""

from __future__ import annotations

import numpy as np

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDoubleSpinBox, QFormLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox, QTabWidget,
    QVBoxLayout, QWidget,
)

from am3d.core.mathutil import compose_trs, decompose_trs

_RANGE = (-1e6, 1e6)


def _spin(value, lo=_RANGE[0], hi=_RANGE[1], step=0.1, decimals=3):
    s = QDoubleSpinBox()
    s.setRange(lo, hi)
    s.setSingleStep(step)
    s.setDecimals(decimals)
    s.setValue(float(value))
    return s


class _Vec3Row(QWidget):
    """Three spin boxes in a row, editing one numpy vec3."""

    def __init__(self, on_change):
        super().__init__()
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.spins = [_spin(0.0) for _ in range(3)]
        for s in self.spins:
            s.valueChanged.connect(on_change)
            row.addWidget(s)

    def set(self, vec):
        for s, v in zip(self.spins, vec):
            s.blockSignals(True)
            s.setValue(float(v))
            s.blockSignals(False)

    def get(self):
        return np.array([s.value() for s in self.spins], dtype=np.float64)


class PropertiesDock(QWidget):
    """Tabbed editor for the current selection's properties.

    A plain widget so it can live inside the tiled area layout; the
    "Dock" name is kept for compatibility with earlier phases.
    """

    data_changed = Signal()

    def __init__(self, main_window):
        super().__init__(main_window)
        self.main = main_window
        self.setWindowTitle("Properties")
        self._context = ("", "", "")     # (kind, object_name, item_name)
        self._loading = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self._build_object_tab()
        self._build_bone_tab()
        self._build_material_tab()
        self._build_render_tab()
        layout.addWidget(self.tabs)

    # -- tabs ---------------------------------------------------------------
    def _build_object_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        self.obj_name = QLineEdit()
        self.obj_name.editingFinished.connect(self._rename_object)
        form.addRow("Name", self.obj_name)
        self.obj_loc = _Vec3Row(self._object_transform_changed)
        self.obj_rot = _Vec3Row(self._object_transform_changed)
        self.obj_scl = _Vec3Row(self._object_transform_changed)
        form.addRow("Location", self.obj_loc)
        form.addRow("Rotation", self.obj_rot)
        form.addRow("Scale", self.obj_scl)
        self.obj_visible = QCheckBox("Visible in viewport")
        self.obj_visible.toggled.connect(self._object_visible_changed)
        form.addRow(self.obj_visible)
        self.tabs.addTab(w, "Object")

    def _build_bone_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        self.bone_label = QLabel("-")
        form.addRow("Bone", self.bone_label)
        self.bone_head = _Vec3Row(self._bone_changed)
        self.bone_tail = _Vec3Row(self._bone_changed)
        form.addRow("Head", self.bone_head)
        form.addRow("Tail", self.bone_tail)
        self.tabs.addTab(w, "Bone")

    def _build_material_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        self.mat_name = QLabel("-")
        form.addRow("Material", self.mat_name)
        swatch_row = QHBoxLayout()
        self.mat_swatch = QPushButton()
        self.mat_swatch.setFixedSize(48, 24)
        self.mat_swatch.clicked.connect(self._pick_color)
        swatch_row.addWidget(self.mat_swatch)
        swatch_row.addStretch(1)
        swatch_w = QWidget()
        swatch_w.setLayout(swatch_row)
        form.addRow("Albedo", swatch_w)
        self.mat_bump = QLineEdit()
        self.mat_transp = QLineEdit()
        self.mat_spec = QLineEdit()
        self.mat_bump.editingFinished.connect(self._material_maps_changed)
        self.mat_transp.editingFinished.connect(self._material_maps_changed)
        self.mat_spec.editingFinished.connect(self._material_maps_changed)
        form.addRow("Bump map", self.mat_bump)
        form.addRow("Transparency", self.mat_transp)
        form.addRow("Specular", self.mat_spec)
        self.tabs.addTab(w, "Material")

    def _build_render_tab(self):
        w = QWidget()
        form = QFormLayout(w)
        self.rnd_supersample = QSpinBox()
        self.rnd_supersample.setRange(1, 8)
        self.rnd_supersample.valueChanged.connect(self._render_changed)
        form.addRow("Supersample", self.rnd_supersample)
        self.rnd_toon = QCheckBox("Toon shading (cel bands + ink)")
        self.rnd_toon.toggled.connect(self._render_changed)
        form.addRow(self.rnd_toon)
        self.tabs.addTab(w, "Render")

    # -- context ------------------------------------------------------------
    def set_context(self, kind, object_name="", item_name=""):
        """Select the tab matching *kind* and populate it from the model."""
        self._context = (kind, object_name, item_name)
        tab = {"object": 0, "bone": 1, "material": 2}.get(kind)
        if tab is not None:
            self.tabs.setCurrentIndex(tab)
        self.refresh()

    def refresh(self):
        kind, oname, iname = self._context
        proj = self.main.session.project
        self._loading = True
        try:
            if kind == "object" and oname in proj.objects:
                obj = proj.objects[oname]
                self.obj_name.setText(obj.name)
                loc, rot, scl = decompose_trs(obj.transform)
                self.obj_loc.set(loc)
                self.obj_rot.set(rot)
                self.obj_scl.set(scl)
                self.obj_visible.setChecked(getattr(obj, "visible", True))
            elif kind == "bone":
                bones = {b.name: b for b in self.main.session.get_bones(oname)}
                bone = bones.get(iname)
                if bone is not None:
                    self.bone_label.setText(f"{oname} / {iname}")
                    self.bone_head.set(bone.head)
                    self.bone_tail.set(bone.tail)
            elif kind == "material":
                mat = proj.materials.get(iname)
                if mat is not None:
                    self.mat_name.setText(iname)
                    self._set_swatch(mat.color)
                    self.mat_bump.setText(mat.bump_map or "")
                    self.mat_transp.setText(mat.transparency_map or "")
                    self.mat_spec.setText(mat.specular_map or "")
            settings = getattr(proj, "render_settings",
                               {"supersample": 2, "toon": True})
            self.rnd_supersample.setValue(int(settings.get("supersample", 2)))
            self.rnd_toon.setChecked(bool(settings.get("toon", True)))
        finally:
            self._loading = False

    # -- object tab -----------------------------------------------------------
    def _selected_object(self):
        kind, oname, _ = self._context
        if kind != "object":
            return None
        return self.main.session.project.objects.get(oname)

    def _rename_object(self):
        if self._loading:
            return
        obj = self._selected_object()
        if obj is None:
            return
        new_name = self.obj_name.text().strip()
        if not new_name or new_name == obj.name:
            return
        if new_name in self.main.session.project.objects:
            self.obj_name.setText(obj.name)
            return
        from .operators import RenameObjectCommand, push_or_apply
        push_or_apply(self.main,
                      RenameObjectCommand(self.main.session, obj.name,
                                          new_name),
                      self.data_changed)
        self._context = ("object", new_name, "")

    def _object_transform_changed(self):
        if self._loading:
            return
        obj = self._selected_object()
        if obj is None:
            return
        from .operators import SetObjectTransformCommand, push_or_apply
        after = compose_trs(self.obj_loc.get(), self.obj_rot.get(),
                            self.obj_scl.get())
        if np.allclose(after, obj.transform):
            return
        push_or_apply(self.main,
                      SetObjectTransformCommand(self.main.session, obj.name,
                                                obj.transform, after),
                      self.data_changed)

    def _object_visible_changed(self, checked):
        if self._loading:
            return
        obj = self._selected_object()
        if obj is None or obj.visible == bool(checked):
            return
        from .operators import SetObjectVisibleCommand, push_or_apply
        push_or_apply(self.main,
                      SetObjectVisibleCommand(self.main.session, obj.name,
                                              bool(checked)),
                      self.data_changed)

    # -- bone tab -------------------------------------------------------------
    def _bone_changed(self):
        if self._loading:
            return
        kind, oname, iname = self._context
        if kind != "bone":
            return
        bones = {b.name: b for b in self.main.session.get_bones(oname)}
        bone = bones.get(iname)
        if bone is None:
            return
        from .operators import SetBoneEndpointsCommand, push_or_apply
        head, tail = self.bone_head.get(), self.bone_tail.get()
        if np.allclose(head, bone.head) and np.allclose(tail, bone.tail):
            return
        push_or_apply(self.main,
                      SetBoneEndpointsCommand(
                          self.main.session, oname, iname,
                          (bone.head, bone.tail), (head, tail)),
                      self.data_changed)
    # -- material tab ---------------------------------------------------------
    def _selected_material(self):
        kind, _, iname = self._context
        if kind != "material":
            return None
        return self.main.session.project.materials.get(iname)

    def _set_swatch(self, color):
        rgb = tuple(int(max(0.0, min(1.0, c)) * 255) for c in color[:3])
        self.mat_swatch.setStyleSheet(
            f"background-color: rgb({rgb[0]}, {rgb[1]}, {rgb[2]});")

    def _pick_color(self):
        mat = self._selected_material()
        if mat is None:
            return
        rgb = tuple(int(v * 255) for v in mat.color[:3])
        col = QColorDialog.getColor(
            QColor(*rgb, 255), self,
            f"Edit {mat.name} colour", QColorDialog.ShowAlphaChannel)
        if col.isValid():
            from .operators import SetMaterialColorCommand, push_or_apply
            color = (col.red() / 255.0, col.green() / 255.0,
                     col.blue() / 255.0, col.alpha() / 255.0)
            push_or_apply(self.main,
                          SetMaterialColorCommand(self.main.session,
                                                  mat.name, color),
                          self.data_changed)
            self._set_swatch(mat.color)

    def _material_maps_changed(self):
        if self._loading:
            return
        mat = self._selected_material()
        if mat is None:
            return
        from .operators import SetMaterialMapsCommand, push_or_apply
        push_or_apply(self.main,
                      SetMaterialMapsCommand(
                          self.main.session, mat.name,
                          self.mat_bump.text().strip() or None,
                          self.mat_transp.text().strip() or None,
                          self.mat_spec.text().strip() or None),
                      self.data_changed)

    # -- render tab -----------------------------------------------------------
    def _render_changed(self):
        if self._loading:
            return
        proj = self.main.session.project
        settings = getattr(proj, "render_settings", None)
        if settings is None:
            settings = proj.render_settings = {}
        settings["supersample"] = int(self.rnd_supersample.value())
        settings["toon"] = bool(self.rnd_toon.isChecked())
        self.data_changed.emit()
