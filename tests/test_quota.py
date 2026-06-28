"""Tests for the SQLite token-bucket quota service.

The concurrency test is the security-critical regression: it fires more
concurrent ``consume_token`` calls than the bucket can satisfy and asserts the
grant count never exceeds capacity. It FAILS against the pre-fix service (whose
read -> refill -> update was three separate autocommits, so racing coroutines
all passed the ``tokens < 1.0`` gate against a stale read and over-granted) and
PASSES once the critical section is serialized per user.
"""

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiosqlite
import pytest

from image_gen.config import Settings
from image_gen.db import engine, migrations
from image_gen.services.quota import QuotaService


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[aiosqlite.Connection]:
    """A migrated, isolated SQLite connection for quota tests."""
    conn = await engine.connect(tmp_path / "quota-test.db")
    await migrations.run_migrations(conn)
    try:
        yield conn
    finally:
        await conn.close()


def _settings(tmp_path: Path, *, max_tokens: int, refill_rate: float) -> Settings:
    return Settings(
        google_api_key="test-key",
        auth_enabled=False,
        data_dir=tmp_path / "data",
        quota_max_tokens=max_tokens,
        quota_refill_rate=refill_rate,
    )


async def test_concurrent_consume_never_over_grants(
    db: aiosqlite.Connection, tmp_path: Path
) -> None:
    max_tokens = 10
    # refill_rate=0 so capacity is exactly max_tokens for the duration of the test.
    settings = _settings(tmp_path, max_tokens=max_tokens, refill_rate=0.0)
    svc = QuotaService(db, settings)
    user = "race-user"

    # Pre-seed the bucket at full capacity so the race under test is purely the
    # read -> check -> update consumption gate (not the separate creation race);
    # this isolates the documented "tokens < 1.0" over-grant defect.
    now = datetime.now(UTC).isoformat()
    await db.execute(
        "INSERT INTO quota_buckets (user_id, tokens, last_refill_at) VALUES (?, ?, ?)",
        (user, float(max_tokens), now),
    )
    await db.commit()

    attempts = max_tokens + 5
    results = await asyncio.gather(*(svc.consume_token(user) for _ in range(attempts)))

    granted = sum(results)
    assert granted == max_tokens, f"over-grant: expected {max_tokens} grants, got {granted}"
    assert results.count(False) == attempts - max_tokens


async def test_independent_users_have_independent_buckets(
    db: aiosqlite.Connection, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, max_tokens=2, refill_rate=0.0)
    svc = QuotaService(db, settings)

    # Two users racing together should each get exactly their own capacity.
    calls = [svc.consume_token("alice") for _ in range(4)] + [
        svc.consume_token("bob") for _ in range(4)
    ]
    results = await asyncio.gather(*calls)
    assert sum(results) == 4  # 2 for alice + 2 for bob


async def test_refill_adds_tokens_proportional_to_elapsed(
    db: aiosqlite.Connection, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, max_tokens=10, refill_rate=0.5)  # 0.5 tokens/sec
    svc = QuotaService(db, settings)
    four_seconds_ago = datetime.now(UTC) - timedelta(seconds=4)

    new_tokens, _now = svc._refill(0.0, four_seconds_ago)

    assert 1.9 <= new_tokens <= 2.1  # ~4s * 0.5 tokens/s


async def test_refill_caps_at_max_tokens(db: aiosqlite.Connection, tmp_path: Path) -> None:
    settings = _settings(tmp_path, max_tokens=10, refill_rate=1.0)
    svc = QuotaService(db, settings)
    long_ago = datetime.now(UTC) - timedelta(seconds=10_000)

    new_tokens, _now = svc._refill(5.0, long_ago)

    assert new_tokens == 10


async def test_consume_succeeds_again_after_refill(
    db: aiosqlite.Connection, tmp_path: Path
) -> None:
    settings = _settings(tmp_path, max_tokens=2, refill_rate=1.0)
    svc = QuotaService(db, settings)
    user = "refill-user"

    assert await svc.consume_token(user) is True
    assert await svc.consume_token(user) is True
    assert await svc.consume_token(user) is False  # bucket depleted

    # Rewind the persisted refill timestamp to simulate elapsed time.
    past = (datetime.now(UTC) - timedelta(seconds=5)).isoformat()
    await db.execute("UPDATE quota_buckets SET last_refill_at = ? WHERE user_id = ?", (past, user))
    await db.commit()

    assert await svc.consume_token(user) is True  # refilled, consume succeeds
