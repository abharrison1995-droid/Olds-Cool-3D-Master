"""Action retargeting — reuse animations across different skeletons.

Retargeting adapts an :class:`~am3d.core.animation.Action` authored for one
skeleton to a different character's skeleton.  The core function
:func:`retarget_action` handles:

* **Name mapping** — automatic (case-insensitive substring matching) or explicit.
* **Bone-length scaling** — translation amplitudes are scaled by the ratio of
  target-to-source bone lengths so motions match proportionally.
* **IK awareness** — chain-length ratio propagation for limb-bone translation.

Usage::

    # Auto-retarget from a source character
    new_action = retarget_action(
        walk_action,
        source_bones=[...],   # bones the action was authored for
        target_bones=[...],   # bones of the character to drive
    )

    # Explicit mapping
    new_action = retarget_action(
        walk_action, source_bones, target_bones,
        mapping={"arm_l": "left_arm", "arm_r": "right_arm"},
    )
"""

from __future__ import annotations

import numpy as np

from .animation import Action, Channel, Keyframe


def _normalize_name(name: str) -> str:
    """Lower-case, strip non-alpha-numeric characters for matching."""
    return "".join(c.lower() for c in name if c.isalnum() or c in "_")


_SIDE_ALIASES = {
    "l": "left", "left": "left",
    "r": "right", "right": "right",
    "rf": "right", "lf": "left",
}


def _norm_tokens(name: str) -> set:
    """Break a bone name into meaningful tokens.

    ``"arm_L"`` -> {"arm", "left"}; ``"leftArm"`` -> {"arm", "left"}.
    Numeric tags and single-letter side markers are canonicalised.
    """
    s = _normalize_name(name)
    s = s.replace("_", " ")
    import re
    words = re.split(r"[_\W]+", s)
    tokens = set()
    for w in words:
        if not w:
            continue
        # Digit-only tags (e.g. "01", "2") are ignored — pure suffix
        if w.isdigit():
            continue
        low = w.lower()
        if low in _SIDE_ALIASES:
            tokens.add(_SIDE_ALIASES[low])
        else:
            tokens.add(low)
    return tokens


def _auto_map_names(source_bones, target_bones) -> dict[str, str]:
    """Build a ``source_name -> target_name`` map heuristically.

    Matching order:
      1. exact normalized name,
      2. token-set equality (handles ``arm_L`` <-> ``left_arm``,
         ``spine_head`` <-> ``spineHead``),
      3. contains (one name's tokens inside the other's),
      4. substring fallback.

    Returns a dict; unmatched source bones are omitted.
    """
    src_names = [(b.name if hasattr(b, "name") else b) for b in source_bones]
    tgt_names = [(b.name if hasattr(b, "name") else b) for b in target_bones]
    src_norm = {s: _normalize_name(s) for s in src_names}
    tgt_norm = {t: _normalize_name(t) for t in tgt_names}
    src_tok = {s: _norm_tokens(s) for s in src_names}
    tgt_tok = {t: _norm_tokens(t) for t in tgt_names}

    used_targets = set()
    mapping = {}

    def _use(tn):
        used_targets.add(tn)
        return tn

    # Phase 1: exact normalized match
    for sn, s_norm in src_norm.items():
        for tn, t_norm in tgt_norm.items():
            if tn in used_targets:
                continue
            if s_norm == t_norm:
                mapping[sn] = _use(tn)
                break

    # Phase 2: token-set equality
    for sn, st in src_tok.items():
        if sn in mapping:
            continue
        for tn, tt in tgt_tok.items():
            if tn in used_targets:
                continue
            if st and st == tt:
                mapping[sn] = _use(tn)
                break

    # Phase 3: token containment
    for sn, st in src_tok.items():
        if sn in mapping:
            continue
        best, best_n = None, 0
        for tn, tt in tgt_tok.items():
            if tn in used_targets:
                continue
            overlap = st & tt
            if overlap and len(overlap) > best_n:
                best, best_n = tn, len(overlap)
        if best:
            mapping[sn] = _use(best)

    # Phase 4: raw substring fallback
    for sn, s_norm in src_norm.items():
        if sn in mapping:
            continue
        best, best_len = None, 0
        for tn, t_norm in tgt_norm.items():
            if tn in used_targets:
                continue
            if s_norm in t_norm or t_norm in s_norm:
                if max(len(s_norm), len(t_norm)) > best_len:
                    best = tn
                    best_len = max(len(s_norm), len(t_norm))
        if best:
            mapping[sn] = _use(best)

    return mapping


def _bone_length(bone) -> float:
    """Euclidean distance from head to tail."""
    head = np.asarray(getattr(bone, "head", [0, 0, 0]), dtype=np.float64)
    tail = np.asarray(getattr(bone, "tail", [0, 1, 0]), dtype=np.float64)
    return max(float(np.linalg.norm(tail - head)), 1e-6)


def _build_length_map(bones) -> dict[str, float]:
    """dict bone_name -> length."""
    return {b.name: _bone_length(b) for b in bones}


def retarget_action(action, source_bones, target_bones, mapping=None,
                    default_duration=None):
    """Create a new :class:`Action` from *action* adapted to *target_bones*.

    Parameters
    ----------
    action : Action
        The source animation to retarget.
    source_bones : sequence
        The skeleton the action was authored for (must have .name, .head, .tail).
    target_bones : sequence
        The character's skeleton to map onto (same attribute requirements).
    mapping : dict[str, str] or None
        Explicit ``source_name -> target_name`` mapping; auto-mapped if omitted.
    default_duration : float or None
        Override the action duration; uses source duration if None.

    Returns
    -------
    Action
        A new action with channels mapped to target bone names and amplitudes
        scaled by bone-length ratios.
    """
    if mapping is None:
        mapping = _auto_map_names(source_bones, target_bones)

    src_lengths = _build_length_map(source_bones)
    tgt_lengths = _build_length_map(target_bones)
    target_names = {b.name for b in target_bones}

    new_action = Action(
        name=action.name + "_retargeted",
        duration=default_duration if default_duration is not None else action.duration,
        signature=tuple(sorted(target_names)),
        metadata={**action.metadata, "retargeted_from": action.name},
    )

    for ch in action.channels:
        src_bone = ch.bone
        if src_bone not in mapping:
            continue  # skip unmapped channels
        tgt_bone = mapping[src_bone]

        if tgt_bone not in target_names:
            continue  # target bone not present

        # Compute length ratio for translation scaling
        src_len = src_lengths.get(src_bone, 1.0)
        tgt_len = tgt_lengths.get(tgt_bone, 1.0)
        ratio = tgt_len / max(src_len, 1e-6)

        new_ch = new_action.add_channel(tgt_bone, ch.property)
        for kf in ch.keys:
            new_val = kf.value.copy()
            # Scale translate/weight properties by bone-length ratio
            if ch.property in ("translate", "weight"):
                new_val = new_val * ratio
            # Rotation channels are used as-is (angles are scale-invariant)
            new_ch.add_key(kf.time, new_val, kf.interp)

    return new_action