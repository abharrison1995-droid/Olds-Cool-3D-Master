"""Offline history operations used by the owned Qt history worker.

The store remains the authority. A list row is only a summary; completed
records become actionable after ``get_record`` verifies their full manifest.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _store(store_root: str, store_factory=None):
    if store_factory is None:
        from am3d.ai.records import GenerationRecordStore
        store_factory = GenerationRecordStore
    return store_factory(store_root)


def list_history(store_root: str, store_factory=None) -> list[dict[str, Any]]:
    store = _store(store_root, store_factory)
    recover = getattr(store, "recover_interrupted", None)
    if callable(recover):
        recover()
    rows = store.list_records()
    result = []
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("run_id"), str):
            continue
        brief = row.get("accepted_brief", row.get("brief", ""))
        if not brief and isinstance(row.get("record"), dict):
            attempt_record = row["record"]
            brief = attempt_record.get(
                "accepted_brief", attempt_record.get("brief", ""))
        if isinstance(brief, dict):
            brief = brief.get("brief", "")
        if not isinstance(brief, str):
            brief = ""
        result.append({
            "run_id": row["run_id"],
            "parent_generation_id": row.get("parent_generation_id"),
            "status": str(row.get("status", "unavailable")),
            "brief": brief[:1024],
            "completed_utc": str(row.get("completed_utc")
                                  or row.get("updated_utc") or ""),
            "model": _model_label(row.get("provider")),
            "successful": bool(row.get("status") == "complete"),
        })
    return result


def load_history_detail(store_root: str, run_id: str,
                        store_factory=None) -> dict[str, Any]:
    """Verify every saved artifact, reopen native state, and decode its preview."""
    from PySide6.QtGui import QImage
    from am3d.core.serializer import load_project, project_content_digest

    store = _store(store_root, store_factory)
    record = store.get_record(run_id)
    if (record.get("status") != "complete"
            or record.get("run_id") != run_id
            or not _checked(record)):
        raise ValueError("saved generation is not a checked, completed record")
    project_path = Path(record["project_path"])
    project = load_project(str(project_path))
    generation = getattr(project, "generation", None)
    if (not isinstance(generation, dict)
            or generation.get("run_id") != run_id
            or generation.get("parent_generation_id")
            != record.get("parent_generation_id")
            or generation.get("recipe") != record.get("accepted_recipe")):
        raise ValueError("saved native project does not identify this history record")
    # Recompute from the reopened bytes. Do not trust the editable provenance
    # digest: a checked manifest and native project are the authority.
    project_digest = project_content_digest(
        project, actions=getattr(project, "actions", {}))
    manifest = record.get("artifact_manifest")
    if not isinstance(manifest, list):
        raise ValueError("saved generation has no verified artifact manifest")
    preview_entry = next((item for item in manifest
                          if isinstance(item, dict)
                          and item.get("path") == "preview.png"), None)
    if preview_entry is None:
        raise FileNotFoundError("saved checked preview is missing")
    preview_path = Path(record["run_root"]) / "preview.png"
    image = QImage(str(preview_path))
    if image.isNull():
        raise ValueError("saved checked preview could not be decoded")
    # A detached image stays valid after the worker returns and the file is
    # subsequently selected away from in the GUI.
    image = image.copy()
    parent_record = None
    parent_id = record.get("parent_generation_id")
    if isinstance(parent_id, str):
        try:
            parent_record = store.get_record(parent_id)
        except Exception:
            # A child remains inspectable when an older parent sidecar was
            # explicitly deleted or has since become unavailable.
            parent_record = None
    return {
        "record": record,
        "project_digest": project_digest,
        "preview_image": image,
        "parent_record": parent_record,
        "recipe_diff": (deterministic_recipe_diff(
            parent_record.get("accepted_recipe", {}),
            record.get("accepted_recipe", {}))
            if isinstance(parent_record, dict) else None),
    }


def delete_history(store_root: str, run_id: str, *, confirm_parent=False,
                   store_factory=None) -> dict[str, Any]:
    return _store(store_root, store_factory).delete(
        run_id, confirm_parent=bool(confirm_parent))


def deterministic_recipe_diff(parent: dict, child: dict) -> str:
    """Describe full-replacement recipe changes without model comparison."""
    lines: list[str] = []
    for collection, label in (("objects", "Components"),
                              ("materials", "Materials")):
        before = _named_items(parent.get(collection))
        after = _named_items(child.get(collection))
        added = sorted(set(after) - set(before), key=str.casefold)
        removed = sorted(set(before) - set(after), key=str.casefold)
        changed = []
        for name in sorted(set(before) & set(after), key=str.casefold):
            old_item, new_item = before[name], after[name]
            fields = sorted(
                (key for key in set(old_item) | set(new_item)
                 if _canonical(old_item.get(key)) != _canonical(new_item.get(key))),
                key=str.casefold)
            if fields:
                changed.append(f"{name} ({', '.join(fields)})")
        if added:
            lines.append(f"{label} added: {', '.join(added[:8])}")
        if removed:
            lines.append(f"{label} removed: {', '.join(removed[:8])}")
        if changed:
            lines.append(f"{label} changed: " + "; ".join(changed[:8]))
    if not lines:
        return "No deterministic object or material recipe differences were found."
    return "Recipe changes from parent:\n" + "\n".join(f"• {line}" for line in lines)


def _checked(record: dict) -> bool:
    report = record.get("check_report")
    recipe = record.get("accepted_recipe")
    return (isinstance(report, dict) and report.get("ok") is True
            and report.get("status") == "passed" and isinstance(recipe, dict))


def _named_items(value) -> dict[str, dict]:
    if not isinstance(value, list):
        return {}
    result = {}
    for item in value:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            result[item["name"]] = item
    return result


def _canonical(value) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False,
                          separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError):
        return repr(value)


def _model_label(value) -> str:
    if not isinstance(value, dict):
        return ""
    model = value.get("model")
    return model[:128] if isinstance(model, str) else ""


__all__ = ["delete_history", "deterministic_recipe_diff", "list_history",
           "load_history_detail"]
