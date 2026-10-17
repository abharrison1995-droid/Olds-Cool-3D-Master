"""Command-line interface for recipe-driven asset generation.

Usage::

    python -m am3d.recipes --recipe knight.json
    python -m am3d.recipes --recipe knight.json --out ./assets --quiet

Designed for LLM pipelines: reads a JSON recipe, prints a compact JSON
report on stdout (or human-readable lines with ``--verbose``), exits 0 on
success and 1 with the error text otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys


_MAX_AI_RECIPE_BYTES = 128 * 1024
_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_.])(?:[A-Za-z]:[\\/]|/)(?:[^\\/\s:'\"]+[\\/])*[^\\/\s:'\"]+")


def _program_name() -> str:
    """How this CLI was actually invoked.

    Finding CLI-01: the frozen ``am3d-recipe`` executable printed usage for
    ``python -m am3d.recipes``, a command a user with no Python installed
    cannot run -- the shipped bundle told them to use something it does not
    contain.
    """
    if getattr(sys, "frozen", False):
        return os.path.basename(sys.argv[0]) or "am3d-recipe"
    return "python -m am3d.recipes"


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog=_program_name(),
        description="Build 3D/sprite assets from a 3D MASTER:2005 recipe.",
    )
    p.add_argument("--recipe", required=True,
                   help="path to a recipe .json file ('-' for stdin)")
    p.add_argument("--out", default=None,
                   help="override every export path prefix with this directory")
    p.add_argument("--validate-only", action="store_true",
                   help="check the recipe and exit without building")
    p.add_argument("--ai-mode", action="store_true",
                   help="apply strict AI capability and resource limits")
    p.add_argument("--verbose", action="store_true",
                   help="human-readable progress instead of a JSON report")
    return p


def _error_record(exc, *, code="input_error", stage="parse", path="recipe"):
    record = {
        "code": getattr(exc, "code", code),
        "stage": getattr(exc, "stage", stage),
        "path": getattr(exc, "path", path),
        "message": str(exc),
    }
    hint = getattr(exc, "hint", None)
    if hint:
        record["hint"] = hint
    return record


def _scrub_record(record):
    """Keep host paths out of a machine-facing diagnostic."""
    clean = dict(record)
    for field in ("message", "hint"):
        if isinstance(clean.get(field), str):
            clean[field] = _ABSOLUTE_PATH.sub("<path>", clean[field])
    return clean


def _relative_artifacts(manifest, base_dir):
    artifacts = []
    for raw in manifest:
        entry = dict(raw)
        path = entry.get("path")
        if path:
            try:
                entry["path"] = os.path.relpath(os.path.abspath(path), base_dir)
            except (OSError, ValueError):
                entry["path"] = os.path.basename(path)
        sidecar = entry.get("sidecar_of")
        if sidecar:
            try:
                entry["sidecar_of"] = os.path.relpath(
                    os.path.abspath(sidecar), base_dir)
            except (OSError, ValueError):
                entry["sidecar_of"] = os.path.basename(sidecar)
        artifacts.append(entry)
    return artifacts


def _emit_failure(record, *, records=None) -> int:
    all_records = [_scrub_record(item) for item in
                   (list(records) if records else [record])]
    report = {
        "ok": False,
        "artifacts": [],
        "warnings": [],
        "error_records": all_records,
    }
    print(json.dumps(report, separators=(",", ":")))
    return 1


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)
    if args.ai_mode and not args.out:
        return _emit_failure({
            "code": "missing_output_root", "stage": "resource",
            "path": "--out", "message":
            "AI mode requires a host-chosen output root through --out",
            "hint": "Choose a private output directory on the host and pass it with --out."})

    try:
        if args.recipe == "-":
            if hasattr(sys.stdin, "buffer"):
                raw = sys.stdin.buffer.read(
                    _MAX_AI_RECIPE_BYTES + 1 if args.ai_mode else -1)
                if args.ai_mode and len(raw) > _MAX_AI_RECIPE_BYTES:
                    return _emit_failure({
                        "code": "resource_limit", "stage": "resource",
                        "path": "recipe", "message":
                        f"recipe JSON exceeds the {_MAX_AI_RECIPE_BYTES}-byte AI-mode limit"})
                data = json.loads(raw.decode("utf-8-sig"))
            else:
                text = sys.stdin.read(
                    _MAX_AI_RECIPE_BYTES + 1 if args.ai_mode else -1)
                if args.ai_mode and len(text.encode("utf-8")) > _MAX_AI_RECIPE_BYTES:
                    return _emit_failure({
                        "code": "resource_limit", "stage": "resource",
                        "path": "recipe", "message":
                        f"recipe JSON exceeds the {_MAX_AI_RECIPE_BYTES}-byte AI-mode limit"})
                if text.startswith("\ufeff"):
                    text = text[1:]
                data = json.loads(text)
        else:
            if args.ai_mode:
                with open(args.recipe, "rb") as fh:
                    raw = fh.read(_MAX_AI_RECIPE_BYTES + 1)
                if len(raw) > _MAX_AI_RECIPE_BYTES:
                    return _emit_failure({
                        "code": "resource_limit", "stage": "resource",
                        "path": "recipe", "message":
                        f"recipe JSON exceeds the {_MAX_AI_RECIPE_BYTES}-byte AI-mode limit"})
                data = json.loads(raw.decode("utf-8-sig"))
            else:
                # utf-8-sig transparently strips a BOM if one is present.
                with open(args.recipe, "r", encoding="utf-8-sig") as fh:
                    data = json.load(fh)
    except MemoryError:
        return _emit_failure({
            "code": "resource_exhausted", "stage": "resource",
            "path": "recipe", "message":
            "recipe could not be loaded within the available memory"})
    except Exception as exc:
        return _emit_failure(
            _error_record(exc, code="recipe_read_error", stage="parse"))

    from .executor import RecipeExecutor
    from .schema import recipe_from_dict, validate_recipe

    try:
        recipe = recipe_from_dict(data)
        problems = validate_recipe(recipe, ai_mode=args.ai_mode)
    except Exception as exc:
        return _emit_failure(_error_record(exc, code="schema_error",
                                           stage="schema"))
    problem_records = []
    for problem in problems:
        if hasattr(problem, "to_record"):
            problem_records.append(problem.to_record())
        else:
            problem_records.append({
                "code": getattr(problem, "code", "validation_error"),
                "stage": getattr(problem, "stage", "schema"),
                "path": getattr(problem, "path", "recipe"),
                "message": str(problem),
                "hint": getattr(problem, "hint", "Correct the listed fields and retry."),
            })
    recipe_dir = None if args.recipe == "-" else os.path.dirname(
        os.path.abspath(args.recipe))
    executor = RecipeExecutor(output_root=args.out, base_dir=recipe_dir,
                              ai_mode=args.ai_mode)
    if args.validate_only:
        records = list(problem_records)
        estimate = None
        if not problems:
            from .resources import estimate_recipe_resources, resource_limit_issues
            estimate = estimate_recipe_resources(recipe)
            if args.ai_mode:
                records.extend(resource_limit_issues(estimate))
        try:
            executor._prepare_output_paths(recipe)
        except Exception as exc:
            records.append(_error_record(exc, code="path_error",
                                         stage="resource"))
        if records:
            return _emit_failure(records[0], records=records)
        report = {"ok": True, "validated": True, "artifacts": [],
                  "warnings": [], "error_records": [],
                  "resource_estimate": estimate}
        print(json.dumps(report, separators=(",", ":")))
        return 0
    if problems:
        return _emit_failure(problem_records[0], records=problem_records)

    result = executor.execute(recipe)

    if args.verbose:
        for obj in result.objects:
            print(f"object:   {obj}")
        for mat in result.materials:
            print(f"material: {mat}")
        for act in result.actions:
            print(f"action:   {act}")
        base_dir = os.path.abspath(args.out or recipe_dir or os.getcwd())
        for fmt, path in result.exports:
            try:
                shown_path = os.path.relpath(os.path.abspath(path), base_dir)
            except (OSError, ValueError):
                shown_path = os.path.basename(path)
            print(f"exported: [{fmt}] {shown_path}")
        for warn in result.warnings:
            print(f"warning:  {warn}")

    base_dir = os.path.abspath(args.out or recipe_dir or os.getcwd())
    report = {
        "ok": result.ok,
        "artifacts": _relative_artifacts(result.manifest, base_dir),
        "warnings": [_ABSOLUTE_PATH.sub("<path>", warning)
                     for warning in result.warnings],
        "error_records": [_scrub_record(record)
                          for record in result.error_records],
    }
    print(json.dumps(report, separators=(",", ":")))

    if not result.ok:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
