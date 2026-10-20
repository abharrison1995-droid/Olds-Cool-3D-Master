#!/usr/bin/env python3
"""Copy exact license and copyright notices for the runtime closure."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import sysconfig


COMMON_DISTRIBUTIONS = (
    "numpy", "msgpack", "PySide6", "PySide6_Addons", "PySide6_Essentials",
    "shiboken6", "Pillow", "moderngl", "glcontext", "httpx", "httpcore",
    "h11", "anyio", "certifi", "idna", "keyring", "typing_extensions",
    "jaraco.classes", "jaraco.context", "jaraco.functools", "more-itertools",
)
PLATFORM_DISTRIBUTIONS = {
    "windows": ("pywin32-ctypes",),
    "linux": (
        "SecretStorage", "cryptography", "cffi", "pycparser", "jeepney",
    ),
}
_LICENSE_NAMES = re.compile(
    r"^(license|licence|copying|notice|third.party)(\..*)?$", re.IGNORECASE)


def _is_link(path: Path) -> bool:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    attrs = getattr(info, "st_file_attributes", 0)
    return (stat.S_ISLNK(info.st_mode)
            or bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)))


def _assert_no_links(path: Path, stop: Path) -> None:
    current = path
    while True:
        if _is_link(current):
            raise ValueError("release license path contains a link")
        if current == stop:
            return
        if current.parent == current:
            raise ValueError("release license path escaped its output root")
        current = current.parent


def _license_label(distribution) -> str:
    metadata = distribution.metadata
    expression = metadata.get("License-Expression")
    if expression:
        return _clean_label(expression)
    value = metadata.get("License")
    if value and value.strip().casefold() not in {"unknown", "see license"}:
        return _clean_label(value)
    classifiers = metadata.get_all("Classifier") or []
    choices = [item.split(" :: ")[-1] for item in classifiers
               if item.startswith("License :: OSI Approved :: ")]
    return _clean_label(choices[0]) if choices else "not stated in wheel metadata"


def _clean_label(value: str) -> str:
    value = " ".join(value.split())
    if len(value) > 180 or any(ord(char) < 32 for char in value):
        return "see included license text"
    return value


def _license_files(distribution) -> list[tuple[Path, str]]:
    result = []
    for item in distribution.files or ():
        relative = Path(str(item))
        name = relative.name
        parent_names = {part.casefold() for part in relative.parts[:-1]}
        is_named = bool(_LICENSE_NAMES.match(name))
        is_license_dir = bool(parent_names & {"licenses", "license", "license_files"})
        if not (is_named or is_license_dir):
            continue
        source = Path(distribution.locate_file(item))
        if _is_link(source) or not source.is_file():
            continue
        if source.stat().st_size > 8 * 1024 * 1024:
            continue
        # Package names and relative wheel paths are kept as the only
        # destination components; metadata cannot choose an output root.
        relative_name = Path(*[part for part in relative.parts
                               if part not in {"..", ".", ""}])
        if not relative_name.parts or relative.is_absolute():
            continue
        result.append((source, relative_name.as_posix()))
    return sorted(result, key=lambda pair: pair[1].casefold())


def runtime_distribution_names(platform: str) -> tuple[str, ...]:
    if platform not in PLATFORM_DISTRIBUTIONS:
        raise ValueError("unsupported platform for runtime notices")
    return tuple(dict.fromkeys(
        (*COMMON_DISTRIBUTIONS, *PLATFORM_DISTRIBUTIONS[platform])))


def _python_version_tag() -> str:
    return f"{sys.version_info.major}.{sys.version_info.minor}"


def _within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _interpreter_notice_source(platform: str) -> tuple[Path, str]:
    """Resolve only exact interpreter notice paths inside the selected base."""
    base_prefix = Path(sys.base_prefix).resolve(strict=True)
    base_license = base_prefix / "LICENSE.txt"
    candidates = [(base_license, "base")]
    doc_candidates: list[Path] = []
    stdlib_license = None
    version = _python_version_tag()

    if platform == "linux":
        configured_stdlib = Path(sysconfig.get_path("stdlib")).resolve(strict=False)
        if _within(configured_stdlib, base_prefix):
            stdlib_license = configured_stdlib / "LICENSE.txt"
            candidates.append((stdlib_license, "stdlib"))

        doc_root = base_prefix / "share" / "doc"
        doc_candidates = [
            doc_root / f"python{version}" / "copyright",
            doc_root / f"python{version}-minimal" / "copyright",
            doc_root / f"libpython{version}-minimal" / "copyright",
        ]
        candidates.extend((path, "distro") for path in doc_candidates)
    elif platform != "windows":
        raise ValueError("unsupported platform for interpreter notices")

    def regular_exact_source(path: Path, source_kind: str) -> Path | None:
        if not path.exists() or _is_link(path):
            return None
        resolved = path.resolve(strict=True)
        if not resolved.is_file() or not _within(resolved, base_prefix):
            raise ValueError("interpreter notice source is outside the selected base installation")
        if source_kind == "distro":
            resolved_doc_root = (base_prefix / "share" / "doc").resolve(strict=True)
            if not _within(resolved, resolved_doc_root):
                raise ValueError("distribution copyright file is outside the selected share/doc tree")
        return resolved

    # Symlinks are accepted only on Linux, and only when they resolve to one
    # of the exact regular base/stdlib or version-specific distribution files.
    approved_targets: set[Path] = set()
    approved_targets_by_kind: dict[str, set[Path]] = {
        "base": set(), "stdlib": set(), "distro": set(),
    }
    for path, source_kind in candidates:
        if not _is_link(path):
            try:
                source = regular_exact_source(path, source_kind)
            except (OSError, RuntimeError) as exc:
                raise ValueError("interpreter notice source could not be resolved") from exc
            if source is not None:
                approved_targets.add(source)
                approved_targets_by_kind[source_kind].add(source)

    for path, source_kind in candidates:
        if not path.exists() and not _is_link(path):
            continue
        try:
            if _is_link(path):
                if platform != "linux":
                    raise ValueError("the CPython base installation LICENSE.txt is linked")
                resolved = path.resolve(strict=True)
                if resolved not in approved_targets:
                    raise ValueError("interpreter notice symlink does not resolve to an approved exact notice")
                if not resolved.is_file():
                    raise ValueError("interpreter notice symlink target is not a regular file")
            else:
                resolved = regular_exact_source(path, source_kind)
                if resolved is None:
                    continue
        except (OSError, RuntimeError) as exc:
            raise ValueError("interpreter notice source could not be resolved") from exc

        if resolved in approved_targets_by_kind["distro"]:
            source_description = (
                "Linux distribution copyright: "
                f"{resolved.relative_to(base_prefix).as_posix()}"
            )
        elif resolved in approved_targets_by_kind["stdlib"]:
            source_description = (
                "CPython standard-library LICENSE.txt: "
                f"{resolved.relative_to(base_prefix).as_posix()}"
            )
        else:
            source_description = (
                "CPython base-prefix LICENSE.txt: "
                f"{resolved.relative_to(base_prefix).as_posix()}"
            )

        if _is_link(path):
            source_description += (
                " (selected path "
                f"{path.relative_to(base_prefix).as_posix()} resolves to "
                f"{resolved.relative_to(base_prefix).as_posix()})"
            )
        return resolved, source_description

    raise ValueError("the selected interpreter's exact license notice is missing")


def _bundled_component_sources(platform: str) -> list[dict]:
    """Return exact local notices for the interpreter and PyInstaller code."""
    from importlib import metadata

    python_license, python_source_description = _interpreter_notice_source(platform)

    try:
        pyinstaller = metadata.distribution("PyInstaller")
    except metadata.PackageNotFoundError:
        raise ValueError("the PyInstaller build distribution is missing") from None

    copying_files = []
    for item in pyinstaller.files or ():
        relative = Path(str(item))
        parts = [part.casefold() for part in relative.parts]
        if (relative.name.casefold() == "copying.txt" and len(parts) >= 3
                and parts[-2] == "licenses" and parts[-3].endswith(".dist-info")):
            copying_files.append(item)
    if len(copying_files) != 1:
        raise ValueError("PyInstaller's installed wheel has no unique upstream COPYING.txt notice")
    pyinstaller_license = Path(pyinstaller.locate_file(copying_files[0]))
    if _is_link(pyinstaller_license) or not pyinstaller_license.is_file():
        raise ValueError("PyInstaller's upstream COPYING.txt is missing or linked")

    is_distro_notice = python_source_description.startswith(
        "Linux distribution copyright:")
    return [
        {
            "name": ("Python interpreter distribution copyright notice"
                     if is_distro_notice else
                     "CPython interpreter and standard library"),
            "version": sys.version.split()[0],
            "source": python_license,
            "source_description": python_source_description,
            "license_file": "interpreter/CPython-LICENSE.txt",
        },
        {
            "name": "PyInstaller bootloader and embedded runtime hooks",
            "version": pyinstaller.version,
            "source": pyinstaller_license,
            "source_description": "PyInstaller wheel dist-info/licenses/COPYING.txt",
            "license_file": "pyinstaller/PyInstaller-COPYING.txt",
        },
    ]


def _copy_bundled_component_notices(licenses_root: Path, platform: str) -> list[dict]:
    components = []
    for component in _bundled_component_sources(platform):
        target = licenses_root.joinpath(*Path(component["license_file"]).parts)
        _assert_no_links(target.parent, licenses_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_links(target.parent, licenses_root)
        if target.exists() or _is_link(target):
            raise ValueError("bundled component license output already exists")
        shutil.copyfile(component["source"], target)
        components.append({
            "name": component["name"],
            "version": component["version"],
            "source": component["source_description"],
            "license_file": component["license_file"],
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        })
    return components


def write_licenses(root: Path, output: Path, platform: str) -> dict:
    from importlib import metadata

    root = root.resolve(strict=True)
    release_lexical = Path(os.path.abspath(os.fspath(root / "release")))
    if _is_link(release_lexical):
        raise ValueError("repository release directory is linked")
    release_root = release_lexical.resolve(strict=True)
    output = Path(os.path.abspath(os.fspath(output)))
    try:
        relative = output.relative_to(release_lexical)
    except ValueError as exc:
        raise ValueError("license output must be inside this repository's release directory") from exc
    _assert_no_links(output, release_lexical)
    output = output.resolve(strict=True)
    if not relative.parts or not output.is_dir() or _is_link(output):
        raise ValueError("license output must be an existing candidate directory")

    licenses_root = output / "LICENSES"
    if not licenses_root.is_dir() or _is_link(licenses_root):
        raise ValueError("candidate LICENSES directory is missing or linked")
    destination = licenses_root / "third_party"
    if destination.exists() or _is_link(destination):
        raise ValueError("third-party license output already exists")
    destination.mkdir()

    packages = []
    seen = set()
    for requested_name in runtime_distribution_names(platform):
        try:
            distribution = metadata.distribution(requested_name)
        except metadata.PackageNotFoundError:
            raise ValueError(f"required runtime distribution is missing: {requested_name}") from None
        canonical = re.sub(r"[-_.]+", "-", distribution.metadata["Name"]).casefold()
        if canonical in seen:
            continue
        seen.add(canonical)
        package_dir = destination / canonical
        package_dir.mkdir()
        copied = []
        for source, relative_name in _license_files(distribution):
            target = package_dir.joinpath(*Path(relative_name).parts)
            _assert_no_links(target.parent, package_dir)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            copied.append(target.relative_to(destination).as_posix())
        packages.append({
            "name": distribution.metadata["Name"],
            "version": distribution.version,
            "license": _license_label(distribution),
            "license_files": copied,
        })

    bundled_components = _copy_bundled_component_notices(licenses_root, platform)

    notice = [
        "3D MASTER:2005 Beta",
        "Copyright (c) 2026",
        "",
        "Runtime package notices for this platform build:",
    ]
    for package in packages:
        label = package["license"]
        files = package["license_files"]
        file_note = (", ".join(path.split("/", 1)[1] for path in files)
                     if files else "no upstream license text present in installed wheel")
        notice.append(f"- {package['name']} {package['version']}: {label}; {file_note}")
    notice.extend((
        "",
        "Bundled interpreter and bootloader/runtime-hook notices:",
    ))
    for component in bundled_components:
        notice.append(
            f"- {component['name']} {component['version']}: "
            f"{component['license_file']} ({component['source']}; "
            "verbatim source text)"
        )
    notice.extend((
        "",
        "Upstream license files found in installed runtime wheels are included",
        "under LICENSES/third_party. Package metadata labels are reported",
        "verbatim when supplied; missing metadata is identified above.",
        "PyInstaller is a build tool; this notice covers its bundled bootloader",
        "and embedded runtime hooks, not the PyInstaller tool package as runtime.",
    ))
    (licenses_root / "NOTICE.txt").write_text("\n".join(notice) + "\n",
                                             encoding="utf-8")
    manifest = {
        "format_version": 2,
        "platform": platform,
        "packages": packages,
        "bundled_components": bundled_components,
    }
    (licenses_root / "THIRD_PARTY_LICENSES.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path,
                        default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, required=True,
                        help="candidate release directory under repository/release")
    parser.add_argument("--platform", choices=("windows", "linux"), required=True)
    args = parser.parse_args(argv)
    try:
        result = write_licenses(args.root, args.output, args.platform)
    except (OSError, ValueError) as exc:
        print(f"license notice generation failed: {type(exc).__name__}: {exc}",
              file=sys.stderr)
        return 1
    print(
        f"Wrote notices for {len(result['packages'])} runtime packages and "
        f"{len(result['bundled_components'])} bundled components."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
