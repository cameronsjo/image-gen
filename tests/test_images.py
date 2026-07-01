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
    app.state.storage.get_image_path = MagicMock(
        side_effect=StorageError("escapes storage containment: secret detail")
    )
    resp = await client.get(f"/api/images/{created['id']}/file")
    assert resp.status_code == 404
    assert "containment" not in resp.text
    assert "secret detail" not in resp.text
