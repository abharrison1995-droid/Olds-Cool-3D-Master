#!/usr/bin/env python3
"""Create a deterministic digest for the files that feed a Linux build.

The walk intentionally includes present untracked files as well as tracked
files. It scans the source, assets, recipe contract, and files copied or used
by the two PyInstaller builds. Generated Python caches are omitted because
they are not build inputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


INPUT_DIRS = ("am3d", "assets", "docs/recipes", "scripts")
INPUT_FILES = (
    "README.md",
    "pyproject.toml",
    "requirements.txt",
    "requirements-dev.txt",
    "requirements-lock-linux.txt",
    "am3d.spec",
    "am3d_recipe.spec",
    "build_linux.sh",
    "scripts/build_input_digest.py",
    "docs/QUICK_START.md",
    "docs/SUPPORTED_PLATFORMS.md",
    "docs/CAPABILITY_MATRIX.md",
    "docs/USER_GUIDE.md",
)
IGNORED_DIRS = {"__pycache__", ".pytest_cache"}


def _tracked_paths(root: Path) -> set[str]:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--cached", "-z"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return set()
    return {p.decode("utf-8", "surrogateescape")
            for p in result.stdout.split(b"\0") if p}


def _input_paths(root: Path) -> list[Path]:
    paths: set[Path] = set()
    for rel in INPUT_FILES:
        path = root / rel
        if path.exists() or path.is_symlink():
            paths.add(path)

    for rel in INPUT_DIRS:
        base = root / rel
        if not base.is_dir():
            continue
        for current, dirs, files in os.walk(base, topdown=True,
                                            followlinks=False):
            current_path = Path(current)
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS)
            for directory in dirs:
                candidate = current_path / directory
                if candidate.is_symlink():
                    paths.add(candidate)
            for filename in files:
                if filename.endswith(".pyc"):
                    continue
                paths.add(current_path / filename)

    return sorted(paths, key=lambda p: p.relative_to(root).as_posix())


def build_manifest(root: Path) -> dict:
    tracked = _tracked_paths(root)
    entries = []
    for path in _input_paths(root):
        rel = path.relative_to(root).as_posix()
        if path.is_symlink():
            entry = {"path": rel, "kind": "symlink",
                     "target": os.readlink(path)}
        else:
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            entry = {"path": rel, "kind": "file",
                     "sha256": digest.hexdigest()}
        entry["git_state"] = "tracked" if rel in tracked else "untracked"
        entries.append(entry)

    canonical = json.dumps(entries, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True).encode("utf-8")
    return {
        "format_version": 1,
        "algorithm": "sha256",
        "scope": {
            "directories": list(INPUT_DIRS),
            "files": list(INPUT_FILES),
            "omitted_generated_directories": sorted(IGNORED_DIRS),
            "omitted_suffixes": [".pyc"],
        },
        "input_file_count": len(entries),
        "tracked_file_count": sum(e["git_state"] == "tracked"
                                   for e in entries),
        "untracked_file_count": sum(e["git_state"] == "untracked"
                                     for e in entries),
        "build_input_digest": hashlib.sha256(canonical).hexdigest(),
        "inputs": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--digest-only", action="store_true",
                        help="print only the digest")
    parser.add_argument("--write-manifest", type=Path,
                        help="write the complete JSON input manifest")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = build_manifest(root)
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
