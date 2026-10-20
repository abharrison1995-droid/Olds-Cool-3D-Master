#!/usr/bin/env python3
"""Hash the complete, explicit set of stable inputs used by V1 packaging.

The manifest includes tracked and present untracked source, tests, schemas,
prompts, benchmarks, build scripts/specs, locks, assets, and shipped documents.
Generated identity, build outputs, caches, bytecode, and evidence are not
inputs. Paths and symlink targets are repository-relative and no local root is
written to the manifest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import ntpath
import os
import stat
import subprocess
from pathlib import Path


INPUT_DIRS = (
    "am3d",
    "assets",
    "benchmarks",
    "docs/recipes",
    "scripts",
)
INPUT_FILES = (
    "README.md",
    "PRODUCT.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-lock-linux.txt",
    "requirements-lock-windows.txt",
    "am3d.spec",
    "am3d_recipe.spec",
    "build_linux.sh",
    "build_windows.ps1",
    ".github/workflows/windows.yml",
    "docs/QUICK_START.md",
    "docs/USER_GUIDE.md",
    "docs/SUPPORTED_PLATFORMS.md",
    "docs/CAPABILITY_MATRIX.md",
)
IGNORED_DIRS = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
GENERATED_FILES = {"am3d/build_identity.json"}


class InputInventoryError(RuntimeError):
    """The complete tracked-input inventory could not be established."""


def _walk_error(error: OSError) -> None:
    raise error


def _is_reparse_point(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return (stat.S_ISLNK(info.st_mode)
            or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def _tracked_paths(root: Path) -> set[str]:
    try:
        result = subprocess.run(
            ["git", "-C", os.fspath(root), "ls-files", "--cached", "-z"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        # Returning an empty set here would make a Git failure look like a
        # complete inventory of untracked files. In particular, a deleted
        # tracked build input would disappear from the resulting identity.
        # Keep the message fixed and omit paths and process error details.
        raise InputInventoryError(
            "could not enumerate tracked build inputs with Git; run this tool from a working checkout with Git available"
        ) from None
    return {item.decode("utf-8", "surrogateescape")
            for item in result.stdout.split(b"\0") if item}


def _included(rel: str) -> bool:
    path = Path(rel)
    if rel in GENERATED_FILES or any(part in IGNORED_DIRS for part in path.parts):
        return False
    return path.suffix.casefold() not in IGNORED_SUFFIXES


def _input_paths(root: Path, tracked: set[str]) -> tuple[list[Path], list[str]]:
    paths: set[Path] = set()
    missing: set[str] = set()

    for rel in INPUT_FILES:
        if not _included(rel):
            continue
        path = root / Path(rel)
        if path.exists() or _is_reparse_point(path):
            paths.add(path)
        elif rel in tracked:
            missing.add(rel)

    for rel in INPUT_DIRS:
        base = root / Path(rel)
        if not base.is_dir() or _is_reparse_point(base):
            continue
        for current, dirs, files in os.walk(base, topdown=True, followlinks=False,
                                            onerror=_walk_error):
            current_path = Path(current)
            kept_dirs = []
            for directory in sorted(dirs):
                candidate = current_path / directory
                relative = candidate.relative_to(root).as_posix()
                if directory in IGNORED_DIRS:
                    continue
                if _is_reparse_point(candidate):
                    if _included(relative):
                        paths.add(candidate)
                    continue
                kept_dirs.append(directory)
            dirs[:] = kept_dirs
            for filename in sorted(files):
                candidate = current_path / filename
                relative = candidate.relative_to(root).as_posix()
                if _included(relative):
                    paths.add(candidate)

    # Report deleted tracked inputs explicitly. A deleted tracked path must
    # change the digest just as a newly created file does.
    for rel in tracked:
        if not _included(rel):
            continue
        path = root / Path(rel)
        if any(rel == prefix or rel.startswith(prefix.rstrip("/") + "/")
               for prefix in INPUT_DIRS) or rel in INPUT_FILES:
            if not path.exists() and not _is_reparse_point(path):
                missing.add(rel)

    ordered = sorted(paths, key=lambda item: item.relative_to(root).as_posix())
    return ordered, sorted(missing)


def build_manifest(root: Path) -> dict:
    root = root.resolve(strict=True)
    tracked = _tracked_paths(root)
    paths, missing = _input_paths(root, tracked)
    entries = []

    for path in paths:
        rel = path.relative_to(root).as_posix()
        tracked_state = "tracked" if rel in tracked else "untracked"
        if _is_reparse_point(path):
            try:
                target = os.readlink(path)
            except (OSError, ValueError):
                entries.append({"path": rel, "kind": "symlink",
                                "target_kind": "unavailable",
                                "git_state": tracked_state})
                continue
            if Path(target).is_absolute() or ntpath.isabs(target):
                target_identity = {
                    "target_kind": "absolute",
                    "target_sha256": hashlib.sha256(os.fsencode(target)).hexdigest(),
                }
            else:
                target_identity = {"target_kind": "relative", "target": target}
            entries.append({"path": rel, "kind": "symlink",
                            **target_identity, "git_state": tracked_state})
            continue

        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        entries.append({"path": rel, "kind": "file",
                        "sha256": digest.hexdigest(),
                        "git_state": tracked_state})

    for rel in missing:
        entries.append({"path": rel, "kind": "missing",
                        "git_state": "tracked"})
    entries.sort(key=lambda entry: entry["path"])

    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True).encode("ascii")
    return {
        "format_version": 2,
        "algorithm": "sha256",
        "scope": {
            "directories": list(INPUT_DIRS),
            "files": list(INPUT_FILES),
            "omitted_generated_files": sorted(GENERATED_FILES),
            "omitted_generated_directories": sorted(IGNORED_DIRS),
            "omitted_suffixes": sorted(IGNORED_SUFFIXES),
            "symlink_identity": "repository-relative path plus literal relative target or hashed absolute target; targets are not followed",
        },
        "input_file_count": len(entries),
        "tracked_file_count": sum(e["git_state"] == "tracked" for e in entries),
        "untracked_file_count": sum(e["git_state"] == "untracked" for e in entries),
        "build_input_digest": hashlib.sha256(canonical).hexdigest(),
        "inputs": entries,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--digest-only", action="store_true",
                        help="print only the digest")
    parser.add_argument("--write-manifest", type=Path,
                        help="write the complete JSON input manifest")
    args = parser.parse_args(argv)
    root = args.root.resolve(strict=True)
    try:
        manifest = build_manifest(root)
    except InputInventoryError as exc:
        parser.error(str(exc))
    if args.write_manifest:
        destination = args.write_manifest.resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(json.dumps(manifest, indent=2) + "\n",
                               encoding="utf-8")
    if args.digest_only:
        print(manifest["build_input_digest"])
    else:
        print(json.dumps(manifest, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
