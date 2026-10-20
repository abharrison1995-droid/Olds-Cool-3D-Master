#!/usr/bin/env python3
"""Scan every regular payload file for a forbidden absolute build path."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import stat
import sys


_CHUNK_BYTES = 1024 * 1024


def _walk_error(error: OSError) -> None:
    raise error


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return (stat.S_ISLNK(info.st_mode)
            or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def _tokens(root: Path) -> tuple[bytes, ...]:
    native = os.path.abspath(os.fspath(root)).rstrip("\\/")
    slash = native.replace("\\", "/")
    values = set()
    for value in (native, slash):
        if not value:
            continue
        for encoded in (value.encode("utf-8"), value.encode("utf-16le")):
            values.add(encoded.lower())
    if not values:
        raise ValueError("forbidden root must be an absolute non-empty path")
    return tuple(sorted(values, key=len, reverse=True))


def _contains_any(path: Path, tokens: tuple[bytes, ...]) -> bool:
    overlap = max(len(token) for token in tokens) - 1
    tail = b""
    with path.open("rb") as stream:
        while True:
            block = stream.read(_CHUNK_BYTES)
            if not block:
                return False
            data = (tail + block).lower()
            if any(token in data for token in tokens):
                return True
            tail = data[-overlap:] if overlap else b""


def audit(payload: Path, forbidden_root: Path) -> list[str]:
    # Check the caller's lexical path before resolving it: resolving first
    # would hide a junction/symlink supplied as the payload itself.
    payload = Path(os.path.abspath(os.fspath(payload)))
    current = payload
    while True:
        if _is_link(current):
            raise ValueError("payload path contains a link or junction")
        if current.parent == current:
            break
        current = current.parent
    payload = payload.resolve(strict=True)
    if not payload.is_dir():
        raise ValueError("payload must be a regular directory")
    tokens = _tokens(forbidden_root)
    leaks = []
    for current, dirs, files in os.walk(payload, topdown=True, followlinks=False,
                                        onerror=_walk_error):
        base = Path(current)
        for name in sorted(dirs):
            path = base / name
            if _is_link(path):
                raise ValueError("payload contains a link or junction")
        for name in sorted(files):
            path = base / name
            if _is_link(path) or not path.is_file():
                raise ValueError("payload contains a linked or non-regular file")
            if _contains_any(path, tokens):
                leaks.append(path.relative_to(payload).as_posix())
                if len(leaks) >= 20:
                    return leaks
    return leaks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", type=Path, required=True)
    parser.add_argument("--forbidden-root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        leaks = audit(args.payload, args.forbidden_root)
    except (OSError, ValueError) as exc:
        print(f"payload audit failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    if leaks:
        print("build path found in payload files:", file=sys.stderr)
        print("\n".join(leaks), file=sys.stderr)
        return 1
    print("No forbidden build path found across all payload files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
