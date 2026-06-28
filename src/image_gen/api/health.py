"""Health and readiness endpoints."""

from fastapi import APIRouter, HTTPException, Request

from image_gen.models import HealthResponse, ReadyResponse

router = APIRouter()


@router.get("/health")
async def health() -> HealthResponse:
    """Liveness probe — always returns 200 if the process is running."""
    return HealthResponse()


@router.get("/ready")
async def ready(request: Request) -> ReadyResponse:
    """Readiness probe — verifies DB connectivity and reports available providers."""
    db = request.app.state.db
    registry: dict = request.app.state.provider_registry
    settings = request.app.state.settings

    # Verify DB is reachable (fetchone ensures the query actually executes)
    cursor = await db.execute("SELECT 1")
    row = await cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=503, detail="Database check failed")

    return ReadyResponse(
        default_provider=settings.default_provider,
        providers=sorted(registry.keys()),
    )
