"""Async SQLite connection factory."""

from pathlib import Path

import aiosqlite


async def connect(db_path: Path) -> aiosqlite.Connection:
    """Create an aiosqlite connection with WAL mode enabled."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(db_path)
    db.row_factory = aiosqlite.Row
    await db.execute("PRAGMA journal_mode=WAL")
    await db.execute("PRAGMA foreign_keys=ON")
    return db
