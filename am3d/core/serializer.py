"""Serialization for reusable assets (.am3a Actions) and projects.

Actions are saved as independent, reusable assets (in the spirit of
Animation Master).  We use msgpack plus numpy-aware helpers, so the format
is compact and readily consumable by an external agentic pipeline.
"""

from __future__ import annotations

import io
import math
import os
from .paths import is_absolute_any_platform
import tempfile

import msgpack
import numpy as np

class ProjectFormatError(Exception):
    """Raised when a project file is malformed or exceeds safety limits."""


# Schema version and safety limits
FORMAT_VERSION = 2
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


def _check_container_depth(val, depth=0):
    if depth > _MAX_CONTAINER_DEPTH:
        raise ProjectFormatError(
            f"Container nesting depth {depth} exceeds safety limit {_MAX_CONTAINER_DEPTH}")
    if isinstance(val, dict):
        for v in val.values():
            _check_container_depth(v, depth + 1)
    elif isinstance(val, (list, tuple)):
        for item in val:
            _check_container_depth(item, depth + 1)


def _unpack_msgpack(payload: bytes) -> dict:
    """``msgpack.unpackb`` with the array-length safety limit applied at
    unpack time.

    ``_check_container_depth``/``_unpack_ndarray`` catch oversized data only
    after msgpack has already built the Python structure in memory -- too
    late to stop a single huge top-level array claim from allocating it.
    ``max_array_len`` rejects that during unpacking instead, and any failure
    is surfaced as ``ProjectFormatError`` like every other load-time error.
    """
    try:
        return msgpack.unpackb(payload, raw=False,
                               max_array_len=_MAX_ARRAY_ELEMENTS)
    except (ValueError, msgpack.exceptions.UnpackException) as exc:
        raise ProjectFormatError(f"Malformed msgpack data: {exc}") from exc


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
    if not isinstance(data, dict):
        raise ProjectFormatError("Project data payload must be a dict")
    _check_container_depth(data)
    if "name" not in data or not isinstance(data["name"], str):
        raise ProjectFormatError("Project root missing required string 'name'")
    objs = data.get("objects", {})
    if not isinstance(objs, dict):
        raise ProjectFormatError("'objects' field must be a dictionary")
    if len(objs) > _MAX_OBJECTS:
        raise ProjectFormatError(
            f"Too many objects: {len(objs)} (max {_MAX_OBJECTS})")
    for oname, odata in objs.items():
        if not isinstance(odata, dict):
            raise ProjectFormatError(f"Object {oname!r} must be a dictionary")
        splines = odata.get("splines", {})
        if not isinstance(splines, dict):
            raise ProjectFormatError(f"Object {oname!r} 'splines' must be a dictionary")
        if len(splines) > _MAX_SPLINES:
            raise ProjectFormatError(
                f"Too many splines in {oname!r}")
        patches = odata.get("patches", [])
        if not isinstance(patches, list):
            raise ProjectFormatError(f"Object {oname!r} 'patches' must be a list")
        if len(patches) > _MAX_PATCHES:
            raise ProjectFormatError(
                f"Too many patches in {oname!r}")
        for pdata in patches:
            if not isinstance(pdata, dict):
                raise ProjectFormatError(f"Patch in object {oname!r} must be a dictionary")
        hooks = odata.get("hooks", [])
        if not isinstance(hooks, list):
            raise ProjectFormatError(f"Object {oname!r} 'hooks' must be a list")
        for hdata in hooks:
            if not isinstance(hdata, dict):
                raise ProjectFormatError(f"Hook in object {oname!r} must be a dictionary")
    skels = data.get("skeletons", {})
    if not isinstance(skels, dict):
        raise ProjectFormatError("'skeletons' field must be a dictionary")
    for oname, bones in skels.items():
        if not isinstance(bones, dict):
            raise ProjectFormatError(f"Skeleton for {oname!r} must be a dictionary")
        if len(bones) > _MAX_BONES:
            raise ProjectFormatError(
                f"Too many bones in {oname!r} (max {_MAX_BONES})")
    mats = data.get("materials")
    if mats is not None and not isinstance(mats, (dict, list)):
        raise ProjectFormatError("'materials' field must be a dictionary or list")
    adata = data.get("actions", {})
    if isinstance(adata, dict):
        acts = adata.get("items", {})
        if isinstance(acts, dict):
            if len(acts) > _MAX_ACTIONS:
                raise ProjectFormatError(
                    f"Too many actions: {len(acts)} (max {_MAX_ACTIONS})")
            for aname, aobj in acts.items():
                if isinstance(aobj, dict):
                    chans = aobj.get("channels", [])
                    if isinstance(chans, list) and len(chans) > _MAX_CHANNELS:
                        raise ProjectFormatError(
                            f"Action {aname!r} exceeds channel limit {_MAX_CHANNELS}")


from .animation import Action, Channel, Interpolation, Keyframe
from .project import Material, Project, Spline, ControlPoint


def _pack_ndarray(a):
    return {"__nd__": True, "shape": list(a.shape),
            "dtype": str(a.dtype), "data": np.ascontiguousarray(a).tobytes()}


def _unpack_ndarray(obj):
    if isinstance(obj, dict) and obj.get("__nd__"):
        dtype_str = obj.get("dtype")
        if dtype_str not in _ALLOWED_DTYPES:
            raise ProjectFormatError(f"Disallowed or unknown numpy dtype: {dtype_str!r}")
        raw_shape = obj.get("shape")
        if not isinstance(raw_shape, list) or not (0 <= len(raw_shape) <= 4):
            raise ProjectFormatError(f"Invalid array shape: {raw_shape!r}")
        for dim in raw_shape:
            if not isinstance(dim, int) or dim < 0:
                raise ProjectFormatError(f"Invalid array dimension: {dim!r}")
        elements = math.prod(raw_shape) if raw_shape else 1
        if elements > _MAX_ARRAY_ELEMENTS:
            raise ProjectFormatError(f"Array element count {elements} exceeds limit {_MAX_ARRAY_ELEMENTS}")
        data_bytes = obj.get("data")
        if not isinstance(data_bytes, (bytes, bytearray, memoryview)):
            raise ProjectFormatError("Array data must be bytes")
        itemsize = np.dtype(dtype_str).itemsize
        if len(data_bytes) != elements * itemsize:
            raise ProjectFormatError(
                f"Array payload byte length mismatch: got {len(data_bytes)}, expected {elements * itemsize}")
        arr = np.frombuffer(data_bytes, dtype=dtype_str).reshape(raw_shape)
        if np.issubdtype(arr.dtype, np.floating) and not np.all(np.isfinite(arr)):
            raise ProjectFormatError("Array contains non-finite values (NaN or Inf)")
        return arr
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
    if not isinstance(c, dict) or "bone" not in c or "property" not in c:
        raise ProjectFormatError("Channel record missing required 'bone' or 'property'")
    ch = Channel(bone=str(c["bone"]), property=str(c["property"]))
    raw_keys = c.get("keys", [])
    if not isinstance(raw_keys, list):
        raise ProjectFormatError("Channel keys must be a list")
    if len(raw_keys) > _MAX_KEYS:
        raise ProjectFormatError(f"Too many keys in channel: {len(raw_keys)} (max {_MAX_KEYS})")
    for k in raw_keys:
        if not isinstance(k, dict) or "t" not in k or "v" not in k:
            raise ProjectFormatError("Keyframe record missing required 't' or 'v'")
        try:
            t = float(k["t"])
        except (ValueError, TypeError):
            raise ProjectFormatError("Keyframe time must be a float")
        if not math.isfinite(t):
            raise ProjectFormatError("Keyframe time must be finite")
        v = _unpack_ndarray(k.get("v"))
        v_arr = np.asarray(v, dtype=np.float64).reshape(-1)
        if not np.all(np.isfinite(v_arr)):
            raise ProjectFormatError("Keyframe value contains non-finite numbers")
        interp = k.get("i", "smooth")
        kv = Keyframe(t, v_arr, interp)
        ti = k.get("ti")
        to = k.get("to")
        if ti is not None:
            ti_arr = np.asarray(_unpack_ndarray(ti), dtype=np.float64).reshape(-1)
            if not np.all(np.isfinite(ti_arr)):
                raise ProjectFormatError("Keyframe in_tangent contains non-finite numbers")
            kv.in_tangent = ti_arr
        if to is not None:
            to_arr = np.asarray(_unpack_ndarray(to), dtype=np.float64).reshape(-1)
            if not np.all(np.isfinite(to_arr)):
                raise ProjectFormatError("Keyframe out_tangent contains non-finite numbers")
            kv.out_tangent = to_arr
        ch.keys.append(kv)
    ch.keys.sort(key=lambda kk: kk.time)
    return ch


def _decode(obj):
    if isinstance(obj, dict) and obj.get("__nd__"):
        return _unpack_ndarray(obj)
    if isinstance(obj, dict) and obj.get("__action__"):
        channels_raw = obj.get("channels", [])
        if not isinstance(channels_raw, list) or len(channels_raw) > _MAX_CHANNELS:
            raise ProjectFormatError(
                f"Action channel count {len(channels_raw) if isinstance(channels_raw, list) else 'invalid'} exceeds safety limit {_MAX_CHANNELS}")
        chans = [_decode_ch(c) for c in channels_raw]
        dur = float(obj.get("duration", 1.0))
        if not math.isfinite(dur) or dur <= 0:
            raise ProjectFormatError(f"Action duration must be positive and finite, got {dur}")
        return Action(name=str(obj.get("name", "action")),
                      duration=dur,
                      channels=chans,
                      signature=tuple(obj.get("signature", ())),
                      metadata=dict(obj.get("metadata", {})))
    if isinstance(obj, dict) and obj.get("__channel__"):
        return _decode_ch(obj)
    return obj


def _atomic_write(path: str, payload: bytes) -> str:
    """Write payload atomically via same-directory tempfile and rename."""
    target = os.path.abspath(path)
    target_dir = os.path.dirname(target)
    if target_dir:
        os.makedirs(target_dir, exist_ok=True)
    tmp_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=target_dir, prefix=".am3d_tmp_", delete=False) as fh:
            tmp_name = fh.name
            fh.write(payload)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except (AttributeError, OSError):
                pass
        os.replace(tmp_name, target)
        tmp_name = None
        return target
    finally:
        if tmp_name and os.path.exists(tmp_name):
            try:
                os.remove(tmp_name)
            except OSError:
                pass


def resolve_resource_path(resource_path: str, base_dir: str | None = None) -> str:
    """Resolve a resource path relative to base_dir if relative."""
    if not resource_path:
        return resource_path
    # A project saved on Windows may carry "C:/tex.png"; os.path.isabs would
    # call that relative on POSIX and join it onto base_dir instead.
    if is_absolute_any_platform(resource_path):
        return resource_path
    if base_dir:
        return os.path.normpath(os.path.join(base_dir, resource_path))
    return resource_path


def dump_action(action: Action) -> bytes:
    """Serialize an Action to a compact byte payload (.am3a)."""
    return msgpack.packb(_encode(action), use_bin_type=True)


def load_action(payload: bytes) -> Action:
    """Deserialize an Action from :func:`dump_action` output."""
    validate_project_bytes(payload)
    data = _unpack_msgpack(payload)
    _check_container_depth(data)
    return _decode(data)


def save_action(action: Action, path: str):
    _atomic_write(path, dump_action(action))


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
    if not isinstance(data, dict) or "name" not in data or "head" not in data or "tail" not in data:
        raise ProjectFormatError("Bone record missing required fields")
    head = _unpack_ndarray(data["head"])
    tail = _unpack_ndarray(data["tail"])
    head_arr = np.asarray(head, dtype=np.float64).reshape(3)
    tail_arr = np.asarray(tail, dtype=np.float64).reshape(3)
    if not np.all(np.isfinite(head_arr)) or not np.all(np.isfinite(tail_arr)):
        raise ProjectFormatError(f"Bone {data['name']!r} has non-finite head or tail coordinates")
    raw_weights = data.get("cp_weights", {})
    if not isinstance(raw_weights, dict):
        raise ProjectFormatError(f"Bone {data['name']!r} cp_weights must be a dict")
    cp_weights = {}
    for k, v in raw_weights.items():
        try:
            k_int = int(k)
            v_flt = float(v)
        except (ValueError, TypeError):
            raise ProjectFormatError(f"Bone {data['name']!r} has invalid cp_weight ({k}: {v})")
        if not math.isfinite(v_flt) or v_flt < 0.0:
            raise ProjectFormatError(f"Bone {data['name']!r} has non-finite or negative cp_weight")
        cp_weights[k_int] = v_flt
    return Bone(
        name=str(data["name"]),
        parent=data.get("parent"),
        head=head_arr,
        tail=tail_arr,
        cp_weights=cp_weights,
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
                "material": getattr(obj, "material", None),
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
                        "material": getattr(patch, "material", None),
                        "degree_u": int(getattr(patch, "degree_u", 3)),
                        "degree_v": int(getattr(patch, "degree_v", 3)),
                        "generator": (dict(patch.generator)
                                      if getattr(patch, "generator", None)
                                      else None),
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
                "roughness": float(getattr(m, "roughness", 0.5)),
                "metalness": float(getattr(m, "metalness", 0.0)),
                "texture": getattr(m, "texture", None),
                "pattern": getattr(m, "pattern", None),
                "params": dict(getattr(m, "params", {}) or {}),
                "graph": list(getattr(m, "graph", []) or []),
                "objects": list(getattr(m, "objects", []) or []),
                "bump_map": m.bump_map,
                "transparency_map": m.transparency_map,
                "specular_map": m.specular_map,
            }
            for n, m in project.materials.items()
        },
    }
    if actions is None:
        actions = getattr(project, "actions", {})
    if actions:
        body["actions"] = {
            "version": 1,
            "items": {name: _encode(act) for name, act in actions.items()},
        }

    encoded_poses = {}
    for oname, bposes in getattr(project, "poses", {}).items():
        if isinstance(bposes, dict):
            encoded_poses[oname] = {
                bname: _pack_ndarray(np.asarray(rot, dtype=np.float64))
                for bname, rot in bposes.items()
            }
    encoded_offsets = {}
    for oname, boffsets in getattr(project, "pose_offsets", {}).items():
        if isinstance(boffsets, dict):
            encoded_offsets[oname] = {
                bname: _pack_ndarray(np.asarray(off, dtype=np.float64))
                for bname, off in boffsets.items()
            }

    body["session_state"] = {
        "version": 2,
        "active_action": getattr(project, "active_action", None),
        "action_assignments": dict(getattr(project, "action_assignments", {}) or {}),
        "poses": encoded_poses,
        "pose_offsets": encoded_offsets,
    }
    body["format_version"] = 2
    return msgpack.packb(body, use_bin_type=True)


def load_project_bytes(payload: bytes) -> Project:
    validate_project_bytes(payload)
    data = _unpack_msgpack(payload)
    # Absent means a file saved before this field existed (format 1);
    # only a version newer than this build understands is a hard error.
    fmt = data.get("format_version", 1)
    if not isinstance(fmt, int) or fmt > FORMAT_VERSION:
        raise ProjectFormatError(
            f"Unsupported project format version {fmt!r} "
            f"(this build supports up to {FORMAT_VERSION})")
    validate_project_data(data)
    p = Project(name=data["name"])
    p.mode = data.get("mode", "object")
    p.frame = float(data.get("frame", 0.0))
    p.fps = float(data.get("fps", 30.0))
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
        obj.material = odata.get("material")
        if odata.get("transform") is not None:
            t = _unpack_ndarray(odata["transform"]).reshape(4, 4)
            if not np.all(np.isfinite(t)):
                raise ProjectFormatError(f"object {oname!r} transform contains non-finite values")
            obj.transform = t
        for sname, sdata in odata.get("splines", {}).items():
            if "cps" not in sdata or not isinstance(sdata["cps"], list) or len(sdata["cps"]) != 2:
                raise ProjectFormatError(f"object {oname!r} spline {sname!r}: missing or invalid 'cps' structure")
            pts = _unpack_ndarray(sdata["cps"][0])
            weights = sdata["cps"][1]
            if not isinstance(weights, (list, tuple, np.ndarray)):
                raise ProjectFormatError(f"object {oname!r} spline {sname!r}: weights must be a sequence")
            pts_arr = np.asarray(pts, dtype=np.float64)
            if pts_arr.ndim != 2 or pts_arr.shape[1] != 3:
                raise ProjectFormatError(f"object {oname!r} spline {sname!r}: control points must have shape (N, 3)")
            if len(pts_arr) != len(weights):
                raise ProjectFormatError(
                    f"object {oname!r} spline {sname!r}: control point count ({len(pts_arr)}) "
                    f"does not match weight count ({len(weights)})")
            if not np.all(np.isfinite(pts_arr)):
                raise ProjectFormatError(f"object {oname!r} spline {sname!r}: non-finite control point coordinate")
            weights_arr = np.asarray(weights, dtype=np.float64)
            if not np.all(np.isfinite(weights_arr)):
                raise ProjectFormatError(f"object {oname!r} spline {sname!r}: non-finite weight")
            if np.any(weights_arr <= 0):
                raise ProjectFormatError(f"object {oname!r} spline {sname!r}: weights must be positive")
            cps = [_CP(pts_arr[i], float(weights_arr[i])) for i in range(len(pts_arr))]
            if "degree" not in sdata:
                raise ProjectFormatError(f"object {oname!r} spline {sname!r}: missing 'degree'")
            degree = sdata["degree"]
            if not isinstance(degree, int) or isinstance(degree, bool) or degree < 1:
                raise ProjectFormatError(f"object {oname!r} spline {sname!r}: 'degree' must be a positive integer")
            if "closed" not in sdata:
                raise ProjectFormatError(f"object {oname!r} spline {sname!r}: missing 'closed'")
            closed = sdata["closed"]
            if not isinstance(closed, bool):
                raise ProjectFormatError(f"object {oname!r} spline {sname!r}: 'closed' must be a boolean")
            obj.add_spline(_Spline(name=sname, cps=cps, degree=degree, closed=closed))
        for pdata in odata.get("patches", []):
            interior = None
            if pdata.get("interior") is not None:
                interior = _unpack_ndarray(pdata["interior"])
                if interior is not None:
                    interior = np.asarray(interior, dtype=np.float64)
            generator = pdata.get("generator")
            if generator is not None and not isinstance(generator, dict):
                raise ProjectFormatError(
                    f"object {oname!r} patch "
                    f"{pdata.get('name', 'patch')!r}: 'generator' must be a "
                    f"mapping or absent")
            obj.patches.append(_Patch(name=pdata.get("name", "patch"),
                                      splines=list(pdata.get("splines", [])),
                                      interior=interior,
                                      material=pdata.get("material"),
                                      degree_u=int(pdata.get("degree_u", 3)),
                                      degree_v=int(pdata.get("degree_v", 3)),
                                      generator=(dict(generator) if generator
                                                 else None)))
        for hdata in odata.get("hooks", []):
            obj.hooks.append(_Hook(source=tuple(hdata.get("source", ())),
                                   target=tuple(hdata.get("target", ())),
                                   strength=float(hdata.get("strength", 1.0))))

    for oname, rig_data in data.get("skeletons", {}).items():
        p.skeletons[oname] = {bname: _decode_bone(bd)
                              for bname, bd in rig_data.items()}

    for n, mdata in data.get("materials", {}).items():
        if isinstance(mdata, dict):
            color = tuple(mdata.get("color", (0.8, 0.8, 0.8)))
            roughness = float(mdata.get("roughness", 0.5))
            metalness = float(mdata.get("metalness", 0.0))
            if not (0.0 <= roughness <= 1.0) or not math.isfinite(roughness):
                raise ProjectFormatError(f"material {n!r}: roughness must be between 0.0 and 1.0")
            if not (0.0 <= metalness <= 1.0) or not math.isfinite(metalness):
                raise ProjectFormatError(f"material {n!r}: metalness must be between 0.0 and 1.0")
            p.materials[n] = Material(
                name=n,
                color=color,
                roughness=roughness,
                metalness=metalness,
                texture=mdata.get("texture"),
                pattern=mdata.get("pattern"),
                params=dict(mdata.get("params", {}) or {}),
                graph=list(mdata.get("graph", []) or []),
                objects=list(mdata.get("objects", []) or []),
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
        raw_poses = ss.get("poses", {})
        if isinstance(raw_poses, dict):
            for oname, bposes in raw_poses.items():
                if isinstance(bposes, dict):
                    p.poses[oname] = {
                        bname: _unpack_ndarray(rot)
                        for bname, rot in bposes.items()
                    }
        raw_offsets = ss.get("pose_offsets", {})
        if isinstance(raw_offsets, dict):
            for oname, boffsets in raw_offsets.items():
                if isinstance(boffsets, dict):
                    p.pose_offsets[oname] = {
                        bname: _unpack_ndarray(off)
                        for bname, off in boffsets.items()
                    }
    return p


def save_project(project: Project, path: str, actions: dict | None = None):
    _atomic_write(path, dump_project(project, actions=actions))


def load_project(path: str) -> Project:
    with open(path, "rb") as fh:
        payload = fh.read()
    proj = load_project_bytes(payload)
    proj.project_path = os.path.abspath(path)
    return proj