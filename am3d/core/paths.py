"""Platform-independent path policy shared by the recipe executor and loader.

A recipe (or a saved project's resource reference) is a portable document: the
same file must behave identically whether it is executed on Linux or on
Windows.  ``os.path`` cannot provide that, because it silently changes meaning
per host -- ``os.path.splitdrive("D:out")`` yields ``("", "D:out")`` on POSIX,
so a Windows drive-relative path reads as an innocent relative filename there
and as an escape on Windows.  The helpers below therefore judge a path string
by its *syntax* on every platform, and never by the host's conventions.
"""

from __future__ import annotations

import os
import re

__all__ = [
    "DRIVE_RE",
    "has_drive_letter",
    "is_unc",
    "is_absolute_any_platform",
    "split_segments",
    "has_traversal",
    "reserved_component",
    "classify_portable_relative_path",
]

# A leading Windows drive specification: "C:\x", "C:/x" (drive-absolute) and
# "C:x" (drive-relative, resolved against that drive's own working directory).
DRIVE_RE = re.compile(r"^[A-Za-z]:")

# Windows reserved device names; a file cannot be created with these stems.
_RESERVED = frozenset(
    ["CON", "PRN", "AUX", "NUL"]
    + [f"COM{i}" for i in range(1, 10)]
    + [f"LPT{i}" for i in range(1, 10)]
)

# Characters Windows forbids in a filename. "\\" and "/" are handled as
# separators before this check, and ":" is covered by the drive check.
_BAD_CHARS = '<>:"|?*'


def has_drive_letter(path: str) -> bool:
    """True for "C:...", including the drive-*relative* "C:name" form."""
    return bool(DRIVE_RE.match(path))


def is_unc(path: str) -> bool:
    """True for a UNC/network root such as ``\\\\server\\share`` or ``//server/share``."""
    head = path[:2]
    return head in ("\\\\", "//", "\\/", "/\\")


def is_absolute_any_platform(path: str) -> bool:
    """True if *path* is absolute under POSIX **or** Windows rules.

    Used instead of :func:`os.path.isabs` wherever a path may have been
    authored on the other platform.
    """
    if not path:
        return False
    return (
        path[0] in "/\\"
        or is_unc(path)
        or bool(re.match(r"^[A-Za-z]:[\\/]", path))
    )


def split_segments(path: str) -> list[str]:
    """Split on both separators, dropping empty segments."""
    return [seg for seg in re.split(r"[\\/]+", path) if seg]


def has_traversal(path: str) -> bool:
    """True if any segment is ``..`` (either separator style)."""
    return any(seg == ".." for seg in split_segments(path))


def reserved_component(path: str) -> str | None:
    """Return the first Windows-reserved device name used as a component."""
    for seg in split_segments(path):
        stem = seg.split(".", 1)[0].strip().upper()
        if stem in _RESERVED:
            return seg
    return None


def classify_portable_relative_path(path: str) -> tuple[str, str] | None:
    """Validate *path* as a portable, relative, non-escaping artifact path.

    Returns ``None`` when the path is acceptable, otherwise a
    ``(reason, hint)`` pair describing the first violation found.  Non-ASCII
    (Unicode) names are explicitly allowed; only structurally unsafe or
    non-portable syntax is rejected.
    """
    raw = os.fspath(path)
    if not raw or not raw.strip():
        return ("path must not be empty",
                "Provide a relative artifact name below the output root.")
    if has_drive_letter(raw):
        return (f"path {raw!r} must not specify a Windows drive letter",
                "Use a relative artifact name below the output root.")
    if is_unc(raw):
        return (f"path {raw!r} must not be a UNC network path",
                "Use a relative artifact name below the output root.")
    if is_absolute_any_platform(raw):
        return ("path must be relative when an output root is supplied",
                "Use a relative artifact name below the output root.")
    if has_traversal(raw):
        return (f"path {raw!r} must not contain '..' segments",
                "Remove '..' segments or provide a child path within the output root.")
    if not split_segments(raw):
        # e.g. "." or "./" -- resolves to the root itself, not a file.
        return (f"path {raw!r} does not name a file",
                "Provide a file name below the output root.")
    if split_segments(raw)[-1] in (".",):
        return (f"path {raw!r} does not name a file",
                "Provide a file name below the output root.")
    bad = set(raw) & set(_BAD_CHARS)
    if bad:
        return (f"path {raw!r} contains characters that are invalid on Windows: "
                f"{''.join(sorted(bad))}",
                "Use a portable file name (letters, digits, '-', '_', '.').")
    reserved = reserved_component(raw)
    if reserved is not None:
        return (f"path {raw!r} uses the Windows reserved device name {reserved!r}",
                "Choose a different file name.")
    return None


def normalize_separators(path: str) -> str:
    """Rewrite a portable relative path to use the host separator.

    A recipe may legitimately use either ``/`` or ``\\`` to mean "subdirectory".
    Normalising here makes ``sub\\file.obj`` denote the same artifact on Linux
    and on Windows, instead of a literal file name containing a backslash.
    """
    return os.sep.join(split_segments(path))
