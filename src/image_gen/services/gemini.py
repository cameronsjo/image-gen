"""Async Gemini SDK wrapper with pre-flight validation and retry logic."""

import asyncio
from dataclasses import dataclass

import structlog
from google import genai
from google.genai import types

from image_gen.config import Settings

logger = structlog.get_logger()

MAX_RETRIES = 3
BASE_RETRY_DELAY_SECONDS = 10


@dataclass
class GeminiResult:
    """Result of an image generation call."""

    image_data: bytes
    mime_type: str


class GeminiService:
    """Wraps the Google GenAI SDK for image generation."""

    def __init__(self, settings: Settings) -> None:
        self._client = genai.Client(api_key=settings.google_api_key)
        self._model = settings.gemini_model

    @property
    def model_name(self) -> str:
        return self._model

    async def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "1:1",
        resolution: str = "2K",
    ) -> GeminiResult:
        """Generate an image from a text prompt with retry on transient failures.

        Pre-validates the prompt before making the expensive API call.
        Retries on 503/UNAVAILABLE with exponential backoff.
        """
        if not prompt.strip():
            msg = "Prompt cannot be empty"
            raise ValueError(msg)

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

                # google-genai is synchronous — run in executor to avoid blocking
                response = await asyncio.to_thread(
                    self._client.models.generate_content,
                    model=self._model,
                    contents=prompt,
                    config=config,
                )

                for part in response.parts:
                    if part.inline_data is not None:
                        logger.info("Image generated successfully", model=self._model)
                        return GeminiResult(
                            image_data=part.inline_data.data,
                            mime_type=part.inline_data.mime_type or "image/png",
                        )

                msg = "Gemini response contained no image data"
                raise ValueError(msg)

            except Exception as e:
                error_str = str(e)
                if "503" in error_str or "UNAVAILABLE" in error_str:
                    delay = BASE_RETRY_DELAY_SECONDS * (2**attempt)
                    logger.warning(
                        "Gemini unavailable, retrying",
                        attempt=attempt + 1,
                        max_retries=MAX_RETRIES,
                        delay_seconds=delay,
                        error=error_str,
                    )
                    last_error = e
                    await asyncio.sleep(delay)
                else:
                    logger.error("Gemini API error", error=error_str)
                    raise

        msg = f"Gemini generation failed after {MAX_RETRIES} retries"
        raise RuntimeError(msg) from last_error
