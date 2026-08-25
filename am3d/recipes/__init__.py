"""Recipe-driven asset generation (the LLM-facing layer).

An LLM produces a plain-JSON *recipe*; this package validates it, executes
it against a live project and exports the resulting assets.
"""

from __future__ import annotations

from .schema import (  # noqa: F401
    ACTION_KINDS,
    EXPORT_FORMATS,
    PRIMITIVES,
    ActionRecipe,
    BoneRecipe,
    ChannelRecipe,
    ExportRecipe,
    KeyframeRecipe,
    MaterialRecipe,
    ObjectRecipe,
    Recipe,
    SplineRecipe,
    recipe_from_dict,
    validate_recipe,
)

__all__ = [
    "ACTION_KINDS", "EXPORT_FORMATS", "PRIMITIVES",
    "ActionRecipe", "BoneRecipe", "ChannelRecipe", "ExportRecipe",
    "KeyframeRecipe", "MaterialRecipe", "ObjectRecipe", "Recipe",
    "SplineRecipe", "recipe_from_dict", "validate_recipe",
]


def __getattr__(name):
    """Lazy heavy imports: executor (pulls renderer/export machinery)."""
    if name in ("executor", "RecipeExecutor", "ExecutionResult"):
        from . import executor as _module
        if name == "executor":
            return _module
        return getattr(_module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")