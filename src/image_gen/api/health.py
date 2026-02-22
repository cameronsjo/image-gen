"""Health and readiness endpoints."""

from fastapi import APIRouter, Request

from image_gen.models import HealthResponse, ReadyResponse
from image_gen.services.gemini import GeminiService

router = APIRouter()


@router.get("/health")
async def health() -> HealthResponse:
    """Liveness probe — always returns 200 if the process is running."""
    return HealthResponse()


@router.get("/ready")
async def ready(request: Request) -> ReadyResponse:
    """Readiness probe — verifies DB and Gemini connectivity."""
    gemini: GeminiService = request.app.state.gemini
    db = request.app.state.db

    # Verify DB is reachable
    await db.execute("SELECT 1")

    return ReadyResponse(gemini_model=gemini.model_name)
