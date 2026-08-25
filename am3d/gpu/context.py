"""Offscreen OpenGL context management (headless — no window needed).

Used by the GPU renderer, and as a fallback for sprite-sheet baking when a
window system is absent.
"""

from __future__ import annotations

import threading


_CTX_STACK = threading.local()


class ContextManager:
    """Wraps a ModernGL context with automatic destruction."""

    def __init__(self, width=512, height=512):
        self.width = width
        self.height = height
        self.ctx = None
        self._owned = False
        self._fallback_window = None

    def create(self):
        """Create or reuse a thread-local offscreen context."""
        if self.ctx is not None:
            return self.ctx
        try:
            import moderngl as mgl
        except ImportError:
            raise RuntimeError("ModernGL is required for GPU rendering; "
                               "install with: pip install moderngl")
        local = getattr(_CTX_STACK, "ctx", None)
        if local is not None:
            self.ctx = local
            self._owned = False
            return self.ctx

        # Try standalone context first (ModernGL >= 5.x uses size=(w,h))
        try:
            self.ctx = mgl.create_standalone_context(
                size=(self.width, self.height))
            self.ctx.gc_mode = "context_gc"
            _CTX_STACK.ctx = self.ctx
            self._owned = True
            return self.ctx
        except Exception:
            pass

        # Fallback: hidden PySide6 window for a GL context
        try:
            from PySide6.QtWidgets import QApplication, QWidget
            app = QApplication.instance()
            if app is None:
                app = QApplication([])
            self._fallback_window = QWidget()
            self._fallback_window.resize(self.width, self.height)
            self._fallback_window.hide()
            self.ctx = mgl.create_context()
            _CTX_STACK.ctx = self.ctx
            self._owned = True
            return self.ctx
        except Exception as exc:
            raise RuntimeError(
                f"cannot create OpenGL context (standalone or window): {exc}")

    def destroy(self):
        if self._owned and self.ctx is not None:
            try:
                self.ctx.release()
            except Exception:
                pass
            self.ctx = None
            try:
                del _CTX_STACK.ctx
            except AttributeError:
                pass
        if self._fallback_window is not None:
            try:
                self._fallback_window.close()
            except Exception:
                pass
            self._fallback_window = None

    def __enter__(self):
        self.create()
        return self

    def __exit__(self, *exc):
        self.destroy()


def create_offscreen_context(width=512, height=512) -> ContextManager:
    """Create and return a :class:`ContextManager` ready for rendering."""
    mgr = ContextManager(width, height)
    mgr.create()
    return mgr