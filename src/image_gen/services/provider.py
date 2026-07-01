"""Abstract base class for image generation providers.

All providers implement :class:`ImageProvider` and return a :class:`ProviderResult`.
The concrete implementations live alongside this module:

- :mod:`image_gen.services.gemini` — Google Gemini
- :mod:`image_gen.services.openai_provider` — OpenAI gpt-image-2
- :mod:`image_gen.services.openrouter_provider` — OpenRouter (any model)
"""

import base64
from abc import ABC, abstractmethod
from dataclasses import dataclass

from image_gen.exceptions import ProviderError


@dataclass
class ProviderResult:
    """Result of an image generation call."""

    image_data: bytes
    mime_type: str
    # USD cost of this generation when the provider reports it (OpenRouter's
    # ``usage.cost``).  Defaulted so providers that don't surface a cost (Gemini,
    # OpenAI) construct a ProviderResult unchanged and leave it ``None``.
    cost_usd: float | None = None


def decode_b64_image(b64: str, provider_name: str) -> bytes:
    """Decode a base64 image payload, raising ProviderError on malformed data."""
    try:
        return base64.b64decode(b64)
    except ValueError as exc:  # binascii.Error subclasses ValueError
        msg = f"{provider_name} returned malformed base64 image data"
        raise ProviderError(msg) from exc


def models_with_default(default: str, discovered: list[str]) -> list[str]:
    """Return *discovered* models with *default* guaranteed present and first.

    De-duplicates while preserving order so the configured default leads the list
    (the UI's pre-selected option) and a discovery run that already surfaced it
    doesn't list it twice.  A discovery failure therefore degrades to ``[default]``
    rather than dropping the working model.
    """
    # dict.fromkeys preserves insertion order and de-duplicates in one pass — the
    # default leads, discovery follows, and any repeat (e.g. discovery surfacing the
    # default) collapses to a single entry.
    return list(dict.fromkeys([default, *discovered]))


class ImageProvider(ABC):
    """Abstract base for image generation providers."""

    name: str  # "gemini" | "openai" | "openrouter"

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Return the model identifier string used by this provider."""
        ...

    @abstractmethod
    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
        model: str | None = None,
    ) -> ProviderResult:
        """Generate an image from a text prompt.

        Args:
            prompt: The image description.
            aspect_ratio: Canonical aspect ratio string (e.g. "1:1", "16:9").
            resolution: Canonical resolution tier ("1K", "2K", or "4K").
            model: Provider model identifier; ``None`` uses the provider's
                configured default (:attr:`model_name`).

        Returns:
            A :class:`ProviderResult` with raw image bytes and MIME type.

        Raises:
            :class:`image_gen.exceptions.UnsupportedParameterError`: If the provider
                cannot honor the requested aspect_ratio / resolution combination.
            :class:`image_gen.exceptions.ProviderError`: If the provider API call fails.
        """
        ...

    async def list_models(self) -> list[str]:
        """Discover the image models this provider can serve.

        The default returns only the configured model.  Providers override this to
        query their list-models API once at startup; on any failure they fall back to
        ``[self.model_name]`` (via :func:`models_with_default`) so discovery never
        removes the working default.  The configured default leads the returned list.
        """
        return [self.model_name]

    async def aclose(self) -> None:
        """Release any pooled network resources held by the provider.

        Called once during application shutdown (lifespan teardown). The default is
        a no-op for providers that hold no long-lived client; providers that pool a
        connection (e.g. a shared ``httpx.AsyncClient`` or SDK client) override this
        to close it cleanly.
        """
        return None
