"""Gemini image-generation provider.

Wraps the synchronous Google GenAI SDK in an async executor call with:

- Timeout via :func:`asyncio.timeout` so a hung SDK call cannot exhaust the thread pool.
- Typed retry on :class:`google.genai.errors.ServerError` (HTTP 503 / UNAVAILABLE) with
  exponential back-off.
- Domain errors mapped to :class:`~image_gen.exceptions.ProviderError` instead of bare
  ``ValueError`` / ``RuntimeError`` so the API layer can categorise them correctly.
"""

import asyncio

import structlog
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from image_gen.config import Settings
from image_gen.exceptions import ProviderError
from image_gen.services.provider import ImageProvider, ProviderResult

logger = structlog.get_logger()

MAX_RETRIES = 3
BASE_RETRY_DELAY_SECONDS = 10


class GeminiProvider(ImageProvider):
    """Wraps the Google GenAI SDK for image generation."""

    name = "gemini"

    def __init__(self, settings: Settings) -> None:
        self._client = genai.Client(api_key=settings.google_api_key)
        self._model = settings.gemini_model
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
        """Generate an image from a text prompt with retry on transient failures.

        Pre-validates the prompt before making the expensive API call.
        Retries on ServerError (503/UNAVAILABLE) with exponential back-off.
        Wraps the entire attempt sequence in an asyncio timeout.
        """
        if not prompt.strip():
            msg = "Prompt cannot be empty"
            raise ProviderError(msg)

        config = types.GenerateContentConfig(
            response_modalities=["IMAGE"],
            image_config=types.ImageConfig(
                aspect_ratio=aspect_ratio,
                image_size=resolution,
            ),
        )

        last_error: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                logger.info(
                    "Calling Gemini API",
                    model=self._model,
                    aspect_ratio=aspect_ratio,
                    resolution=resolution,
                    attempt=attempt + 1,
                )

                # google-genai is synchronous — run in executor to avoid blocking.
                # asyncio.timeout wraps the whole thread dispatch so a hung call
                # raises TimeoutError instead of blocking indefinitely.
                async with asyncio.timeout(self._timeout):
                    response = await asyncio.to_thread(
                        self._client.models.generate_content,
                        model=self._model,
                        contents=prompt,
                        config=config,
                    )

                for part in response.parts or []:
                    if part.inline_data is not None and part.inline_data.data is not None:
                        logger.info("Image generated successfully", model=self._model)
                        return ProviderResult(
                            image_data=part.inline_data.data,
                            mime_type=part.inline_data.mime_type or "image/png",
                        )

                # Response parsed cleanly but contained no image — the model
                # refused the request or the response shape changed.
                msg = "Gemini response contained no image data — request may have been refused"
                raise ProviderError(msg)

            except ProviderError:
                raise
            except genai_errors.ServerError as e:
                # Typed retry: ServerError covers 503 / UNAVAILABLE from the SDK.
                delay = BASE_RETRY_DELAY_SECONDS * (2**attempt)
                logger.warning(
                    "Gemini unavailable, retrying",
                    attempt=attempt + 1,
                    max_retries=MAX_RETRIES,
                    delay_seconds=delay,
                    status=getattr(e, "status", None),
                    code=getattr(e, "code", None),
                )
                last_error = e
                await asyncio.sleep(delay)
            except Exception as e:
                logger.error("Gemini API error", error=str(e))
                raise ProviderError(f"Gemini API error: {e}") from e

        msg = f"Gemini generation failed after {MAX_RETRIES} retries"
        raise ProviderError(msg) from last_error


# Backward-compatible alias — existing import sites outside this module
# (conftest, tests) reference GeminiResult; new code uses ProviderResult directly.
GeminiResult = ProviderResult
# Backward-compatible alias for service name used before provider abstraction.
GeminiService = GeminiProvider
