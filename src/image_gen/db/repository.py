"""Generation record CRUD operations."""

from datetime import UTC, datetime

import aiosqlite
import structlog
from ulid import ULID

from image_gen.models import GenerationResponse, GenerationStatus, ProviderName

logger = structlog.get_logger()


def _row_to_response(row: aiosqlite.Row) -> GenerationResponse:
    """Convert a database row to a GenerationResponse."""
    # Defensive: provider column may be absent on pre-migration databases.
    # sqlite3.Row.__contains__ checks values, not keys — use .keys() explicitly.
    provider_val = row["provider"] if "provider" in row.keys() else "gemini"  # noqa: SIM118

    return GenerationResponse(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        prompt=row["prompt"],
        aspect_ratio=row["aspect_ratio"],
        resolution=row["resolution"],
        provider=ProviderName(provider_val),
        status=GenerationStatus(row["status"]),
        error=row["error"],
        file_path=row["file_path"],
        file_size=row["file_size"],
        created_at=datetime.fromisoformat(row["created_at"]),
        completed_at=(datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None),
    )


async def create_generation(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    name: str,
    prompt: str,
    aspect_ratio: str,
    resolution: str,
    provider: str = "gemini",
) -> GenerationResponse:
    """Insert a new generation record and return it."""
    generation_id = str(ULID())
    now = datetime.now(UTC).isoformat()

    await db.execute(
        """
        INSERT INTO generations
            (id, user_id, name, prompt, aspect_ratio, resolution, status, provider, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (generation_id, user_id, name, prompt, aspect_ratio, resolution, "pending", provider, now),
    )
    await db.commit()

    logger.info(
        "Generation record created",
        generation_id=generation_id,
        user_id=user_id,
        name=name,
        provider=provider,
    )

    return GenerationResponse(
        id=generation_id,
        user_id=user_id,
        name=name,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        provider=ProviderName(provider),
        status=GenerationStatus.PENDING,
        created_at=datetime.fromisoformat(now),
    )


async def update_generation(
    db: aiosqlite.Connection,
    generation_id: str,
    *,
    status: GenerationStatus | None = None,
    error: str | None = None,
    file_path: str | None = None,
    file_size: int | None = None,
    completed_at: datetime | None = None,
) -> None:
    """Update fields on an existing generation record."""
    updates: list[str] = []
    params: list[object] = []

    if status is not None:
        updates.append("status = ?")
        params.append(status.value)
    if error is not None:
        updates.append("error = ?")
        params.append(error)
    if file_path is not None:
        updates.append("file_path = ?")
        params.append(file_path)
    if file_size is not None:
        updates.append("file_size = ?")
        params.append(file_size)
    if completed_at is not None:
        updates.append("completed_at = ?")
        params.append(completed_at.isoformat())

    if not updates:
        return

    params.append(generation_id)
    query = f"UPDATE generations SET {', '.join(updates)} WHERE id = ?"
    await db.execute(query, params)
    await db.commit()


async def get_generation(db: aiosqlite.Connection, generation_id: str) -> GenerationResponse | None:
    """Fetch a single generation by ID."""
    cursor = await db.execute("SELECT * FROM generations WHERE id = ?", (generation_id,))
    row = await cursor.fetchone()
    return _row_to_response(row) if row else None


async def list_generations(
    db: aiosqlite.Connection,
    *,
    user_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[GenerationResponse]:
    """List generation records, optionally filtered by user."""
    if user_id:
        cursor = await db.execute(
            "SELECT * FROM generations WHERE user_id = ? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset),
        )
    else:
        cursor = await db.execute(
            "SELECT * FROM generations ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        )
    rows = await cursor.fetchall()
    return [_row_to_response(row) for row in rows]
