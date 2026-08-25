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
import sys


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m am3d.recipes",
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


def main(argv=None) -> int:
    args = _build_parser().parse_args(argv)

    try:
        if args.recipe == "-":
            data = json.load(sys.stdin)
        else:
            # utf-8-sig transparently strips a BOM if one is present.
            with open(args.recipe, "r", encoding="utf-8-sig") as fh:
                data = json.load(fh)
    except Exception as exc:
        print(f"error reading recipe: {exc}", file=sys.stderr)
        return 1

    from .executor import RecipeExecutor
    from .schema import recipe_from_dict, validate_recipe

    try:
        recipe = recipe_from_dict(data)
        problems = validate_recipe(recipe)
    except Exception as exc:
        print(f"invalid recipe: {exc}", file=sys.stderr)
        return 1
    if problems:
        for problem in problems:
            print(f"invalid recipe: {problem}", file=sys.stderr)
        return 1
    if args.validate_only:
        report = {"ok": True, "validated": True, "name": recipe.name}
        print(json.dumps(report))
        return 0

    if args.out:
        for export in recipe.exports:
            export.path = args.out.rstrip("/\\") + "/" + export.path

    result = RecipeExecutor().execute(recipe)

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
    }
    print(json.dumps(report, indent=2))

    if not result.ok:
        for err in result.errors:
            print(f"error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())