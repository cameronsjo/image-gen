"""Tests for image browsing and download endpoints."""

import re
from unittest.mock import MagicMock

from httpx import AsyncClient

from image_gen.exceptions import StorageError

VALID_PROMPT = (
    "A photorealistic image of a single red cube sitting on a clean white surface "
    "with soft studio lighting. The cube has slightly rounded edges and a matte finish. "
    "The background is a pure white gradient that fades gently, creating a minimal and "
    "elegant composition. Light reflects subtly off the surface beneath the cube, casting "
    "a soft shadow to the right. The overall aesthetic is clean, modern, and suitable for "
    "product photography or design reference material."
)


async def _create_image(client: AsyncClient) -> dict:
    """Helper to generate an image and return the response data."""
    resp = await client.post(
        "/api/generate",
        json={"name": "list-test", "prompt": VALID_PROMPT},
    )
    assert resp.status_code == 201
    return resp.json()


async def test_list_images_empty(client: AsyncClient) -> None:
    resp = await client.get("/api/images")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_list_images_returns_generated(client: AsyncClient) -> None:
    await _create_image(client)
    resp = await client.get("/api/images")
    assert resp.status_code == 200
    images = resp.json()
    assert len(images) == 1
    assert images[0]["name"] == "list-test"


async def test_get_image_by_id(client: AsyncClient) -> None:
    created = await _create_image(client)
    resp = await client.get(f"/api/images/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


async def test_get_image_not_found(client: AsyncClient) -> None:
    resp = await client.get("/api/images/nonexistent")
    assert resp.status_code == 404


async def test_download_image_file(client: AsyncClient) -> None:
    created = await _create_image(client)
    resp = await client.get(f"/api/images/{created['id']}/file")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert len(resp.content) > 0


async def test_download_filename_is_descriptive(client: AsyncClient) -> None:
    """Content-Disposition offers the descriptive, collision-free download_name,
    not the bare ``<name>.png`` it used to."""
    created = await _create_image(client)
    expected = created["download_name"]

    resp = await client.get(f"/api/images/{created['id']}/file")
    assert resp.status_code == 200
    disposition = resp.headers["content-disposition"]
    # The header offers exactly the server-computed name...
    assert expected in disposition
    # ...which is descriptive, not the old "<name>.png".
    assert expected != f"{created['name']}.png"
    # Shape: name-model-YYYYMMDD-HHMMSS-<ULID>.png
    assert re.search(r"-\d{8}-\d{6}-[0-9A-Za-z]{26}\.png", disposition)


async def test_download_nonexistent_image(client: AsyncClient) -> None:
    resp = await client.get("/api/images/nonexistent/file")
    assert resp.status_code == 404


async def test_download_storage_error_is_404_not_leaked(client: AsyncClient) -> None:
    """A StorageError (e.g. path containment) maps to 404 without leaking internals."""
    created = await _create_image(client)
    app = client._transport.app  # type: ignore[attr-defined]
    # Force the storage layer to reject the path as if it escaped containment.
    app.state.storage.resolve_stored_path = MagicMock(
        side_effect=StorageError("escapes storage containment: secret detail")
    )
    resp = await client.get(f"/api/images/{created['id']}/file")
    assert resp.status_code == 404
    assert "containment" not in resp.text
    assert "secret detail" not in resp.text


async def test_new_images_use_descriptive_storage_and_legacy_files_still_serve(client):
    from pathlib import Path

    from image_gen.db import repository

    created = await _create_image(client)
    app = client._transport.app
    stored = Path(created["file_path"])
    assert stored.name == created["download_name"]
    assert not app.state.storage.get_image_path(created["id"]).exists()
    assert (await client.get(f"/api/images/{created['id']}/file")).content == stored.read_bytes()
    legacy = app.state.storage.get_image_path(created["id"])
    legacy.write_bytes(stored.read_bytes())
    await repository.update_generation(app.state.db, created["id"], file_path=str(legacy))
    assert (await client.get(f"/api/images/{created['id']}/file")).status_code == 200


async def test_stored_outside_path_is_rejected_without_leaking(client, tmp_path):
    from image_gen.db import repository

    created = await _create_image(client)
    app = client._transport.app
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"private-outside-content")
    await repository.update_generation(app.state.db, created["id"], file_path=str(outside))
    response = await client.get(f"/api/images/{created['id']}/file")
    assert response.status_code == 404
    assert b"private-outside-content" not in response.content


async def test_user_controlled_names_stay_contained(client):
    from pathlib import Path

    VALID_PROMPT = (
        "A detailed photograph of a red fox in a snowy forest with warm morning light. " * 6
    )

    ids = set()
    for name in ("../escape", "/absolute/path", "💣 café", "same", "same"):
        response = await client.post("/api/generate", json={"name": name, "prompt": VALID_PROMPT})
        assert response.status_code == 201
        record = response.json()
        path = Path(record["file_path"])
        root = client._transport.app.state.settings.images_dir.resolve()
        assert path.parent == root
        assert path.name == record["download_name"]
        assert record["id"] not in ids
        ids.add(record["id"])
        assert (await client.get(f"/api/images/{record['id']}/file")).status_code == 200


async def test_cost_summary_is_user_scoped_and_reconciles_statuses(client):
    """The aggregate is all-time/today and excludes non-completed rows from cost."""
    from datetime import UTC, datetime, timedelta

    from image_gen.db import repository
    from image_gen.models import GenerationStatus

    db = client._transport.app.state.db

    async def add_record(user_id, status, cost=None, created_at=None):
        record = await repository.create_generation(
            db,
            user_id=user_id,
            name=f"summary-{status}",
            prompt="A summary test image",
            aspect_ratio="1:1",
            resolution="1K",
        )
        updates = {"status": status}
        if cost is not None:
            updates["cost_usd"] = cost
        await repository.update_generation(db, record.id, **updates)
        if created_at is not None:
            await db.execute(
                "UPDATE generations SET created_at = ? WHERE id = ?",
                (created_at.isoformat(), record.id),
            )
            await db.commit()
        return record

    now = datetime.now(UTC).replace(microsecond=0)
    yesterday = now - timedelta(days=1)
    await add_record("anonymous", GenerationStatus.COMPLETED, 0.0042, now)
    await add_record("anonymous", GenerationStatus.COMPLETED, created_at=now)
    await add_record("anonymous", GenerationStatus.COMPLETED, float("inf"), now)
    for _ in range(13):
        await add_record("anonymous", GenerationStatus.COMPLETED, 0.0, now)
    await add_record("anonymous", GenerationStatus.PENDING, created_at=now)
    await add_record("anonymous", GenerationStatus.GENERATING, created_at=now)
    await add_record("anonymous", GenerationStatus.FAILED, created_at=now)
    await add_record("anonymous", GenerationStatus.COMPLETED, 0.9, yesterday)
    await add_record("anonymous", GenerationStatus.COMPLETED, 0.7, now + timedelta(days=1))
    await add_record("other-user", GenerationStatus.COMPLETED, 1.0, now)

    response = await client.get("/api/images/costs")
    assert response.status_code == 200
    body = response.json()

    assert body["all_time"] == {
        "total_count": 21,
        "known_cost_usd": 1.6042,
        "completed_known_count": 16,
        "completed_unknown_count": 2,
        "pending_count": 1,
        "generating_count": 1,
        "failed_count": 1,
        "other_count": 0,
    }
    assert body["today"] == {
        "total_count": 19,
        "known_cost_usd": 0.0042,
        "completed_known_count": 14,
        "completed_unknown_count": 2,
        "pending_count": 1,
        "generating_count": 1,
        "failed_count": 1,
        "other_count": 0,
    }


async def test_cost_summary_overflow_remains_explicitly_unknown(client):
    from image_gen.db import repository
    from image_gen.models import GenerationStatus

    db = client._transport.app.state.db
    for _ in range(2):
        record = await repository.create_generation(
            db,
            user_id="anonymous",
            name="overflow",
            prompt="A test image",
            aspect_ratio="1:1",
            resolution="1K",
        )
        await repository.update_generation(
            db,
            record.id,
            status=GenerationStatus.COMPLETED,
            cost_usd=1e308,
        )
    summary = await repository.summarize_costs(db, user_id="anonymous")
    assert summary.all_time.completed_known_count == 2
    assert summary.all_time.known_cost_usd is None
    response = await client.get("/api/images/costs")
    assert response.status_code == 200
    assert response.json()["all_time"]["known_cost_usd"] is None
