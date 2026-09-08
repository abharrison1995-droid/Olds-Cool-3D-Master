"""Centralized collision-safe naming utilities."""

from __future__ import annotations

from typing import Iterable


def allocate_unique_name(existing_names: Iterable[str], base: str, max_attempts: int = 1000) -> str:
    """Generate a unique name from *base* that does not exist in *existing_names*.

    If *base* is not present in *existing_names*, returns *base*.
    Otherwise attempts `{base}_{i:03d}` for i starting at 1 up to *max_attempts*.
    If all attempts collide, raises :class:`RuntimeError` with an explicit diagnostic
    instead of failing silently.
    """
    names_set = set(existing_names)
    if base not in names_set:
        return base
    for i in range(1, max_attempts + 1):
        cand = f"{base}_{i:03d}"
        if cand not in names_set:
            return cand
    raise RuntimeError(
        f"Naming collision limit reached for base {base!r} after {max_attempts} attempts")
