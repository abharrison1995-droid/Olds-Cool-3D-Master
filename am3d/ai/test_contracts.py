import math

import pytest

from am3d.ai.contracts import (
    AnimationIntent,
    AssetBrief,
    ComponentRequirement,
    Dimensions,
    GenerationEvent,
    GenerationRequest,
    MaterialIntent,
    ProviderConfig,
    ProviderMessage,
)


def test_asset_brief_keeps_component_dimension_material_animation_and_export_intent_separate():
    brief = AssetBrief(
        brief="A small windmill for a game scene.",
        required_components=(ComponentRequirement("tower", "Tapered stone base"),),
        dimensions=Dimensions(2.0, 4.0, 2.0, "m"),
        materials=(MaterialIntent("stone", "Pale rough stone", (0.7, 0.68, 0.62)),),
        animation=AnimationIntent(("turning blades",), duration_seconds=5.0, looping=True),
        exports=("am3d", "glb"),
        style="low-poly retro",
        intended_use="game prop",
        approximations=("painted stone texture",),
    )

    assert brief.required_components[0].name == "tower"
    assert brief.dimensions == Dimensions(2.0, 4.0, 2.0, "m")
    assert brief.materials[0].color_srgb == (0.7, 0.68, 0.62)
    assert brief.animation.actions == ("turning blades",)
    assert brief.exports == ("am3d", "glb")
    assert brief.schema_version == 1


@pytest.mark.parametrize("dimensions", [
    (0.0, 1.0, 1.0),
    (1.0, float("nan"), 1.0),
    (1.0, 1.0, float("inf")),
])
def test_dimensions_reject_zero_and_nonfinite_values(dimensions):
    with pytest.raises(ValueError):
        Dimensions(*dimensions)


def test_generation_request_enforces_provider_and_recipe_output_caps():
    brief = AssetBrief("A prop")
    message = ProviderMessage("user", "Return a JSON object.")
    assert GenerationRequest(brief, (message,)).max_output_bytes == 1_048_576
    assert GenerationRequest(brief, (message,), max_output_bytes=524_288).max_output_bytes == 524_288
    with pytest.raises(ValueError, match="1 MiB"):
        GenerationRequest(brief, (message,), max_output_bytes=1_048_577)
    with pytest.raises(ValueError, match="1 MiB"):
        GenerationRequest(brief, (ProviderMessage("user", "x" * 1_048_577),))


def test_provider_requires_explicit_model_and_bounds_attempt_timeout():
    with pytest.raises(TypeError):
        ProviderConfig()  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="90 seconds"):
        ProviderConfig(model="chosen-model", timeout_seconds=90.1)


def test_generation_event_rejects_unmeasurable_progress():
    with pytest.raises(ValueError):
        GenerationEvent("run", 1, "provider", 1, "Working", progress=math.nan)
    event = GenerationEvent("run", 1, "provider", 1, "Requesting", progress=0.5)
    assert event.progress == 0.5
