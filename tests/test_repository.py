"""CRUD tests for image_gen.db.repository.

Uses a local in-memory SQLite fixture rather than the full app lifespan.
Track B adds a `provider` column to the generations table; tests assert on
specific fields only — not full-object equality — so they stay valid when
the schema grows.
"""

import itertools
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest

from image_gen.db import engine, migrations, repository
from image_gen.models import GenerationStatus, ProviderName


@pytest.fixture
async def db(tmp_path: Path) -> aiosqlite.Connection:
    """In-memory SQLite connection with migrations applied."""
    conn = await engine.connect(tmp_path / "test.db")
    await migrations.run_migrations(conn)
    yield conn
    await conn.close()


# ── create_generation ───────────────────────────────────────────────────────


async def test_create_generation_returns_pending(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-a",
        name="sunset",
        prompt="A sunset over the ocean",
        aspect_ratio="16:9",
        resolution="2K",
    )

    assert record.id  # non-empty ULID
    assert record.user_id == "user-a"
    assert record.name == "sunset"
    assert record.prompt == "A sunset over the ocean"
    assert record.aspect_ratio == "16:9"
    assert record.resolution == "2K"
    assert record.status == GenerationStatus.PENDING
    assert record.error is None
    assert record.file_path is None
    assert record.file_size is None
    assert record.completed_at is None
    assert isinstance(record.created_at, datetime)


async def test_create_generation_persists_to_db(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-b",
        name="mountain",
        prompt="Snow-capped mountains at dawn",
        aspect_ratio="1:1",
        resolution="4K",
    )

    fetched = await repository.get_generation(db, record.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.user_id == "user-b"
    assert fetched.status == GenerationStatus.PENDING


# ── get_generation ──────────────────────────────────────────────────────────


async def test_get_generation_returns_none_for_missing(db: aiosqlite.Connection) -> None:
    result = await repository.get_generation(db, "01AAAAAAAAAAAAAAAAAAAAAAA")
    assert result is None


async def test_get_generation_returns_correct_record(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-c",
        name="forest",
        prompt="Dense forest at noon",
        aspect_ratio="4:3",
        resolution="1K",
    )

    fetched = await repository.get_generation(db, record.id)
    assert fetched is not None
    assert fetched.id == record.id
    assert fetched.name == "forest"
    assert fetched.prompt == "Dense forest at noon"
    assert fetched.aspect_ratio == "4:3"
    assert fetched.resolution == "1K"


# ── update_generation ───────────────────────────────────────────────────────


async def test_update_generation_status(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-d",
        name="city",
        prompt="Futuristic city skyline",
        aspect_ratio="21:9",
        resolution="2K",
    )

    await repository.update_generation(db, record.id, status=GenerationStatus.GENERATING)

    fetched = await repository.get_generation(db, record.id)
    assert fetched is not None
    assert fetched.status == GenerationStatus.GENERATING


async def test_update_generation_completed_fields(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-e",
        name="desert",
        prompt="Red sand dunes at sunset",
        aspect_ratio="16:9",
        resolution="2K",
    )

    completed = datetime.now(UTC)
    await repository.update_generation(
        db,
        record.id,
        status=GenerationStatus.COMPLETED,
        file_path="/data/images/abc.png",
        file_size=204800,
        completed_at=completed,
    )

    fetched = await repository.get_generation(db, record.id)
    assert fetched is not None
    assert fetched.status == GenerationStatus.COMPLETED
    assert fetched.file_path == "/data/images/abc.png"
    assert fetched.file_size == 204800
    assert fetched.completed_at is not None


async def test_update_generation_persists_cost_usd(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-cost",
        name="priced",
        prompt="A jeweled goblet",
        aspect_ratio="1:1",
        resolution="2K",
    )

    await repository.update_generation(
        db,
        record.id,
        status=GenerationStatus.COMPLETED,
        cost_usd=0.0042,
        completed_at=datetime.now(UTC),
    )

    fetched = await repository.get_generation(db, record.id)
    assert fetched is not None
    assert fetched.cost_usd == 0.0042


async def test_create_generation_cost_usd_defaults_to_none(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-no-cost",
        name="unpriced",
        prompt="A plain mug",
        aspect_ratio="1:1",
        resolution="2K",
    )

    fetched = await repository.get_generation(db, record.id)
    assert fetched is not None
    assert fetched.cost_usd is None


async def test_update_generation_error_fields(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-f",
        name="space",
        prompt="Deep space nebula",
        aspect_ratio="1:1",
        resolution="2K",
    )

    await repository.update_generation(
        db,
        record.id,
        status=GenerationStatus.FAILED,
        error="Provider returned 503",
    )

    fetched = await repository.get_generation(db, record.id)
    assert fetched is not None
    assert fetched.status == GenerationStatus.FAILED
    assert fetched.error == "Provider returned 503"


async def test_update_generation_noop_when_no_fields(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-g",
        name="lake",
        prompt="Calm lake at dawn",
        aspect_ratio="3:2",
        resolution="2K",
    )

    # No-op call — should not raise
    await repository.update_generation(db, record.id)

    fetched = await repository.get_generation(db, record.id)
    assert fetched is not None
    assert fetched.status == GenerationStatus.PENDING


# ── list_generations ────────────────────────────────────────────────────────


async def test_list_generations_returns_all_when_no_filter(db: aiosqlite.Connection) -> None:
    await repository.create_generation(
        db, user_id="alice", name="a1", prompt="prompt a1", aspect_ratio="1:1", resolution="2K"
    )
    await repository.create_generation(
        db, user_id="bob", name="b1", prompt="prompt b1", aspect_ratio="1:1", resolution="2K"
    )

    results = await repository.list_generations(db)
    assert len(results) >= 2  # may have records from other tests in the same db


async def test_list_generations_filters_by_user_id(db: aiosqlite.Connection) -> None:
    await repository.create_generation(
        db, user_id="alice", name="a2", prompt="prompt a2", aspect_ratio="1:1", resolution="2K"
    )
    await repository.create_generation(
        db, user_id="alice", name="a3", prompt="prompt a3", aspect_ratio="1:1", resolution="2K"
    )
    await repository.create_generation(
        db, user_id="bob", name="b2", prompt="prompt b2", aspect_ratio="1:1", resolution="2K"
    )

    alice_results = await repository.list_generations(db, user_id="alice")
    bob_results = await repository.list_generations(db, user_id="bob")

    # All returned records belong to the requested user
    assert all(r.user_id == "alice" for r in alice_results)
    assert all(r.user_id == "bob" for r in bob_results)
    # Alice has at least 2 records from this test
    assert len(alice_results) >= 2
    # Bob has at least 1 record from this test
    assert len(bob_results) >= 1


async def test_list_generations_empty_for_unknown_user(db: aiosqlite.Connection) -> None:
    results = await repository.list_generations(db, user_id="nobody")
    assert results == []


# ── model column / migration ────────────────────────────────────────────────


async def test_create_generation_persists_model(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-m",
        name="modelled",
        prompt="A teapot",
        aspect_ratio="1:1",
        resolution="2K",
        provider="openai",
        model="gpt-image-2",
    )
    assert record.model == "gpt-image-2"

    fetched = await repository.get_generation(db, record.id)
    assert fetched is not None
    assert fetched.model == "gpt-image-2"


async def test_create_generation_model_defaults_to_none(db: aiosqlite.Connection) -> None:
    record = await repository.create_generation(
        db,
        user_id="user-n",
        name="no-model",
        prompt="A kettle",
        aspect_ratio="1:1",
        resolution="2K",
    )
    assert record.model is None


async def test_migrations_are_idempotent(tmp_path: Path) -> None:
    """Running migrations twice must not raise — the model column guard holds."""
    conn = await engine.connect(tmp_path / "idempotent.db")
    await migrations.run_migrations(conn)
    await migrations.run_migrations(conn)  # second run must be a no-op

    cursor = await conn.execute("PRAGMA table_info(generations)")
    columns = {row[1] for row in await cursor.fetchall()}
    assert "model" in columns
    await conn.close()


async def test_pre_migration_row_reads_model_none(tmp_path: Path) -> None:
    """A row written before the model column existed reads back as model=None."""
    conn = await engine.connect(tmp_path / "legacy.db")
    # Legacy schema: no provider/model columns.
    await conn.execute(
        """
        CREATE TABLE generations (
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
        )
        """
    )
    await conn.execute(
        "INSERT INTO generations (id, user_id, name, prompt, created_at) VALUES (?, ?, ?, ?, ?)",
        ("01LEGACYROW0000000000000000", "u", "legacy", "old prompt", datetime.now(UTC).isoformat()),
    )
    await conn.commit()

    # Migrate forward — adds provider (NOT NULL DEFAULT 'gemini') and model (nullable).
    await migrations.run_migrations(conn)

    fetched = await repository.get_generation(conn, "01LEGACYROW0000000000000000")
    assert fetched is not None
    assert fetched.model is None
    assert fetched.provider == ProviderName.GEMINI
    await conn.close()


async def test_list_generations_ordered_by_created_at_desc(db: aiosqlite.Connection) -> None:
    for i in range(3):
        await repository.create_generation(
            db,
            user_id="carol",
            name=f"carol-{i}",
            prompt=f"prompt {i}",
            aspect_ratio="1:1",
            resolution="2K",
        )

    results = await repository.list_generations(db, user_id="carol")
    assert len(results) >= 3
    # created_at should be non-increasing
    for earlier, later in itertools.pairwise(results):
        assert earlier.created_at >= later.created_at
