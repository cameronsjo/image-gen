"""Abstract base class for image generation providers.

All providers implement :class:`ImageProvider` and return a :class:`ProviderResult`.
The concrete implementations live alongside this module:

- :mod:`image_gen.services.gemini` — Google Gemini
- :mod:`image_gen.services.openai_provider` — OpenAI gpt-image-2
- :mod:`image_gen.services.openrouter_provider` — OpenRouter (any model)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class ProviderResult:
    """Result of an image generation call."""

    image_data: bytes
    mime_type: str


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
    ) -> ProviderResult:
        """Generate an image from a text prompt.

        Args:
            prompt: The image description.
            aspect_ratio: Canonical aspect ratio string (e.g. "1:1", "16:9").
            resolution: Canonical resolution tier ("1K", "2K", or "4K").

        Returns:
            A :class:`ProviderResult` with raw image bytes and MIME type.

        Raises:
            :class:`image_gen.exceptions.UnsupportedParameterError`: If the provider
                cannot honor the requested aspect_ratio / resolution combination.
            :class:`image_gen.exceptions.ProviderError`: If the provider API call fails.
        """
        ...
