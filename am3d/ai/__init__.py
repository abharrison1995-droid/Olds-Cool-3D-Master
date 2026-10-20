"""Headless contracts and provider transport for AI-assisted generation.

The AI package deliberately has no Qt imports. Its provider talks only to a
configured JSON endpoint and never receives a project ``Session``.
"""

from .contracts import (
    AssetBrief,
    AnimationIntent,
    CancellationToken,
    ComponentRequirement,
    DeadlineExceededError,
    Dimensions,
    GenerationCancelledError,
    GenerationEvent,
    GenerationRequest,
    MaterialIntent,
    ProviderConfig,
    ProviderError,
    ProviderMessage,
    ProviderResponse,
    ProviderUsage,
)
from .providers import OpenAICompatibleProvider
from .credentials import CredentialStore, SessionCredentialStore, SystemCredentialStore
from .contracts import (
    ProviderAuthenticationError,
    ProviderConfigurationError,
    ProviderCredentialError,
    ProviderModelError,
    ProviderProtocolError,
    ProviderRateLimitError,
    ProviderRefusalError,
    ProviderRequestError,
    ProviderResponseTooLargeError,
    ProviderTransientError,
    ProviderTruncatedResponseError,
)

__all__ = [
    "AssetBrief",
    "AnimationIntent",
    "CancellationToken",
    "ComponentRequirement",
    "CredentialStore",
    "DeadlineExceededError",
    "Dimensions",
    "GenerationCancelledError",
    "GenerationEvent",
    "GenerationRequest",
    "MaterialIntent",
    "OpenAICompatibleProvider",
    "SessionCredentialStore",
    "SystemCredentialStore",
    "ProviderAuthenticationError",
    "ProviderConfig",
    "ProviderConfigurationError",
    "ProviderCredentialError",
    "ProviderError",
    "ProviderModelError",
    "ProviderMessage",
    "ProviderProtocolError",
    "ProviderRateLimitError",
    "ProviderRefusalError",
    "ProviderRequestError",
    "ProviderResponse",
    "ProviderResponseTooLargeError",
    "ProviderTransientError",
    "ProviderTruncatedResponseError",
    "ProviderUsage",
]
