"""OpenAI image-generation provider (gpt-image-2).

Maps canonical :class:`~image_gen.models.AspectRatio` / :class:`~image_gen.models.Resolution`
values to OpenAI ``size`` and ``quality`` parameters.  GPT-image models always return
base64-encoded PNG regardless of ``response_format``; this provider requests ``b64_json``
explicitly to make the intent clear.

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
  Computed from the ratio numerators and the resolution base.  Width and height are
  rounded to the nearest multiple of 16 and capped so neither exceeds 3840.
  Any ratio in :class:`~image_gen.models.AspectRatio` falls within OpenAI's supported
  1:3-3:1 range, so all canonical ratios are accepted without error.

Raises :class:`~image_gen.exceptions.UnsupportedParameterError` only for values that
fall outside the provider's hard limits (unknown ratio / resolution string, or computed
dimensions that overflow 3840 on any axis).
"""

import base64
import math

import structlog
from openai import AsyncOpenAI

from image_gen.config import Settings
from image_gen.exceptions import ProviderError, UnsupportedParameterError
from image_gen.services.provider import ImageProvider, ProviderResult

logger = structlog.get_logger()

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
    "4K": ("high", 3840),  # 4096 > 3840 max — cap to 3840
}

_MAX_DIM = 3840  # OpenAI max for any single dimension
_DIVISOR = 16


def _compute_size(aspect_ratio: str, resolution: str) -> str:
    """Return an OpenAI-compatible ``WxH`` size string for the given params.

    Raises:
        UnsupportedParameterError: If the ratio or resolution is not recognised,
            or if the computed dimensions overflow 3840 x 2160.
    """
    if aspect_ratio not in _RATIO_MAP:
        msg = f"OpenAI provider does not recognise aspect ratio {aspect_ratio!r}"
        raise UnsupportedParameterError(msg)
    if resolution not in _RESOLUTION_MAP:
        msg = f"OpenAI provider does not recognise resolution {resolution!r}"
        raise UnsupportedParameterError(msg)

    w_parts, h_parts = _RATIO_MAP[aspect_ratio]
    _, base = _RESOLUTION_MAP[resolution]

    # Compute pixel dimensions: scale so the long edge equals ``base``.
    if w_parts >= h_parts:
        width = min(base, _MAX_DIM)
        height = math.floor(width * h_parts / w_parts / _DIVISOR) * _DIVISOR
        height = max(height, _DIVISOR)
    else:
        height = min(base, _MAX_DIM)
        width = math.floor(height * w_parts / h_parts / _DIVISOR) * _DIVISOR
        width = max(width, _DIVISOR)

    if width > _MAX_DIM or height > _MAX_DIM:
        msg = (
            f"Computed dimensions {width}x{height} exceed OpenAI's maximum "
            f"{_MAX_DIM}x{_MAX_DIM} for aspect_ratio={aspect_ratio!r}, "
            f"resolution={resolution!r}"
        )
        raise UnsupportedParameterError(msg)

    return f"{width}x{height}"


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
    ) -> ProviderResult:
        """Generate an image via the OpenAI images API.

        GPT-image models always return base64; we request ``b64_json`` explicitly.
        The native SDK ``timeout`` parameter is used so a slow response raises
        ``httpx.ReadTimeout`` (surfaced as :class:`~image_gen.exceptions.ProviderError`)
        rather than blocking indefinitely.
        """
        size = _compute_size(aspect_ratio, resolution)
        quality, _ = _RESOLUTION_MAP[resolution]

        logger.info(
            "Calling OpenAI images API",
            model=self._model,
            size=size,
            quality=quality,
        )

        try:
            response = await self._client.images.generate(
                model=self._model,
                prompt=prompt,
                n=1,
                size=size,
                quality=quality,
                response_format="b64_json",
                timeout=self._timeout,
            )
        except Exception as e:
            logger.error("OpenAI API error", error=str(e))
            raise ProviderError(f"OpenAI API error: {e}") from e

        b64 = response.data[0].b64_json
        if not b64:
            msg = "OpenAI response contained no image data"
            raise ProviderError(msg)

        image_data = base64.b64decode(b64)
        logger.info("OpenAI image generated successfully", model=self._model, size=size)
        return ProviderResult(image_data=image_data, mime_type="image/png")
