"""Database schema migrations — CREATE TABLE IF NOT EXISTS on startup."""

import aiosqlite
import structlog

logger = structlog.get_logger()

SCHEMA = """
CREATE TABLE IF NOT EXISTS generations (
    id          TEXT PRIMARY KEY,
    user_id     TEXT NOT NULL,
    name        TEXT NOT NULL,
    prompt      TEXT NOT NULL,
    aspect_ratio TEXT NOT NULL DEFAULT '1:1',
    resolution  TEXT NOT NULL DEFAULT '2K',
    status      TEXT NOT NULL DEFAULT 'pending',
    error       TEXT,
    file_path   TEXT,
    file_size   INTEGER,
    created_at  TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_generations_user_id ON generations(user_id);
CREATE INDEX IF NOT EXISTS idx_generations_created_at ON generations(created_at);

CREATE TABLE IF NOT EXISTS quota_buckets (
    user_id        TEXT PRIMARY KEY,
    tokens         REAL NOT NULL,
    last_refill_at TEXT NOT NULL
);
"""


async def _add_provider_column(db: aiosqlite.Connection) -> None:
    """Idempotently add the ``provider`` column to the generations table.

    Uses ``PRAGMA table_info`` to guard against re-adding an already-present
    column, which would raise an error on SQLite.
    """
    cursor = await db.execute("PRAGMA table_info(generations)")
    columns = {row[1] for row in await cursor.fetchall()}
    if "provider" not in columns:
        await db.execute(
            "ALTER TABLE generations ADD COLUMN provider TEXT NOT NULL DEFAULT 'gemini'"
        )
        logger.info("Added provider column to generations table")
    else:
        logger.debug("Provider column already present, skipping migration")


async def run_migrations(db: aiosqlite.Connection) -> None:
    """Apply all schema migrations."""
    await db.executescript(SCHEMA)
    await _add_provider_column(db)
    await db.commit()
    logger.info("Database migrations applied")
