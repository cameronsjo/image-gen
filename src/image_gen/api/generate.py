"""Image generation endpoint."""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Request

from image_gen.db import repository
from image_gen.exceptions import ProviderError, UnsupportedParameterError
from image_gen.models import GenerationRequest, GenerationResponse, GenerationStatus
from image_gen.services.prompt import ParsedPrompt, validate_prompt
from image_gen.services.provider import ImageProvider
from image_gen.services.quota import QuotaService
from image_gen.services.storage import StorageService

logger = structlog.get_logger()

router = APIRouter(prefix="/api")


@router.post("/generate", status_code=201)
async def generate(body: GenerationRequest, request: Request) -> GenerationResponse:
    """Generate an image from a text prompt.

    Flow: validate → check quota → consume token → call provider → save image → return.

    The ``provider`` field selects the backend (gemini / openai / openrouter).  If the
    requested provider is not configured (API key missing) the endpoint returns 422.
    """
    registry: dict[str, ImageProvider] = request.app.state.provider_registry
    storage: StorageService = request.app.state.storage
    quota: QuotaService = request.app.state.quota
    db = request.app.state.db

    # Resolve user — fall back to "anonymous" when auth is disabled
    user_id: str = getattr(request.state, "user_id", "anonymous")

    # Resolve and validate provider selection
    provider_name = body.provider.value
    if provider_name not in registry:
        raise HTTPException(
            status_code=422,
            detail={
                "error": f"Provider {provider_name!r} is not configured",
                "available_providers": sorted(registry.keys()),
            },
        )
    provider: ImageProvider = registry[provider_name]

    # Pre-flight validation (cost boundary: Expensive tier)
    parsed = ParsedPrompt(
        name=body.name,
        body=body.prompt,
        aspect_ratio=body.aspect_ratio.value,
        resolution=body.resolution.value,
    )
    errors = validate_prompt(parsed)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})

    # Rate limit check before the expensive provider call
    if not await quota.consume_token(user_id):
        status = await quota.get_status(user_id)
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded",
                "remaining_tokens": status.remaining_tokens,
                "next_token_at": status.next_token_at.isoformat() if status.next_token_at else None,
            },
        )

    # Create DB record in pending state
    record = await repository.create_generation(
        db,
        user_id=user_id,
        name=body.name,
        prompt=body.prompt,
        aspect_ratio=body.aspect_ratio.value,
        resolution=body.resolution.value,
        provider=provider_name,
    )

    # Update to generating status
    await repository.update_generation(db, record.id, status=GenerationStatus.GENERATING)

    try:
        result = await provider.generate_image(
            prompt=body.prompt,
            aspect_ratio=body.aspect_ratio.value,
            resolution=body.resolution.value,
        )

        file_path = await storage.save_image(result.image_data, record.id)
        file_size = len(result.image_data)

        now = datetime.now(UTC)
        await repository.update_generation(
            db,
            record.id,
            status=GenerationStatus.COMPLETED,
            file_path=str(file_path),
            file_size=file_size,
            completed_at=now,
        )

        logger.info(
            "Image generation completed",
            generation_id=record.id,
            user_id=user_id,
            provider=provider_name,
            file_size=file_size,
        )

        # Return the updated record
        return await repository.get_generation(db, record.id)  # type: ignore[return-value]

    except UnsupportedParameterError as e:
        error_msg = str(e)
        await repository.update_generation(
            db,
            record.id,
            status=GenerationStatus.FAILED,
            error=error_msg,
            completed_at=datetime.now(UTC),
        )
        raise HTTPException(status_code=422, detail={"error": error_msg}) from e

    except ProviderError as e:
        error_msg = str(e)
        await repository.update_generation(
            db,
            record.id,
            status=GenerationStatus.FAILED,
            error=error_msg,
            completed_at=datetime.now(UTC),
        )
        logger.error(
            "Image generation failed",
            generation_id=record.id,
            user_id=user_id,
            provider=provider_name,
            error=error_msg,
        )
        raise HTTPException(status_code=500, detail={"error": error_msg}) from e

    except Exception as e:
        error_msg = str(e)
        await repository.update_generation(
            db,
            record.id,
            status=GenerationStatus.FAILED,
            error=error_msg,
            completed_at=datetime.now(UTC),
        )
        logger.error(
            "Image generation failed",
            generation_id=record.id,
            user_id=user_id,
            provider=provider_name,
            error=error_msg,
        )
        raise HTTPException(status_code=500, detail={"error": error_msg}) from e
