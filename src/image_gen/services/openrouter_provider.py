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

import httpx
import structlog

from image_gen.config import Settings
from image_gen.exceptions import ProviderError, UnsupportedParameterError
from image_gen.services._sizing import compute_size
from image_gen.services.provider import ImageProvider, ProviderResult, decode_b64_image

logger = structlog.get_logger()

_OPENROUTER_IMAGE_URL = "https://openrouter.ai/api/v1/images"

# Canonical resolution → (quality param, long-edge pixel target)
_RESOLUTION_MAP: dict[str, tuple[str, int]] = {
    "1K": ("low", 1024),
    "2K": ("medium", 2048),
    "4K": ("high", 3840),
}


def _compute_resolution(aspect_ratio: str, resolution: str) -> str:
    """Return a ``WxH`` size string for OpenRouter.

    Raises:
        UnsupportedParameterError: If the ratio or resolution is not recognised.
    """
    if resolution not in _RESOLUTION_MAP:
        msg = f"OpenRouter provider does not recognise resolution {resolution!r}"
        raise UnsupportedParameterError(msg)
    _, base = _RESOLUTION_MAP[resolution]
    return compute_size(aspect_ratio, base, "OpenRouter")


class OpenRouterProvider(ImageProvider):
    """Generates images via the OpenRouter image API."""

    name = "openrouter"

    def __init__(self, settings: Settings) -> None:
        self._api_key = settings.openrouter_api_key
        self._model = settings.openrouter_model
        self._timeout = settings.request_timeout_seconds
        # Pool one client for the provider's lifetime so connections and TLS
        # sessions are reused across requests instead of a fresh handshake per
        # call. Closed via aclose() during application shutdown.
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(self._timeout))

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
        Uses the pooled :class:`httpx.AsyncClient` (its own timeout bounds the call);
        :func:`asyncio.timeout` wraps it as an outer backstop.
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
                resp = await self._client.post(
                    _OPENROUTER_IMAGE_URL,
                    json=payload,
                    headers=headers,
                )
        except (TimeoutError, httpx.TimeoutException) as e:
            msg = f"OpenRouter request timed out after {self._timeout}s"
            raise ProviderError(msg) from e
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

        image_data = decode_b64_image(b64, "OpenRouter")
        logger.info("OpenRouter image generated successfully", model=self._model)
        return ProviderResult(image_data=image_data, mime_type="image/png")

    async def aclose(self) -> None:
        """Close the pooled HTTP client."""
        await self._client.aclose()
