"""Generation record CRUD operations."""

from datetime import UTC, datetime, timedelta
from math import isfinite

import aiosqlite
import structlog
from ulid import ULID

from image_gen.models import (
    CostAggregate,
    CostSummaryResponse,
    GenerationResponse,
    GenerationStatus,
    ProviderName,
)

logger = structlog.get_logger()


def _row_to_response(row: aiosqlite.Row) -> GenerationResponse:
    """Convert a database row to a GenerationResponse."""
    # Defensive: provider/model columns may be absent on pre-migration databases.
    # sqlite3.Row.__contains__ checks values, not keys — use .keys() explicitly.
    provider_val = row["provider"] if "provider" in row.keys() else "gemini"  # noqa: SIM118
    model_val = row["model"] if "model" in row.keys() else None  # noqa: SIM118
    cost_usd_val = row["cost_usd"] if "cost_usd" in row.keys() else None  # noqa: SIM118

    return GenerationResponse(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        prompt=row["prompt"],
        aspect_ratio=row["aspect_ratio"],
        resolution=row["resolution"],
        provider=ProviderName(provider_val),
        model=model_val,
        status=GenerationStatus(row["status"]),
        error=row["error"],
        file_path=row["file_path"],
        file_size=row["file_size"],
        cost_usd=cost_usd_val,
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
    model: str | None = None,
) -> GenerationResponse:
    """Insert a new generation record and return it."""
    generation_id = str(ULID())
    now = datetime.now(UTC).isoformat()

    await db.execute(
        """
        INSERT INTO generations
            (id, user_id, name, prompt, aspect_ratio, resolution, status, provider, model,
             created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            generation_id,
            user_id,
            name,
            prompt,
            aspect_ratio,
            resolution,
            "pending",
            provider,
            model,
            now,
        ),
    )
    await db.commit()

    logger.info(
        "Generation record created",
        generation_id=generation_id,
        user_id=user_id,
        name=name,
        provider=provider,
        model=model,
    )

    return GenerationResponse(
        id=generation_id,
        user_id=user_id,
        name=name,
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        resolution=resolution,
        provider=ProviderName(provider),
        model=model,
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
    cost_usd: float | None = None,
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
    if cost_usd is not None:
        updates.append("cost_usd = ?")
        params.append(cost_usd)
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
    """List generation records, optionally filtered by user.

    ``user_id=None`` lists across all users (internal/admin use). An empty string
    filters to that (empty) user rather than falling through to all rows — so a
    caller that resolves to a blank identity never leaks the whole table.
    """
    if user_id is not None:
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


async def _aggregate_costs(
    db: aiosqlite.Connection,
    *,
    user_id: str,
    since: str | None,
    until: str | None = None,
) -> CostAggregate:
    """Aggregate one user-scoped time window without loading generation rows."""
    clauses = ["user_id = ?"]
    params: list[object] = [user_id]
    if since is not None:
        clauses.append("created_at >= ?")
        params.append(since)
    if until is not None:
        clauses.append("created_at < ?")
        params.append(until)

    # SQLite can store IEEE infinity in a REAL column.  Treat it and any
    # nonnumeric value as an unknown reported cost, matching the UI's finite
    # number check and keeping the JSON response serializable.
    finite_cost = "cost_usd IS NOT NULL AND cost_usd >= 0 AND cost_usd < ?"
    query_params: list[object] = [float("inf"), float("inf"), float("inf"), *params]
    cursor = await db.execute(
        f"""
        SELECT
            COUNT(*) AS total_count,
            COALESCE(SUM(CASE WHEN status = 'completed'
                AND {finite_cost} THEN 1 ELSE 0 END), 0)
                AS completed_known_count,
            COALESCE(SUM(CASE WHEN status = 'completed'
                AND NOT ({finite_cost}) THEN 1 ELSE 0 END), 0)
                AS completed_unknown_count,
            COALESCE(SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END), 0)
                AS pending_count,
            COALESCE(SUM(CASE WHEN status = 'generating' THEN 1 ELSE 0 END), 0)
                AS generating_count,
            COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0)
                AS failed_count,
            COALESCE(SUM(CASE WHEN status IS NULL
                OR status NOT IN ('completed', 'pending', 'generating', 'failed')
                THEN 1 ELSE 0 END), 0) AS other_count,
            COALESCE(SUM(CASE WHEN status = 'completed'
                AND {finite_cost} THEN cost_usd ELSE 0 END), 0)
                AS known_cost_usd
        FROM generations
        WHERE {" AND ".join(clauses)}
        """,
        query_params,
    )
    row = await cursor.fetchone()
    if row is None:  # pragma: no cover - COUNT(*) always returns one row
        raise RuntimeError("cost aggregate query returned no row")

    completed_known_count = int(row["completed_known_count"])
    total = float(row["known_cost_usd"])
    return CostAggregate(
        total_count=int(row["total_count"]),
        known_cost_usd=(total if completed_known_count and isfinite(total) else None),
        completed_known_count=completed_known_count,
        completed_unknown_count=int(row["completed_unknown_count"]),
        pending_count=int(row["pending_count"]),
        generating_count=int(row["generating_count"]),
        failed_count=int(row["failed_count"]),
        other_count=int(row["other_count"]),
    )


async def summarize_costs(
    db: aiosqlite.Connection,
    *,
    user_id: str,
) -> CostSummaryResponse:
    """Return user-scoped all-time and current-UTC-day reported-cost aggregates."""
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return CostSummaryResponse(
        all_time=await _aggregate_costs(db, user_id=user_id, since=None),
        today=await _aggregate_costs(
            db,
            user_id=user_id,
            since=today.isoformat(),
            until=(today + timedelta(days=1)).isoformat(),
        ),
    )
