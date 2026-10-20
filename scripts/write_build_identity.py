#!/usr/bin/env python3
"""Write the compact generated identity embedded in a platform bundle.

The full build provenance is recorded outside the payload by the build
script. The embedded record intentionally uses the narrow whitelist accepted
by am3d.ai.records.application_identity and contains no machine paths.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import stat
import sys


def _literal_assignment(source: Path, name: str) -> str:
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=source.name)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name
                   for target in node.targets):
                value = ast.literal_eval(node.value)
                if isinstance(value, str):
                    return value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name:
                value = ast.literal_eval(node.value)
                if isinstance(value, str):
                    return value
    raise ValueError(f"{name} must be a literal string assignment")


def _assert_no_links(path: Path) -> None:
    current = path
    while True:
        try:
            info = current.lstat()
        except FileNotFoundError:
            pass
        else:
            attrs = getattr(info, "st_file_attributes", 0)
            if (stat.S_ISLNK(info.st_mode)
                    or attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)):
                raise ValueError("identity output path contains a link")
        if current.parent == current:
            return
        current = current.parent


def build_identity(root: Path, build_input_digest: str) -> dict[str, str]:
    if len(build_input_digest) != 64 or any(
            char not in "0123456789abcdef" for char in build_input_digest):
        raise ValueError("build input digest must be a lowercase SHA-256")
    version = _literal_assignment(root / "am3d" / "__init__.py", "__version__")
    capability = _literal_assignment(root / "am3d" / "ai" / "records.py",
                                     "_CAPABILITY_VERSION")
    # source_sha256 and build_id both retain the complete input digest. The
    # duplicated value is deliberate: existing records expose build_id while
    # the compact on-disk envelope keeps the full source_sha256 field too.
    return {
        "version": version,
        "build_id": f"build-input-sha256:{build_input_digest}",
        "capability_version": capability,
        "source_sha256": build_input_digest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--platform", choices=("windows", "linux"), required=True)
    parser.add_argument("--digest", required=True)
    args = parser.parse_args(argv)

    root = args.root.resolve(strict=True)
    output = root / "build" / args.platform / "build_identity.json"
    _assert_no_links(output)
    if output.exists() and not output.is_file():
        raise SystemExit("identity output exists and is not a regular file")
    output.parent.mkdir(parents=True, exist_ok=True)
    identity = build_identity(root, args.digest)
    temp = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    try:
        if temp.exists() or temp.is_symlink():
            raise SystemExit("identity temporary output already exists")
        temp.write_text(json.dumps(identity, sort_keys=True, separators=(",", ":")) + "\n",
                        encoding="utf-8")
        os.replace(temp, output)
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
    print(json.dumps({"platform": args.platform, "version": identity["version"],
                      "build_id": identity["build_id"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
