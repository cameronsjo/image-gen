"""Image browsing and download endpoints."""

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from image_gen.db import repository
from image_gen.models import GenerationResponse
from image_gen.services.storage import StorageService

router = APIRouter(prefix="/api")


@router.get("/images")
async def list_images(
    request: Request,
    limit: int = 50,
    offset: int = 0,
) -> list[GenerationResponse]:
    """List generation records, most recent first."""
    db = request.app.state.db
    return await repository.list_generations(db, limit=limit, offset=offset)


@router.get("/images/{image_id}")
async def get_image(image_id: str, request: Request) -> GenerationResponse:
    """Get metadata for a single generation."""
    db = request.app.state.db
    record = await repository.get_generation(db, image_id)
    if not record:
        raise HTTPException(status_code=404, detail="Generation not found")
    return record


@router.get("/images/{image_id}/file")
async def get_image_file(image_id: str, request: Request) -> FileResponse:
    """Download the generated image file."""
    db = request.app.state.db
    storage: StorageService = request.app.state.storage

    record = await repository.get_generation(db, image_id)
    if not record:
        raise HTTPException(status_code=404, detail="Generation not found")

    if not record.file_path or not storage.image_exists(image_id):
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(
        path=storage.get_image_path(image_id),
        media_type="image/png",
        filename=f"{record.name}.png",
    )
