"""Filesystem boundary and collision tests for local generation storage."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from .contracts import GenerationResult, GenerationStatus
from .storage import GenerationStore


def test_run_id_collision_allocates_a_fresh_private_attempt(tmp_path):
    store = GenerationStore(tmp_path)
    repeated = "1" * 32
    fresh = "2" * 32
    with patch("am3d.ai.storage.uuid.uuid4",
               side_effect=[SimpleNamespace(hex=repeated),
                            SimpleNamespace(hex=repeated),
                            SimpleNamespace(hex=fresh)]):
        first = store.new_attempt()
        second = store.new_attempt()
    try:
        assert first.run_id == repeated
        assert second.run_id == fresh
        assert first.worker_root != second.worker_root
    finally:
        store.cleanup_attempt(first)
        store.cleanup_attempt(second)


@pytest.mark.skipif(not hasattr(Path, "symlink_to"),
                    reason="symlink support is unavailable")
def test_publication_rejects_symlinked_worker_artifacts(tmp_path):
    store = GenerationStore(tmp_path)
    attempt = store.new_attempt()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside", encoding="utf-8")
    link = attempt.output_root / "escape.txt"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        store.cleanup_attempt(attempt)
        pytest.skip("this account cannot create symlinks")
    result = GenerationResult(attempt.run_id, GenerationStatus.COMPLETE)
    try:
        with pytest.raises(ValueError, match="symlink"):
            store.publish_success(attempt, result, '{"version":1}')
    finally:
        store.cleanup_attempt(attempt)
    assert not (store.generations / attempt.run_id).exists()
