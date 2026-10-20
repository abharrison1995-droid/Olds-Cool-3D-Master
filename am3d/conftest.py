"""Shared test fixtures for offline and headless rendering tests."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _disable_native_gpu_context_by_default(monkeypatch):
    """Use the software renderer unless a test host explicitly opts into GL.

    Creating a standalone ModernGL context can terminate some headless
    Windows runners with a native access violation before Python can catch an
    exception. Keep ordinary tests deterministic and let dedicated,
    graphics-qualified runs opt in with ``AM3D_TEST_REAL_GPU=1``.
    """
    if os.environ.get("AM3D_TEST_REAL_GPU", "").strip() == "1":
        return

    from am3d.gpu.context import ContextManager

    def no_native_context(self):
        raise RuntimeError("native GPU context disabled for offline tests")

    monkeypatch.setattr(ContextManager, "create", no_native_context)
