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
