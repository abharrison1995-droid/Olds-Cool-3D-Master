"""Serialization for reusable assets (.am3a Actions) and projects.

Actions are saved as independent, reusable assets (in the spirit of
Animation Master).  We use msgpack plus numpy-aware helpers, so the format
is compact and readily consumable by an external agentic pipeline.
"""

from __future__ import annotations

import io

import msgpack
import numpy as np

class ProjectFormatError(Exception):
    """Raised when a project file is malformed or exceeds safety limits."""


# Schema version and safety limits
FORMAT_VERSION = 1
_MAX_FILE_BYTES = 64 * 1024 * 1024       # 64 MB
_MAX_OBJECTS = 1000
_MAX_SPLINES = 5000
_MAX_PATCHES = 5000
_MAX_BONES = 500
_MAX_ACTIONS = 200
_MAX_CHANNELS = 2000
_MAX_KEYS = 50000
_MAX_CONTAINER_DEPTH = 20
_MAX_ARRAY_ELEMENTS = 10_000_000
_ALLOWED_DTYPES = {"float16", "float32", "float64", "int8", "int16",
                   "int32", "int64", "uint8", "uint16", "uint32", "uint64",
                   "bool"}


def validate_project_bytes(payload: bytes) -> None:
    """Check *payload* size and structural limits before unpacking.

    Raises ProjectFormatError if any limit is exceeded.
    """
    if len(payload) > _MAX_FILE_BYTES:
        raise ProjectFormatError(
            f"File too large: {len(payload)} bytes (max {_MAX_FILE_BYTES})")
    if len(payload) < 4:
        raise ProjectFormatError("File too small (truncated?)")


def validate_project_data(data: dict) -> None:
    """Validate deserialized project dict against safety limits."""
    objs = data.get("objects", {})
    if len(objs) > _MAX_OBJECTS:
        raise ProjectFormatError(
            f"Too many objects: {len(objs)} (max {_MAX_OBJECTS})")
    for oname, odata in objs.items():
        if len(odata.get("splines", {})) > _MAX_SPLINES:
            raise ProjectFormatError(
                f"Too many splines in {oname!r}")
        if len(odata.get("patches", [])) > _MAX_PATCHES:
            raise ProjectFormatError(
                f"Too many patches in {oname!r}")
    skels = data.get("skeletons", {})
    for oname, bones in skels.items():
        if len(bones) > _MAX_BONES:
            raise ProjectFormatError(
                f"Too many bones in {oname!r} (max {_MAX_BONES})")
    acts = data.get("actions", {}).get("items", {})
    if len(acts) > _MAX_ACTIONS:
        raise ProjectFormatError(
            f"Too many actions: {len(acts)} (max {_MAX_ACTIONS})")


from .animation import Action, Channel, Interpolation, Keyframe
from .project import Material, Project, Spline, ControlPoint


def _pack_ndarray(a):
    return {"__nd__": True, "shape": list(a.shape),
            "dtype": str(a.dtype), "data": np.ascontiguousarray(a).tobytes()}


def _unpack_ndarray(obj):
    if isinstance(obj, dict) and obj.get("__nd__"):
        return np.frombuffer(obj["data"], dtype=obj["dtype"]).reshape(obj["shape"])
    return obj


def _encode(obj):
    if isinstance(obj, np.ndarray):
        return _pack_ndarray(obj)
    if isinstance(obj, Action):
        return {"__action__": True,
                "name": obj.name, "duration": obj.duration,
                "signature": list(obj.signature), "metadata": obj.metadata,
                "channels": [_encode_ch(ch) for ch in obj.channels]}
    raise TypeError(f"cannot encode {type(obj).__name__}")


def _encode_ch(ch):
    return {"__channel__": True, "bone": ch.bone, "property": ch.property,
            "keys": [{"t": k.time, "v": _pack_ndarray(k.value),
                      "i": k.interp,
                      "ti": (_pack_ndarray(np.asarray(k.in_tangent,
                                                    dtype=np.float64))
                             if k.in_tangent is not None else None),
                      "to": (_pack_ndarray(np.asarray(k.out_tangent,
                                                      dtype=np.float64))
                             if k.out_tangent is not None else None)}
                     for k in ch.keys]}


def _decode_ch(c):
    ch = Channel(bone=c["bone"], property=c["property"])
    for k in c["keys"]:
        kv = Keyframe(k["t"], _unpack_ndarray(k.get("v")), k.get("i", "smooth"))
        kv.value = np.asarray(kv.value, dtype=np.float64).reshape(-1)
        ti = k.get("ti")
        to = k.get("to")
        if ti is not None:
            kv.in_tangent = np.asarray(_unpack_ndarray(ti),
                                       dtype=np.float64).reshape(-1)
        if to is not None:
            kv.out_tangent = np.asarray(_unpack_ndarray(to),
                                        dtype=np.float64).reshape(-1)
        ch.keys.append(kv)
    ch.keys.sort(key=lambda kk: kk.time)
    return ch


def _decode(obj):
    if isinstance(obj, dict) and obj.get("__nd__"):
        return _unpack_ndarray(obj)
    if isinstance(obj, dict) and obj.get("__action__"):
        chans = [_decode_ch(c) for c in obj["channels"]]
        return Action(name=obj["name"], duration=obj["duration"],
                      channels=chans, signature=tuple(obj["signature"]),
                      metadata=obj.get("metadata", {}))
    if isinstance(obj, dict) and obj.get("__channel__"):
        return _decode_ch(obj)
    return obj


def dump_action(action: Action) -> bytes:
    """Serialize an Action to a compact byte payload (.am3a)."""
    return msgpack.packb(_encode(action), use_bin_type=True)


def load_action(payload: bytes) -> Action:
    """Deserialize an Action from :func:`dump_action` output."""
    return _decode(msgpack.unpackb(payload, raw=False))


def save_action(action: Action, path: str):
    with open(path, "wb") as fh:
        fh.write(dump_action(action))


def load_action_file(path: str) -> Action:
    with open(path, "rb") as fh:
        return load_action(fh.read())


def _encode_bone(bone) -> dict:
    return {
        "name": bone.name,
        "parent": bone.parent,
        "head": _pack_ndarray(np.asarray(bone.head, dtype=np.float64)),
        "tail": _pack_ndarray(np.asarray(bone.tail, dtype=np.float64)),
        "cp_weights": {str(k): float(v)
                       for k, v in getattr(bone, "cp_weights", {}).items()},
    }


def _decode_bone(data: dict):
    from .project import Bone
    return Bone(
        name=data["name"],
        parent=data.get("parent"),
        head=_unpack_ndarray(data["head"]),
        tail=_unpack_ndarray(data["tail"]),
        cp_weights={int(k): float(v)
                    for k, v in data.get("cp_weights", {}).items()},
    )


def dump_project(project: Project, actions: dict | None = None) -> bytes:
    """Serialize the whole project document (compact).

    ``actions`` (optional mapping name -> Action) is stored in a versioned
    ``actions`` section so Session-level actions survive project save/load.
    """
    body = {
        "name": project.name,
        "mode": project.mode,
        "frame": project.frame,
        "fps": project.fps,
        "render_settings": dict(getattr(project, "render_settings",
                                        {"supersample": 2, "toon": True})),
        "animation_settings": dict(getattr(project, "animation_settings",
                                           {"frame_start": 0,
                                            "frame_end": 120,
                                            "fps": 30.0})),
        "objects": {
            name: {
                "visible": bool(getattr(obj, "visible", True)),
                "transform": _pack_ndarray(
                    np.asarray(obj.transform, dtype=np.float64)),
                "splines": {
                    sname: {
                        "degree": spl.degree, "closed": spl.closed,
                        "cps": [_pack_ndarray(spl.point_array()),
                                spl.weights_array().tolist()],
                    }
                    for sname, spl in obj.splines.items()
                },
                # Patches carry their own interior B-spline control net.
                "patches": [
                    {
                        "name": patch.name,
                        "splines": list(patch.splines),
                        "interior": (_pack_ndarray(patch.interior)
                                     if patch.interior is not None else None),
                    }
                    for patch in obj.patches
                ],
                "hooks": [
                    {"source": list(h.source), "target": list(h.target),
                     "strength": float(h.strength)}
                    for h in obj.hooks
                ],
            }
            for name, obj in project.objects.items()
        },
        # Skeletons: object_name -> {bone_name -> encoded bone}
        "skeletons": {
            oname: {bname: _encode_bone(bone) for bname, bone in rig.items()}
            for oname, rig in project.skeletons.items()
        },
        "materials": {
            n: {
                "color": list(m.color),
                "bump_map": m.bump_map,
                "transparency_map": m.transparency_map,
                "specular_map": m.specular_map,
            }
            for n, m in project.materials.items()
        },
    }
    if actions:
        body["actions"] = {
            "version": 1,
            "items": {name: _encode(act) for name, act in actions.items()},
        }
    body["session_state"] = {
        "version": 2,
        "active_action": project.active_action,
        "action_assignments": dict(project.action_assignments),
    }
    body["format_version"] = 2
    return msgpack.packb(body, use_bin_type=True)


def load_project_bytes(payload: bytes) -> Project:
    validate_project_bytes(payload)
    data = msgpack.unpackb(payload, raw=False)
    validate_project_data(data)
    p = Project(name=data["name"])
    p.mode = data.get("mode", "object")
    p.frame = data.get("frame", 0.0)
    p.fps = data.get("fps", 30.0)
    rs = data.get("render_settings")
    if isinstance(rs, dict):
        p.render_settings.update(rs)
    # Optional animation settings (absent in old files -> defaults stay).
    ans = data.get("animation_settings")
    if isinstance(ans, dict):
        p.animation_settings.update(ans)

    from .project import Hook as _Hook, Object3D as _Object3D, \
        Patch as _Patch, Spline as _Spline, ControlPoint as _CP

    for oname, odata in data.get("objects", {}).items():
        obj = p.create_object(oname)
        obj.visible = bool(odata.get("visible", True))
        if odata.get("transform") is not None:
            obj.transform = _unpack_ndarray(odata["transform"]).reshape(4, 4)
        for sname, sdata in odata.get("splines", {}).items():
            pts = _unpack_ndarray(sdata["cps"][0])
            weights = sdata["cps"][1]
            cps = [_CP(np.asarray(pt, dtype=np.float64), w)
                   for pt, w in zip(pts, weights)]
            obj.add_spline(_Spline(name=sname, cps=cps,
                                   degree=sdata["degree"],
                                   closed=sdata["closed"]))
        for pdata in odata.get("patches", []):
            interior = None
            if pdata.get("interior") is not None:
                interior = _unpack_ndarray(pdata["interior"])
                if interior is not None:
                    interior = np.asarray(interior, dtype=np.float64)
            obj.patches.append(_Patch(name=pdata.get("name", "patch"),
                                      splines=list(pdata.get("splines", [])),
                                      interior=interior))
        for hdata in odata.get("hooks", []):
            obj.hooks.append(_Hook(source=tuple(hdata.get("source", ())),
                                   target=tuple(hdata.get("target", ())),
                                   strength=float(hdata.get("strength", 1.0))))

    for oname, rig_data in data.get("skeletons", {}).items():
        p.skeletons[oname] = {bname: _decode_bone(bd)
                              for bname, bd in rig_data.items()}

    for n, mdata in data.get("materials", {}).items():
        if isinstance(mdata, dict):
            p.materials[n] = Material(
                name=n, color=tuple(mdata["color"]),
                bump_map=mdata.get("bump_map"),
                transparency_map=mdata.get("transparency_map"),
                specular_map=mdata.get("specular_map"))
        else:  # legacy format: bare color list
            p.materials[n] = Material(name=n, color=tuple(mdata))

    p.actions = {}
    adata = data.get("actions")
    if isinstance(adata, dict):
        p.actions = {name: _decode(a)
                     for name, a in adata.get("items", {}).items()}

    # Session state (V2+)
    ss = data.get("session_state")
    if isinstance(ss, dict):
        p.active_action = ss.get("active_action")
        ass = ss.get("action_assignments", {})
        if isinstance(ass, dict):
            p.action_assignments = dict(ass)
    return p


def save_project(project: Project, path: str, actions: dict | None = None):
    with open(path, "wb") as fh:
        fh.write(dump_project(project, actions=actions))


def load_project(path: str) -> Project:
    with open(path, "rb") as fh:
        return load_project_bytes(fh.read())