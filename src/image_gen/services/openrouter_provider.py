"""OpenRouter image-generation provider.

Calls the OpenRouter image endpoint over plain HTTPX (OpenRouter has no official Python
SDK).  Maps canonical resolution values to pixel-dimension strings compatible with the
underlying model (defaulting to ``openai/gpt-image-2``).

OpenRouter request shape (POST https://openrouter.ai/api/v1/images):
  ``{model, prompt, n, resolution, quality, output_format}``

Response shape:
  ``{"data": [{"b64_json": "<base64>"}], ...}``

Raises :class:`~image_gen.exceptions.ProviderError` on any non-2xx HTTP response or
missing image data.
"""

import asyncio
import base64
import math

import httpx
import structlog

from image_gen.config import Settings
from image_gen.exceptions import ProviderError, UnsupportedParameterError
from image_gen.services.provider import ImageProvider, ProviderResult

logger = structlog.get_logger()

_OPENROUTER_IMAGE_URL = "https://openrouter.ai/api/v1/images"

# Canonical aspect-ratio string → (width_parts, height_parts)
_RATIO_MAP: dict[str, tuple[int, int]] = {
    "1:1": (1, 1),
    "2:3": (2, 3),
    "3:2": (3, 2),
    "3:4": (3, 4),
    "4:3": (4, 3),
    "4:5": (4, 5),
    "5:4": (5, 4),
    "9:16": (9, 16),
    "16:9": (16, 9),
    "21:9": (21, 9),
}

# Canonical resolution → (quality param, long-edge pixel target)
_RESOLUTION_MAP: dict[str, tuple[str, int]] = {
    "1K": ("low", 1024),
    "2K": ("medium", 2048),
    "4K": ("high", 3840),
}

_DIVISOR = 16
_MAX_DIM = 3840


def _compute_resolution(aspect_ratio: str, resolution: str) -> str:
    """Return a ``WxH`` size string for OpenRouter.

    Raises:
        UnsupportedParameterError: If the ratio or resolution is not recognised.
    """
    if aspect_ratio not in _RATIO_MAP:
        msg = f"OpenRouter provider does not recognise aspect ratio {aspect_ratio!r}"
        raise UnsupportedParameterError(msg)
    if resolution not in _RESOLUTION_MAP:
        msg = f"OpenRouter provider does not recognise resolution {resolution!r}"
        raise UnsupportedParameterError(msg)

    w_parts, h_parts = _RATIO_MAP[aspect_ratio]
    _, base = _RESOLUTION_MAP[resolution]

    if w_parts >= h_parts:
        width = min(base, _MAX_DIM)
        height = math.floor(width * h_parts / w_parts / _DIVISOR) * _DIVISOR
        height = max(height, _DIVISOR)
    else:
        height = min(base, _MAX_DIM)
        width = math.floor(height * w_parts / h_parts / _DIVISOR) * _DIVISOR
        width = max(width, _DIVISOR)

    return f"{width}x{height}"


class OpenRouterProvider(ImageProvider):
    """Generates images via the OpenRouter image API."""

    name = "openrouter"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.openrouter_api_key
        self._model = settings.openrouter_model
        self._timeout = settings.request_timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
    ) -> ProviderResult:
        """Generate an image via the OpenRouter images endpoint.

        Non-2xx responses raise :class:`~image_gen.exceptions.ProviderError`.
        The timeout is applied via :func:`asyncio.timeout` around the whole HTTPX call.
        """
        size_str = _compute_resolution(aspect_ratio, resolution)
        quality, _ = _RESOLUTION_MAP[resolution]

        payload = {
            "model": self._model,
            "prompt": prompt,
            "n": 1,
            "resolution": size_str,
            "quality": quality,
            "output_format": "png",
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        logger.info(
            "Calling OpenRouter images API",
            model=self._model,
            resolution=size_str,
            quality=quality,
        )

        try:
            async with asyncio.timeout(self._timeout):
                async with httpx.AsyncClient() as http_client:
                    resp = await http_client.post(
                        _OPENROUTER_IMAGE_URL,
                        json=payload,
                        headers=headers,
                    )
        except TimeoutError:
            msg = f"OpenRouter request timed out after {self._timeout}s"
            raise ProviderError(msg) from None
        except Exception as e:
            logger.error("OpenRouter HTTP error", error=str(e))
            raise ProviderError(f"OpenRouter HTTP error: {e}") from e

        if resp.status_code >= 400:
            body_preview = resp.text[:200]
            msg = f"OpenRouter returned HTTP {resp.status_code}: {body_preview}"
            logger.error("OpenRouter API error", status=resp.status_code, body=body_preview)
            raise ProviderError(msg)

        try:
            data = resp.json()
            b64 = data["data"][0]["b64_json"]
        except (KeyError, IndexError, ValueError) as e:
            msg = f"OpenRouter response shape unexpected: {e}"
            raise ProviderError(msg) from e

        if not b64:
            msg = "OpenRouter response contained no image data"
            raise ProviderError(msg)

        image_data = base64.b64decode(b64)
        logger.info("OpenRouter image generated successfully", model=self._model)
        return ProviderResult(image_data=image_data, mime_type="image/png")
