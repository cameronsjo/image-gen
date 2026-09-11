"""OpenAI image-generation provider (gpt-image-2).

Maps canonical :class:`~image_gen.models.AspectRatio` / :class:`~image_gen.models.Resolution`
values to OpenAI ``size`` and ``quality`` parameters.  GPT-image models always return
base64-encoded PNG; ``response_format`` is not a valid parameter for them and is omitted.

Param mapping
-------------
Resolution → quality + pixel scale:

  ============  =======  ================
  Resolution    quality  long-edge pixels
  ============  =======  ================
  1K            low      1024
  2K            medium   2048
  4K            high     3840 (capped)
  ============  =======  ================

Aspect ratio → size:
  Computed from the ratio numerators and the resolution base via the shared
  :func:`image_gen.services._sizing.compute_size` helper.  Width and height are
  rounded to a multiple of 16 and capped so neither exceeds 3840.  Any ratio in
  :class:`~image_gen.models.AspectRatio` falls within OpenAI's supported 1:3-3:1
  range, so all canonical ratios are accepted without error.

Raises :class:`~image_gen.exceptions.UnsupportedParameterError` for an unknown ratio or
resolution string.  Dimensions are capped to 3840 per axis by construction.
"""

import re
from typing import Literal

import structlog
from openai import AsyncOpenAI

from image_gen.config import Settings
from image_gen.exceptions import ProviderError, UnsupportedParameterError
from image_gen.services._sizing import compute_size
from image_gen.services.provider import (
    ImageProvider,
    ProviderResult,
    decode_b64_image,
    models_with_default,
)

logger = structlog.get_logger()

# OpenAI's models.list() exposes no capability field, so image models are
# identified by id prefix (gpt-image-*, dall-e-*).
_IMAGE_MODEL_RE = re.compile(r"^(gpt-image|dall-e)")

# OpenAI's gpt-image quality tiers we map onto (subset of the SDK Literal).
_OpenAIQuality = Literal["low", "medium", "high"]

# Canonical resolution → (quality param, long-edge pixel target)
_RESOLUTION_MAP: dict[str, tuple[_OpenAIQuality, int]] = {
    "1K": ("low", 1024),
    "2K": ("medium", 2048),
    "4K": ("high", 3840),  # 4096 > 3840 max — cap to 3840
}


def _compute_size(aspect_ratio: str, resolution: str) -> str:
    """Return an OpenAI-compatible ``WxH`` size string for the given params.

    Raises:
        UnsupportedParameterError: If the ratio or resolution is not recognised.
    """
    if resolution not in _RESOLUTION_MAP:
        msg = f"OpenAI provider does not recognise resolution {resolution!r}"
        raise UnsupportedParameterError(msg)
    _, base = _RESOLUTION_MAP[resolution]
    return compute_size(aspect_ratio, base, "OpenAI")


class OpenAIProvider(ImageProvider):
    """Generates images via the OpenAI images API (gpt-image-2)."""

    name = "openai"

    def __init__(self, settings: Settings) -> None:
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_model
        self._timeout = settings.request_timeout_seconds

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
        model: str | None = None,
    ) -> ProviderResult:
        """Generate an image via the OpenAI images API.

        GPT-image models always return base64, so ``response_format`` is not sent
        (these models reject it).  The native SDK ``timeout`` parameter bounds the call;
        a slow response raises ``httpx.ReadTimeout``, surfaced as
        :class:`~image_gen.exceptions.ProviderError`.
        """
        model = model or self._model
        size = _compute_size(aspect_ratio, resolution)
        quality, _ = _RESOLUTION_MAP[resolution]

        logger.info(
            "Calling OpenAI images API",
            model=model,
            size=size,
            quality=quality,
        )

        try:
            response = await self._client.images.generate(
                model=model,
                prompt=prompt,
                n=1,
                size=size,
                quality=quality,
                timeout=self._timeout,
            )
        except Exception as e:
            logger.error("OpenAI API error", error=str(e))
            raise ProviderError(f"OpenAI API error: {e}") from e

        if not response.data:
            msg = "OpenAI response contained no image data"
            raise ProviderError(msg)
        b64 = response.data[0].b64_json
        if not b64:
            msg = "OpenAI response contained no image data"
            raise ProviderError(msg)

        image_data = decode_b64_image(b64, "OpenAI")
        logger.info("OpenAI image generated successfully", model=model, size=size)
        return ProviderResult(image_data=image_data, mime_type="image/png")

    async def list_models(self) -> list[str]:
        """Discover OpenAI image models via ``models.list()``.

        The API has no capability field, so ids are matched against
        :data:`_IMAGE_MODEL_RE` (``gpt-image-*`` / ``dall-e-*``).  Any failure
        degrades to the configured default.
        """
        try:
            page = await self._client.models.list()
            discovered = [m.id for m in page.data if _IMAGE_MODEL_RE.match(m.id)]
        except Exception as exc:
            logger.warning("OpenAI model discovery failed", error=str(exc))
            discovered = []
        return models_with_default(self._model, discovered)

    async def aclose(self) -> None:
        """Close the underlying AsyncOpenAI client."""
        await self._client.close()
