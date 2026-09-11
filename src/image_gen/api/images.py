"""Image browsing and download endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from image_gen.auth import AuthenticatedUser, get_current_user
from image_gen.db import repository
from image_gen.exceptions import StorageError
from image_gen.models import GenerationResponse
from image_gen.services.storage import StorageService

router = APIRouter(prefix="/api")


@router.get("/images")
async def list_images(
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
    limit: int = 50,
    offset: int = 0,
) -> list[GenerationResponse]:
    """List the caller's own generation records, most recent first."""
    db = request.app.state.db
    return await repository.list_generations(
        db, user_id=current_user.user_id, limit=limit, offset=offset
    )


@router.get("/images/{image_id}")
async def get_image(
    image_id: str,
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> GenerationResponse:
    """Get metadata for a single generation owned by the caller."""
    db = request.app.state.db
    record = await repository.get_generation(db, image_id)
    # Same 404 for "missing" and "not yours" so we never leak existence.
    if record is None or record.user_id != current_user.user_id:
        raise HTTPException(status_code=404, detail="Generation not found")
    return record


@router.get("/images/{image_id}/file")
async def get_image_file(
    image_id: str,
    request: Request,
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> FileResponse:
    """Download a generated image file owned by the caller."""
    db = request.app.state.db
    storage: StorageService = request.app.state.storage

    record = await repository.get_generation(db, image_id)
    if record is None or record.user_id != current_user.user_id:
        raise HTTPException(status_code=404, detail="Generation not found")

    if not record.file_path:
        raise HTTPException(status_code=404, detail="Image file not found")

    try:
        path = storage.get_image_path(image_id)
    except StorageError as exc:
        # Never surface containment / I/O internals to the caller.
        raise HTTPException(status_code=404, detail="Image file not found") from exc
    if not path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    return FileResponse(
        path=path,
        media_type="image/png",
        filename=record.download_name,
    )
