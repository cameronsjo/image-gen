"""Image generation endpoint."""

from datetime import UTC, datetime

import structlog
from fastapi import APIRouter, HTTPException, Request

from image_gen.db import repository
from image_gen.models import GenerationRequest, GenerationResponse, GenerationStatus
from image_gen.services.gemini import GeminiService
from image_gen.services.prompt import ParsedPrompt, validate_prompt
from image_gen.services.quota import QuotaService
from image_gen.services.storage import StorageService

logger = structlog.get_logger()

router = APIRouter(prefix="/api")


@router.post("/generate", status_code=201)
async def generate(body: GenerationRequest, request: Request) -> GenerationResponse:
    """Generate an image from a text prompt.

    Flow: validate → check quota → consume token → call Gemini → save image → return.
    """
    gemini: GeminiService = request.app.state.gemini
    storage: StorageService = request.app.state.storage
    quota: QuotaService = request.app.state.quota
    db = request.app.state.db

    # Resolve user — fall back to "anonymous" when auth is disabled
    user_id: str = getattr(request.state, "user_id", "anonymous")

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

    # Rate limit check before the expensive Gemini call
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
    )

    # Update to generating status
    await repository.update_generation(db, record.id, status=GenerationStatus.GENERATING)

    try:
        result = await gemini.generate_image(
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
            file_size=file_size,
        )

        # Return the updated record
        return await repository.get_generation(db, record.id)  # type: ignore[return-value]

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
            error=error_msg,
        )
        raise HTTPException(status_code=500, detail={"error": error_msg}) from e
