"""Token bucket rate limiter backed by SQLite."""

import asyncio
from datetime import UTC, datetime

import aiosqlite
import structlog

from image_gen.config import Settings
from image_gen.models import QuotaStatus

logger = structlog.get_logger()


class QuotaService:
    """Token bucket rate limiter persisted in SQLite.

    Each user gets a bucket with max_tokens capacity that refills
    at refill_rate tokens per second.

    The service targets a single-process deployment that shares one SQLite
    connection. ``consume_token`` is serialized per user with an
    :class:`asyncio.Lock` so the read -> refill -> write sequence runs as one
    critical section; without it concurrent coroutines all observe the same
    pre-decrement token count and over-grant (a TOCTOU race).
    """

    def __init__(self, db: aiosqlite.Connection, settings: Settings) -> None:
        self._db = db
        self._max_tokens = settings.quota_max_tokens
        self._refill_rate = settings.quota_refill_rate
        # Per-user critical-section locks, plus a guard so two coroutines do
        # not race to create the same user's lock in the registry.
        self._locks: dict[str, asyncio.Lock] = {}
        self._locks_guard = asyncio.Lock()

    async def _user_lock(self, user_id: str) -> asyncio.Lock:
        """Return (creating if needed) the per-user lock.

        Fast path: reading an existing lock is a plain dict lookup — never awaited,
        so no coroutine is preempted mid-lookup. Only first-touch creation takes the
        process-wide guard, so established users don't serialize on it on every call.
        """
        lock = self._locks.get(user_id)
        if lock is not None:
            return lock
        async with self._locks_guard:
            lock = self._locks.get(user_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[user_id] = lock
            return lock

    async def _get_or_create_bucket(self, user_id: str) -> tuple[float, datetime]:
        """Fetch the user's bucket, creating one at max capacity if missing."""
        cursor = await self._db.execute(
            "SELECT tokens, last_refill_at FROM quota_buckets WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()

        if row:
            return float(row["tokens"]), datetime.fromisoformat(row["last_refill_at"])

        now = datetime.now(UTC)
        # INSERT OR IGNORE so a first-touch race (e.g. get_status racing
        # consume_token for a brand-new user) can't hit the PK and raise
        # IntegrityError. Re-read afterwards in case a concurrent caller won.
        await self._db.execute(
            "INSERT OR IGNORE INTO quota_buckets (user_id, tokens, last_refill_at) "
            "VALUES (?, ?, ?)",
            (user_id, float(self._max_tokens), now.isoformat()),
        )
        await self._db.commit()
        cursor = await self._db.execute(
            "SELECT tokens, last_refill_at FROM quota_buckets WHERE user_id = ?",
            (user_id,),
        )
        row = await cursor.fetchone()
        if row is None:  # pragma: no cover - INSERT OR IGNORE guarantees the row exists
            msg = "quota bucket missing immediately after INSERT OR IGNORE"
            raise RuntimeError(msg)
        return float(row["tokens"]), datetime.fromisoformat(row["last_refill_at"])

    def _refill(self, tokens: float, last_refill: datetime) -> tuple[float, datetime]:
        """Calculate refilled token count based on elapsed time."""
        now = datetime.now(UTC)
        elapsed = (now - last_refill).total_seconds()
        new_tokens = min(self._max_tokens, tokens + elapsed * self._refill_rate)
        return new_tokens, now

    async def consume_token(self, user_id: str) -> bool:
        """Atomically check and consume one token. Returns True if successful.

        The entire read -> refill -> update runs inside the per-user lock so
        concurrent callers cannot all pass the ``tokens < 1.0`` gate against a
        stale read and over-draw the bucket.
        """
        lock = await self._user_lock(user_id)
        async with lock:
            tokens, last_refill = await self._get_or_create_bucket(user_id)
            tokens, now = self._refill(tokens, last_refill)

            if tokens < 1.0:
                logger.warning(
                    "Quota exceeded",
                    user_id=user_id,
                    tokens=tokens,
                    max_tokens=self._max_tokens,
                )
                # Still persist the refill so the timestamp advances.
                await self._db.execute(
                    "UPDATE quota_buckets SET tokens = ?, last_refill_at = ? WHERE user_id = ?",
                    (tokens, now.isoformat(), user_id),
                )
                await self._db.commit()
                return False

            tokens -= 1.0
            await self._db.execute(
                "UPDATE quota_buckets SET tokens = ?, last_refill_at = ? WHERE user_id = ?",
                (tokens, now.isoformat(), user_id),
            )
            await self._db.commit()

            logger.info(
                "Quota token consumed",
                user_id=user_id,
                remaining=tokens,
                max_tokens=self._max_tokens,
            )
            return True

    async def get_status(self, user_id: str) -> QuotaStatus:
        """Get current quota status for a user."""
        tokens, last_refill = await self._get_or_create_bucket(user_id)
        tokens, _now = self._refill(tokens, last_refill)

        # Calculate when next token will be available if depleted
        next_token_at = None
        if tokens < 1.0:
            seconds_until_token = (1.0 - tokens) / self._refill_rate
            next_token_at = datetime.fromtimestamp(
                datetime.now(UTC).timestamp() + seconds_until_token, tz=UTC
            )

        return QuotaStatus(
            user_id=user_id,
            remaining_tokens=tokens,
            max_tokens=self._max_tokens,
            refill_rate=self._refill_rate,
            next_token_at=next_token_at,
        )
