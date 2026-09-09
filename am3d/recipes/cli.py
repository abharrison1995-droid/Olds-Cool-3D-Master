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
import sys


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


def _emit_failure(record, *, records=None, diagnostic=None) -> int:
    all_records = list(records) if records else [record]
    report = {
        "ok": False,
        "objects": [],
        "materials": [],
        "actions": [],
        "exports": [],
        "warnings": [],
        "errors": [r["message"] for r in all_records],
        "error_records": all_records,
        "manifest": [],
        "partial_publication": False,
    }
    print(json.dumps(report, indent=2))
    print(f"error: {diagnostic or record['message']}", file=sys.stderr)
    return 1


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        if args.recipe == "-":
            if hasattr(sys.stdin, "buffer"):
                raw = sys.stdin.buffer.read()
                data = json.loads(raw.decode("utf-8-sig"))
            else:
                text = sys.stdin.read()
                if text.startswith("\ufeff"):
                    text = text[1:]
                data = json.loads(text)
        else:
            # utf-8-sig transparently strips a BOM if one is present.
            with open(args.recipe, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
    except Exception as exc:
        return _emit_failure(
            _error_record(exc, code="recipe_read_error", stage="parse"),
            diagnostic=f"error reading recipe: {exc}")

    from .executor import RecipeExecutor
    from .schema import recipe_from_dict, validate_recipe

    try:
        recipe = recipe_from_dict(data)
        problems = validate_recipe(recipe)
    except Exception as exc:
        return _emit_failure(_error_record(exc, code="schema_error",
                                           stage="schema"),
                             diagnostic=f"invalid recipe: {exc}")
    if problems:
        records = []
        for problem in problems:
            if hasattr(problem, "to_record"):
                records.append(problem.to_record())
            else:
                records.append({
                    "code": getattr(problem, "code", "validation_error"),
                    "stage": getattr(problem, "stage", "schema"),
                    "path": getattr(problem, "path", "recipe"),
                    "message": str(problem),
                    "hint": getattr(problem, "hint", "Correct the listed fields and retry."),
                })
        return _emit_failure(records[0], records=records,
                             diagnostic="invalid recipe: " +
                             "; ".join(str(p) for p in problems))
    if args.validate_only:
        report = {"ok": True, "validated": True, "name": recipe.name,
                  "version": recipe.version, "error_records": []}
        print(json.dumps(report))
        return 0

    recipe_dir = None if args.recipe == "-" else os.path.dirname(
        os.path.abspath(args.recipe))
    result = RecipeExecutor(output_root=args.out, base_dir=recipe_dir).execute(
        recipe)

    if args.verbose:
        for obj in result.objects:
            print(f"object:   {obj}")
        for mat in result.materials:
            print(f"material: {mat}")
        for act in result.actions:
            print(f"action:   {act}")
        for fmt, path in result.exports:
            print(f"exported: [{fmt}] {path}")
        for warn in result.warnings:
            print(f"warning:  {warn}")

    report = {
        "ok": result.ok,
        "objects": result.objects,
        "materials": result.materials,
        "actions": result.actions,
        "exports": [{"format": f, "path": p} for f, p in result.exports],
        "warnings": result.warnings,
        "errors": result.errors,
        "error_records": result.error_records,
        "manifest": result.manifest,
        "partial_publication": result.partial_publication,
    }
    print(json.dumps(report, indent=2))

    if not result.ok:
        for err in result.errors:
            print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
