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


async def _add_column_if_missing(db: aiosqlite.Connection, column: str, ddl: str) -> None:
    """Idempotently add *column* to the generations table by executing *ddl*.

    Uses ``PRAGMA table_info`` to guard against re-adding an already-present
    column, which would raise an error on SQLite.  Each new column migration is a
    one-line call rather than another copy of this PRAGMA pattern.
    """
    cursor = await db.execute("PRAGMA table_info(generations)")
    columns = {row[1] for row in await cursor.fetchall()}
    if column not in columns:
        await db.execute(ddl)
        logger.info("Added column to generations table", column=column)
    else:
        logger.debug("Column already present, skipping migration", column=column)


async def run_migrations(db: aiosqlite.Connection) -> None:
    """Apply all schema migrations.

    The ``provider`` and ``model`` columns are added post-hoc (not in ``SCHEMA``) so
    pre-existing databases pick them up.  ``model`` is nullable with no default, so
    rows written before that migration read back as ``model=None``.
    """
    await db.executescript(SCHEMA)
    await _add_column_if_missing(
        db,
        "provider",
        "ALTER TABLE generations ADD COLUMN provider TEXT NOT NULL DEFAULT 'gemini'",
    )
    await _add_column_if_missing(db, "model", "ALTER TABLE generations ADD COLUMN model TEXT")
    await db.commit()
    logger.info("Database migrations applied")
