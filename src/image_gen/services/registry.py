"""Provider registry — builds the runtime map of configured providers.

:func:`build_registry` is called once during application startup (lifespan).
It inspects which API keys are present and instantiates only the providers that
are configured.  If the configured ``default_provider`` is absent from the
resulting registry the service fails fast with :class:`ProviderNotConfiguredError`
so the operator knows immediately rather than discovering it at request time.
"""

import structlog

from image_gen.config import Settings
from image_gen.exceptions import ProviderNotConfiguredError
from image_gen.services.gemini import GeminiProvider
from image_gen.services.openai_provider import OpenAIProvider
from image_gen.services.openrouter_provider import OpenRouterProvider
from image_gen.services.provider import ImageProvider

logger = structlog.get_logger()


def build_registry(settings: Settings) -> dict[str, ImageProvider]:
    """Instantiate providers whose API keys are present in *settings*.

    Returns:
        Mapping of provider name → :class:`~image_gen.services.provider.ImageProvider`
        instance.  At least one entry is guaranteed (or the function raises).

    Raises:
        ProviderNotConfiguredError: If ``settings.default_provider`` is not among the
            configured providers (i.e. its API key is missing).
    """
    registry: dict[str, ImageProvider] = {}

    if settings.google_api_key:
        registry["gemini"] = GeminiProvider(settings)
        logger.debug("Registered provider", provider="gemini", model=settings.gemini_model)

    if settings.openai_api_key:
        registry["openai"] = OpenAIProvider(settings)
        logger.debug("Registered provider", provider="openai", model=settings.openai_model)

    if settings.openrouter_api_key:
        registry["openrouter"] = OpenRouterProvider(settings)
        logger.debug("Registered provider", provider="openrouter", model=settings.openrouter_model)

    if settings.default_provider not in registry:
        configured = sorted(registry.keys()) or ["none"]
        msg = (
            f"Default provider {settings.default_provider!r} is not configured. "
            f"Set the corresponding API key.  Available: {', '.join(configured)}"
        )
        raise ProviderNotConfiguredError(msg)

    return registry
